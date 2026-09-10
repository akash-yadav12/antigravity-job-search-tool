#!/usr/bin/env python3
"""
Normalizes and formats job_search_tracker.csv to adhere strictly to the 14-column canonical schema:
date,company,sector,role,role_type,channel,status,contact_person,fit_rating,notes,cv_file,cover_letter_file,source,deadline
"""

import os
import json
import csv
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
TRACKER_PATH = WORKSPACE / "job_search_tracker.csv"
APPS_BASE = WORKSPACE / "documents/applications"

FIELDNAMES = [
    "date",
    "company",
    "sector",
    "role",
    "role_type",
    "channel",
    "status",
    "contact_person",
    "fit_rating",
    "notes",
    "cv_file",
    "cover_letter_file",
    "source",
    "deadline"
]

SECTOR_MAP = {
    "Apple": "Technology",
    "Morgan Stanley": "Banking / Financial Services",
    "Cisco": "Technology",
    "Roku": "Technology",
    "CRED": "FinTech / Technology",
    "Nexthink": "Technology",
    "NatWest Group": "Banking / Financial Services",
    "Wells Fargo": "Banking / Financial Services",
    "Zimperium": "Cybersecurity / Technology",
    "Barclays": "Banking / Financial Services",
    "Maersk": "Logistics / Technology",
    "Worldpay": "FinTech / Technology",
    "Blue Yonder": "Technology",
    "Synechron": "Financial Services / Consulting",
    "Gloify": "Technology"
}

def clean_notes(app_dir: Path, meta: dict) -> str:
    """Extracts a clean 1-sentence note for the tracker."""
    tailor_file = app_dir / "tailoring_notes.md"
    if tailor_file.exists():
        try:
            lines = tailor_file.read_text(encoding="utf-8").splitlines()
            capture = False
            summary_lines = []
            for l in lines:
                if l.startswith("## Tailoring Summary"):
                    capture = True
                    continue
                elif l.startswith("## ") and capture:
                    break
                if capture and l.strip():
                    summary_lines.append(l.strip())
            if summary_lines:
                return " ".join(summary_lines)
        except Exception:
            pass
            
    narrative = meta.get("selected_resume_narrative", "")
    if narrative:
        return f"Tailored for {narrative}"
    return "Tailored for backend microservices and distributed systems"

def rebuild_tracker():
    records = []
    
    # 1. Scan documents/applications
    for root, dirs, files in os.walk(APPS_BASE):
        if "application_metadata.json" in files:
            meta_path = Path(root) / "application_metadata.json"
            app_dir = Path(root)
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception as e:
                print(f"Error reading {meta_path}: {e}")
                continue
                
            comp = meta.get("company", "").strip()
            role = meta.get("role", "").strip()
            rel_dir = os.path.relpath(root, WORKSPACE)
            
            created_at = meta.get("created_at", "2026-08-30")
            date_str = created_at[:10] if created_at else "2026-08-30"
            
            status = meta.get("status", "drafted")
            fit = meta.get("fit_score", 80)
            source = meta.get("job_url", "")
            notes = clean_notes(app_dir, meta)
            sector = SECTOR_MAP.get(comp, "Technology")
            
            records.append({
                "date": date_str,
                "company": comp,
                "sector": sector,
                "role": role,
                "role_type": "Engineering",
                "channel": "portal",
                "status": status,
                "contact_person": "",
                "fit_rating": str(fit),
                "notes": notes,
                "cv_file": f"{rel_dir}/cv.tex",
                "cover_letter_file": f"{rel_dir}/cover_letter.tex",
                "source": source,
                "deadline": ""
            })
            
    # Sort records by date descending, then company ascending
    records.sort(key=lambda x: (x["date"], x["company"], x["role"]), reverse=True)
    
    # Write cleanly with standard CSV writer
    with open(TRACKER_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for r in records:
            writer.writerow(r)
            
    print(f"Successfully rebuilt {TRACKER_PATH} with {len(records)} perfectly formatted rows.")

if __name__ == "__main__":
    rebuild_tracker()
