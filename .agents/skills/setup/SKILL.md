---
name: setup
description: Initialize or update the candidate profile, behavioral style, compensation parameters, and search preferences from CV documents in cv/ or documents/cv/ or interactive Q&A. Trigger on /setup, setup profile, update candidate info, import cv.
---

# Setup Workflow (Antigravity Drop-In Candidate Onboarding)

This skill enables Antigravity to ingest a candidate's CV/resume dropped into `cv/` or `documents/cv/`, extract their profile facts, and configure the entire workspace for personalized job search and application generation.

## Onboarding Procedure

1. **Detect CV File**:
   - Check `cv/` and `documents/cv/` for any `.pdf` or `.tex` file (e.g. `cv/resume.pdf` or `documents/cv/my_cv.pdf`).
   - If multiple CVs exist, parse all to cross-reference details.
2. **Extract Text Layer**:
   - Run `python3 tools/verify_pdf.py cv/<filename>.pdf --dump-text /tmp/cv_extracted.txt` (or view with `view_file`).
3. **Extract Structured Candidate Data**:
   - **Identity**: Full name, first/last name, email, phone, location, LinkedIn URL, GitHub URL.
   - **Status**: Notice period, current title, current employer, availability, compensation expectations.
   - **Education**: Degrees, institutions, graduation years, GPA, key coursework.
   - **Experience**: Employer names, locations, job titles, start/end dates, key achievements, metrics.
   - **Technical Stack**: Primary languages, frameworks, distributed systems, cloud, databases, tools.
   - **Behavioral Profile**: Working style, leadership traits, strengths, growth areas.
   - **Target Roles & Locations**: Target job titles, domains, commute/location constraints.
4. **Populate Canonical Files**:
   - Write `data/candidate_profile.json` with the machine-readable profile (used by compensation, submission, and gating tools).
   - Populate `CLAUDE.md` with candidate profile, preferences, and role expectations.
   - Populate `.claude/skills/job-application-assistant/01-candidate-profile.md` with full structured experience.
   - Populate `02-behavioral-profile.md` with behavioral traits inferred from experience.
   - Populate `04-job-evaluation.md` with strong/moderate/weak match areas and exclude current employer.
   - Populate `05-cv-templates.md` with targeted profile statement templates.
   - Populate `07-interview-prep.md` with ready-made STAR stories extracted from accomplishments.
   - Populate `.claude/skills/job-scraper/search-queries.md` with role titles, skills, and target locations.
   - Populate `cv/main_example.tex` with candidate data and compile via `cd cv && lualatex main_example.tex`.
5. **Verify Tracker**:
   - Ensure `job_search_tracker.csv` has the 14-column header, ready to record opportunities.
6. **Confirm to User**:
   - Present a summary of extracted details and prompt if any adjustments are desired.
