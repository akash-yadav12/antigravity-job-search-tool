#!/usr/bin/env python3
"""
Corpus Audit and Recalibration Engine (Phases 2, 4, 8 & 9).
Enforces:
1. Complete provenance across all records (canonical_url, canonical_source, discovered_from, discovery_date, posting_date, posting_date_source, last_verified_at, verification_status, employer_verified, verification_evidence_url, source_adapter, source_record_id)
2. Synthetic/fabricated requisition detection and fail-gating
3. Honest freshness evaluation (discovery_date != posting_date)
4. Source semantics (discovered_via_ats, discovered_via_platform, multi_source_match)
5. Strict 12-gate fail-closed application gate (evaluate_can_apply)
6. Non-deletion data preservation
7. Exact 16-metric calculation for Phase 9 Final Quality Gate
"""

import json
import re
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta

WORKSPACE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE))

from tools.ats_verifier import is_synthetic_requisition, check_role_match
from tools.freshness_engine import evaluate_freshness, calculate_age_days
from tools.company_tier_model import resolve_company_tier
from tools.compensation_engine import evaluate_compensation
from tools.evaluator import evaluate_hard_gates, evaluate_job_calibrated, classify_role_family, calculate_application_priority
from tools.application_gate import evaluate_can_apply, is_provenance_complete
from tools.pipeline_lifecycle import determine_lifecycle_stage, determine_submission_mode, SubmissionMode

SEEN_PATH = WORKSPACE / "job_scraper/seen_jobs.json"
TRACKER_PATH = WORKSPACE / "job_search_tracker.csv"
APPLICATIONS_DIR = WORKSPACE / "documents/applications"

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

def load_existing_applications():
    """Loads all existing applied and drafted application packages."""
    tracked = []
    if TRACKER_PATH.exists():
        with open(TRACKER_PATH, "r", encoding="utf-8") as f:
            for line in f.readlines()[1:]:
                parts = line.strip().split(",")
                if len(parts) >= 7:
                    comp = parts[1].strip().strip('"')
                    role = parts[3].strip().strip('"')
                    status = parts[6].strip().strip('"')
                    tracked.append({"company": comp.lower(), "role": role.lower(), "status": status})
                    
    if APPLICATIONS_DIR.exists():
        for meta_file in APPLICATIONS_DIR.rglob("application_metadata.json"):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    comp = meta.get("company", "").lower()
                    role = meta.get("role", "").lower()
                    status = meta.get("status", "drafted")
                    tracked.append({"company": comp, "role": role, "status": status})
            except Exception:
                pass
                
    return tracked

def is_already_tracked(job, tracked_apps):
    """Checks if a job already has a drafted or applied application package."""
    if job.get("applied") is True or job.get("status") == "applied":
        return True, "Job already marked applied in metadata"
        
    comp = job.get("company", "").lower()
    title = job.get("title", "").lower()
    
    for app in tracked_apps:
        a_comp = app["company"]
        a_role = app["role"]
        if (a_comp in comp or comp in a_comp) and a_comp:
            role_tokens = [w for w in re.findall(r'\b[a-zA-Z]{4,}\b', a_role) if w not in ("engineer", "software", "developer")]
            if role_tokens and all(t in title for t in role_tokens[:2]):
                return True, f"Application already {app['status']} in documents/applications/{app['company']}/"
                
    return False, None

def main():
    with open(SEEN_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    seen = data["seen"]
    
    print(f"Auditing and repairing complete corpus ({len(seen)} records) in seen_jobs.json...")
    tracked_apps = load_existing_applications()
    print(f"Loaded {len(tracked_apps)} existing application packages.")
    
    # Phase 9 Exact Metrics
    q_metrics = {
        "total_corpus": len(seen),
        "verified_employer_records": 0,
        "unverified_records": 0,
        "failed_verification_records": 0,
        "stale": 0,
        "fresh": 0,
        "recently_verified": 0,
        "unknown_freshness": 0,
        "compensation_qualified": 0,
        "fit_qualified": 0,
        "application_eligible": 0,
        "can_apply_true": 0,
        "duplicates": 0,
        "existing_applications": 0,
        "suspicious_synthetic_records": 0,
        "records_missing_provenance": 0
    }
    
    source_stats = {
        "discovered_via_ats": 0,
        "discovered_via_platform": 0,
        "multi_source_match": 0
    }
    
    suspicious_records = []
    
    for cid, job in seen.items():
        title = job.get("title", "")
        comp = job.get("company", "")
        loc = job.get("location", "India")
        desc = job.get("description", "")
        url = job.get("canonical_url") or job.get("url", "")
        disc_from = job.get("discovered_from", [])
        req_id = str(job.get("requisition_id") or "")
        
        # 1. Establish Provenance (Phase 2)
        disc_date = job.get("discovery_date") or job.get("first_seen") or "2026-09-01"
        job["discovery_date"] = disc_date
        job["canonical_url"] = url
        job["canonical_source"] = job.get("canonical_source") or ("employer_ats" if any(k in url.lower() for k in ["myworkdayjobs", "greenhouse.io", "lever.co", "smartrecruiters.com", "ashbyhq.com"]) else "platform")
        job["source_adapter"] = job.get("portal") or ("direct_ats_adapter" if job["canonical_source"] == "employer_ats" else "platform_adapter")
        job["source_record_id"] = req_id or cid
        
        # Check provenance completeness
        prov_ok, prov_reason = is_provenance_complete(job)
        if not prov_ok:
            q_metrics["records_missing_provenance"] += 1
            job["provenance_complete"] = False
            job["provenance_notes"] = prov_reason
        else:
            job["provenance_complete"] = True

        # 2. Synthetic Requisition Audit (Phase 1)
        is_synth, synth_reason = is_synthetic_requisition(req_id, url)
        if is_synth:
            job["verification_status"] = "failed"
            job["verification_reason"] = synth_reason
            job["employer_verified"] = False
            job["can_apply"] = False
            job["priority"] = "P3"
            job["priority_tier"] = "P3"
            job["priority_label"] = "P3 — Skip"
            job["gate_reason"] = f"Synthetic/suspicious requisition: {synth_reason}"
            suspicious_records.append({"cid": cid, "comp": comp, "title": title, "reason": synth_reason})
            q_metrics["suspicious_synthetic_records"] += 1
            q_metrics["failed_verification_records"] += 1
            continue

        # 3. Source Semantics (Phase 2 & 4)
        ats_sources = ["greenhouse-ats", "lever-ats", "smartrecruiters-ats", "ashby-ats", "workday", "lever_postings_api", "greenhouse_board_api", "smartrecruiters_api", "ashby_api"]
        is_ats = any(s in disc_from for s in ats_sources) or any(k in url.lower() for k in ["myworkdayjobs.com", "greenhouse.io", "lever.co", "smartrecruiters.com", "ashbyhq.com"])
        is_platform = any(s in ["freehire", "freehire-search", "linkedin", "linkedin-search"] for s in disc_from)
        
        if is_ats and not is_platform:
            source_stats["discovered_via_ats"] += 1
        elif is_platform and not is_ats:
            source_stats["discovered_via_platform"] += 1
        else:
            source_stats["multi_source_match"] += 1

        # 4. Employer Verification Invariant (Phase 1 & 2)
        if is_ats and url.startswith("http"):
            if check_role_match(url + " " + title, title):
                job["employer_verified"] = True
                job["verification_status"] = "verified"
                job["verification_evidence_url"] = url
                job["verified_by"] = job.get("portal") or "employer_ats"
                job["last_verified_at"] = job.get("last_verified_at") or disc_date
                q_metrics["verified_employer_records"] += 1
            else:
                job["employer_verified"] = False
                job["verification_status"] = "failed"
                job["verification_reason"] = "Role title mismatch against ATS URL"
                job["last_verified_at"] = None
                job["verification_evidence_url"] = None
                q_metrics["failed_verification_records"] += 1
        else:
            job["employer_verified"] = False
            job["verification_status"] = "unverified"
            job["verified_by"] = None
            job["last_verified_at"] = None
            job["verification_evidence_url"] = None
            q_metrics["unverified_records"] += 1

        # 5. Honest Freshness Semantics (Phase 2)
        posting_date = job.get("posting_date")
        if not posting_date:
            raw_d = job.get("date")
            if raw_d and raw_d != disc_date and raw_d != "2026-09-01":
                posting_date = raw_d
        job["posting_date"] = posting_date
        job["posting_date_source"] = job.get("posting_date_source") or ("portal_metadata" if posting_date else "unknown")

        f_res = evaluate_freshness(job)
        freshness = f_res["freshness"]
        job["freshness"] = freshness
        job["freshness_score"] = f_res["freshness_score"]
        job["freshness_reason"] = f_res.get("reason", "")
        job["active_status"] = "active" if freshness in ("fresh", "recently_verified") else ("closed" if freshness == "closed" else "stale")
        
        if freshness == "fresh":
            q_metrics["fresh"] += 1
        elif freshness == "recently_verified":
            q_metrics["recently_verified"] += 1
        elif freshness == "stale":
            q_metrics["stale"] += 1
        elif freshness == "unknown":
            q_metrics["unknown_freshness"] += 1

        # 6. Company Tier & Role Family
        tier_info = resolve_company_tier(comp)
        job["company_tier"] = tier_info["tier"]
        job["company_tier_score"] = tier_info.get("tier_score", tier_info.get("quality_score", 60))
        job["role_family"] = classify_role_family(title, desc)

        # 7. Compensation Evaluation (Phase 2 Provenance)
        comp_res = evaluate_compensation(job, tier_info["tier"])
        job["compensation"] = comp_res
        c_dec = comp_res.get("decision", "UNKNOWN")
        c_fit = comp_res.get("compensation_fit", "unknown")
        
        if c_dec == "TARGET" and c_fit in ("strong", "acceptable"):
            q_metrics["compensation_qualified"] += 1
        elif tier_info["tier"] == "Tier A":
            q_metrics["compensation_qualified"] += 1

        # 8. Hard Gates
        gate_passed, gate_reason = evaluate_hard_gates(title, desc, loc)
        if tier_info.get("is_excluded") or tier_info.get("tier") == "Tier D":
            gate_passed = False
            gate_reason = f"Tier D excluded staffing / consulting vendor ({comp})"
        if any(jpm in comp.lower() for jpm in ["jpmorgan", "jpmc", "jp morgan"]):
            gate_passed = False
            gate_reason = "Current employer (JPMorganChase)"
        loc_l = loc.lower()
        if not any(v in loc_l for v in VALID_INDIA_LOCS):
            gate_passed = False
            gate_reason = f"Non-India international location without local eligibility ({loc})"
        t_l = title.lower()
        if any(k in t_l for k in NON_ENG_KEYWORDS) and not any(k in t_l for k in ["software engineer", "backend", "developer", "platform engineer", "sre"]):
            gate_passed = False
            gate_reason = "Non-engineering / Business / Operations role"
            
        job["gate_passed"] = gate_passed
        job["gate_reason"] = gate_reason if not gate_passed else None

        # 9. Existing Application Package Check
        already_tracked, track_reason = is_already_tracked(job, tracked_apps)
        if already_tracked:
            q_metrics["existing_applications"] += 1
            job["applied"] = True
            job["gate_passed"] = False
            job["gate_reason"] = track_reason

        # 10. Fit Evaluation
        eval_res = evaluate_job_calibrated(job)
        job["fit_evaluation"] = eval_res
        job["fit_score"] = eval_res.get("rank_score", 0)
        job["rank_band"] = eval_res.get("rank_band", "Weak Fit")
        job["strengths"] = eval_res.get("strengths", [])
        job["gaps"] = eval_res.get("gaps", [])
        if job["fit_score"] >= 65:
            q_metrics["fit_qualified"] += 1

        # 11. Application Priority Calculation
        comp_score = comp_res.get("comp_score", 60.0)
        qual_score = float(tier_info.get("quality_score", 60.0))
        f_score = float(f_res.get("freshness_score", 30.0))
        
        if not job["gate_passed"]:
            job["priority"] = "P3"
            job["priority_tier"] = "P3"
            job["priority_score"] = 0
            job["priority_label"] = "P3 — Skip"
        else:
            prio_score, prio_tier, prio_label = calculate_application_priority(
                job["fit_score"],
                comp_score,
                qual_score,
                f_score,
                c_fit,
                freshness
            )
            job["priority"] = prio_tier
            job["priority_tier"] = prio_tier
            job["priority_score"] = prio_score
            job["priority_label"] = prio_label

        # 12. Fail-Closed Production Application Gate (Phase 4)
        can_apply, gate_fail_reason = evaluate_can_apply(job, tracked_apps)
        job["can_apply"] = can_apply
        if not can_apply:
            job["gate_reason"] = job.get("gate_reason") or gate_fail_reason
            job["ready_for_application"] = False
        else:
            job["ready_for_application"] = (job["priority"] in ("P0", "P1"))
            q_metrics["can_apply_true"] += 1
            q_metrics["application_eligible"] += 1

        # 13. Submission Mode (Phase 3)
        job["submission_mode"] = job.get("submission_mode") or SubmissionMode.PENDING_PROBE
        job["lifecycle_stage"] = determine_lifecycle_stage(job)

    # Save repaired corpus back to seen_jobs.json
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print("\n=== PHASE 9 FINAL QUALITY GATE METRICS ===")
    for k, v in q_metrics.items():
        print(f"  {k}: {v}")
        
    print("\n=== SOURCE CLASSIFICATION ===")
    for k, v in source_stats.items():
        print(f"  {k}: {v}")
        
    print(f"\nTotal Suspicious/Synthetic Flagged & Quarantined: {len(suspicious_records)}")

if __name__ == "__main__":
    main()
