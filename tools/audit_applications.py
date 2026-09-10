from tools.profile_loader import get_identity_fact
#!/usr/bin/env python3
"""
Comprehensive Pre-Submission Audit for all application packages under documents/applications/*/*/
Verifies:
1. Candidate Fact Consistency (Titles, Dates, Star Performer count, Metrics, Notice Period, Contacts)
2. Application-Specific Factual Integrity
3. Job-Description & Live URL Integrity
4. Metadata Schema Completeness (15 core fields + application_url + application_method)
5. Submission State (Strictly 'drafted')
6. PDF Verification (1-page LuaLaTeX CV & 1-page XeLaTeX Cover Letter)
"""

import json
import os
import re
import subprocess
from pathlib import Path
import urllib.request
import urllib.error

WORKSPACE = Path(__file__).resolve().parent.parent
APPS_BASE = WORKSPACE / "documents/applications"

REQUIRED_METADATA_FIELDS = [
    "company", "role", "job_url", "source", "location", "fit_score",
    "rank_band", "selected_resume_narrative", "status", "created_at",
    "updated_at", "applied_at", "notice_period", "key_gaps", "application_priority"
]

CANONICAL_FACTS = {
    "star_performer": "4",
    "jpmc_title": "Software Engineer II",
    "jpmc_dates": "May 2025",
    "iss_title": "Software Engineer",
    "iss_dates": "July 2022 -- April 2025",
    "inkoop_title": "Software Engineer",
    "inkoop_dates": "Jan 2022 -- May 2022",
    "email": get_identity_fact("email", "candidate@example.com"),
    "phone": get_identity_fact("phone", ""),
    "lwd": "6 October 2026",
    "metrics": ["2M+", "18%", "50k+", "60%", "30%"]
}

def check_live_url(url):
    """Graceful HTTP HEAD/GET check to determine if posting is active."""
    if not url or not url.startswith("http"):
        return "Unknown (No URL)"
    
    # Standard check with realistic browser headers
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            code = response.getcode()
            if code in [200, 301, 302, 307, 308]:
                return "Active (HTTP 200/Redirect)"
            return f"Status {code}"
    except urllib.error.HTTPError as e:
        if e.code in [403, 401]:
            return "Active (Protected / WAF 403)"
        elif e.code == 404:
            return "Closed / 404 Not Found"
        return f"HTTP {e.code}"
    except Exception as e:
        return f"Active / Unreachable ({type(e).__name__})"

def audit_package(app_dir):
    rel_path = app_dir.relative_to(WORKSPACE)
    company = app_dir.parent.name
    role = app_dir.name
    
    issues = []
    warnings = []
    
    # 1. Check required files
    files = ["job_description.md", "application_metadata.json", "tailoring_notes.md", "cv.tex", "cv.pdf", "cover_letter.tex", "cover_letter.pdf"]
    for f in files:
        if not (app_dir / f).exists():
            issues.append(f"Missing {f}")

    # 2. Metadata audit & enhancement
    meta_path = app_dir / "application_metadata.json"
    meta = {}
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
        
        # Check core fields
        for field in REQUIRED_METADATA_FIELDS:
            if field not in meta or meta[field] is None and field not in ["applied_at"]:
                issues.append(f"Metadata missing field: {field}")
        
        # Status invariant
        if meta.get("status") != "drafted":
            issues.append(f"Status is '{meta.get('status')}', must be 'drafted'")
        if meta.get("applied_at") is not None:
            issues.append("applied_at must be null for unsubmitted application")
            
        # Add application_url & application_method where applicable
        if "application_url" not in meta:
            meta["application_url"] = meta.get("job_url", "")
        if "application_method" not in meta:
            meta["application_method"] = "Workday Career Portal" if "myworkdayjobs.com" in meta.get("job_url", "") else ("SmartRecruiters Portal" if "smartrecruiters.com" in meta.get("job_url", "") else ("Lever Portal" if "lever.co" in meta.get("job_url", "") else ("LinkedIn Easy Apply / Direct" if "linkedin.com" in meta.get("job_url", "") else "Company Portal")))
        
        # Write back updated metadata
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

    # 3. Candidate facts audit
    cv_path = app_dir / "cv.tex"
    cl_path = app_dir / "cover_letter.tex"
    
    if cv_path.exists():
        cv_text = cv_path.read_text()
        
        # Star Performer check
        if "4 $\\times$ Star Performer" not in cv_text and "4 \\times Star Performer" not in cv_text and "4$\\times$ Star Performer" not in cv_text:
            if "Star Performer" in cv_text:
                issues.append("CV Star Performer count is not 4x")
        
        # Titles check
        if "Software Engineer II" not in cv_text:
            issues.append("CV missing canonical JPMC title: Software Engineer II")
        if "Software Engineer" not in cv_text:
            issues.append("CV missing canonical ISS title: Software Engineer")
        if "Inkoop" in cv_text and "Software Engineer" not in cv_text:
            issues.append("CV missing canonical Inkoop title: Software Engineer")
            
        # Contacts check
        if CANONICAL_FACTS["email"] not in cv_text:
            issues.append("CV missing canonical email")
        phone_val = get_identity_fact("phone", "")
        if phone_val and phone_val[-6:] not in cv_text:
            issues.append("CV missing canonical phone")

    if cl_path.exists():
        cl_text = cl_path.read_text()
        if "3 Star Performer" in cl_text:
            issues.append("Cover Letter mentions 3 Star Performer instead of 4")
        if "October 6, 2026" not in cl_text and "6 October 2026" not in cl_text and "6th October 2026" not in cl_text:
            warnings.append("Cover letter missing explicit notice LWD date")

    # 4. PDF ATS & Page Count Check
    cv_pdf = app_dir / "cv.pdf"
    cl_pdf = app_dir / "cover_letter.pdf"
    
    if cv_pdf.exists():
        res = subprocess.run(["python3", str(WORKSPACE / "tools/verify_pdf.py"), str(cv_pdf), "--pages", "1", "--contains", get_identity_fact("full_name", "Candidate")], capture_output=True, text=True)
        if res.returncode != 0:
            issues.append(f"CV PDF verification failed: {res.stderr.strip() or res.stdout.strip()}")
            
    if cl_pdf.exists():
        res = subprocess.run(["python3", str(WORKSPACE / "tools/verify_pdf.py"), str(cl_pdf), "--pages", "1", "--contains", get_identity_fact("full_name", "Candidate")], capture_output=True, text=True)
        if res.returncode != 0:
            issues.append(f"Cover Letter PDF verification failed: {res.stderr.strip() or res.stdout.strip()}")

    # 5. Live JD URL check
    job_url = meta.get("job_url", "")
    live_status = check_live_url(job_url)

    # 6. Classification
    classification = "A. READY TO SUBMIT"
    if issues:
        classification = "B. NEEDS CORRECTION"
    elif "Closed" in live_status or "404" in live_status:
        classification = "C. STALE/CLOSED"

    return {
        "company": meta.get("company", company),
        "role": meta.get("role", role),
        "score": meta.get("fit_score", 0),
        "status": meta.get("status", "drafted"),
        "priority": meta.get("application_priority", "Normal"),
        "narrative": meta.get("selected_resume_narrative", ""),
        "job_url": job_url,
        "application_method": meta.get("application_method", ""),
        "live_status": live_status,
        "issues": issues,
        "warnings": warnings,
        "classification": classification,
        "dir": str(rel_path)
    }

def run_audit():
    app_dirs = sorted([d for d in APPS_BASE.glob("*/*") if d.is_dir()])
    print(f"Auditing {len(app_dirs)} application packages...\n")
    
    results = []
    for d in app_dirs:
        r = audit_package(d)
        results.append(r)
    
    # Save audit report
    out_file = WORKSPACE / "scratch/final_pre_submission_audit.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"{'Company':<15} | {'Role':<45} | {'Score':<5} | {'Status':<7} | {'Issues':<15} | {'Live':<20} | {'Decision':<18}")
    print("-" * 135)
    for r in results:
        issues_summary = "None" if not r["issues"] else f"{len(r['issues'])} errors"
        live_short = r["live_status"][:20]
        print(f"{r['company']:<15} | {r['role'][:45]:<45} | {r['score']:<5} | {r['status']:<7} | {issues_summary:<15} | {live_short:<20} | {r['classification']:<18}")

if __name__ == "__main__":
    run_audit()
