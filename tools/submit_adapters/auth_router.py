"""
Authentication router for the /submit workflow (v2).

Classifies application portals into one of three execution paths based on
LIVE browser behaviour — not URL patterns or portal name heuristics.

The router provides:
1. An AuthDecision dataclass carrying requirement, confidence, and evidence.
2. A browser task description for the auth detection probe.
3. A classifier that interprets the browser subagent's report.

CONSERVATIVE ROUTING RULE:
- Only NO_AUTH_REQUIRED + confidence == "high" enters the automated path.
- NO_AUTH_REQUIRED + confidence in ("medium", "low") -> MANUAL_REVIEW_REQUIRED.
- AUTH_REQUIRED -> MANUAL_REQUIRED.
- AUTH_STATUS_UNKNOWN -> MANUAL_REVIEW_REQUIRED.

SECURITY INVARIANTS:
- This module NEVER accesses credentials, system keystore, or account registries.
- It only reads the browser's DOM report to make a routing decision.
- No passwords, OTPs, or session tokens are involved at any point.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from tools.submit_adapters.base_adapter import AuthRequirement, SubmissionState


@dataclass
class AuthDecision:
    """Structured decision returned by auth detection.

    Attributes:
        auth_requirement: AuthRequirement enum (NO_AUTH_REQUIRED, AUTH_REQUIRED, AUTH_STATUS_UNKNOWN)
        confidence: "high" | "medium" | "low"
        evidence: Concise explanation of what was detected.
    """

    auth_requirement: AuthRequirement
    confidence: str  # "high" | "medium" | "low"
    evidence: str

    @property
    def target_state(self) -> SubmissionState:
        """Apply the conservative routing rule to determine next submission state:
        - Only NO_AUTH_REQUIRED + confidence == 'high' -> SUBMISSION_IN_PROGRESS (automated form filling)
        - NO_AUTH_REQUIRED + (medium|low) -> MANUAL_REVIEW_REQUIRED
        - AUTH_REQUIRED -> MANUAL_REQUIRED
        - AUTH_STATUS_UNKNOWN -> MANUAL_REVIEW_REQUIRED
        """
        if self.auth_requirement == AuthRequirement.NO_AUTH_REQUIRED and self.confidence == "high":
            return SubmissionState.SUBMISSION_IN_PROGRESS
        if self.auth_requirement == AuthRequirement.AUTH_REQUIRED:
            return SubmissionState.MANUAL_REQUIRED
        return SubmissionState.MANUAL_REVIEW_REQUIRED

    @property
    def is_automated_allowed(self) -> bool:
        """Return True if and only if safe for full automation."""
        return self.auth_requirement == AuthRequirement.NO_AUTH_REQUIRED and self.confidence == "high"

    def __eq__(self, other: object) -> bool:
        """Support comparison with both AuthDecision and AuthRequirement enum for backward compatibility."""
        if isinstance(other, AuthRequirement):
            return self.auth_requirement == other
        if isinstance(other, AuthDecision):
            return (
                self.auth_requirement == other.auth_requirement
                and self.confidence == other.confidence
                and self.evidence == other.evidence
            )
        return False


# Patterns indicating authentication is REQUIRED.
# Matched case-insensitively against the browser subagent's report.
_AUTH_REQUIRED_PATTERNS = [
    r"\bsign\s*in\b",
    r"\blog\s*in\b",
    r"\blogin\b",
    r"\bcreate\s+(?:an?\s+)?account\b",
    r"\bsign\s*up\b",
    r"\bregister\b",
    r"\bexisting\s+user\b",
    r"\balready\s+have\s+an?\s+account\b",
    r"\bpassword\s+field\b",
    r"\benter\s+(?:your\s+)?password\b",
    r"\busername\s+(?:and|or)\s+password\b",
    r"\blinkedin\s+login\b",
    r"\blinkedin\s+sign\s*in\b",
    r"\bBLOCKED_AUTH\b",
    r"\brequires?\s+(?:you\s+to\s+)?(?:log|sign)\s*in\b",
    r"\bauthenticat(?:e|ion)\s+required\b",
    r"\bsso\s+redirect\b",
    r"\boauth\s+login\b",
]

# Patterns indicating NO authentication is required.
# Matched case-insensitively against the browser subagent's report.
_NO_AUTH_PATTERNS = [
    r"\bapplication\s+form\b",
    r"\bapply\s+now\b",
    r"\bpersonal\s+information\b",
    r"\bresume\s+upload\b",
    r"\benter\s+your\s+details\b",
    r"\bcontact\s+information\b",
    r"\bfill\s+(?:in|out)\b",
    r"\bupload\s+(?:your\s+)?(?:resume|cv)\b",
    r"\bcandidate\s+information\b",
    r"\bmy\s+information\b",
    r"\bapplication\s+(?:page|step|questions)\b",
    r"\bREADY_FOR_REVIEW\b",
    r"\bno\s+(?:login|sign\s*in|authentication)\s+(?:required|needed|detected)\b",
    r"\bpublic\s+(?:application|form)\b",
]

# Compiled regexes
_AUTH_REQUIRED_RE = [re.compile(p, re.IGNORECASE) for p in _AUTH_REQUIRED_PATTERNS]
_NO_AUTH_RE = [re.compile(p, re.IGNORECASE) for p in _NO_AUTH_PATTERNS]


def detect_application_auth_requirement(browser_report: str) -> AuthDecision:
    """Classify the browser's initial page report into an auth requirement with confidence and evidence.

    Parses the browser subagent's report from the initial navigation
    to determine if authentication is required.

    Returns:
        AuthDecision instance containing auth_requirement, confidence ('high'|'medium'|'low'),
        and a concise explanation string in evidence.
    """
    if not browser_report or not browser_report.strip():
        return AuthDecision(
            auth_requirement=AuthRequirement.AUTH_STATUS_UNKNOWN,
            confidence="low",
            evidence="Application flow could not be determined.",
        )

    report_text = browser_report.strip()

    # Strong signal: explicit BLOCKED_AUTH from browser subagent
    if re.search(r"\bBLOCKED_AUTH\b", report_text):
        if "linkedin" in report_text.lower():
            evidence = "LinkedIn login required before application form."
        elif "workday" in report_text.lower():
            evidence = "Workday Sign In/Create Account screen detected before application form."
        else:
            evidence = "Authentication required by portal (BLOCKED_AUTH reported)."
        return AuthDecision(
            auth_requirement=AuthRequirement.AUTH_REQUIRED,
            confidence="high",
            evidence=evidence,
        )

    # Check for structured AUTH_CLASSIFICATION header if emitted by browser subagent
    has_explicit_no_auth = bool(re.search(r"AUTH_CLASSIFICATION:\s*NO_AUTH_REQUIRED", report_text, re.IGNORECASE))
    has_explicit_auth_req = bool(re.search(r"AUTH_CLASSIFICATION:\s*AUTH_REQUIRED", report_text, re.IGNORECASE))
    has_explicit_unknown = bool(re.search(r"AUTH_CLASSIFICATION:\s*AUTH_STATUS_UNKNOWN", report_text, re.IGNORECASE))

    # Count pattern matches
    auth_matches = sum(1 for rx in _AUTH_REQUIRED_RE if rx.search(report_text))
    no_auth_matches = sum(1 for rx in _NO_AUTH_RE if rx.search(report_text))

    # Check for specific "none" or no auth controls in structured report
    auth_elements_none = bool(re.search(r"AUTH_ELEMENTS:\s*(?:none|none\s+detected|n/a)", report_text, re.IGNORECASE))

    # 1. Clear NO_AUTH_REQUIRED
    if (has_explicit_no_auth and auth_elements_none) or (no_auth_matches > 0 and auth_matches == 0):
        evidence = "Public application form is visible and no sign-in/create-account controls are present."
        return AuthDecision(
            auth_requirement=AuthRequirement.NO_AUTH_REQUIRED,
            confidence="high",
            evidence=evidence,
        )

    # 2. Clear AUTH_REQUIRED
    if has_explicit_auth_req or (auth_matches > 0 and no_auth_matches == 0):
        if "workday" in report_text.lower():
            evidence = "Workday Sign In/Create Account screen detected before application form."
        elif "linkedin" in report_text.lower():
            evidence = "LinkedIn login required before application form."
        elif re.search(r"\bcreate\s+(?:an?\s+)?account\b", report_text, re.IGNORECASE):
            evidence = "Portal Create Account screen detected before application form."
        elif re.search(r"\bsign\s*in\s+to\s+apply\b", report_text, re.IGNORECASE):
            evidence = "Sign In to Apply screen detected before application form."
        else:
            evidence = "Sign In/Create Account screen detected before application form."
        return AuthDecision(
            auth_requirement=AuthRequirement.AUTH_REQUIRED,
            confidence="high",
            evidence=evidence,
        )

    # 3. Explicit Unknown
    if has_explicit_unknown and auth_matches == 0 and no_auth_matches == 0:
        return AuthDecision(
            auth_requirement=AuthRequirement.AUTH_STATUS_UNKNOWN,
            confidence="low",
            evidence="Application flow could not be determined.",
        )

    # 4. Mixed signals: both form elements and sign-in text present
    if auth_matches > 0 and no_auth_matches > 0:
        if no_auth_matches > auth_matches:
            # Public form dominates, but "sign in" or similar text is present (e.g. employee portal link in nav)
            # Safe conservative classification: confidence="medium", which conservative rule routes to MANUAL_REVIEW_REQUIRED
            evidence = "Public application form detected, but secondary sign-in text or links are present on the page."
            return AuthDecision(
                auth_requirement=AuthRequirement.NO_AUTH_REQUIRED,
                confidence="medium",
                evidence=evidence,
            )
        elif auth_matches > no_auth_matches:
            evidence = "Authentication screen detected with partial application form keywords."
            return AuthDecision(
                auth_requirement=AuthRequirement.AUTH_REQUIRED,
                confidence="medium",
                evidence=evidence,
            )
        else:
            # Equal mixed signals
            evidence = "Ambiguous page: mixed authentication and application form elements detected."
            return AuthDecision(
                auth_requirement=AuthRequirement.AUTH_STATUS_UNKNOWN,
                confidence="low",
                evidence=evidence,
            )

    # 5. Weak single signals or unrecognizable content
    if no_auth_matches > 0:
        return AuthDecision(
            auth_requirement=AuthRequirement.NO_AUTH_REQUIRED,
            confidence="low",
            evidence="Weak application form indicators detected without explicit form confirmation.",
        )
    if auth_matches > 0:
        return AuthDecision(
            auth_requirement=AuthRequirement.AUTH_REQUIRED,
            confidence="low",
            evidence="Weak authentication indicators detected without explicit login confirmation.",
        )

    # Default fallback
    return AuthDecision(
        auth_requirement=AuthRequirement.AUTH_STATUS_UNKNOWN,
        confidence="low",
        evidence="Application flow could not be determined.",
    )


def get_auth_detection_task_description(url: str, portal_type: str) -> str:
    """Generate a browser_subagent task to detect auth requirements.

    Navigates to the URL, clicks Apply, and reports what kind of
    page appeared (login form, public application form, etc.)

    This is a DETECTION-ONLY task. The browser subagent MUST NOT:
    - Enter any credentials
    - Create any accounts
    - Submit any forms
    - Fill any application fields
    """
    return f"""
TASK: Detect whether this job application requires authentication.

PORTAL TYPE: {portal_type}
APPLICATION URL: {url}

=== CRITICAL RULES ===
1. This is a DETECTION task only. DO NOT fill any forms.
2. DO NOT enter any credentials, passwords, or personal information.
3. DO NOT create any accounts.
4. DO NOT click any Submit buttons.
5. DO NOT click "Apply with LinkedIn" or any social login.

=== INSTRUCTIONS ===
1. Navigate to the application URL: {url}
2. If there is an "Apply" or "Apply Now" button, click it.
3. Observe the resulting page carefully.
4. Report what you see using the classification below.

=== CLASSIFICATION CRITERIA ===

Report "NO_AUTH_REQUIRED" if you see:
- A public application form (personal information, resume upload, etc.)
- No login/sign-in requirement
- Direct access to candidate information fields
- An "Enter your details" or "Personal Information" step

Report "AUTH_REQUIRED" if you see:
- A "Sign In" or "Log In" page/modal
- A "Create Account" prompt
- A username/password form
- An SSO redirect
- A LinkedIn login requirement
- A message saying authentication is required
- A "Sign In to Apply" or "Log In to Continue" prompt

Report "AUTH_STATUS_UNKNOWN" if:
- The page is ambiguous
- You cannot determine if auth is required
- The page timed out or errored
- You see mixed signals

=== REPORTING FORMAT ===
Report exactly:
1. AUTH_CLASSIFICATION: [NO_AUTH_REQUIRED | AUTH_REQUIRED | AUTH_STATUS_UNKNOWN]
2. CURRENT_URL: [the URL you are on]
3. PAGE_DESCRIPTION: [brief description of visible elements]
4. AUTH_ELEMENTS: [list any login/signup elements you see, or "none"]
5. FORM_ELEMENTS: [list any application form elements you see, or "none"]
"""
