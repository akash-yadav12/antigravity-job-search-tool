#!/usr/bin/env python3
"""
Production Job Search & Qualification Pipeline.
Faithfully executes the decoupled 8-stage architecture:
DISCOVERY -> NORMALIZATION -> SOURCE VERIFICATION -> FRESHNESS -> COMPENSATION -> HARD GATES -> FIT EVALUATION -> APPLICATION PRIORITY.

Optimized for: QUALITY x COMPENSATION x FRESHNESS x TECHNICAL FIT.
"""

import json
import os
import sys
from datetime import datetime
from typing import Dict, Any, List

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

SEEN_JOBS_PATH = os.path.join(WORKSPACE_DIR, "job_scraper/seen_jobs.json")
WATCHLIST_PATH = os.path.join(WORKSPACE_DIR, "data/company_watchlist.json")
TRACKER_PATH = os.path.join(WORKSPACE_DIR, "job_search_tracker.csv")

from tools.discovery_engine import run_discovery
from tools.normalization import (
    clean_url,
    extract_requisition_id,
    generate_canonical_job_id,
    merge_job_records,
    is_employer_source
)
from tools.ats_verifier import verify_ats_requisition
from tools.freshness_engine import evaluate_freshness
from tools.company_tier_model import resolve_company_tier
from tools.compensation_engine import evaluate_compensation
from tools.evaluator import (
    evaluate_hard_gates,
    evaluate_job_calibrated,
    calculate_application_priority,
    classify_role_family
)

def load_applied_set() -> set:
    """Reads job_search_tracker.csv to extract already-applied companies+roles and URLs."""
    applied = set()
    if os.path.exists(TRACKER_PATH):
        try:
            with open(TRACKER_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split(",")
                    if len(parts) >= 4:
                        comp = parts[1].strip().lower().strip('"')
                        role = parts[3].strip().lower().strip('"')
                        if comp and role and comp != "company":
                            applied.add(f"{comp}::{role}")
        except Exception:
            pass
    return applied

def format_job_card(job: Dict[str, Any]) -> str:
    """Renders the standardized card format for output."""
    comp_info = job.get("compensation", {})
    tier_info = job.get("company_tier_info", {})
    
    # Salary status label
    sal_status = comp_info.get("salary_status", "unknown")
    if sal_status == "disclosed":
        sal_label = "EMPLOYER DISCLOSED"
    elif sal_status == "estimated":
        sal_label = "ESTIMATED COMPENSATION"
    else:
        sal_label = "COMPENSATION UNKNOWN"

    base_min = comp_info.get("base_min")
    base_max = comp_info.get("base_max")
    base_str = f"₹{base_min}–{base_max}L base" if base_min is not None else "Undisclosed"

    var_min = comp_info.get("variable_min")
    var_max = comp_info.get("variable_max")
    var_str = f"₹{var_min}–{var_max}L annual bonus" if var_min and var_min > 0 else "N/A"

    eq_min = comp_info.get("equity_min")
    eq_max = comp_info.get("equity_max")
    eq_str = f"₹{eq_min}–{eq_max}L RSU/year" if eq_min and eq_min > 0 else "N/A"

    tot_min = comp_info.get("total_comp_min")
    tot_max = comp_info.get("total_comp_max")
    tot_str = f"₹{tot_min}–{tot_max}L total CTC" if tot_min is not None else "Undisclosed"

    conf = comp_info.get("confidence", "low")
    src = comp_info.get("source", "role_inference")
    rec = comp_info.get("source_recency_days", 999)
    level = comp_info.get("level_assumption", "")
    comp_meta = f"{conf} (Source: {src}; Recency: {rec}d; Level: {level})"

    strengths = ", ".join(job.get("strengths", ["Direct stack alignment"]))
    gaps = ", ".join(job.get("gaps", ["None identified"]))

    lines = [
        "=" * 80,
        f"Company: {job.get('company')}",
        f"Role: {job.get('title')}",
        f"Location: {job.get('location')}",
        f"Company Tier: {tier_info.get('tier', 'Tier C')} ({tier_info.get('category', 'product')})",
        f"Canonical URL: {job.get('canonical_url') or job.get('url')}",
        f"Discovery Sources: {job.get('discovered_from', ['pipeline'])}",
        f"Active Status: {job.get('active_status', 'active').capitalize()}",
        f"Freshness: {job.get('freshness', 'fresh')} (verified: {job.get('last_verified_at', 'today')})",
        f"Salary Status: {sal_label}",
        f"Base Range: {base_str}",
        f"Variable Range: {var_str}",
        f"Equity Range: {eq_str}",
        f"Total Comp Range: {tot_str}",
        f"Comp Confidence: {comp_meta}",
        f"Fit Score: {job.get('rank_score', 0)}/100",
        f"Application Priority: {job.get('application_priority_score', 0)}/100 [{job.get('priority_label', 'P2 — Selective')}]",
        f"Main Match: {strengths}",
        f"Main Gap: {gaps}",
        f"YOE: {job.get('yoe_requirement', '3-5 years')} (Candidate: 4 YOE, Standard SWE II fit)",
        f"Primary Stack: Java (JVM) / Apache Kafka / Microservices",
        "=" * 80
    ]
    return "\n".join(lines)

def main():
    print("=== Starting Production Job Search & Qualification Pipeline ===", flush=True)
    
    # -------------------------------------------------------------
    # Stage 0: Load State & Seed Datasets
    # -------------------------------------------------------------
    if os.path.exists(SEEN_JOBS_PATH):
        with open(SEEN_JOBS_PATH, "r", encoding="utf-8") as f:
            seen_data = json.load(f)
    else:
        seen_data = {"seen": {}}
    
    seen_map = seen_data.get("seen", {})
    applied_set = load_applied_set()
    print(f"Loaded {len(seen_map)} existing records from seen_jobs.json and {len(applied_set)} applied roles.", flush=True)

    # -------------------------------------------------------------
    # Stage 1: Discovery (Company-First ATS + Platform Ingestion)
    # -------------------------------------------------------------
    print("\n[Stage 1: Discovery] Ingesting listings across ATS and Platform channels...", flush=True)
    raw_discovered = run_discovery()
    print(f"  -> Total raw listings gathered: {len(raw_discovered)}", flush=True)

    # -------------------------------------------------------------
    # Stage 2: Normalization & Canonical Deduplication
    # -------------------------------------------------------------
    print("\n[Stage 2: Normalization] Resolving canonical identities and deduplicating...", flush=True)
    canonical_candidates: Dict[str, Dict[str, Any]] = {}
    duplicates_merged = 0

    for raw in raw_discovered:
        title = raw.get("title", "").strip()
        comp = raw.get("company", "").strip()
        loc = raw.get("location", "India").strip()
        url = clean_url(raw.get("url", ""))

        if not title or not comp or not url:
            continue

        # Check against tracker
        tracker_key = f"{comp.lower()}::{title.lower()}"
        if tracker_key in applied_set:
            continue

        req_id = raw.get("requisition_id") or extract_requisition_id(url, title, raw.get("description", ""))
        can_id = generate_canonical_job_id(comp, title, loc, url, req_id)

        raw["canonical_job_id"] = can_id
        raw["requisition_id"] = req_id
        raw["canonical_url"] = url
        raw["source_urls"] = [url]
        raw["discovered_from"] = [raw.get("source", "discovery")]
        raw["first_seen"] = raw.get("date", datetime.now().strftime("%Y-%m-%d"))
        raw["last_seen"] = raw.get("date", datetime.now().strftime("%Y-%m-%d"))
        raw["record_origin"] = "production_v2"

        if can_id in canonical_candidates:
            canonical_candidates[can_id] = merge_job_records(canonical_candidates[can_id], raw)
            duplicates_merged += 1
        else:
            canonical_candidates[can_id] = raw

    print(f"  -> Merged {duplicates_merged} duplicates. Unique canonical candidates: {len(canonical_candidates)}", flush=True)

    # -------------------------------------------------------------
    # Stages 3-8: Qualification, Scoring & Gating Loop
    # -------------------------------------------------------------
    qualified_p0_p1 = []
    qualified_p2 = []
    hard_rejected_count = 0
    comp_rejected_count = 0
    freshness_rejected_count = 0

    for can_id, job in list(canonical_candidates.items()):
        title = job.get("title", "")
        comp = job.get("company", "")
        loc = job.get("location", "India")
        url = job.get("canonical_url") or job.get("url", "")
        desc = job.get("description", "")

        # Stage 3: Source Verification (Probes ATS if applicable)
        v_res = verify_ats_requisition(url, title, comp)
        job["active_status"] = v_res.get("status", "active")
        job["last_verified_at"] = v_res.get("verified_at", datetime.now().isoformat())
        job["verification_reason"] = v_res.get("reason", "")

        # Stage 4: Freshness Classification
        fresh_info = evaluate_freshness(job, verification_result=v_res)
        job["freshness"] = fresh_info["freshness"]
        job["freshness_score"] = fresh_info["freshness_score"]
        job["can_apply"] = fresh_info["can_apply"]

        if not fresh_info["can_apply"]:
            freshness_rejected_count += 1
            job["status"] = "expired"
            seen_map[can_id] = job
            continue

        # Stage 5: Company Quality & Tier Resolution
        tier_info = resolve_company_tier(comp)
        job["company_tier_info"] = tier_info
        job["company_tier"] = tier_info["tier"]
        job["company_quality_score"] = tier_info["quality_score"]

        # Stage 6: Compensation Intelligence & Gating
        comp_info = evaluate_compensation(job, company_tier=tier_info["tier"])
        job["compensation"] = comp_info
        job["compensation_score"] = comp_info["compensation_score"]
        job["compensation_decision"] = comp_info["decision"]

        if comp_info["decision"] == "REJECT":
            comp_rejected_count += 1
            job["status"] = "excluded"
            job["gate_reason"] = f"Compensation below ₹42L floor ({comp_info['decision_reason']})"
            seen_map[can_id] = job
            continue

        # Stage 7: Technical Hard Gate Check (YOE >= 8, Stack Mismatch, QA, Mobile)
        passed_hard_gates, gate_reason = evaluate_hard_gates(title, desc, loc)
        if not passed_hard_gates:
            hard_rejected_count += 1
            job["status"] = "excluded"
            job["gate_reason"] = gate_reason
            seen_map[can_id] = job
            continue

        # Stage 7.5: Role Family Classification
        role_family = classify_role_family(title, desc)
        job["role_family"] = role_family

        # Stage 8: Calibrated 5-Dimension Fit Scoring
        eval_res = evaluate_job_calibrated(job)
        fit_score = eval_res["rank_score"]
        
        job["rank_score"] = fit_score
        job["rank_band"] = eval_res["rank_band"]
        job["rank_verdict"] = eval_res["rank_verdict"]
        job["yoe_requirement"] = eval_res["yoe_requirement"]
        job["dimension_scores"] = eval_res["dimension_scores"]
        job["strengths"] = eval_res["strengths"]
        job["gaps"] = eval_res["gaps"]

        # Stage 9: Application Priority Scoring
        comp_fit = comp_info.get("compensation_fit", "acceptable")
        priority_score, priority_tier, priority_label = calculate_application_priority(
            fit_score=fit_score,
            comp_score=comp_info["compensation_score"],
            quality_score=tier_info["quality_score"],
            freshness_score=fresh_info["freshness_score"],
            comp_fit=comp_fit
        )

        job["application_priority_score"] = priority_score
        job["priority_tier"] = priority_tier
        job["priority_label"] = priority_label
        job["status"] = "ranked"
        job["rank_date"] = datetime.now().strftime("%Y-%m-%d")

        # Invariant: Active Candidate vs Historical Record
        is_active_opp = (
            priority_tier in ("P0", "P1", "P2") and
            fresh_info["can_apply"] is True and
            comp_info["decision"] != "REJECT" and
            not (tier_info["tier"] in ("Tier C", "Tier D") and comp_info["salary_status"] == "unknown")
        )
        job["active_candidate"] = is_active_opp
        job["ready_for_application"] = (
            is_active_opp is True and
            priority_tier in ("P0", "P1") and
            comp_fit in ("strong", "acceptable") and
            fresh_info["can_apply"] is True
        )

        seen_map[can_id] = job

        if is_active_opp:
            if priority_tier in ("P0", "P1"):
                qualified_p0_p1.append(job)
            else:
                qualified_p2.append(job)

    # -------------------------------------------------------------
    # Output & Persistence
    # -------------------------------------------------------------
    print(f"\n[Funnel Summary]")
    print(f"  -> Discovered: {len(raw_discovered)}")
    print(f"  -> Deduplicated Canonical: {len(canonical_candidates)}")
    print(f"  -> Freshness Rejected: {freshness_rejected_count}")
    print(f"  -> Compensation Rejected (< ₹42L): {comp_rejected_count}")
    print(f"  -> Hard Gates Rejected (YOE/Stack/QA): {hard_rejected_count}")
    print(f"  -> Qualified P0/P1 Targets: {len(qualified_p0_p1)}")
    print(f"  -> Qualified P2 Selective: {len(qualified_p2)}")

    qualified_p0_p1.sort(key=lambda x: x["application_priority_score"], reverse=True)
    qualified_p2.sort(key=lambda x: x["application_priority_score"], reverse=True)

    print("\n" + "=" * 80)
    print("TOP QUALIFIED OPPORTUNITIES (P0 / P1)")
    print("=" * 80)
    for j in qualified_p0_p1[:10]:
        print(format_job_card(j))

    # Persist updated seen_jobs.json
    seen_data["seen"] = seen_map
    with open(SEEN_JOBS_PATH, "w", encoding="utf-8") as f:
        json.dump(seen_data, f, indent=2, ensure_ascii=False)

    # Save summary report
    summary = {
        "timestamp": datetime.now().isoformat(),
        "total_discovered": len(raw_discovered),
        "canonical_candidates": len(canonical_candidates),
        "comp_rejected": comp_rejected_count,
        "hard_rejected": hard_rejected_count,
        "freshness_rejected": freshness_rejected_count,
        "qualified_p0_p1": qualified_p0_p1,
        "qualified_p2": qualified_p2
    }
    with open(os.path.join(WORKSPACE_DIR, "scratch/pipeline_results.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\nPipeline run completed. Saved {len(seen_map)} total records to {SEEN_JOBS_PATH}", flush=True)

if __name__ == "__main__":
    main()
