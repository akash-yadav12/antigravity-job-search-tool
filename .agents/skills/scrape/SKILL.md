---
name: scrape
description: Search job portals (LinkedIn, Freehire, WebSearch) for new listings matching candidate search queries and ingest them into job_scraper/seen_jobs.json. Trigger on /scrape, scrape jobs, find jobs, search jobs.
---

# Scrape Workflow (Thin Pointer)

This skill is an Antigravity thin pointer to the canonical job scraper methodology.

## Instructions
1. Load and read the canonical specification in [`.claude/skills/job-scraper/SKILL.md`](.claude/skills/job-scraper/SKILL.md) and query categories in [`.claude/skills/job-scraper/search-queries.md`](.claude/skills/job-scraper/search-queries.md).
2. Execute targeted searches across configured portals using the Bun search CLIs under `.agents/skills/*/cli/` or run `python3 tools/discovery_engine.py`.
3. Ingest discovered postings into `job_scraper/seen_jobs.json` with provenance metadata, deduplicating against existing entries.
