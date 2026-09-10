"""
State machine and base adapter for the /submit workflow.

Defines the canonical submission states, legal transitions, and the abstract
adapter interface that portal-specific adapters implement.

Authentication Routing (v2):
    The production /submit workflow classifies each application into one of
    three execution paths based on LIVE browser behaviour:

    - NO_AUTH_REQUIRED  → automated form-filling → review gate → applied
    - AUTH_REQUIRED     → manual_required (user submits manually)
    - AUTH_STATUS_UNKNOWN → manual_review_required (user decides)

    The existing credential manager, account registry, and old authentication
    states are preserved as dormant infrastructure for backward compatibility.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


class AuthRequirement(enum.Enum):
    """Result of live browser auth detection for a portal.

    Determined by navigating to the application URL and observing
    whether the portal presents a login/account-creation page or
    a public application form.

    NO_AUTH_REQUIRED   – public form, proceed with automation
    AUTH_REQUIRED      – login/account page, route to manual_required
    AUTH_STATUS_UNKNOWN – ambiguous, route to manual_review_required
    """

    NO_AUTH_REQUIRED = "no_auth_required"
    AUTH_REQUIRED = "auth_required"
    AUTH_STATUS_UNKNOWN = "auth_status_unknown"


class SubmissionState(enum.Enum):
    """Canonical submission lifecycle states.

    Terminal success state: APPLIED
    Terminal failure states: SUBMISSION_FAILED, STALE_JOB
    Blocking states (awaiting human): SUBMISSION_BLOCKED_AUTH,
        SUBMISSION_BLOCKED_CAPTCHA, SUBMISSION_BLOCKED_MISSING_ANSWER,
        AWAITING_MANUAL_CREDENTIAL_ENTRY, EMAIL_VERIFICATION_REQUIRED,
        AWAITING_USER_CONFIRMATION
    Auth/Account states (dormant — preserved for backward compatibility):
        AUTHENTICATION_REQUIRED, ACCOUNT_CREATION_IN_PROGRESS,
        AUTHENTICATED, AUTHENTICATION_FAILED, ACCOUNT_CREATION_FAILED,
        EMAIL_VERIFICATION_TIMEOUT
    Auth routing states (v2):
        AUTHENTICATION_CHECK  — transient auth detection phase
        MANUAL_REQUIRED       — auth detected, user must submit manually
        MANUAL_REVIEW_REQUIRED — auth status unknown, user must decide
    """

    DRAFTED = "drafted"
    SUBMISSION_IN_PROGRESS = "submission_in_progress"

    # Auth routing (v2) — production states
    AUTHENTICATION_CHECK = "authentication_check"
    MANUAL_REQUIRED = "manual_required"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"

    # Legacy auth/account states — dormant but preserved
    AUTHENTICATION_REQUIRED = "authentication_required"
    ACCOUNT_CREATION_IN_PROGRESS = "account_creation_in_progress"
    AWAITING_MANUAL_CREDENTIAL_ENTRY = "awaiting_manual_credential_entry"
    EMAIL_VERIFICATION_REQUIRED = "email_verification_required"
    AUTHENTICATED = "authenticated"
    AUTHENTICATION_FAILED = "authentication_failed"
    ACCOUNT_CREATION_FAILED = "account_creation_failed"
    EMAIL_VERIFICATION_TIMEOUT = "email_verification_timeout"

    AWAITING_USER_CONFIRMATION = "awaiting_user_confirmation"
    APPLIED = "applied"

    # Failure / interrupt states
    SUBMISSION_BLOCKED_AUTH = "submission_blocked_auth"
    SUBMISSION_BLOCKED_CAPTCHA = "submission_blocked_captcha"
    SUBMISSION_BLOCKED_MISSING_ANSWER = "submission_blocked_missing_answer"
    SUBMISSION_FAILED = "submission_failed"
    STALE_JOB = "stale_job"


# The ONLY legal state transitions. Any transition not listed here is
# rejected by SubmissionContext.transition().
LEGAL_TRANSITIONS: dict[SubmissionState, set[SubmissionState]] = {
    SubmissionState.DRAFTED: {
        SubmissionState.SUBMISSION_IN_PROGRESS,
        SubmissionState.STALE_JOB,
    },
    SubmissionState.SUBMISSION_IN_PROGRESS: {
        # Auth routing (v2) — production path
        SubmissionState.AUTHENTICATION_CHECK,
        # Legacy auth states — dormant but legal
        SubmissionState.AUTHENTICATION_REQUIRED,
        SubmissionState.ACCOUNT_CREATION_IN_PROGRESS,
        SubmissionState.AWAITING_MANUAL_CREDENTIAL_ENTRY,
        SubmissionState.AUTHENTICATED,
        # Direct to review (post-auth-check, during form filling)
        SubmissionState.AWAITING_USER_CONFIRMATION,
        # Blocking / failure
        SubmissionState.SUBMISSION_BLOCKED_AUTH,
        SubmissionState.SUBMISSION_BLOCKED_CAPTCHA,
        SubmissionState.SUBMISSION_BLOCKED_MISSING_ANSWER,
        SubmissionState.SUBMISSION_FAILED,
        SubmissionState.STALE_JOB,
    },
    # Auth routing (v2) — transient detection phase
    SubmissionState.AUTHENTICATION_CHECK: {
        # No auth → resume form filling
        SubmissionState.SUBMISSION_IN_PROGRESS,
        # Auth required → stop, route to manual
        SubmissionState.MANUAL_REQUIRED,
        # Unknown → stop, ask user
        SubmissionState.MANUAL_REVIEW_REQUIRED,
        # Legacy: allow transition to old auth states if re-enabled
        SubmissionState.AUTHENTICATION_REQUIRED,
        SubmissionState.SUBMISSION_FAILED,
    },
    # Auth routing (v2) — near-terminal states
    SubmissionState.MANUAL_REQUIRED: {
        # Only allow retry (explicit reprocessing)
        SubmissionState.DRAFTED,
    },
    SubmissionState.MANUAL_REVIEW_REQUIRED: {
        # Only allow retry after user resolves ambiguity
        SubmissionState.DRAFTED,
    },
    # Legacy auth states — dormant but preserved for backward compatibility
    SubmissionState.AUTHENTICATION_REQUIRED: {
        SubmissionState.ACCOUNT_CREATION_IN_PROGRESS,
        SubmissionState.AWAITING_MANUAL_CREDENTIAL_ENTRY,
        SubmissionState.AUTHENTICATED,
        SubmissionState.AUTHENTICATION_FAILED,
        SubmissionState.SUBMISSION_BLOCKED_CAPTCHA,
        SubmissionState.SUBMISSION_FAILED,
        SubmissionState.SUBMISSION_IN_PROGRESS,
        SubmissionState.DRAFTED,
    },
    SubmissionState.ACCOUNT_CREATION_IN_PROGRESS: {
        SubmissionState.AWAITING_MANUAL_CREDENTIAL_ENTRY,
        SubmissionState.EMAIL_VERIFICATION_REQUIRED,
        SubmissionState.AUTHENTICATED,
        SubmissionState.ACCOUNT_CREATION_FAILED,
        SubmissionState.SUBMISSION_BLOCKED_CAPTCHA,
        SubmissionState.SUBMISSION_FAILED,
        SubmissionState.DRAFTED,
    },
    SubmissionState.AWAITING_MANUAL_CREDENTIAL_ENTRY: {
        SubmissionState.AUTHENTICATED,
        SubmissionState.EMAIL_VERIFICATION_REQUIRED,
        SubmissionState.ACCOUNT_CREATION_FAILED,
        SubmissionState.AUTHENTICATION_FAILED,
        SubmissionState.SUBMISSION_BLOCKED_CAPTCHA,
        SubmissionState.SUBMISSION_FAILED,
        SubmissionState.DRAFTED,
    },
    SubmissionState.EMAIL_VERIFICATION_REQUIRED: {
        SubmissionState.AUTHENTICATED,
        SubmissionState.EMAIL_VERIFICATION_TIMEOUT,
        SubmissionState.SUBMISSION_IN_PROGRESS,
        SubmissionState.SUBMISSION_FAILED,
        SubmissionState.DRAFTED,
    },
    SubmissionState.AUTHENTICATED: {
        SubmissionState.SUBMISSION_IN_PROGRESS,
        SubmissionState.AWAITING_USER_CONFIRMATION,
        SubmissionState.SUBMISSION_BLOCKED_CAPTCHA,
        SubmissionState.SUBMISSION_BLOCKED_MISSING_ANSWER,
        SubmissionState.SUBMISSION_FAILED,
    },
    SubmissionState.AUTHENTICATION_FAILED: {
        SubmissionState.AUTHENTICATION_REQUIRED,
        SubmissionState.ACCOUNT_CREATION_IN_PROGRESS,
        SubmissionState.AWAITING_MANUAL_CREDENTIAL_ENTRY,
        SubmissionState.SUBMISSION_FAILED,
        SubmissionState.DRAFTED,
    },
    SubmissionState.ACCOUNT_CREATION_FAILED: {
        SubmissionState.AUTHENTICATION_REQUIRED,
        SubmissionState.ACCOUNT_CREATION_IN_PROGRESS,
        SubmissionState.AWAITING_MANUAL_CREDENTIAL_ENTRY,
        SubmissionState.SUBMISSION_FAILED,
        SubmissionState.DRAFTED,
    },
    SubmissionState.EMAIL_VERIFICATION_TIMEOUT: {
        SubmissionState.EMAIL_VERIFICATION_REQUIRED,
        SubmissionState.SUBMISSION_FAILED,
        SubmissionState.DRAFTED,
    },
    SubmissionState.AWAITING_USER_CONFIRMATION: {
        SubmissionState.APPLIED,
        SubmissionState.SUBMISSION_FAILED,
        # User can abort — go back to drafted
        SubmissionState.DRAFTED,
    },
    # Blocking states can be retried or abandoned
    SubmissionState.SUBMISSION_BLOCKED_AUTH: {
        SubmissionState.AUTHENTICATION_REQUIRED,
        SubmissionState.SUBMISSION_IN_PROGRESS,
        SubmissionState.SUBMISSION_FAILED,
        SubmissionState.DRAFTED,
    },
    SubmissionState.SUBMISSION_BLOCKED_CAPTCHA: {
        SubmissionState.SUBMISSION_IN_PROGRESS,
        SubmissionState.SUBMISSION_FAILED,
        SubmissionState.DRAFTED,
    },
    SubmissionState.SUBMISSION_BLOCKED_MISSING_ANSWER: {
        SubmissionState.SUBMISSION_IN_PROGRESS,
        SubmissionState.SUBMISSION_FAILED,
        SubmissionState.DRAFTED,
    },
    # Terminal states — no further transitions
    SubmissionState.APPLIED: set(),
    SubmissionState.SUBMISSION_FAILED: set(),
    SubmissionState.STALE_JOB: set(),
}


class IllegalStateTransition(Exception):
    """Raised when a state transition violates the state machine."""

    def __init__(self, current: SubmissionState, target: SubmissionState):
        self.current = current
        self.target = target
        super().__init__(
            f"Illegal state transition: {current.value} -> {target.value}"
        )


class PortalType(enum.Enum):
    """Supported portal / ATS platform types."""

    WORKDAY = "workday"
    LEVER = "lever"
    SMARTRECRUITERS = "smartrecruiters"
    GREENHOUSE = "greenhouse"
    LINKEDIN = "linkedin"
    GENERIC = "generic"


def detect_portal(url: str) -> PortalType:
    """Detect the portal type from a job posting or application URL."""
    url_lower = url.lower()
    if "myworkdayjobs.com" in url_lower or "myworkdaysite.com" in url_lower:
        return PortalType.WORKDAY
    if "lever.co" in url_lower:
        return PortalType.LEVER
    if "smartrecruiters.com" in url_lower:
        return PortalType.SMARTRECRUITERS
    if "greenhouse.io" in url_lower or "boards.greenhouse" in url_lower:
        return PortalType.GREENHOUSE
    if "linkedin.com" in url_lower:
        return PortalType.LINKEDIN
    return PortalType.GENERIC


# Fields that are NEVER safe to auto-answer without explicit user approval.
STOP_AND_ASK_CATEGORIES = frozenset(
    {
        "salary_expectations",
        "compensation",
        "work_authorization",
        "visa_sponsorship",
        "legal_declaration",
        "criminal_background",
        "demographic_disclosure",
        "eeo_disclosure",
        "disability_disclosure",
        "veteran_status",
        "non_compete",
        "arbitration_agreement",
        "security_clearance",
        "open_ended_technical",
        "subjective_question",
    }
)

# Patterns in question text that trigger mandatory human review.
STOP_AND_ASK_PATTERNS = [
    "salary", "compensation", "pay", "ctc", "expected ctc",
    "current ctc", "current salary", "expected salary",
    "work authori", "visa", "sponsorship", "citizenship",
    "criminal", "felony", "conviction", "background check",
    "disability", "veteran", "gender", "race", "ethnicity",
    "non-compete", "non compete", "restrictive covenant",
    "arbitration",
    "security clearance",
    "willing to relocate",  # judgment call — needs user input
]

# Credential / secret patterns that must NEVER appear in persisted files.
CREDENTIAL_PATTERNS = frozenset(
    {
        "password",
        "passwd",
        "otp",
        "one-time",
        "session_token",
        "auth_token",
        "bearer",
        "cookie",
        "recovery_code",
        "secret_key",
        "api_key",
    }
)


@dataclass
class SubmissionContext:
    """Holds the full state for a single submission attempt.

    Enforces the state machine: all transitions go through `transition()`.
    """

    company: str
    role: str
    app_dir: Path
    job_url: str
    portal_type: PortalType
    state: SubmissionState = SubmissionState.DRAFTED

    # Populated during submission
    populated_fields: dict[str, str] = field(default_factory=dict)
    uploaded_files: dict[str, str] = field(default_factory=dict)
    unanswered_questions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    state_history: list[tuple[str, str, str]] = field(default_factory=list)

    # Post-submission
    confirmation_number: str | None = None
    confirmation_url: str | None = None
    applied_at: str | None = None
    application_method: str | None = None
    failure_reason: str | None = None
    failure_point: str | None = None

    # Auth routing (v2) — submission mode tracking
    submission_mode: str | None = None            # "automated" | "manual" | "manual_review_required"
    authentication_required: bool | None = None    # True / False / None (unknown)
    manual_required_reason: str | None = None      # "authentication_required" | None
    submitted_via: str | None = None               # "portal" | "manual portal submission" | None
    fit_score: int | None = None                   # Carried from application_metadata for summary display
    auth_confidence: str | None = None             # "high" | "medium" | "low"
    auth_evidence: str | None = None               # Concise explanation of detected auth state

    def transition(self, target: SubmissionState, reason: str = "") -> None:
        """Transition to a new state, enforcing the state machine."""
        legal = LEGAL_TRANSITIONS.get(self.state, set())
        if target not in legal:
            raise IllegalStateTransition(self.state, target)
        old = self.state
        self.state = target
        self.state_history.append(
            (old.value, target.value, reason or f"{old.value} -> {target.value}")
        )
        if target == SubmissionState.APPLIED:
            self.applied_at = datetime.now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict safe for JSON persistence.

        SECURITY: This method NEVER includes credentials, tokens, or secrets.
        """
        return {
            "company": self.company,
            "role": self.role,
            "app_dir": str(self.app_dir),
            "job_url": self.job_url,
            "portal_type": self.portal_type.value,
            "state": self.state.value,
            "populated_fields": self.populated_fields,
            "uploaded_files": self.uploaded_files,
            "unanswered_questions": self.unanswered_questions,
            "warnings": self.warnings,
            "state_history": self.state_history,
            "confirmation_number": self.confirmation_number,
            "confirmation_url": self.confirmation_url,
            "applied_at": self.applied_at,
            "application_method": self.application_method,
            "failure_reason": self.failure_reason,
            "failure_point": self.failure_point,
            # Auth routing (v2)
            "submission_mode": self.submission_mode,
            "authentication_required": self.authentication_required,
            "manual_required_reason": self.manual_required_reason,
            "submitted_via": self.submitted_via,
            "fit_score": self.fit_score,
            "auth_confidence": self.auth_confidence,
            "auth_evidence": self.auth_evidence,
        }

    def save_state(self, path: Path | None = None) -> Path:
        """Persist submission state to a JSON file in the application directory.

        SECURITY: Scans output for credential patterns before writing.
        """
        target = path or (self.app_dir / "submission_state.json")
        data = self.to_dict()

        # Security scan: ensure no credential material leaked into state
        serialized = json.dumps(data).lower()
        for pattern in CREDENTIAL_PATTERNS:
            if pattern in serialized:
                # Strip the value, keep the key for debugging
                for key in list(data.get("populated_fields", {}).keys()):
                    if pattern in key.lower():
                        data["populated_fields"][key] = "[REDACTED]"

        target.write_text(json.dumps(data, indent=2))
        return target

    def pre_submission_summary(self) -> str:
        """Generate the human-readable pre-submission summary for the approval gate."""
        lines = [
            "=" * 60,
            "PRE-SUBMISSION SUMMARY — AWAITING YOUR CONFIRMATION",
            "=" * 60,
            "",
            f"Company:           {self.company}",
            f"Role:              {self.role}",
            f"Portal:            {self.portal_type.value}",
            f"Application URL:   {self.job_url}",
            "",
            "--- Documents Uploaded ---",
        ]
        for label, path in self.uploaded_files.items():
            lines.append(f"  {label}: {path}")
        if not self.uploaded_files:
            lines.append("  (none)")

        lines.append("")
        lines.append("--- Populated Fields ---")
        for question, answer in self.populated_fields.items():
            lines.append(f"  {question}: {answer}")
        if not self.populated_fields:
            lines.append("  (none)")

        if self.unanswered_questions:
            lines.append("")
            lines.append("--- Unanswered Questions (NEED YOUR INPUT) ---")
            for q in self.unanswered_questions:
                lines.append(f"  ⚠ {q}")

        if self.warnings:
            lines.append("")
            lines.append("--- Warnings ---")
            for w in self.warnings:
                lines.append(f"  ⚠ {w}")

        lines.append("")
        lines.append("To proceed, reply with: \"Submit it\"")
        lines.append("To abort, reply with: \"Abort\" or \"Cancel\"")
        lines.append("=" * 60)
        return "\n".join(lines)

    def manual_required_summary(self) -> str:
        """Generate the human-readable summary when auth routing stops automation.

        Displayed when authentication_required or auth_status_unknown is detected.
        """
        lines = [
            "=" * 60,
            "MANUAL SUBMISSION REQUIRED",
            "=" * 60,
            "",
            f"Company:           {self.company}",
            f"Role:              {self.role}",
            f"Portal:            {self.portal_type.value}",
            f"Application URL:   {self.job_url}",
        ]
        if self.fit_score is not None:
            lines.append(f"Fit Score:         {self.fit_score}")
        lines.append("")
        lines.append(f"Reason:            {self.manual_required_reason or 'unknown'}")
        lines.append(f"Submission Mode:   {self.submission_mode or 'manual'}")
        if self.auth_confidence:
            lines.append(f"Confidence:        {self.auth_confidence}")
        if self.auth_evidence:
            lines.append(f"Evidence:          {self.auth_evidence}")
        lines.append("")
        lines.append("--- Application Package ---")
        cv_path = self.app_dir / "cv.pdf"
        cl_path = self.app_dir / "cover_letter.pdf"
        lines.append(f"  CV:              {cv_path}")
        lines.append(f"  Cover Letter:    {cl_path}")
        lines.append("")
        lines.append("Automation stopped. Please submit this application manually.")
        lines.append("After submitting, use /outcome to record the result.")
        lines.append("=" * 60)
        return "\n".join(lines)


class BaseAdapter:
    """Abstract base class for portal-specific submission adapters.

    Subclasses implement portal-specific DOM interaction logic that is
    dispatched as browser_subagent task descriptions.

    The base class provides:
    - State management via SubmissionContext
    - Answer governance via AnswersProvider
    - File path resolution
    - Pre/post submission hooks
    """

    portal_type: PortalType = PortalType.GENERIC

    def __init__(self, context: SubmissionContext):
        self.context = context

    @property
    def cv_pdf_path(self) -> Path:
        return self.context.app_dir / "cv.pdf"

    @property
    def cover_letter_pdf_path(self) -> Path:
        return self.context.app_dir / "cover_letter.pdf"

    def get_apply_url(self) -> str:
        """Return the URL to navigate to for starting the application.

        Subclasses may transform the job posting URL into an apply URL.
        """
        return self.context.job_url

    def get_browser_task_description(self) -> str:
        """Generate the browser_subagent task description for this portal.

        This is the core method: it returns a detailed, self-contained prompt
        that the browser subagent will execute. The prompt must include:
        - Navigation instructions
        - Field-filling instructions with exact values
        - File upload instructions with exact paths
        - STOP conditions (auth, captcha, unknown questions, review page)
        - What to report back

        Subclasses MUST override this.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_browser_task_description()"
        )

    def build_field_map(self) -> dict[str, str]:
        """Build the deterministic field -> value map from the answers provider.

        Subclasses can extend this with portal-specific field names.
        """
        # Lazy import to avoid circular dependency
        from tools.submit_adapters.answers_provider import AnswersProvider

        provider = AnswersProvider()
        return provider.get_deterministic_fields()

    def update_metadata_applied(self) -> None:
        """Update application_metadata.json after successful automated submission."""
        meta_path = self.context.app_dir / "application_metadata.json"
        if not meta_path.exists():
            return

        meta = json.loads(meta_path.read_text())
        meta["status"] = "applied"
        meta["applied_at"] = self.context.applied_at
        meta["application_method"] = self.context.application_method or self.portal_type.value
        meta["submission_mode"] = self.context.submission_mode or "automated"
        meta["authentication_required"] = self.context.authentication_required
        meta["submitted_via"] = self.context.submitted_via or "portal"
        if self.context.auth_confidence:
            meta["auth_confidence"] = self.context.auth_confidence
        if self.context.auth_evidence:
            meta["auth_evidence"] = self.context.auth_evidence
        if self.context.confirmation_number:
            meta["confirmation_number"] = self.context.confirmation_number
        if self.context.confirmation_url:
            meta["confirmation_url"] = self.context.confirmation_url
        meta["updated_at"] = datetime.now().isoformat()
        meta_path.write_text(json.dumps(meta, indent=2))

    def update_metadata_manual_required(self) -> None:
        """Update application_metadata.json when auth routing stops automation.

        Sets submission_mode to 'manual' and preserves status as 'drafted'.
        The status only changes to 'applied' when the user explicitly
        confirms manual submission via /outcome.
        """
        meta_path = self.context.app_dir / "application_metadata.json"
        if not meta_path.exists():
            return

        meta = json.loads(meta_path.read_text())
        # Status stays 'drafted' — only /outcome sets it to 'applied'
        meta["submission_mode"] = self.context.submission_mode or "manual"
        meta["authentication_required"] = self.context.authentication_required
        meta["manual_required_reason"] = self.context.manual_required_reason
        if self.context.auth_confidence:
            meta["auth_confidence"] = self.context.auth_confidence
        if self.context.auth_evidence:
            meta["auth_evidence"] = self.context.auth_evidence
        meta["updated_at"] = datetime.now().isoformat()
        meta_path.write_text(json.dumps(meta, indent=2))
