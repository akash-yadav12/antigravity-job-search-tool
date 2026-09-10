#!/usr/bin/env python3
"""
Large-Scale Multi-Source Discovery Engine (v2 Pipeline).
Discovers, normalizes, deduplicates, verifies, evaluates compensation,
applies hard gates, calculates calibrated fit scores, and updates seen_jobs.json.
"""

import json
import os
import re
import ssl
import subprocess
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import sys

# Workspace paths
WORKSPACE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE))
SEEN_JOBS_PATH = WORKSPACE / "job_scraper/seen_jobs.json"
WATCHLIST_PATH = WORKSPACE / "data/company_watchlist.json"
BENCHMARKS_PATH = WORKSPACE / "data/compensation_benchmarks.json"
import shutil
def find_bun() -> str:
    which = shutil.which("bun") or shutil.which("bun.exe")
    if which:
        return which
    candidates = [
        os.path.expanduser("~/.bun/bin/bun"),
        os.path.expanduser("~/.bun/bin/bun.exe"),
        os.path.expandvars(r"%USERPROFILE%\.bun\bin\bun.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\bun\bin\bun.exe"),
        "/usr/local/bin/bun",
        "/opt/homebrew/bin/bun",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "bun.exe" if sys.platform == "win32" else "bun"

BUN_BIN = find_bun()

# Import domain tools
from tools.normalization import (
    normalize_slug,
    normalize_metro,
    clean_url,
    extract_requisition_id,
    normalize_title,
    generate_canonical_job_id,
    is_employer_source,
    merge_job_records
)
from tools.company_tier_model import resolve_company_tier
from tools.freshness_engine import evaluate_freshness
from tools.compensation_engine import evaluate_compensation
from tools.evaluator import (
    evaluate_hard_gates,
    evaluate_job_calibrated,
    classify_role_family,
    calculate_application_priority
)

# HTTP Setup
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*"
}

def extract_yoe(text: str) -> Optional[float]:
    """Extracts minimum years of experience from text."""
    if not text:
        return None
    m = re.search(r'\b(\d+)\s*(?:[-–—to]+\s*(\d+))?\s*(?:years?|yrs?|yoe)\b', text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            pass
    return None

# 1. EXPANDED TARGET WATCHLIST FOR DIRECT ATS SEARCH
GREENHOUSE_TARGETS = [
    ("postman", "Postman"),
    ("roku", "Roku"),
    ("elastic", "Elastic"),
    ("mongodb", "MongoDB"),
    ("stripe", "Stripe"),
    ("cloudflare", "Cloudflare"),
    ("gitlab", "GitLab"),
    ("inmobi", "InMobi"),
    ("datadog", "Datadog"),
    ("rubrik", "Rubrik"),
    ("branch", "Branch"),
    ("braze", "Braze"),
    ("affirm", "Affirm"),
    ("brex", "Brex"),
    ("gusto", "Gusto"),
    ("instacart", "Instacart"),
    ("confluent", "Confluent"),
    ("reddit", "Reddit"),
    ("flexport", "Flexport"),
    ("chainlink", "Chainlink Labs")
]

LEVER_TARGETS = [
    ("cred", "CRED"),
    ("zimperium", "Zimperium"),
    ("cohere", "Cohere"),
    ("atlan", "Atlan"),
    ("meesho", "Meesho"),
    ("groww", "Groww"),
    ("urbancompany", "Urban Company"),
    ("slice", "slice"),
    ("clevertap", "CleverTap"),
    ("browserstack", "BrowserStack"),
    ("moengage", "MoEngage"),
    ("palantir", "Palantir"),
    ("benchling", "Benchling"),
    ("spotify", "Spotify")
]

SMARTRECRUITERS_TARGETS = [
    ("Nexthink", "Nexthink"),
    ("ServiceNow", "ServiceNow"),
    ("Visa", "Visa"),
    ("Square", "Block / Square"),
    ("Deliveroo", "Deliveroo"),
    ("WoltersKluwer", "Wolters Kluwer"),
    ("EpicGames", "Epic Games")
]

ASHBY_TARGETS = [
    ("inkeep", "Inkeep"),
    ("dust", "Dust"),
    ("cohere", "Cohere"),
    ("together", "Together AI"),
    ("anyscale", "Anyscale"),
    ("modal", "Modal Labs"),
    ("ramp", "Ramp"),
    ("replit", "Replit"),
    ("cursor", "Anysphere (Cursor)"),
    ("langchain", "LangChain"),
    ("suno", "Suno"),
    ("perplexity", "Perplexity")
]

# 2. DIVERSIFIED FREEHIRE QUERIES ACROSS TECH HUBS
FREEHIRE_QUERIES = [
    ("Java", "in"),
    ("Spring Boot", "in"),
    ("Kafka", "in"),
    ("Microservices", "in"),
    ("Distributed Systems", "in"),
    ("Event Streaming", "in"),
    ("Backend Engineer", "in"),
    ("Software Engineer II", "in"),
    ("Senior Software Engineer", "in"),
    ("Platform Engineer", "in"),
    ("AI Platform", "in"),
    ("RAG", "in"),
    ("LLM Platform", "in"),
    ("Developer Productivity", "in"),
    ("JVM", "in"),
    ("Java Go", "in"),
    ("Java Kubernetes", "in"),
    ("AWS Kafka", "in"),
    ("Data Platform", "in"),
    ("High Concurrency Java", "in"),
    ("Java AWS S3", "in"),
    ("Staff Backend Engineer", "in"),
    ("API Platform", "in"),
    ("Streaming Infrastructure", "in")
]

# 3. LINKEDIN SEARCH QUERIES
LINKEDIN_QUERIES = [
    ("Java Software Engineer", "Bengaluru, Karnataka, India"),
    ("Kafka Distributed Systems", "Bengaluru, Karnataka, India"),
    ("Java Backend Engineer", "Mumbai, Maharashtra, India"),
    ("Spring Boot Microservices", "Pune, Maharashtra, India"),
    ("Backend Platform Engineer", "Hyderabad, Telangana, India"),
    ("Staff Java Engineer", "Bengaluru, Karnataka, India"),
    ("AI Backend Engineer", "Bengaluru, Karnataka, India"),
    ("Distributed Systems Engineer", "Remote")
]

def is_relevant_role(title: str, loc: str) -> bool:
    """Filters for relevant technical backend/platform/AI engineering roles in valid locations."""
    if not title:
        return False
    t_l = title.lower()
    
    # 1. Reject non-engineering
    non_eng = [
        "account executive", "sales manager", "sales development", "marketing manager", "product marketing",
        "paid media", "counsel", "legal", "recruiter", "talent acquisition", "human resources", "finance manager",
        "tax manager", "workplace", "product manager", "content", "copywriter", "graphic designer", "support representative"
    ]
    if any(k in t_l for k in non_eng) and not any(k in t_l for k in ["software engineer", "backend engineer", "developer", "platform engineer", "sre"]):
        return False
        
    # 2. Require technical backend / platform / engineering keywords
    tech_keys = ["engineer", "developer", "backend", "software", "java", "kafka", "platform", "systems", "ai", "sre", "data infrastructure", "architect"]
    if not any(k in t_l for k in tech_keys):
        return False
        
    # 3. Location check
    loc_l = (loc or "").lower()
    valid_locs = ["india", "bengaluru", "bangalore", "mumbai", "pune", "hyderabad", "gurugram", "gurgaon", "noida", "remote", "chennai", "delhi", "apac", "worldwide", "anywhere"]
    if not any(v in loc_l for v in valid_locs):
        return False
        
    return True

def fetch_greenhouse(slug: str, company_name: str) -> List[Dict[str, Any]]:
    jobs = []
    url = f"https://api.greenhouse.io/v1/boards/{slug}/jobs"
    try:
        req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                for j in data.get("jobs", []):
                    title = j.get("title", "")
                    loc = j.get("location", {}).get("name", "India")
                    if is_relevant_role(title, loc):
                        jobs.append({
                            "title": title,
                            "company": company_name,
                            "location": loc,
                            "url": j.get("absolute_url", ""),
                            "requisition_id": str(j.get("id", "")),
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "source": "greenhouse-ats",
                            "portal": "greenhouse_board_api",
                            "description": ""
                        })
    except Exception:
        pass
    return jobs

def fetch_lever(slug: str, company_name: str) -> List[Dict[str, Any]]:
    jobs = []
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    try:
        req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                for j in data:
                    title = j.get("text", "")
                    loc = j.get("categories", {}).get("location", "India")
                    if is_relevant_role(title, loc):
                        jobs.append({
                            "title": title,
                            "company": company_name,
                            "location": loc,
                            "url": j.get("hostedUrl", ""),
                            "requisition_id": str(j.get("id", "")),
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "source": "lever-ats",
                            "portal": "lever_postings_api",
                            "description": j.get("descriptionPlain", "")
                        })
    except Exception:
        pass
    return jobs

def fetch_smartrecruiters(slug: str, company_name: str) -> List[Dict[str, Any]]:
    jobs = []
    url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100"
    try:
        req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                for j in data.get("content", []):
                    title = j.get("name", "")
                    loc_dict = j.get("location", {})
                    loc = f"{loc_dict.get('city', '')}, {loc_dict.get('country', '')}".strip(", ") or "India"
                    if is_relevant_role(title, loc):
                        post_id = str(j.get("id", ""))
                        job_url = f"https://jobs.smartrecruiters.com/{slug}/{post_id}"
                        jobs.append({
                            "title": title,
                            "company": company_name,
                            "location": loc,
                            "url": job_url,
                            "requisition_id": post_id,
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "source": "smartrecruiters-ats",
                            "portal": "smartrecruiters_api",
                            "description": ""
                        })
    except Exception:
        pass
    return jobs

def fetch_ashby(slug: str, company_name: str) -> List[Dict[str, Any]]:
    jobs = []
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    try:
        req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                for j in data.get("jobs", []):
                    title = j.get("title", "")
                    loc = j.get("location", "Remote")
                    if is_relevant_role(title, loc):
                        post_id = str(j.get("id", ""))
                        job_url = j.get("jobUrl", f"https://jobs.ashbyhq.com/{slug}/{post_id}")
                        jobs.append({
                            "title": title,
                            "company": company_name,
                            "location": loc,
                            "url": job_url,
                            "requisition_id": post_id,
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "source": "ashby-ats",
                            "portal": "ashby_api",
                            "description": ""
                        })
    except Exception:
        pass
    return jobs

def fetch_freehire_query(query: str, country: str) -> List[Dict[str, Any]]:
    jobs = []
    for page in [1, 2]:
        args = [
            BUN_BIN, "run",
            str(WORKSPACE / ".agents/skills/freehire-search/cli/src/cli.ts"),
            "search",
            "-q", query,
            "--limit", "35",
            "--page", str(page),
            "--jobage", "30",
            "--no-description"
        ]
        try:
            res = subprocess.run(args, capture_output=True, text=True, cwd=str(WORKSPACE), timeout=20)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout.strip())
                for hit in data.get("results", []):
                    title = hit.get("title") or ""
                    loc = hit.get("location") or "India"
                    if is_relevant_role(title, loc):
                        jobs.append({
                            "title": title,
                            "company": hit.get("company") or "Unknown",
                            "location": loc,
                            "url": hit.get("url") or "",
                            "requisition_id": hit.get("id") or "",
                            "date": (hit.get("date") or datetime.now().strftime("%Y-%m-%d"))[:10],
                            "source": "freehire",
                            "portal": "freehire_aggregator",
                            "description": ""
                        })
        except Exception:
            pass
    return jobs

def fetch_linkedin_query(query: str, location: str) -> List[Dict[str, Any]]:
    jobs = []
    args = [
        BUN_BIN, "run",
        str(WORKSPACE / ".agents/skills/linkedin-search/cli/src/cli.ts"),
        "search",
        "-q", query,
        "-l", location,
        "--jobage", "14",
        "--limit", "25",
        "--format", "json"
    ]
    try:
        res = subprocess.run(args, capture_output=True, text=True, cwd=str(WORKSPACE), timeout=25)
        if res.returncode == 0 and res.stdout.strip():
            stdout = res.stdout.strip()
            # Extract JSON if wrapped
            s_idx = stdout.find('{')
            e_idx = stdout.rfind('}')
            if s_idx != -1 and e_idx != -1:
                data = json.loads(stdout[s_idx:e_idx+1])
                for hit in data.get("results", []):
                    jobs.append({
                        "title": hit.get("title", ""),
                        "company": hit.get("company", ""),
                        "location": hit.get("location", location),
                        "url": hit.get("url", ""),
                        "requisition_id": hit.get("id", ""),
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "source": "linkedin",
                        "portal": "linkedin_guest_api",
                        "description": ""
                    })
    except Exception:
        pass
    return jobs

def run_all_discovery() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Runs all discovery tasks in parallel across ATS and aggregator sources."""
    print("=== Launching Large-Scale Multi-Source Discovery Engine ===")
    all_raw_jobs: List[Dict[str, Any]] = []
    source_stats: Dict[str, Dict[str, int]] = {}
    
    tasks = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        # 1. Direct ATS Greenhouse
        for slug, comp in GREENHOUSE_TARGETS:
            tasks.append(("greenhouse-ats", executor.submit(fetch_greenhouse, slug, comp)))
            
        # 2. Direct ATS Lever
        for slug, comp in LEVER_TARGETS:
            tasks.append(("lever-ats", executor.submit(fetch_lever, slug, comp)))
            
        # 3. Direct ATS SmartRecruiters
        for slug, comp in SMARTRECRUITERS_TARGETS:
            tasks.append(("smartrecruiters-ats", executor.submit(fetch_smartrecruiters, slug, comp)))
            
        # 4. Direct ATS Ashby
        for slug, comp in ASHBY_TARGETS:
            tasks.append(("ashby-ats", executor.submit(fetch_ashby, slug, comp)))
            
        # 5. Freehire Multi-Query
        for q, c in FREEHIRE_QUERIES:
            tasks.append(("freehire", executor.submit(fetch_freehire_query, q, c)))
            
        # 6. LinkedIn Multi-Query
        for q, l in LINKEDIN_QUERIES:
            tasks.append(("linkedin", executor.submit(fetch_linkedin_query, q, l)))
            
        for src, future in tasks:
            try:
                res = future.result()
                if src not in source_stats:
                    source_stats[src] = {"raw": 0, "unique": 0, "active": 0, "comp_qualified": 0}
                source_stats[src]["raw"] += len(res)
                all_raw_jobs.extend(res)
            except Exception as e:
                pass
                
    print(f"Total raw listings discovered across all sources: {len(all_raw_jobs)}")
    return all_raw_jobs, source_stats

def main():
    start_time = time.time()
    
    # 1. Load existing seen_jobs.json
    existing_seen_jobs = {}
    if SEEN_JOBS_PATH.exists():
        try:
            with open(SEEN_JOBS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                existing_seen_jobs = data.get("seen", {})
        except Exception as e:
            print(f"Error loading seen_jobs.json: {e}")
            
    print(f"Loaded {len(existing_seen_jobs)} existing records from seen_jobs.json")
    
    # 2. Run Large-Scale Discovery
    raw_jobs, source_stats = run_all_discovery()
    
    # 3. Canonical Deduplication & Normalization
    print("=== Processing Canonical Deduplication & Normalization ===")
    canonical_jobs: Dict[str, Dict[str, Any]] = {}
    url_to_canonical: Dict[str, str] = {}
    
    # Pre-populate url_to_canonical from existing
    for can_id, job in existing_seen_jobs.items():
        for u in job.get("source_urls", []):
            url_to_canonical[u] = can_id
        if job.get("canonical_url"):
            url_to_canonical[job["canonical_url"]] = can_id
            
    duplicates_merged_count = 0
    today_str = datetime.now().strftime("%Y-%m-%d")
    now_iso = datetime.now().isoformat()
    
    # Discovery uniqueness tracking
    source_unique_stats = {
        "employer_ats_only": 0,
        "platforms_only": 0,
        "multi_source": 0
    }
    
    for item in raw_jobs:
        raw_url = item.get("url", "")
        if not raw_url:
            continue
            
        company_raw = item.get("company") or "Unknown"
        title_raw = item.get("title") or "Software Engineer"
        loc_raw = item.get("location") or "India"
        src = item.get("source") or "unknown"
        
        comp_canon = company_raw.strip()
        title_clean = title_raw.strip()
        loc_norm = loc_raw.strip()
        req_id = extract_requisition_id(raw_url, title_raw, "")
        can_id = generate_canonical_job_id(comp_canon, title_clean, loc_norm, raw_url, req_id)
        
        # Check if already known
        existing_can_id = url_to_canonical.get(raw_url) or (can_id if can_id in existing_seen_jobs else None) or (can_id if can_id in canonical_jobs else None)
        
        target_id = existing_can_id or can_id
        
        if target_id in canonical_jobs:
            duplicates_merged_count += 1
            existing = canonical_jobs[target_id]
            if raw_url not in existing["source_urls"]:
                existing["source_urls"].append(raw_url)
            if src not in existing["discovered_from"]:
                existing["discovered_from"].append(src)
            existing["last_seen"] = today_str
        elif target_id in existing_seen_jobs:
            duplicates_merged_count += 1
            existing = existing_seen_jobs[target_id]
            if raw_url not in existing.get("source_urls", []):
                existing.setdefault("source_urls", []).append(raw_url)
            if src not in existing.get("discovered_from", []):
                existing.setdefault("discovered_from", []).append(src)
            existing["last_seen"] = today_str
            # Add to canonical_jobs for evaluation
            canonical_jobs[target_id] = existing
        else:
            # Genuinely new record
            canonical_jobs[target_id] = {
                "canonical_job_id": target_id,
                "requisition_id": req_id,
                "company": comp_canon,
                "company_raw": company_raw,
                "title": title_clean,
                "title_raw": title_raw,
                "location": loc_norm,
                "location_raw": loc_raw,
                "canonical_url": raw_url,
                "source_urls": [raw_url],
                "discovered_from": [src],
                "first_seen": item.get("date", today_str),
                "last_seen": today_str,
                "last_verified_at": now_iso,
                "record_origin": "production_v2",
                "applied": False,
                "description": item.get("description", "")
            }
            url_to_canonical[raw_url] = target_id
            
    print(f"Total Unique Canonical Jobs in this cycle: {len(canonical_jobs)} (Merged Duplicates: {duplicates_merged_count})")
    
    # 4. Pipeline Stages: Tiering, Freshness, Compensation, Gating, Calibrated Fit
    print("=== Running Evaluation & Qualification Pipeline ===")
    
    funnel = {
        "raw_discovered": len(raw_jobs),
        "unique_canonical": len(canonical_jobs),
        "duplicates_merged": duplicates_merged_count,
        "employer_verified": 0,
        "fresh": 0,
        "recently_verified": 0,
        "stale": 0,
        "closed": 0,
        "comp_qualified": 0,
        "comp_unknown": 0,
        "below_comp_floor": 0,
        "hard_gated": 0,
        "p0": 0,
        "p1": 0,
        "p2": 0,
        "p3": 0
    }
    
    evaluated_jobs = {}
    new_active_opportunities = []
    
    for can_id, job in canonical_jobs.items():
        comp = job.get("company", "")
        title = job.get("title", "")
        loc = job.get("location", "")
        url = job.get("canonical_url", "")
        desc = job.get("description", "")
        disc_from = job.get("discovered_from", [])
        
        # Source uniqueness classification
        is_ats = any("ats" in s or s in ["workday", "greenhouse", "lever", "smartrecruiters", "ashby"] for s in disc_from)
        is_plat = any(s in ["freehire", "linkedin", "wellfound", "naukri"] for s in disc_from)
        if is_ats and not is_plat:
            source_unique_stats["employer_ats_only"] += 1
        elif is_plat and not is_ats:
            source_unique_stats["platforms_only"] += 1
        else:
            source_unique_stats["multi_source"] += 1
            
        # 1. Company Tiering
        tier_info = resolve_company_tier(comp)
        job["company_tier"] = tier_info["tier"]
        job["company_tier_score"] = tier_info.get("tier_score", tier_info.get("quality_score", 60))
        
        # 2. Freshness
        freshness_res = evaluate_freshness(job)
        job["freshness"] = freshness_res["freshness"]
        job["freshness_score"] = freshness_res["freshness_score"]
        job["active_status"] = "active" if freshness_res["freshness"] in ("fresh", "recently_verified") else ("closed" if freshness_res["freshness"] == "closed" else "stale")
        
        f_status = job["freshness"]
        if f_status == "fresh":
            funnel["fresh"] += 1
        elif f_status == "recently_verified":
            funnel["recently_verified"] += 1
        elif f_status == "stale":
            funnel["stale"] += 1
        elif f_status == "closed":
            funnel["closed"] += 1
            
        if is_ats:
            funnel["employer_verified"] += 1
            
        # 3. Role Family
        role_fam = classify_role_family(title, desc)
        job["role_family"] = role_fam
        # 4. Compensation Intelligence
        comp_res = evaluate_compensation(job, tier_info["tier"])
        job["compensation"] = comp_res
        
        comp_decision = comp_res.get("decision", "UNKNOWN")
        comp_fit = comp_res.get("compensation_fit", "unknown")
        
        if comp_decision == "TARGET":
            funnel["comp_qualified"] += 1
        elif comp_decision == "REJECT":
            funnel["below_comp_floor"] += 1
        else:
            funnel["comp_unknown"] += 1
            
        # Update source breakdown stats
        for s in disc_from:
            if s in source_stats:
                source_stats[s]["unique"] += 1
                if job["active_status"] != "closed":
                    source_stats[s]["active"] += 1
                if comp_decision == "TARGET":
                    source_stats[s]["comp_qualified"] += 1
                    
        # 5. Fit & Hard Gates
        gate_passed, gate_reason = evaluate_hard_gates(title, desc, loc)
        job["can_apply"] = gate_passed
        job["gate_reason"] = gate_reason if not gate_passed else None
        
        eval_result = evaluate_job_calibrated(job)
        job["fit_evaluation"] = eval_result
        job["fit_score"] = eval_result.get("rank_score", 0)
        job["rank_band"] = eval_result.get("rank_band", "Weak Fit")
        job["strengths"] = eval_result.get("strengths", [])
        job["gaps"] = eval_result.get("gaps", [])
        
        comp_score = comp_res.get("comp_score", 60.0)
        quality_score = float(tier_info.get("quality_score", 60.0))
        freshness_score = 100.0 if f_status == "fresh" else (85.0 if f_status == "recently_verified" else (50.0 if f_status == "stale" else 0.0))
        
        if not gate_passed:
            funnel["hard_gated"] += 1
            job["priority"] = "P3"
            job["priority_tier"] = "P3"
            job["ready_for_application"] = False
            funnel["p3"] += 1
        else:
            # 6. Priority Calculation
            final_prio_score, prio_tier, prio_label = calculate_application_priority(
                job["fit_score"],
                comp_score,
                quality_score,
                freshness_score,
                comp_fit
            )
            job["priority"] = prio_tier
            job["priority_tier"] = prio_tier
            job["priority_score"] = final_prio_score
            job["priority_label"] = prio_label
            job["ready_for_application"] = (prio_tier in ["P0", "P1"])
            
            if prio_tier == "P0":
                funnel["p0"] += 1
            elif prio_tier == "P1":
                funnel["p1"] += 1
            elif prio_tier == "P2":
                funnel["p2"] += 1
            else:
                funnel["p3"] += 1
                
            # Collect active opportunity if genuinely new and not already applied
            if not job.get("applied") and prio_tier in ["P0", "P1", "P2"]:
                new_active_opportunities.append(job)
                
        evaluated_jobs[can_id] = job
        existing_seen_jobs[can_id] = job
        
    # 5. Save back to seen_jobs.json
    with open(SEEN_JOBS_PATH, "w", encoding="utf-8") as f:
        json.dump({"version": "2.0.0", "updated_at": now_iso, "seen": existing_seen_jobs}, f, indent=2)
        
    print(f"Updated seen_jobs.json with {len(existing_seen_jobs)} total records.")
    
    # 6. Write Discovery Report
    elapsed = time.time() - start_time
    print(f"\n=== Discovery Cycle Completed in {elapsed:.1f}s ===")
    
    # Sort top new opportunities
    # Priority order: P0 > P1 > P2, then fit_score desc, then total_comp desc
    prio_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    new_active_opportunities.sort(
        key=lambda x: (
            prio_order.get(x.get("priority", "P3"), 99),
            -(x.get("fit_score") or 0),
            -(x.get("compensation", {}).get("total_comp_expected") or 0.0)
        )
    )
    
    # Generate Output Data structure for agent reporting
    output_summary = {
        "funnel": funnel,
        "source_stats": source_stats,
        "source_uniqueness": source_unique_stats,
        "top_new_opportunities": new_active_opportunities[:60]
    }
    
    report_json_path = WORKSPACE / "scratch/large_scale_discovery_results.json"
    with open(report_json_path, "w", encoding="utf-8") as f:
        json.dump(output_summary, f, indent=2)
        
    print(f"Saved full discovery results JSON to {report_json_path}")

if __name__ == "__main__":
    main()
