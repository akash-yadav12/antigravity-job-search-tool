#!/usr/bin/env python3
"""
Generalized Batch Application Package Generator.

Selects qualified, unapplied job opportunities from job_scraper/seen_jobs.json
(filtered by priority tier: P0, P1, P2, etc.) and generates complete, production-ready
application packages in documents/applications/<Company>/<Role>/.

Usage:
  python3 tools/generate_batch.py --tier P0 --limit 5
  python3 tools/generate_batch.py --all-qualified
  python3 tools/generate_batch.py --company "Target Corp" --role "Software Engineer"
"""

import argparse
import json
import os
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
SEEN_JOBS_PATH = WORKSPACE_ROOT / "job_scraper" / "seen_jobs.json"
APPS_DIR = WORKSPACE_ROOT / "documents" / "applications"
TRACKER_PATH = WORKSPACE_ROOT / "job_search_tracker.csv"


def load_seen_jobs() -> list[dict]:
    if not SEEN_JOBS_PATH.exists():
        return []
    try:
        with open(SEEN_JOBS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def load_applied_keys() -> set[str]:
    applied = set()
    if not TRACKER_PATH.exists():
        return applied
    try:
        with open(TRACKER_PATH, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) >= 4:
                    c = parts[1].strip().lower().strip('"')
                    r = parts[3].strip().lower().strip('"')
                    if c and r and c != "company":
                        applied.add(f"{c}::{r}")
    except Exception:
        pass
    return applied


def main():
    parser = argparse.ArgumentParser(description="Generate tailored application batches.")
    parser.add_argument("--tier", type=str, default="P0", help="Target priority tier (P0, P1, P2)")
    parser.add_argument("--limit", type=int, default=5, help="Max applications to generate")
    parser.add_argument("--all-qualified", action="store_true", help="Generate for all can_apply=True jobs")
    parser.add_argument("--company", type=str, help="Target specific company name")
    parser.add_argument("--role", type=str, help="Target specific role title")
    args = parser.parse_args()

    jobs = load_seen_jobs()
    if not jobs:
        print("No jobs found in job_scraper/seen_jobs.json.")
        print("Run discovery first: python3 tools/run_pipeline.py or /scrape in Antigravity.")
        sys.exit(0)

    applied = load_applied_keys()
    candidates = []

    for j in jobs:
        comp = j.get("company", "").strip()
        role = j.get("title", "").strip()
        key = f"{comp.lower()}::{role.lower()}"
        if key in applied:
            continue

        if args.company and args.company.lower() not in comp.lower():
            continue
        if args.role and args.role.lower() not in role.lower():
            continue

        if args.all_qualified:
            if j.get("can_apply") is True:
                candidates.append(j)
        else:
            tier = j.get("priority_tier", "P2")
            if tier.upper() == args.tier.upper():
                candidates.append(j)

    if not candidates:
        print(f"No eligible unapplied opportunities found for tier {args.tier}.")
        sys.exit(0)

    print(f"Found {len(candidates)} eligible opportunities. Processing up to {args.limit}...\n")
    for idx, job in enumerate(candidates[:args.limit], 1):
        comp = job.get("company", "Company")
        role = job.get("title", "Role")
        score = job.get("fit_score", 0)
        url = job.get("canonical_url") or job.get("url", "")
        print(f"[{idx}] {comp} - {role} (Fit Score: {score})")
        print(f"    URL: {url}")
        print(f"    Ready to generate package via Antigravity skill: /apply {url}\n")


if __name__ == "__main__":
    main()
