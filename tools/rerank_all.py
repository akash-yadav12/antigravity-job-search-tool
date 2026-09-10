#!/usr/bin/env python3
"""
Calibrated Re-Ranking Script for all 221 jobs in job_scraper/seen_jobs.json.
Applies Hard Gates, Zero-Baseline 5-Dimension Evaluation, Anomaly Checks, and Persistence.
"""

import json
import os
import re
import sys
import statistics
from datetime import datetime
from evaluator import evaluate_hard_gates, evaluate_job_calibrated, DEEP_DOMAIN_MISMATCHES

WORKSPACE_DIR = str(Path(__file__).resolve().parent.parent)
SEEN_JOBS_PATH = os.path.join(WORKSPACE_DIR, "job_scraper/seen_jobs.json")

def main():
    print("=== Starting Full Calibrated Re-Ranking Batch ===")
    
    if not os.path.exists(SEEN_JOBS_PATH):
        print(f"Error: {SEEN_JOBS_PATH} not found!", file=sys.stderr)
        sys.exit(1)

    with open(SEEN_JOBS_PATH, "r") as f:
        seen_data = json.load(f)

    seen_map = seen_data.get("seen", {})
    total_jobs = len(seen_map)
    print(f"Total jobs in seen_jobs.json: {total_jobs}")

    hard_rejected = []
    ranked_jobs = []
    anomalies = []

    for key, job in seen_map.items():
        title = job.get("title", "")
        company = job.get("company", "")
        location = job.get("location", "India")
        description = job.get("description", "")
        url = job.get("url", key)

        # 1. Hard Gate Check
        passed_gate, gate_reason = evaluate_hard_gates(title, description, location)
        
        if not passed_gate:
            job["status"] = "excluded"
            job["rank_score"] = 0
            job["rank_band"] = "Excluded"
            job["rank_verdict"] = "hard reject"
            job["gate_reason"] = gate_reason
            job["rank_date"] = datetime.now().strftime("%Y-%m-%d")
            hard_rejected.append({
                "key": key,
                "title": title,
                "company": company,
                "reason": gate_reason
            })
            continue

        # 2. Calibrated Evaluation
        eval_res = evaluate_job_calibrated(job)
        
        # Update job fields while preserving existing metadata
        job["status"] = "ranked"
        job["rank_score"] = eval_res["rank_score"]
        job["rank_band"] = eval_res["rank_band"]
        job["rank_verdict"] = eval_res["rank_verdict"]
        job["rank_date"] = datetime.now().strftime("%Y-%m-%d")
        job["location_verdict"] = "PASS"
        job["language_gate"] = "PASS"
        job["yoe_requirement"] = eval_res["yoe_requirement"]
        job["dimension_scores"] = eval_res["dimension_scores"]
        job["strengths"] = eval_res["strengths"]
        job["gaps"] = eval_res["gaps"]
        job["priority"] = eval_res["priority"]

        ranked_jobs.append(job)

    # 3. Anomaly Verification Check
    print("\n--- Running Strict Anomaly Checks on Scored Batch ---")
    
    for j in ranked_jobs:
        score = j["rank_score"]
        title = j.get("title", "")
        desc = j.get("description", "")
        full_text = f"{title} {desc}".lower()

        # Check 1: 7+ YOE jobs above 85
        if re.search(r'\b(7\+|7\s*years|7\s*yrs|7\s*yoe)\b', full_text) and score > 85:
            anomalies.append(f"Anomaly: 7+ YOE job scored > 85: '{title}' at '{j.get('company')}' (Score: {score})")

        # Check 2: 8+ YOE jobs not rejected
        if re.search(r'\b(8\+|8\s*to\s*12|8-12|10\+|12\+)\s*(years|yrs|yoe)\b', full_text):
            anomalies.append(f"Anomaly: 8+ YOE job was not hard-rejected: '{title}' at '{j.get('company')}' (Score: {score})")

        # Check 3: Python/Go/C# primary jobs above 85
        if any(k in title.lower() for k in ["python developer", "golang engineer", "go engineer", "scala developer", "c# developer", "rust developer"]) and score > 85:
            anomalies.append(f"Anomaly: Non-Java primary job scored > 85: '{title}' at '{j.get('company')}' (Score: {score})")

        # Check 4: Deep domain mismatch above 70
        for domain_name, keywords in DEEP_DOMAIN_MISMATCHES:
            if any(k in full_text for k in keywords) and score > 70:
                anomalies.append(f"Anomaly: Domain mismatch '{domain_name}' scored > 70: '{title}' at '{j.get('company')}' (Score: {score})")

    if anomalies:
        print(f"\n[CRITICAL] {len(anomalies)} Anomalies Detected:")
        for a in anomalies:
            print(f"  - {a}")
        print("\nStopping before persistence as requested.", file=sys.stderr)
        sys.exit(1)
    else:
        print("[SUCCESS] Zero anomalies detected! Scoring passed all verification rules.")

    # 4. Statistical Distribution Calculation
    scores = [j["rank_score"] for j in ranked_jobs]
    ge_90 = [j for j in ranked_jobs if j["rank_score"] >= 90]
    sc_80_89 = [j for j in ranked_jobs if 80 <= j["rank_score"] <= 89]
    sc_70_79 = [j for j in ranked_jobs if 70 <= j["rank_score"] <= 79]
    sc_60_69 = [j for j in ranked_jobs if 60 <= j["rank_score"] <= 69]
    lt_60 = [j for j in ranked_jobs if j["rank_score"] < 60]

    median_score = statistics.median(scores) if scores else 0
    mean_score = statistics.mean(scores) if scores else 0

    print("\n=======================================================")
    print(f"TOTAL JOBS PROCESSED: {total_jobs}")
    print(f"HARD REJECTED: {len(hard_rejected)}")
    print(f"SUCCESSFULLY RANKED: {len(ranked_jobs)}")
    print("-------------------------------------------------------")
    print(f"Scores >= 90 (Exceptional): {len(ge_90)} ({len(ge_90)/len(scores)*100:.1f}%)")
    print(f"Scores 80–89 (Strong Fit):  {len(sc_80_89)} ({len(sc_80_89)/len(scores)*100:.1f}%)")
    print(f"Scores 70–79 (Good Fit):    {len(sc_70_79)} ({len(sc_70_79)/len(scores)*100:.1f}%)")
    print(f"Scores 60–69 (Borderline):  {len(sc_60_69)} ({len(sc_60_69)/len(scores)*100:.1f}%)")
    print(f"Scores < 60  (Moderate/Low):{len(lt_60)} ({len(lt_60)/len(scores)*100:.1f}%)")
    print(f"Median Score: {median_score}")
    print(f"Mean Score:   {mean_score:.2f}")
    print("=======================================================\n")

    # 5. Persist to seen_jobs.json
    with open(SEEN_JOBS_PATH, "w") as f:
        json.dump(seen_data, f, indent=2)
    print(f"Persisted all {total_jobs} updated job records to {SEEN_JOBS_PATH}")

    # 6. Sort and Dump Summary
    ranked_jobs.sort(key=lambda x: x["rank_score"], reverse=True)
    
    summary = {
        "total_jobs": total_jobs,
        "hard_rejected_count": len(hard_rejected),
        "ranked_count": len(ranked_jobs),
        "scores_ge_90": len(ge_90),
        "scores_80_89": len(sc_80_89),
        "scores_70_79": len(sc_70_79),
        "scores_60_69": len(sc_60_69),
        "scores_lt_60": len(lt_60),
        "median_score": median_score,
        "mean_score": round(mean_score, 2),
        "top_25": ranked_jobs[:25],
        "all_ranked": ranked_jobs,
        "hard_rejected_sample": hard_rejected[:10]
    }

    with open(os.path.join(WORKSPACE_DIR, "scratch/calibrated_rerank_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print("Saved summary report to scratch/calibrated_rerank_summary.json")

if __name__ == "__main__":
    main()
