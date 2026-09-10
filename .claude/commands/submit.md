---
name: submit
description: Submit a prepared application package via browser automation with auth routing, explicit human approval before final submission.
allowed-tools: ["Bash", "Read", "Write", "Edit", "Agent", "WebFetch", "WebSearch", "AskUserQuestion"]
---

# /submit — Application Submission (v2: Auth Routing)

## Inputs

- `$ARGUMENTS`: Company name and role, OR path to application directory, OR `top N`

## Workflow

### 1. Resolve Application Package

Parse `$ARGUMENTS` to identify the application directory under
`documents/applications/<Company>/<Role>/`.

For `top N`: read `job_search_tracker.csv`, select top N drafted applications
sorted by fit score descending with complete packages.

### 2. Preflight Validation

```bash
python3 tools/submit_preflight.py <Company> <Role>
```

Verify all preflight checks pass. If any fail, STOP.

### 3. Load Adapter

```python
from tools.submit_adapters.base_adapter import detect_portal, SubmissionContext, AuthRequirement
from tools.submit_adapters.auth_router import detect_application_auth_requirement, get_auth_detection_task_description
from tools.submit_adapters.answers_provider import AnswersProvider

# Detect portal from job_url in application_metadata.json
portal_type = detect_portal(job_url)

# Load the appropriate adapter
if portal_type == "workday":
    from tools.submit_adapters.workday_adapter import WorkdayAdapter as Adapter
elif portal_type == "lever":
    from tools.submit_adapters.lever_adapter import LeverAdapter as Adapter
# ... etc.
```

### 4. Authentication Detection (NEW)

Use `Agent("browser")` (Antigravity: `browser_subagent`) with
`get_auth_detection_task_description(url, portal_type)` to probe the portal.

Classify the browser report with `detect_application_auth_requirement(report)`.

- `NO_AUTH_REQUIRED` → continue to Step 5
- `AUTH_REQUIRED` → skip to Step 7
- `AUTH_STATUS_UNKNOWN` → skip to Step 8

### 5. Browser Automation (Automated Path)

Use `Agent("browser")` (Antigravity: `browser_subagent`) to execute the
adapter's `get_browser_task_description()`.

STOP and ask the user for: salary, work authorization, sponsorship,
legal/background declarations, demographic disclosures, ambiguous questions,
subjective questions, open-ended technical questions, CAPTCHA, 2FA.

### 6. Human Approval Gate

Present the pre-submission summary via `AskUserQuestion`.

Wait for explicit "Submit it" response.

After "Submit it": click the final submit button via browser.

Update metadata:
- `status = "applied"`
- `applied_at = <timestamp>`
- `submission_mode = "automated"`
- `authentication_required = false`
- `submitted_via = "portal"`

### 7. Manual Required (Auth Path)

Display `MANUAL SUBMISSION REQUIRED` summary with:
- company, role, portal, fit score
- application URL
- CV and cover letter paths
- reason: `authentication_required`

Update metadata:
- `submission_mode = "manual"`
- `authentication_required = true`
- `manual_required_reason = "authentication_required"`
- Status stays `drafted`

Do NOT attempt login, account creation, Keychain access, or credential retrieval.

### 8. Manual Review Required (Unknown Path)

Display summary with `auth_status_unknown` reason.
Ask user whether to proceed manually or retry.

Update metadata:
- `submission_mode = "manual_review_required"`
- `authentication_required = null`

### 9. Post-Submission Updates (Automated Path)

- Update `application_metadata.json` → status: `applied`
- Update `job_search_tracker.csv` → status: `applied`
- Save `submission_state.json` audit trail

### 10. Batch Results (if top N)

Produce summary tables:
- Automated Queue: Company | Role | Portal | Status
- Manual Queue: Company | Role | Portal | Reason | URL
- Manual Review Queue: Company | Role | Reason
