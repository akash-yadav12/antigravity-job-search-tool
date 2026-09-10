"""
Multi-Source Discovery Engine.
Implements parallel discovery paths:
A. Company-First Proactive ATS Discovery (Workday, Greenhouse, Lever, SmartRecruiters, Ashby)
B. Broad Platform Aggregation (Freehire REST API, LinkedIn Guest API, WebSearch Fallbacks)
"""

import json
import os
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
WATCHLIST_PATH = os.path.join(WORKSPACE_DIR, "data/company_watchlist.json")

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*"
}

def run_bun_cli(args: List[str]) -> Optional[Dict[str, Any]]:
    """Runs a bun CLI tool and captures JSON stdout."""
    try:
        res = subprocess.run(args, capture_output=True, text=True, cwd=WORKSPACE_DIR, timeout=40)
        if res.returncode == 0 and res.stdout.strip():
            stdout = res.stdout.strip()
            try:
                return json.loads(stdout)
            except Exception:
                s_idx = stdout.find('{')
                e_idx = stdout.rfind('}')
                if s_idx != -1 and e_idx != -1:
                    return json.loads(stdout[s_idx:e_idx+1])
    except Exception:
        pass
    return None

def fetch_greenhouse_board_jobs(company_slug: str, company_name: str) -> List[Dict[str, Any]]:
    """Fetches live jobs directly from Greenhouse public board API."""
    jobs = []
    api_url = f"https://api.greenhouse.io/v1/boards/{company_slug}/jobs"
    try:
        req = urllib.request.Request(api_url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                for j in data.get("jobs", []):
                    title = j.get("title", "")
                    # Filter for backend / engineering relevancy
                    if any(k in title.lower() for k in ["engineer", "developer", "backend", "software", "java", "kafka", "platform"]):
                        loc = j.get("location", {}).get("name", "India")
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

def fetch_lever_postings_jobs(company_slug: str, company_name: str) -> List[Dict[str, Any]]:
    """Fetches live jobs directly from Lever public postings API."""
    jobs = []
    api_url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    try:
        req = urllib.request.Request(api_url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                for j in data:
                    title = j.get("text", "")
                    if any(k in title.lower() for k in ["engineer", "developer", "backend", "software", "java", "kafka", "platform"]):
                        loc = j.get("categories", {}).get("location", "India")
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

def fetch_smartrecruiters_jobs(company_slug: str, company_name: str) -> List[Dict[str, Any]]:
    """Fetches live jobs directly from SmartRecruiters public postings API."""
    jobs = []
    api_url = f"https://api.smartrecruiters.com/v1/companies/{company_slug}/postings?limit=25"
    try:
        req = urllib.request.Request(api_url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                for j in data.get("content", []):
                    title = j.get("name", "")
                    if any(k in title.lower() for k in ["engineer", "developer", "backend", "software", "java", "kafka", "platform"]):
                        city = j.get("location", {}).get("city", "India")
                        jobs.append({
                            "title": title,
                            "company": company_name,
                            "location": city,
                            "url": f"https://jobs.smartrecruiters.com/{company_slug}/{j.get('id')}",
                            "requisition_id": str(j.get("id", "")),
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "source": "smartrecruiters-ats",
                            "portal": "smartrecruiters_api",
                            "description": ""
                        })
    except Exception:
        pass
    return jobs

def discover_company_first_jobs() -> List[Dict[str, Any]]:
    """
    Executes proactive Company-First ATS discovery across target companies.
    """
    discovered = []
    
    # Direct Greenhouse boards
    gh_companies = [
        ("postman", "Postman"),
        ("roku", "Roku"),
        ("elastic", "Elastic")
    ]
    for slug, name in gh_companies:
        hits = fetch_greenhouse_board_jobs(slug, name)
        discovered.extend(hits)

    # Direct Lever postings
    lever_companies = [
        ("cred", "CRED"),
        ("zimperium", "Zimperium")
    ]
    for slug, name in lever_companies:
        hits = fetch_lever_postings_jobs(slug, name)
        discovered.extend(hits)

    # Direct SmartRecruiters postings
    sr_companies = [
        ("Nexthink", "Nexthink"),
        ("ServiceNow", "ServiceNow")
    ]
    for slug, name in sr_companies:
        hits = fetch_smartrecruiters_jobs(slug, name)
        discovered.extend(hits)

    return discovered

def fetch_linkedin_jobs(queries_and_locations: List[Tuple[str, str]]) -> List[Dict[str, Any]]:
    """Fetches listings from LinkedIn search CLI."""
    jobs = []
    cli_path = ".agents/skills/linkedin-search/cli/src/cli.ts"
    for q, loc in queries_and_locations:
        data = run_bun_cli([BUN_BIN, "run", cli_path, "search", "-q", q, "-l", loc, "--limit", "20", "--jobage", "14", "--format", "json"])
        if data and "results" in data:
            for item in data["results"]:
                jobs.append({
                    "title": item.get("title", "").strip(),
                    "company": item.get("company", "").strip(),
                    "location": item.get("location", loc).strip(),
                    "url": item.get("url", f"https://in.linkedin.com/jobs/view/{item.get('id', '')}"),
                    "requisition_id": f"LI_{item.get('id', '')}" if item.get('id') else None,
                    "date": item.get("date", datetime.now().strftime("%Y-%m-%d")),
                    "source": "linkedin-search",
                    "portal": "linkedin-search",
                    "description": ""
                })
    return jobs

def fetch_freehire_jobs(queries: List[str]) -> List[Dict[str, Any]]:
    """Fetches listings from Freehire API CLI with enrichment data."""
    jobs = []
    cli_path = ".agents/skills/freehire-search/cli/src/cli.ts"
    for q in queries:
        data = run_bun_cli([BUN_BIN, "run", cli_path, "search", "-q", q, "--country", "IN", "--limit", "30", "--format", "json"])
        if data and "results" in data:
            for item in data["results"]:
                jobs.append({
                    "title": (item.get("title") or "").strip(),
                    "company": (item.get("company") or "").strip(),
                    "location": (item.get("location") or "India").strip(),
                    "url": (item.get("url") or "").strip(),
                    "requisition_id": str(item.get("id") or ""),
                    "date": (item.get("date") or datetime.now().strftime("%Y-%m-%d")),
                    "source": "freehire-search",
                    "portal": "freehire-search",
                    "description": item.get("description", "") or "",
                    "skills": item.get("skills", []) or []
                })
    return jobs

def run_discovery() -> List[Dict[str, Any]]:
    """
    Executes full multi-source discovery across Company-First ATS and Platform streams.
    """
    all_discovered = []

    # 1. Company-First ATS Discovery
    print("  -> Probing Company-First ATS portals...", flush=True)
    ats_jobs = discover_company_first_jobs()
    print(f"     Found {len(ats_jobs)} live postings from direct ATS feeds.", flush=True)
    all_discovered.extend(ats_jobs)

    # 2. LinkedIn Discovery
    print("  -> Querying LinkedIn Search across Indian tech hubs...", flush=True)
    linkedin_queries = [
        ("Java Spring Boot", "Mumbai, Maharashtra, India"),
        ("Backend Software Engineer", "Mumbai, Maharashtra, India"),
        ("Senior Backend Software Engineer", "Mumbai, Maharashtra, India"),
        ("Java Spring", "Bengaluru, Karnataka, India"),
        ("Backend Engineer", "Bengaluru, Karnataka, India"),
        ("Senior Java Engineer", "Bengaluru, Karnataka, India"),
        ("Kafka Java", "Bengaluru, Karnataka, India"),
        ("Software Engineer II Java", "Bengaluru, Karnataka, India"),
        ("Distributed Systems Java", "Bengaluru, Karnataka, India"),
        ("AI Backend Engineer", "Bengaluru, Karnataka, India"),
        ("Platform Engineer Java", "Bengaluru, Karnataka, India"),
        ("Java Backend Developer", "Pune, Maharashtra, India"),
        ("Backend Engineer", "Pune, Maharashtra, India"),
        ("Java Microservices", "Hyderabad, Telangana, India"),
        ("Backend Software Engineer", "Hyderabad, Telangana, India"),
        ("Java Backend Engineer", "Remote, India")
    ]
    li_jobs = fetch_linkedin_jobs(linkedin_queries)
    print(f"     Found {len(li_jobs)} live postings from LinkedIn search.", flush=True)
    all_discovered.extend(li_jobs)

    # 3. Freehire Discovery
    print("  -> Querying Freehire ATS Aggregator API...", flush=True)
    freehire_queries = [
        "Java", "Spring Boot", "Backend", "Kafka", "Microservices",
        "Distributed Systems", "AI", "Platform", "AWS"
    ]
    fh_jobs = fetch_freehire_jobs(freehire_queries)
    print(f"     Found {len(fh_jobs)} enriched postings from Freehire.", flush=True)
    all_discovered.extend(fh_jobs)

    return all_discovered
