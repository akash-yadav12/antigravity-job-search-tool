---
name: outcome
description: Record application outcomes (interview invite, rejection, offer), calculate analytics, log retrospective notes, and update job_search_tracker.csv. Trigger on /outcome, application status, track outcome.
---

# Outcome Workflow (Thin Pointer)

This skill is an Antigravity thin pointer to the canonical outcome recording methodology.

## Instructions
1. Load and read the canonical specification in [`.claude/commands/outcome.md`](.claude/commands/outcome.md).
2. Look up the specified application in `job_search_tracker.csv`.
3. Update the `status` column (e.g. `Applied`, `Screening`, `Technical`, `Final Round`, `Offer`, `Rejected`, `Withdrawn`) and append timestamped retrospective notes.
4. Calculate stage conversion rates and pipeline statistics as outlined in `outcome.md`.
