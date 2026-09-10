---
name: rank
description: Batch evaluate, score, and rank unranked job postings in job_scraper/seen_jobs.json against the candidate profile and 5-dimension scoring rubric. Trigger on /rank, rank jobs, score jobs, triage postings.
---

# Rank Workflow (Thin Pointer)

This skill is an Antigravity thin pointer to the canonical ranking methodology.

## Instructions
1. Load and read the canonical specification in [`.claude/commands/rank.md`](.claude/commands/rank.md) via `view_file`.
2. Apply the Google Antigravity tool translation and execution adaptations defined in [`GEMINI.md`](GEMINI.md) (Sequential/Batched scoring instead of subagent dispatch).
3. Evaluate unranked postings (`status: "new"`) in `job_scraper/seen_jobs.json` against [`.claude/skills/job-application-assistant/04-job-evaluation.md`](.claude/skills/job-application-assistant/04-job-evaluation.md) or run `python3 tools/run_pipeline.py`.
4. Persist updated rank scores, verdicts, strengths, and gaps to `job_scraper/seen_jobs.json` while preserving the existing schema.
