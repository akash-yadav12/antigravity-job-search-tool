---
name: interview
description: Generate stage-specific interview preparation packs, company research, and STAR talking points, or run interactive mock interviews. Trigger on /interview, interview prep, mock interview.
---

# Interview Workflow (Thin Pointer)

This skill is an Antigravity thin pointer to the canonical interview preparation methodology.

## Instructions
1. Load and read the canonical specification in [`.claude/commands/interview.md`](.claude/commands/interview.md) and STAR guidelines in [`.claude/skills/job-application-assistant/07-interview-prep.md`](.claude/skills/job-application-assistant/07-interview-prep.md).
2. Load the target company application archive from `documents/applications/<company>_<role>/`.
3. Check `company_research/<company>.json` cache or perform independent company research.
4. Generate structured technical/behavioral prep packs (`interview_prep_<stage>.md`) grounded in verified candidate achievements or conduct interactive interview roleplay.
