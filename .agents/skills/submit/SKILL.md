---
name: submit
description: >
  Submit a prepared application package via browser automation with
  authentication routing. Classifies each portal as no-auth (automated),
  auth-required (manual), or unknown (manual review). Automates safe
  non-authenticated applications end-to-end, stopping at the review gate
  for explicit human confirmation. Routes authenticated portals to the
  manual queue immediately.
  Trigger on /submit, submit application, send application.
---

# /submit — Application Submission Workflow (v2: Auth Routing)

## Purpose

Submit an already-prepared application package (created by `/apply`) through the
employer's ATS portal using visual browser automation.

This workflow NEVER modifies the prepared CV, cover letter, or application content.
It only interacts with the external portal to deliver the prepared materials.

**Production philosophy:**
- **AUTOMATE** every safe non-authenticated application.
- **MANUALLY SUBMIT** every authenticated application.

## Prerequisites

- The application package MUST already exist at `documents/applications/<Company>/<Role>/`
- Status MUST be `drafted` in `application_metadata.json`
- Both `cv.pdf` and `cover_letter.pdf` MUST exist
- The job URL MUST still be active

## State Machine

```
Automated (no-auth):
  drafted → submission_in_progress → authentication_check
    → submission_in_progress → awaiting_user_confirmation → applied

Manual (auth-required):
  drafted → submission_in_progress → authentication_check → manual_required

Unknown:
  drafted → submission_in_progress → authentication_check → manual_review_required

Failure/interrupt states:
  submission_blocked_captcha
  submission_blocked_missing_answer
  submission_failed
  stale_job

Legacy auth states (dormant — backward-compatible):
  authentication_required
  account_creation_in_progress
  awaiting_manual_credential_entry
  email_verification_required
  authenticated
  authentication_failed
  account_creation_failed
  email_verification_timeout
```

Only `applied` means the external application was actually submitted.
`manual_required` means the user must submit manually via the portal.
`manual_review_required` means the user must decide how to proceed.

## Auth Routing

### AuthRequirement Classification

Before form-filling, the workflow runs a **live browser detection probe**:

1. Navigate to the application URL.
2. Click "Apply" if visible.
3. Observe the resulting page.
4. Classify:

| Result | Action |
|---|---|
| `NO_AUTH_REQUIRED` | Proceed with automated form-filling |
| `AUTH_REQUIRED` | Stop immediately → `manual_required` |
| `AUTH_STATUS_UNKNOWN` | Stop → `manual_review_required`, ask user |

**Detection is from actual live portal behaviour, not URL or portal name.**

Examples:
- Public Lever form with no login → `NO_AUTH_REQUIRED`
- SmartRecruiters form without account → `NO_AUTH_REQUIRED`
- Greenhouse application without login → `NO_AUTH_REQUIRED`
- Workday showing Sign In / Create Account → `AUTH_REQUIRED`
- LinkedIn Easy Apply requiring session → `AUTH_REQUIRED`

### AUTH_REQUIRED Behaviour

When authentication is detected:
1. **DO NOT** create accounts, enter passwords, retrieve Keychain credentials,
   handle OTP, handle 2FA, handle email verification, or reuse sessions.
2. Transition to `manual_required`.
3. Update `application_metadata.json`:
   - `submission_mode = "manual"`
   - `authentication_required = true`
   - `manual_required_reason = "authentication_required"`
   - Status stays `drafted`.
4. Display the manual submission summary.
5. Preserve all generated artifacts.

### AUTH_STATUS_UNKNOWN Behaviour

1. Stop. Do not guess.
2. Transition to `manual_review_required`.
3. Set `submission_mode = "manual_review_required"`.
4. Ask the user whether to proceed manually.

## Execution Steps

### Phase 1: Preflight Validation

Run `tools/submit_preflight.py` to verify:
1. Application directory exists
2. Status == drafted
3. PDFs exist and are valid
4. Job URL is accessible
5. Portal type detected

If preflight fails, STOP and report the failure.

### Phase 2: Portal Detection & Adapter Selection

Detect the portal type from the job URL:
- `myworkdayjobs.com` → Workday adapter
- `lever.co` → Lever adapter
- `smartrecruiters.com` → SmartRecruiters adapter
- `linkedin.com` → LinkedIn adapter
- Fallback → Generic adapter

### Phase 3: Authentication Detection (NEW)

Use `browser_subagent` with `get_auth_detection_task_description()` to probe
the portal. Classify the result with `detect_application_auth_requirement()`.

- `NO_AUTH_REQUIRED` → proceed to Phase 4
- `AUTH_REQUIRED` → skip to Phase 7 (Manual Required)
- `AUTH_STATUS_UNKNOWN` → skip to Phase 8 (Manual Review)

### Phase 4: Answer Governance

Load the canonical candidate profile from `CLAUDE.md` and
`01-candidate-profile.md`. Map deterministic facts to portal field labels.

**Auto-fill allowed:**
- Name, email, phone, location
- Current employer, title
- Years of experience
- Education details
- LinkedIn/GitHub URLs
- Notice period (factual statement only)

**MUST STOP and ask the user:**
- Salary expectations / compensation
- Work authorization / visa sponsorship
- Legal declarations (criminal background, etc.)
- Demographic disclosures (EEO, disability, veteran)
- Non-compete / restrictive covenants
- Security clearance
- Any open-ended or subjective question
- Relocation willingness
- CAPTCHA
- 2FA / MFA prompts
- Any unknown requirement

### Phase 5: Browser Automation (Automated Path)

Use `browser_subagent` to:
1. Navigate to the application URL
2. Fill in form fields using the deterministic field map
3. Upload CV and cover letter PDFs
4. Navigate through multi-step forms
5. Answer deterministic questions from candidate profile
6. STOP at the review/summary page

**Hard STOP conditions:**
- CAPTCHA detected → `submission_blocked_captcha`
- Unknown screening question → `submission_blocked_missing_answer`
- Review page reached → `awaiting_user_confirmation`

### Phase 6: Human Approval Gate (Automated Path)

Present a pre-submission summary:
```
============================================================
READY FOR FINAL SUBMISSION
============================================================

Company:           <Company>
Role:              <Role>
Portal:            <portal_type>
Application URL:   <url>

--- Documents Uploaded ---
  Resume: cv.pdf
  Cover Letter: cover_letter.pdf

--- Populated Fields ---
  [list all entered answers]

--- Unanswered/Flagged Questions ---
  [list if any]

To proceed, reply: "Submit it"
To abort, reply:   "Abort"
============================================================
```

**NEVER click Submit without explicit "Submit it" confirmation.**

After receiving explicit "Submit it":
1. Use `browser_subagent` to click the final Submit button
2. Capture confirmation number / URL if available
3. Take a screenshot of the confirmation page

### Phase 7: Manual Required (Auth Path)

Display:
```
============================================================
MANUAL SUBMISSION REQUIRED
============================================================

Company:           <Company>
Role:              <Role>
Portal:            <portal_type>
Application URL:   <url>
Fit Score:         <score>

Reason:            authentication_required
Submission Mode:   manual

--- Application Package ---
  CV:              documents/applications/<Company>/<Role>/cv.pdf
  Cover Letter:    documents/applications/<Company>/<Role>/cover_letter.pdf

Automation stopped. Please submit this application manually.
After submitting, use /outcome to record the result.
============================================================
```

Do NOT attempt further automation.

### Phase 8: Manual Review Required (Unknown Path)

Display the same summary with `Reason: auth_status_unknown`.
Ask the user whether to:
- Retry with automation
- Submit manually

### Phase 9: Post-Submission Updates (Automated Path only)

1. Update `application_metadata.json`:
   - `status` → `applied`
   - `applied_at` → ISO timestamp
   - `application_method` → portal type
   - `submission_mode` → `automated`
   - `authentication_required` → `false`
   - `submitted_via` → `portal`
   - `confirmation_number` / `confirmation_url` if available
2. Update `job_search_tracker.csv` with status `applied`
3. Save `submission_state.json` as audit trail

## Batch Mode

When invoked as `/submit top N`:

1. Read `job_search_tracker.csv`
2. Select the top N eligible applications:
   - status = `drafted`
   - not already applied / stale / duplicate
   - application package complete (cv.pdf + cover_letter.pdf exist)
3. Sort by fit score descending
4. Process each independently
5. One blocked application MUST NOT stop others

At the end, produce:

```
### Automated Queue
Company | Role | Portal | Status

### Manual Queue
Company | Role | Portal | Reason | URL

### Manual Review Queue
Company | Role | Reason
```

## Manual Submission Tracking

When the user reports manual submission via `/outcome`:
- status = `applied`
- applied_at = timestamp
- submission_mode = `manual`
- submitted_via = `manual portal submission`

Do not change CV, cover letter, or ranking information.

## Security Invariants

1. **No credential access in production path**: The production /submit workflow
   MUST NOT access the Keychain, credential manager, or account registry when
   the portal requires authentication. The credential infrastructure is dormant.

2. **No credential persistence**: NEVER persist passwords, OTPs, session tokens,
   cookies, auth headers, or recovery codes — not in files, not in metadata,
   not in state, not in logs.

3. **No auto-login**: If a portal requires authentication, route to `manual_required`.
   Do not attempt login.

4. **No CAPTCHA bypass**: If a CAPTCHA appears, STOP and let the user solve it.

5. **No final submission without explicit confirmation**: The browser must STOP
   at the review page. Only after the user says "Submit it" may the agent
   click the submit button.

6. **Profile grounding**: Every auto-filled answer traces to `CLAUDE.md` or
   `01-candidate-profile.md`. No fabrication.

## Metadata Additions (v2)

| Field | Values |
|---|---|
| `submission_mode` | `automated` / `manual` / `manual_review_required` |
| `authentication_required` | `true` / `false` / `null` |
| `manual_required_reason` | `authentication_required` / `null` |
| `submitted_via` | `portal` / `manual portal submission` / `null` |
| `applied_at` | ISO timestamp / `null` |

## File Layout

```
tools/
  submit_preflight.py          # Preflight validation CLI
  submit_adapters/
    __init__.py                # Package exports
    base_adapter.py            # State machine, base class, AuthRequirement
    auth_router.py             # Live browser auth detection & classification
    answers_provider.py        # Grounded facts resolver
    credential_manager.py      # macOS Keychain (dormant — backward-compatible)
    account_registry.json      # Portal accounts (dormant — backward-compatible)
    workday_adapter.py         # Workday portal adapter
    lever_adapter.py           # Lever portal adapter
    smartrecruiters_adapter.py # SmartRecruiters adapter
    linkedin_adapter.py        # LinkedIn Easy Apply adapter
    generic_adapter.py         # Fallback adapter
```

## Usage

```
/submit Cisco Software_Engineer_Java_Go
/submit --app-dir documents/applications/Cisco/Software_Engineer_Java_Go
/submit top 10
```
