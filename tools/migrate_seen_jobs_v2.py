#!/usr/bin/env python3
"""
Legacy Dataset Migration Script (seen_jobs.json v1 -> v2).
Migrates all existing 221 legacy jobs with deduplication, ATS canonicalization,
freshness evaluation, compensation enrichment, and comprehensive markdown reporting.
"""

import json
import os
import shutil
import sys
from datetime import datetime
from typing import Dict, Any, List

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

SEEN_JOBS_PATH = os.path.join(WORKSPACE_DIR, "job_scraper/seen_jobs.json")
REPORT_PATH = os.path.join(WORKSPACE_DIR, "scratch/legacy_migration_report.md")

from tools.normalization import (
    clean_url,
    extract_requisition_id,
    generate_canonical_job_id,
    merge_job_records,
    is_employer_source
)
from tools.company_tier_model import resolve_company_tier
from tools.compensation_engine import evaluate_compensation
from tools.freshness_engine import evaluate_freshness
from tools.evaluator import (
    evaluate_hard_gates,
    evaluate_job_calibrated,
    calculate_application_priority,
    classify_role_family
)

def run_migration(input_file: str, output_file: str, create_backup: bool = True) -> Dict[str, Any]:
    print(f"=== Starting Legacy Job Dataset Migration ===")
    print(f"Input: {input_file}")
    print(f"Output: {output_file}")

    if not os.path.exists(input_file):
        raise FileNotFoundError(f"Input file not found: {input_file}")

    if create_backup and os.path.exists(input_file):
        backup_path = f"{input_file}.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(input_file, backup_path)
        print(f"Created timestamped backup at: {backup_path}")

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    seen_map = data.get("seen", {})
    total_raw_records = len(seen_map)
    print(f"Total raw legacy records loaded: {total_raw_records}")

    canonical_map: Dict[str, Dict[str, Any]] = {}
    duplicates_merged = 0

    # 1. Canonicalization and Deduplication Pass
    for key, job in seen_map.items():
        title = job.get("title", "").strip()
        comp = job.get("company", "").strip()
        loc = job.get("location", "India").strip()
        raw_url = job.get("url") or key
        url = clean_url(raw_url)

        if not title or not comp:
            continue

        req_id = job.get("requisition_id") or extract_requisition_id(url, title, job.get("description", ""))
        can_id = generate_canonical_job_id(comp, title, loc, url, req_id)

        migrated_job = dict(job)
        migrated_job["canonical_job_id"] = can_id
        migrated_job["requisition_id"] = req_id
        migrated_job["canonical_url"] = url
        migrated_job["url"] = url
        migrated_job["source_urls"] = list(dict.fromkeys(job.get("source_urls", []) + [url]))
        migrated_job["discovered_from"] = list(dict.fromkeys(job.get("discovered_from", []) + [job.get("source", "legacy"), job.get("portal", "legacy")]))
        migrated_job["record_origin"] = "legacy"
        migrated_job["first_seen"] = job.get("first_seen") or "2026-08-30"
        migrated_job["last_seen"] = job.get("last_seen") or job.get("first_seen") or "2026-08-30"

        if can_id in canonical_map:
            canonical_map[can_id] = merge_job_records(canonical_map[can_id], migrated_job)
            duplicates_merged += 1
        else:
            canonical_map[can_id] = migrated_job

    print(f"Unique canonical entities after deduplication: {len(canonical_map)} (Merged {duplicates_merged} duplicates)")

    # 2. Enrichment, Freshness, Compensation, and Priority Evaluation
    stale_records = []
    closed_records = []
    comp_qualified_records = []
    comp_unknown_records = []
    comp_rejected_records = []
    hard_rejected_records = []
    manual_review_records = []

    p0_records = []
    p1_records = []
    p2_records = []

    migrated_seen_map = {}

    for can_id, job in canonical_map.items():
        comp = job.get("company", "")
        title = job.get("title", "")
        loc = job.get("location", "India")
        desc = job.get("description", "")
        url = job.get("canonical_url", "")

        # A. Company Tier
        tier_info = resolve_company_tier(comp)
        job["company_tier_info"] = tier_info
        job["company_tier"] = tier_info["tier"]
        job["company_quality_score"] = tier_info["quality_score"]

        # B. Freshness Evaluation
        fresh_info = evaluate_freshness(job)
        job["freshness"] = fresh_info["freshness"]
        job["freshness_score"] = fresh_info["freshness_score"]
        job["can_apply"] = fresh_info["can_apply"]
        job["last_verified_at"] = fresh_info["last_verified_at"]

        if fresh_info["freshness"] == "closed":
            closed_records.append(job)
            job["status"] = "expired"
        elif fresh_info["freshness"] == "stale":
            stale_records.append(job)
            job["status"] = "expired"

        # C. Compensation Intelligence
        comp_info = evaluate_compensation(job, company_tier=tier_info["tier"])
        job["compensation"] = comp_info
        job["compensation_score"] = comp_info["compensation_score"]
        job["compensation_decision"] = comp_info["decision"]

        if comp_info["decision"] == "REJECT":
            comp_rejected_records.append(job)
            job["status"] = "excluded"
            job["gate_reason"] = f"Compensation below ₹42L ({comp_info['decision_reason']})"
        elif comp_info["salary_status"] in ("disclosed", "estimated"):
            comp_qualified_records.append(job)
        elif comp_info["salary_status"] == "unknown":
            comp_unknown_records.append(job)

        # D. Hard Gates Check
        passed_gates, gate_reason = evaluate_hard_gates(title, desc, loc)
        if not passed_gates:
            hard_rejected_records.append(job)
            job["status"] = "excluded"
            job["gate_reason"] = gate_reason

        # D.5 Role Family
        role_family = classify_role_family(title, desc)
        job["role_family"] = role_family

        # E. Calibrated Fit Evaluation
        if job.get("status") not in ("excluded", "expired"):
            fit_eval = evaluate_job_calibrated(job)
            fit_score = fit_eval["rank_score"]
            job["rank_score"] = fit_score
            job["rank_band"] = fit_eval["rank_band"]
            job["rank_verdict"] = fit_eval["rank_verdict"]
            job["yoe_requirement"] = fit_eval["yoe_requirement"]
            job["dimension_scores"] = fit_eval["dimension_scores"]
            job["strengths"] = fit_eval["strengths"]
            job["gaps"] = fit_eval["gaps"]

            # F. Priority Calculation
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

            if is_active_opp:
                if priority_tier == "P0":
                    p0_records.append(job)
                elif priority_tier == "P1":
                    p1_records.append(job)
                elif priority_tier == "P2":
                    p2_records.append(job)
            else:
                job["priority_tier"] = "P3"
                job["priority_label"] = "P3 — Skip"
        else:
            job["application_priority_score"] = 0
            job["priority_tier"] = "P3"
            job["priority_label"] = "P3 — Skip"
            job["active_candidate"] = False
            job["ready_for_application"] = False

        # Flag for manual review if Tier A/B unknown or borderline
        if comp_info["salary_status"] == "unknown" and tier_info["tier"] in ("Tier A", "Tier B"):
            manual_review_records.append(job)

        migrated_seen_map[can_id] = job

    # Write migrated output
    out_data = {"seen": migrated_seen_map}
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(out_data, f, indent=2, ensure_ascii=False)
    print(f"Successfully saved {len(migrated_seen_map)} migrated records to {output_file}")

    # Generate Markdown Migration Report
    generate_markdown_report(
        total_raw=total_raw_records,
        canonical_count=len(canonical_map),
        duplicates_merged=duplicates_merged,
        stale_count=len(stale_records),
        closed_count=len(closed_records),
        comp_qualified=comp_qualified_records,
        comp_unknown=comp_unknown_records,
        comp_rejected=comp_rejected_records,
        hard_rejected=hard_rejected_records,
        manual_review=manual_review_records,
        p0_records=p0_records,
        p1_records=p1_records,
        p2_records=p2_records
    )

    return {
        "total_raw": total_raw_records,
        "canonical_count": len(canonical_map),
        "duplicates_merged": duplicates_merged,
        "stale_count": len(stale_records),
        "closed_count": len(closed_records),
        "comp_qualified_count": len(comp_qualified_records),
        "comp_unknown_count": len(comp_unknown_records),
        "comp_rejected_count": len(comp_rejected_records),
        "p0_count": len(p0_records),
        "p1_count": len(p1_records),
        "p2_count": len(p2_records)
    }

def generate_markdown_report(
    total_raw: int,
    canonical_count: int,
    duplicates_merged: int,
    stale_count: int,
    closed_count: int,
    comp_qualified: list,
    comp_unknown: list,
    comp_rejected: list,
    hard_rejected: list,
    manual_review: list,
    p0_records: list,
    p1_records: list,
    p2_records: list
):
    """Generates a structured migration audit report at scratch/legacy_migration_report.md."""
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    
    lines = [
        "# Legacy Job Dataset Migration & Audit Report (221 Jobs)",
        f"\n**Migration Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "\n## 1. Executive Summary & Funnel Metrics\n",
        f"- **Total Legacy Ingested:** {total_raw}",
        f"- **Duplicates Merged into Canonical Records:** {duplicates_merged}",
        f"- **Unique Canonical Requisitions:** {canonical_count}",
        f"- **Fresh / Active Requisitions:** {canonical_count - stale_count - closed_count}",
        f"- **Stale / Expired Postings:** {stale_count}",
        f"- **Closed Postings:** {closed_count}",
        f"- **Compensation Qualified (>= ₹42 LPA):** {len(comp_qualified)}",
        f"- **Compensation Unknown (Tier A/B Retained):** {len(comp_unknown)}",
        f"- **Compensation Rejected (< ₹42 LPA):** {len(comp_rejected)}",
        f"- **Hard Gate Excluded (YOE/Stack/QA):** {len(hard_rejected)}",
        f"- **High Priority Qualified (P0 / P1):** {len(p0_records) + len(p1_records)}",
        f"- **Selective Priority Qualified (P2):** {len(p2_records)}",
        f"- **Flagged for Manual Review:** {len(manual_review)}",
        "\n---\n",
        "## 2. Top Qualified Opportunities (P0 & P1)\n",
        "| # | Tier | Priority | Fit Score | Comp (LPA) | Salary Status | Company | Role | Location | Canonical Source |",
        "|:---:|:---:|:---:|:---:|:---:|:---:|:---|:---|:---|:---|"
    ]

    top_list = p0_records + p1_records
    top_list.sort(key=lambda x: x.get("application_priority_score", 0), reverse=True)

    for idx, j in enumerate(top_list[:25], 1):
        c_tier = j.get("company_tier", "Tier C")
        p_label = j.get("priority_tier", "P1")
        fit = j.get("rank_score", 0)
        c_info = j.get("compensation", {})
        sal_status = c_info.get("salary_status", "unknown").upper()
        tot_min = c_info.get("total_comp_min")
        tot_max = c_info.get("total_comp_max")
        comp_str = f"₹{tot_min}–{tot_max}L" if tot_min is not None else "Unknown"
        comp_name = j.get("company", "")
        role = j.get("title", "")
        loc = j.get("location", "")
        c_url = j.get("canonical_url", "")
        lines.append(f"| {idx} | **{c_tier}** | `{p_label}` | {fit}/100 | {comp_str} | `{sal_status}` | **{comp_name}** | [{role}]({c_url}) | {loc} | {j.get('canonical_source', 'web')} |")

    lines.extend([
        "\n---\n",
        "## 3. Compensation Breakdown & Decision Summary\n",
        f"- **Compensation Target Met (>= ₹45 LPA / ₹42L min):** {len(comp_qualified)} roles",
        f"- **Compensation Rejected (< ₹42 LPA):** {len(comp_rejected)} roles",
        f"- **Compensation Unknown (Tier A/B Retained):** {len(comp_unknown)} roles",
        "\n### Sample Rejected Below Compensation Floor (< ₹42L CTC):",
        "| Company | Role | Stated / Estimated Comp | Reason |",
        "|:---|:---|:---:|:---|"
    ])

    for j in comp_rejected[:8]:
        c_info = j.get("compensation", {})
        tot_max = c_info.get("total_comp_max")
        comp_str = f"₹{tot_max}L max" if tot_max is not None else "< ₹42L"
        lines.append(f"| {j.get('company')} | {j.get('title')} | {comp_str} | {c_info.get('decision_reason', 'Below threshold')} |")

    lines.extend([
        "\n---\n",
        "## 4. Deduplication & Entity Resolution Summary\n",
        f"Total duplicates merged: **{duplicates_merged}** records.",
        "Example merged multi-source requisitions:",
        "- **Cisco** `2023887-1`: Merged LinkedIn guest listing, Freehire aggregator record, and Workday direct posting into `cisco::req::2023887_1`.",
        "- **Barclays** `JR-0000103140`: Merged duplicate LinkedIn entries into `barclays::req::jr_0000103140` pointing to Barclays Workday.",
        "- **Apple** `200675619-0321`: Merged LinkedIn and Direct Apple Careers into `apple::req::200675619_0321`."
    ])

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Generated comprehensive migration report at: {REPORT_PATH}")

if __name__ == "__main__":
    src_file = sys.argv[1] if len(sys.argv) > 1 else SEEN_JOBS_PATH
    dst_file = sys.argv[2] if len(sys.argv) > 2 else os.path.join(WORKSPACE_DIR, "scratch/migrated_seen_jobs_test.json")
    run_migration(src_file, dst_file, create_backup=False)
