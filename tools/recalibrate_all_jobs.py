#!/usr/bin/env python3
"""
Recalibrates and audits all jobs in job_scraper/seen_jobs.json.
Ensures 100% data integrity, strict location gating, non-engineering gating,
and consistent priority assignments.
"""

import json
import re
import sys
from pathlib import Path
from collections import defaultdict

WORKSPACE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE))

from tools.normalization import clean_url, extract_requisition_id, normalize_metro
from tools.company_tier_model import resolve_company_tier
from tools.freshness_engine import evaluate_freshness
from tools.compensation_engine import evaluate_compensation
from tools.evaluator import evaluate_hard_gates, evaluate_job_calibrated, classify_role_family, calculate_application_priority

WORKSPACE = Path(__file__).resolve().parent.parent
SEEN_PATH = WORKSPACE / "job_scraper/seen_jobs.json"

VALID_INDIA_LOCS = [
    "india", "bengaluru", "bangalore", "mumbai", "pune", "hyderabad",
    "gurugram", "gurgaon", "noida", "remote", "chennai", "delhi", "navi mumbai",
    "thane", "karnataka", "maharashtra", "telangana", "haryana", "anywhere"
]

NON_ENG_KEYWORDS = [
    "marketing", "paid media", "sales development", "account executive", "general counsel",
    "legal counsel", "attorney", "paralegal", "recruiter", "talent acquisition", "human resources",
    "finance manager", "tax manager", "workplace operations", "product manager", "content writer",
    "copywriter", "graphic designer", "customer support"
]

def main():
    with open(SEEN_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    seen = data["seen"]
    
    print(f"Loaded {len(seen)} records for full recalibration...")
    
    funnel = defaultdict(int)
    funnel["total_corpus"] = len(seen)
    
    source_stats = defaultdict(lambda: {"raw": 0, "unique": 0, "active": 0, "comp_qualified": 0})
    source_uniqueness = {
        "employer_ats_only": 0,
        "platforms_only": 0,
        "multi_source": 0
    }
    
    for cid, job in seen.items():
        title = job.get("title", "")
        comp = job.get("company", "")
        loc = job.get("location", "India")
        desc = job.get("description", "")
        url = job.get("canonical_url") or job.get("url", "")
        disc_from = job.get("discovered_from", [])
        
        # 1. Company Tier
        tier_info = resolve_company_tier(comp)
        job["company_tier"] = tier_info["tier"]
        job["company_tier_score"] = tier_info.get("tier_score", tier_info.get("quality_score", 60))
        
        # 2. Freshness
        f_res = evaluate_freshness(job)
        job["freshness"] = f_res["freshness"]
        job["freshness_score"] = f_res["freshness_score"]
        job["active_status"] = "active" if f_res["freshness"] in ("fresh", "recently_verified") else ("closed" if f_res["freshness"] == "closed" else "stale")
        funnel[job["freshness"]] += 1
        
        # 3. Role Family
        role_fam = classify_role_family(title, desc)
        job["role_family"] = role_fam
        
        # 4. Compensation
        comp_res = evaluate_compensation(job, tier_info["tier"])
        job["compensation"] = comp_res
        
        c_dec = comp_res.get("decision", "UNKNOWN")
        c_fit = comp_res.get("compensation_fit", "unknown")
        
        if c_dec == "TARGET":
            funnel["comp_qualified"] += 1
        elif c_dec == "REJECT":
            funnel["below_comp_floor"] += 1
        else:
            funnel["comp_unknown"] += 1
            
        # 5. Strict Hard Gates
        gate_passed, gate_reason = evaluate_hard_gates(title, desc, loc)
        
        # Tier D Excluded Vendors / Agencies Gate
        if tier_info.get("is_excluded") or tier_info.get("tier") == "Tier D":
            gate_passed = False
            gate_reason = f"Tier D excluded staffing / consulting vendor ({comp})"
            
        # Current Employer Gate (Do not apply externally to current employer)
        if any(jpm in comp.lower() for jpm in ["jpmorgan", "jpmc", "jp morgan"]):
            gate_passed = False
            gate_reason = "Current employer (JPMorganChase)"
            
        # Additional Location check: Ensure location is actually India/Remote
        loc_l = loc.lower()
        if not any(v in loc_l for v in VALID_INDIA_LOCS):
            gate_passed = False
            gate_reason = f"Non-India international location without local eligibility ({loc})"
            
        # Additional Non-Eng check
        t_l = title.lower()
        if any(k in t_l for k in NON_ENG_KEYWORDS) and not any(k in t_l for k in ["software engineer", "backend", "developer", "platform engineer", "sre"]):
            gate_passed = False
            gate_reason = "Non-engineering / Business / Operations role"
            
        job["can_apply"] = gate_passed
        job["gate_reason"] = gate_reason if not gate_passed else None
        
        if not gate_passed:
            funnel["hard_gated"] += 1
            
        # 6. Calibrated Evaluation
        eval_res = evaluate_job_calibrated(job)
        job["fit_evaluation"] = eval_res
        job["fit_score"] = eval_res.get("rank_score", 0)
        job["rank_band"] = eval_res.get("rank_band", "Weak Fit")
        job["strengths"] = eval_res.get("strengths", [])
        job["gaps"] = eval_res.get("gaps", [])
        
        # 7. Application Priority
        comp_score = comp_res.get("comp_score", 60.0)
        qual_score = float(tier_info.get("quality_score", 60.0))
        f_score = float(f_res.get("freshness_score", 50.0))
        
        if not gate_passed:
            job["priority"] = "P3"
            job["priority_tier"] = "P3"
            job["priority_score"] = 0
            job["priority_label"] = "P3 — Skip"
            job["ready_for_application"] = False
            funnel["p3"] += 1
        else:
            final_prio_score, prio_tier, prio_label = calculate_application_priority(
                job["fit_score"],
                comp_score,
                qual_score,
                f_score,
                c_fit
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
                
        # Source breakdown stats
        is_ats = any("ats" in s or s in ["workday", "greenhouse", "lever", "smartrecruiters", "ashby"] for s in disc_from)
        is_plat = any(s in ["freehire", "linkedin", "wellfound", "naukri"] for s in disc_from)
        if is_ats and not is_plat:
            source_uniqueness["employer_ats_only"] += 1
        elif is_plat and not is_ats:
            source_uniqueness["platforms_only"] += 1
        else:
            source_uniqueness["multi_source"] += 1
            
        for s in disc_from:
            source_stats[s]["raw"] += 1
            source_stats[s]["unique"] += 1
            if job["active_status"] != "closed":
                source_stats[s]["active"] += 1
            if c_dec == "TARGET":
                source_stats[s]["comp_qualified"] += 1
                
    # Save back to seen_jobs.json
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        
    print(f"Recalibration complete. Total records: {len(seen)}")
    print("Funnel metrics:")
    for k, v in funnel.items():
        print(f"  {k}: {v}")
        
    output_summary = {
        "funnel": dict(funnel),
        "source_stats": dict(source_stats),
        "source_uniqueness": source_uniqueness
    }
    with open(WORKSPACE / "scratch/large_scale_discovery_results.json", "w", encoding="utf-8") as f:
        json.dump(output_summary, f, indent=2)

if __name__ == "__main__":
    main()
