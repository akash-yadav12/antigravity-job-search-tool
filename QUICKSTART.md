# Quickstart Guide: AI Job Search Scaffold

Welcome to **AI Job Search** — an autonomous job search engine and application orchestrator designed for **Google Antigravity** and **Claude Code**.

Any user on **Windows**, **macOS**, or **Linux** can clone this scaffold, drop their existing resume into the `cv/` folder, and have the AI agent take complete hold of their data, build their profile, tailor 1-page LaTeX CVs and cover letters, and track applications.

---

## 🚀 3-Step Setup

### Step 1: Clone the Repository
```bash
git clone https://github.com/akash-yadav12/antigravity-job-search-tool.git ai-job-search
cd ai-job-search
```

### Step 2: Drop Your Resume in `cv/`
Copy your current resume PDF or LaTeX file into the `cv/` folder:

- **macOS / Linux**:
  ```bash
  cp /path/to/my_resume.pdf cv/resume.pdf
  ```
- **Windows (PowerShell)**:
  ```powershell
  Copy-Item $HOME\Downloads\my_resume.pdf cv\resume.pdf
  ```

*(You can also place supporting career files like a LinkedIn export in `documents/linkedin/` or reference letters in `documents/references/`)*.

### Step 3: Run Onboarding
Simply tell Antigravity in the chat:
> *"I have added my resume in `cv/`. Please set up my profile."*

Or run the onboarding command:
- **macOS / Linux**:
  ```bash
  python3 tools/import_cv.py --auto
  ```
- **Windows (PowerShell / CMD)**:
  ```powershell
  python tools/import_cv.py --auto
  # or: py tools/import_cv.py --auto
  ```
*(If using Claude Code, type `/setup`)*.

---

## ⚡ What Happens Automatically

The agent will:
1. **Extract your complete professional history**: Name, email, phone, location, LinkedIn/GitHub links, education, work history, metrics, and technical stack.
2. **Populate your canonical profile**:
   - `data/candidate_profile.json` (machine-readable settings for compensation & submission engines)
   - `CLAUDE.md` & `01-candidate-profile.md` (canonical candidate specifications)
   - `02-behavioral-profile.md` (inferred behavioral traits and strengths)
   - `04-job-evaluation.md` (tailored match areas and current employer exclusion)
   - `05-cv-templates.md` (role-specific profile statement templates)
   - `07-interview-prep.md` (STAR achievement stories extracted from your work)
   - `search-queries.md` (job portal queries customized for your role and target cities)
3. **Compile your master LaTeX CV**:
   - Populates `cv/main_example.tex` (moderncv banking style) and compiles it to `cv/main_example.pdf`.
4. **Initialize your application tracker**:
   - Prepares `job_search_tracker.csv` to track every application through to offer.

---

## 🛠️ Daily Workflow

### 1. Discover New Job Postings
Search configured job boards (LinkedIn, Freehire, direct ATS portals) for matching opportunities:
- **macOS / Linux**:
  ```bash
  python3 tools/run_pipeline.py
  ```
- **Windows**:
  ```powershell
  python tools/run_pipeline.py
  ```
*(Or use `/scrape` in Antigravity)*. New listings are deduplicated and saved to `job_scraper/seen_jobs.json`.

### 2. Rank & Evaluate Fit
Score discovered jobs against your 5-dimension rubric (Technical Fit, Experience Match, Behavioral/Culture Fit, Career Alignment, and Location):
```
/rank
```
Jobs are assigned priority tiers (`P0` Immediate Apply, `P1`, `P2`, `P3`, or rejected by hard gates).

### 3. Generate Tailored Application Packages
For any target job posting:
```
/apply https://example.com/job/12345
```
Or generate a batch of top opportunities:
- **macOS / Linux**:
  ```bash
  python3 tools/generate_batch.py --tier P0 --limit 5
  ```
- **Windows**:
  ```powershell
  python tools/generate_batch.py --tier P0 --limit 5
  ```
The agent executes the canonical 16-step lifecycle:
- Generates tailored 1-page LuaLaTeX CV (`cv.tex` $\rightarrow$ `cv.pdf`)
- Generates tailored 1-page XeLaTeX cover letter (`cover_letter.tex` $\rightarrow$ `cover_letter.pdf`)
- Verifies factual grounding (zero hallucination against your profile)
- Runs ATS text layer verification (`tools/verify_pdf.py`)
- Saves the complete package in `documents/applications/<Company>/<Role>/`
- Records the opportunity in `job_search_tracker.csv` as `drafted`

### 4. Review & Submit
Review the generated PDFs with Antigravity's `view_file` tool:
```
/submit <Company> <Role>
```
Automated preflight checks verify portal authentication requirements and fill out form answers using verified facts from your profile. **The agent always halts for your explicit approval before submitting.**

### 5. Interview Prep & Tracking
- **Interview Prep**: `/interview <Company>` builds company research and tailored STAR interview talking points.
- **Track Outcomes**: `/outcome <Company>` records interview rounds, feedback, offers, and conversion analytics in `job_search_tracker.csv`.
- **Visual Dashboard**: `/html-report` generates an interactive HTML status report of your job search pipeline.

---

## 📋 Prerequisites

| Component | Windows 10 / 11 | macOS | Linux (Ubuntu / Debian) |
| :--- | :--- | :--- | :--- |
| **Python 3.10+** | `winget install Python.Python.3.12` | `brew install python` | `sudo apt install python3 python3-pip` |
| **Text Extractor** | `pip install pypdf` | `pip install pypdf` | `pip install pypdf` |
| **Bun CLI** | `powershell -c "irm bun.sh/install.ps1 \| iex"` | `brew install oven-sh/bun/bun` | `curl -fsSL https://bun.sh/install \| bash` |
| **LaTeX Engine** | `winget install MiKTeX.MiKTeX` | `brew install --cask mactex-no-gui` | `sudo apt install texlive-luatex texlive-xetex` |
