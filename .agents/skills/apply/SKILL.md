---
name: apply
description: Generate tailored 1-page LaTeX CV and cover letter for a target job posting, execute isolated self-review audit, compile PDFs, and record under documents/applications/<Company>/<Role>/. Trigger on /apply, apply to job, tailor CV, generate cover letter.
---

# Apply Workflow (Antigravity Production Lifecycle)

This skill executes the canonical 16-step application generation lifecycle, storing all outputs in immutable company/role-based directories under `documents/applications/<Company>/<Role>/`.

## Canonical 16-Step Application Lifecycle

1. **Read Ranked Record**: Retrieve target job from `job_scraper/seen_jobs.json`.
2. **Fetch Live Description**: Retrieve full JD text via `read_url_content` or `curl` with browser headers.
3. **Verify Status & Relevance**: Check that the job is active, non-expired, and materially unchanged.
4. **Select Resume Narrative**: Choose the most appropriate narrative:
   - `Backend / Distributed Systems`
   - `AI / Developer Productivity`
   - `Full Stack / Platform`
5. **Generate Tailored 1-Page CV**: Draft `documents/applications/<Company>/<Role>/cv.tex` (based on `cv/main_example.tex` moderncv/banking template).
6. **Generate Tailored 1-Page Cover Letter**: Draft `documents/applications/<Company>/<Role>/cover_letter.tex` (based on `cover.cls` template with relative symlinks).
7. **Factual Grounding Audit**: Verify every date, employer, title, and metric against `CLAUDE.md` and `01-candidate-profile.md`. Zero hallucinations or title/date modifications.
8. **ATS Audit**: Check natural keyword representation, heading structure, and clean extraction.
9. **Compile CV (LuaLaTeX)**: Compile `cv.tex` with LuaLaTeX $\rightarrow$ `cv.pdf` (strictly 1 page).
10. **Compile Cover Letter (XeLaTeX)**: Compile `cover_letter.tex` with XeLaTeX $\rightarrow$ `cover_letter.pdf` (strictly 1 page).
11. **PDF Verification Tool**: Run `tools/verify_pdf.py` on both PDFs to ensure clean text-layer extraction.
12. **Visual Inspection**: Read rendered PDFs using `view_file` to verify layout and spacing.
13. **Store Application Package**: Ensure directory contains:
    - `job_description.md`
    - `application_metadata.json`
    - `cv.tex` & `cv.pdf`
    - `cover_letter.tex` & `cover_letter.pdf`
    - `tailoring_notes.md`
14. **Write Metadata (`application_metadata.json`)**:
    - Record company, role, URL, source, location, score, narrative, notice status (from candidate profile: status & notice period), gaps, and priority.
15. **Record in Tracker**: Update `job_search_tracker.csv` with status `drafted`.
16. **Human Approval Gate**:
    - Stop at `DRAFTED → AWAITING APPROVAL`.
    - **NEVER** submit applications or change status to `applied` without explicit user instruction.
