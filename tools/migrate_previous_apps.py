#!/usr/bin/env python3
"""
Migrates Nexthink and Gloify into canonical documents/applications/<Company>/<Role>/ format
and cleans up orphaned files from cv/ and cover_letters/.
"""

import os
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent

def migrate_prev():
    # Nexthink
    nexthink_dir = WORKSPACE / "documents/applications/Nexthink/Senior_Backend_Software_Engineer"
    nexthink_dir.mkdir(parents=True, exist_ok=True)
    
    cv_src = WORKSPACE / "cv/main_Nexthink_Senior_Backend_Software_Engineer.tex"
    cl_src = WORKSPACE / "cover_letters/cover_Nexthink_Senior_Backend_Software_Engineer.tex"
    jd_src = WORKSPACE / "documents/applications/Nexthink_Senior_Backend_Software_Engineer/job_description.txt"

    if jd_src.exists():
        shutil.copyfile(jd_src, nexthink_dir / "job_description.md")
    if cv_src.exists():
        shutil.copyfile(cv_src, nexthink_dir / "cv.tex")
    if cl_src.exists():
        shutil.copyfile(cl_src, nexthink_dir / "cover_letter.tex")

    meta_nexthink = {
        "company": "Nexthink",
        "role": "Senior Backend Software Engineer (Java)",
        "job_url": "https://in.linkedin.com/jobs/view/senior-backend-software-engineer-java-at-nexthink-4436183162",
        "source": "LinkedIn",
        "location": "Bengaluru, India",
        "fit_score": 86,
        "rank_band": "Strong Fit",
        "resume_narrative": "Backend / Distributed Systems (JVM & Observability)",
        "status": "drafted",
        "applied_date": None,
        "notice_status": "currently serving notice",
        "last_working_day": "2026-10-06",
        "earliest_joining_date": "after 2026-10-06",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    with open(nexthink_dir / "application_metadata.json", "w") as f:
        json.dump(meta_nexthink, f, indent=2)

    tailoring_nexthink = """# Application Tailoring Notes: Nexthink — Senior Backend Software Engineer (Java)

- **Fit Score:** 86 (Strong Fit)
- **Selected Narrative:** Backend / Distributed Systems (JVM & Observability)
- **Status:** Drafted (Review Completed)
- **Notice Period / Availability:** Currently serving notice | LWD: 6 October 2026 | Joining: after 6 October 2026

## Tailoring Rationale
Emphasized Java (17/21), Micronaut, Apache Kafka event streaming, 2M+ record AWS S3 cloud data migration, and AI developer productivity tooling.

## Gaps & Risk Analysis
No material gap identified across JVM backend, Kafka streaming, cloud architecture, and testing dimensions.
"""
    with open(nexthink_dir / "tailoring_notes.md", "w") as f:
        f.write(tailoring_nexthink)

    # Symlinks
    cls_link = nexthink_dir / "cover.cls"
    fonts_link = nexthink_dir / "OpenFonts"
    if cls_link.exists() or cls_link.is_symlink(): cls_link.unlink()
    if fonts_link.exists() or fonts_link.is_symlink(): fonts_link.unlink()
    cls_link.symlink_to("../../../../cover_letters/cover.cls")
    fonts_link.symlink_to("../../../../cover_letters/OpenFonts")

    # Compile
    subprocess.run(["/usr/local/texlive/2026/bin/universal-darwin/lualatex", "-interaction=nonstopmode", "-halt-on-error", "cv.tex"], cwd=nexthink_dir, check=True)
    subprocess.run(["/usr/local/texlive/2026/bin/universal-darwin/xelatex", "-interaction=nonstopmode", "-halt-on-error", "cover_letter.tex"], cwd=nexthink_dir, check=True)

    # Clean up old Nexthink files
    for ext in [".tex", ".pdf", ".log", ".aux", ".out"]:
        p1 = WORKSPACE / f"cv/main_Nexthink_Senior_Backend_Software_Engineer{ext}"
        if p1.exists(): p1.unlink()
        p2 = WORKSPACE / f"cover_letters/cover_Nexthink_Senior_Backend_Software_Engineer{ext}"
        if p2.exists(): p2.unlink()
    old_nexthink_dir = WORKSPACE / "documents/applications/Nexthink_Senior_Backend_Software_Engineer"
    if old_nexthink_dir.exists():
        shutil.rmtree(old_nexthink_dir)

    # Gloify
    gloify_dir = WORKSPACE / "documents/applications/Gloify/Java_Software_Engineer"
    gloify_dir.mkdir(parents=True, exist_ok=True)
    cv_gloify = WORKSPACE / "cv/main_Gloify_Java_Software_Engineer.tex"
    cl_gloify = WORKSPACE / "cover_letters/cover_Gloify_Java_Software_Engineer.tex"
    old_gloify_dir = WORKSPACE / "documents/applications/Gloify_Java_Software_Engineer"
    
    if (old_gloify_dir / "job_posting.md").exists():
        shutil.copyfile(old_gloify_dir / "job_posting.md", gloify_dir / "job_description.md")
    if (old_gloify_dir / "interview_prep_technical.md").exists():
        shutil.copyfile(old_gloify_dir / "interview_prep_technical.md", gloify_dir / "interview_prep.md")
    if cv_gloify.exists():
        shutil.copyfile(cv_gloify, gloify_dir / "cv.tex")
    if cl_gloify.exists():
        shutil.copyfile(cl_gloify, gloify_dir / "cover_letter.tex")

    meta_gloify = {
        "company": "Gloify",
        "role": "Java Software Engineer",
        "job_url": "https://jobs.smartrecruiters.com/Gloify/743999741970976-java",
        "source": "SmartRecruiters",
        "location": "Bengaluru, India",
        "fit_score": 82,
        "rank_band": "Strong Fit",
        "resume_narrative": "Backend / Distributed Systems",
        "status": "drafted",
        "applied_date": None,
        "notice_status": "currently serving notice",
        "last_working_day": "2026-10-06",
        "earliest_joining_date": "after 2026-10-06",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    with open(gloify_dir / "application_metadata.json", "w") as f:
        json.dump(meta_gloify, f, indent=2)

    # Clean up old Gloify files
    for ext in [".tex", ".pdf", ".log", ".aux", ".out"]:
        p1 = WORKSPACE / f"cv/main_Gloify_Java_Software_Engineer{ext}"
        if p1.exists(): p1.unlink()
        p2 = WORKSPACE / f"cover_letters/cover_Gloify_Java_Software_Engineer{ext}"
        if p2.exists(): p2.unlink()
    if old_gloify_dir.exists():
        shutil.rmtree(old_gloify_dir)

    print("Completed migration for Nexthink and Gloify.")

if __name__ == "__main__":
    migrate_prev()
