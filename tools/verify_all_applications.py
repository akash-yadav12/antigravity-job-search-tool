from tools.profile_loader import get_identity_fact
#!/usr/bin/env python3
"""
Comprehensive verification of all application packages in documents/applications/
Checks directory structure, metadata schema, PDF compilation, and ATS text extraction.
"""

import json
import subprocess
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent

def verify_all():
    apps_base = WORKSPACE / "documents/applications"
    app_dirs = [d for d in apps_base.glob("*/*") if d.is_dir()]

    print(f"Discovered {len(app_dirs)} application directories:\n")

    overall_pass = True

    for d in sorted(app_dirs):
        company = d.parent.name
        role = d.name
        print(f"=== Checking {company} / {role} ===")

        # Check required files
        req_files = ["job_description.md", "application_metadata.json", "cv.tex", "cv.pdf", "cover_letter.tex", "cover_letter.pdf", "tailoring_notes.md"]
        missing = [f for f in req_files if not (d / f).exists()]
        if missing:
            print(f"  [ERROR] Missing files: {missing}")
            overall_pass = False
        else:
            print(f"  [OK] All 7 standard application files present.")

        # Check metadata
        meta_file = d / "application_metadata.json"
        if meta_file.exists():
            with open(meta_file) as f:
                meta = json.load(f)
            # Verify factual notice constraints
            if meta.get("notice_status") != "currently serving notice" or meta.get("last_working_day") != "2026-10-06":
                print(f"  [WARNING] Metadata notice period mismatch: {meta.get('notice_status')}")
            else:
                print(f"  [OK] Metadata notice facts verified (Serving Notice | LWD: 2026-10-06).")

        # Verify CV PDF
        cv_pdf = d / "cv.pdf"
        if cv_pdf.exists():
            res_cv = subprocess.run(["python3", str(WORKSPACE / "tools/verify_pdf.py"), str(cv_pdf), "--pages", "1", "--contains", get_identity_fact("full_name", "Candidate")], capture_output=True, text=True)
            if res_cv.returncode == 0:
                print(f"  [OK] CV PDF verified (1 Page, Clean ATS text).")
            else:
                print(f"  [ERROR] CV PDF verification failed: {res_cv.stderr or res_cv.stdout}")
                overall_pass = False

        # Verify Cover Letter PDF
        cl_pdf = d / "cover_letter.pdf"
        if cl_pdf.exists():
            res_cl = subprocess.run(["python3", str(WORKSPACE / "tools/verify_pdf.py"), str(cl_pdf), "--pages", "1", "--contains", get_identity_fact("full_name", "Candidate")], capture_output=True, text=True)
            if res_cl.returncode == 0:
                print(f"  [OK] Cover Letter PDF verified (1 Page, Clean ATS text).")
            else:
                print(f"  [ERROR] Cover Letter PDF verification failed: {res_cl.stderr or res_cl.stdout}")
                overall_pass = False

        print()

    print("==================================================================")
    if overall_pass:
        print("ALL APPLICATION PACKAGES VERIFIED SUCCESSFULLY (100% PASS)")
    else:
        print("SOME CHECKS FAILED — SEE LOGS ABOVE")
    print("==================================================================")

if __name__ == "__main__":
    verify_all()
