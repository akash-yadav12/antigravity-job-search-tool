#!/usr/bin/env python3
"""
Automated CV Importer & Workspace Onboarding Utility.

Scans the cv/ and documents/cv/ folders for candidate resume files (.pdf, .tex, .txt),
extracts raw text using pypdf/pdftotext, parses candidate contact details and experience,
and populates the candidate profile configuration across the repository.

Usage:
  python3 tools/import_cv.py --auto
  python3 tools/import_cv.py --file cv/my_resume.pdf
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
CV_DIR = WORKSPACE_ROOT / "cv"
DOC_CV_DIR = WORKSPACE_ROOT / "documents" / "cv"
PROFILE_JSON_PATH = WORKSPACE_ROOT / "data" / "candidate_profile.json"
CLAUDE_MD_PATH = WORKSPACE_ROOT / "CLAUDE.md"
PROFILE_MD_PATH = WORKSPACE_ROOT / ".claude" / "skills" / "job-application-assistant" / "01-candidate-profile.md"
MAIN_TEX_PATH = WORKSPACE_ROOT / "cv" / "main_example.tex"


def find_candidate_cv() -> Path | None:
    """Finds the most relevant candidate CV file in cv/ or documents/cv/."""
    candidates = []
    for d in [CV_DIR, DOC_CV_DIR]:
        if not d.exists():
            continue
        for p in d.iterdir():
            if p.name.startswith(".") or p.name in ["main_example.tex", "main_example.pdf"]:
                continue
            if p.suffix.lower() in [".pdf", ".tex", ".txt"]:
                candidates.append(p)

    if not candidates:
        return None
    # Return the most recently modified CV
    return max(candidates, key=lambda p: p.stat().st_mtime)


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extracts text using pypdf or pdftotext."""
    try:
        import pypdf
        reader = pypdf.PdfReader(str(pdf_path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if len(text.strip()) > 50:
            return text
    except ImportError:
        pass
    except Exception as e:
        print(f"Warning: pypdf extraction failed ({e}), falling back to pdftotext...")

    import subprocess
    try:
        res = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(pdf_path), "-"],
                             capture_output=True, text=True, check=True)
        return res.stdout
    except Exception as e:
        print(f"Warning: pdftotext failed ({e})")
        return ""


def parse_candidate_identity(text: str) -> dict:
    """Heuristic extraction of basic identity information from CV text."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    first_few_lines = lines[:10] if len(lines) >= 10 else lines

    # 1. Email extraction
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text)
    email = email_match.group(0) if email_match else ""

    # 2. Phone extraction
    phone_match = re.search(r'(\+?\d{1,3}[\s-]?)?\(?\d{3,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,5}', text)
    phone = phone_match.group(0).strip() if phone_match else ""

    # 3. LinkedIn URL
    linkedin_match = re.search(r'linkedin\.com/in/([\w\-]+)', text, re.IGNORECASE)
    linkedin = f"https://www.{linkedin_match.group(0)}" if linkedin_match else ""

    # 4. GitHub URL
    github_match = re.search(r'github\.com/([\w\-]+)', text, re.IGNORECASE)
    github = f"https://www.{github_match.group(0)}" if github_match else ""

    # 5. Name extraction (typically first non-empty line without email/phone)
    full_name = ""
    for line in first_few_lines:
        if "@" in line or "http" in line or any(d in line for d in "0123456789"):
            continue
        if len(line.split()) in [2, 3, 4] and all(part[0].isupper() for part in line.split() if part.isalpha()):
            full_name = line
            break

    if not full_name and first_few_lines:
        full_name = first_few_lines[0]

    parts = full_name.split()
    first_name = parts[0] if parts else ""
    last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

    return {
        "full_name": full_name or "[YOUR_NAME]",
        "first_name": first_name or "[First]",
        "last_name": last_name or "[Last]",
        "email": email or "[your.email@example.com]",
        "phone": phone or "[+XX XXXXXXXXXX]",
        "linkedin_url": linkedin,
        "github_url": github
    }


def update_candidate_profile_json(identity: dict, raw_text: str):
    """Updates data/candidate_profile.json with extracted facts."""
    profile = {}
    if PROFILE_JSON_PATH.exists():
        try:
            with open(PROFILE_JSON_PATH, "r", encoding="utf-8") as f:
                profile = json.load(f)
        except Exception:
            profile = {}

    profile.setdefault("version", "1.0.0")
    profile.setdefault("identity", {})
    profile.setdefault("employment", {})
    profile.setdefault("compensation", {
        "currency": "INR",
        "unit": "LPA",
        "current_ctc": 30.0,
        "comfortable_min_base": 35.0,
        "preferred_base_target": 40.0,
        "min_acceptable_total": 40.0,
        "preferred_total_target": 45.0
    })
    profile.setdefault("preferences", {
        "target_roles": ["Senior Software Engineer", "Backend Engineer", "Software Engineer II"],
        "target_locations": ["Remote", "Hybrid"],
        "excluded_employers": [],
        "narratives": [
            "Backend / Distributed Systems",
            "AI / Developer Productivity",
            "Full Stack / Platform"
        ]
    })

    # Update identity fields
    for k, v in identity.items():
        if v and not v.startswith("["):
            profile["identity"][k] = v

    with open(PROFILE_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)
    print(f"✓ Updated profile: {PROFILE_JSON_PATH}")


def main():
    parser = argparse.ArgumentParser(description="Import candidate resume and bootstrap workspace profile.")
    parser.add_argument("--auto", action="store_true", help="Auto-detect resume in cv/ or documents/cv/")
    parser.add_argument("--file", type=str, help="Path to resume file (.pdf, .tex, .txt)")
    args = parser.parse_args()

    cv_file = Path(args.file) if args.file else find_candidate_cv()

    if not cv_file or not cv_file.exists():
        print("No resume found in cv/ or documents/cv/.")
        print("Please place your resume PDF into the 'cv/' directory (e.g. cv/resume.pdf) and run:")
        print("  python3 tools/import_cv.py --auto")
        sys.exit(1)

    print(f"Reading candidate CV from: {cv_file}")
    if cv_file.suffix.lower() == ".pdf":
        raw_text = extract_text_from_pdf(cv_file)
    else:
        with open(cv_file, "r", encoding="utf-8", errors="ignore") as f:
            raw_text = f.read()

    if not raw_text.strip():
        print(f"Error: Unable to extract text layer from {cv_file}. Ensure file contains selectable text.")
        sys.exit(1)

    identity = parse_candidate_identity(raw_text)
    print("\n--- Extracted Candidate Summary ---")
    for k, v in identity.items():
        print(f"  {k:15}: {v}")
    print("----------------------------------\n")

    update_candidate_profile_json(identity, raw_text)

    # Save extracted text for agent inspection
    out_txt = WORKSPACE_ROOT / "cv" / "cv_extracted.txt"
    with open(out_txt, "w", encoding="utf-8") as f:
        f.write(raw_text)
    print(f"✓ Saved extracted text layer to: {out_txt}")
    print("\nCandidate CV ingested successfully! Antigravity/Claude can now run /setup or tailor applications.")


if __name__ == "__main__":
    main()
