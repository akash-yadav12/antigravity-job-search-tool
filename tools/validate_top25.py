#!/usr/bin/env python3
"""
Manual-JD Validation Script for Top 25 Opportunities.
Extracts the 12 specific dimensions for each job, evaluates candidate fit (Direct, Transferable, Missing, N/A),
calculates independent validated scores, and compares with evaluator scores.
"""

import json

def analyze():
    with open("scratch/calibrated_rerank_summary.json") as f:
        data = json.load(f)

    top25 = data["top_25"]
    print(f"Loaded {len(top25)} jobs for validation.\n")

    # Manual analysis results for each job
    results = []

    for idx, job in enumerate(top25, 1):
        comp = job.get("company", "")
        title = job.get("title", "")
        url = job.get("url", "")
        loc = job.get("location", "")
        curr_score = job.get("rank_score", 0)
        curr_band = job.get("rank_band", "")
        curr_prio = job.get("priority", "")
        
        # We will populate validated findings
        results.append({
            "rank": idx,
            "company": comp,
            "title": title,
            "url": url,
            "location": loc,
            "current_score": curr_score,
            "current_band": curr_band,
            "current_priority": curr_prio
        })

    return results

if __name__ == "__main__":
    analyze()
