"""
Portal submission adapters for the /submit workflow.

This package provides:
- State machine for application submission lifecycle with authentication routing (v2)
- Auth routing: live browser-based classification into automated/manual paths
- Grounded answers provider for deterministic portal field resolution
- Secure credential management via macOS Keychain (/usr/bin/security) [dormant — backward-compatible]
- Non-secret candidate account registry [dormant — backward-compatible]
- Portal-specific adapters (Workday, Lever, SmartRecruiters, LinkedIn, Generic)
- Preflight validation before submission attempts

AUTHENTICATION ROUTING (v2):
    Production /submit classifies each application into one of three paths
    based on LIVE browser behaviour:
    - NO_AUTH_REQUIRED  → automated form-filling → review gate → applied
    - AUTH_REQUIRED     → manual_required (user submits manually)
    - AUTH_STATUS_UNKNOWN → manual_review_required (user decides)

SECURITY INVARIANTS:
1. Passwords are stored ONLY in the native macOS Keychain (dormant in production).
2. Passwords, OTPs, session tokens, cookies, and auth headers are NEVER
   written to repository files, JSON, Markdown, logs, state files, or Git history.
3. The production /submit path does NOT access the Keychain when auth is required.
"""

from tools.submit_adapters.base_adapter import (
    AuthRequirement,
    SubmissionState,
    SubmissionContext,
    BaseAdapter,
    IllegalStateTransition,
    LEGAL_TRANSITIONS,
    PortalType,
    detect_portal,
)
from tools.submit_adapters.auth_router import (
    AuthDecision,
    detect_application_auth_requirement,
    get_auth_detection_task_description,
)
from tools.submit_adapters.answers_provider import AnswersProvider, AnswerResult
from tools.submit_adapters.credential_manager import (
    generate_strong_password,
    extract_tenant_key,
    make_service_name,
    store_credential,
    get_credential,
    has_credential,
    delete_credential,
    AccountRegistry,
    CANONICAL_USERNAME,
)

__all__ = [
    # Auth routing (v2)
    "AuthRequirement",
    "AuthDecision",
    "detect_application_auth_requirement",
    "get_auth_detection_task_description",
    # State machine
    "SubmissionState",
    "SubmissionContext",
    "BaseAdapter",
    "IllegalStateTransition",
    "LEGAL_TRANSITIONS",
    "PortalType",
    "detect_portal",
    # Answers
    "AnswersProvider",
    "AnswerResult",
    # Credential manager (dormant — backward-compatible)
    "generate_strong_password",
    "extract_tenant_key",
    "make_service_name",
    "store_credential",
    "get_credential",
    "has_credential",
    "delete_credential",
    "AccountRegistry",
    "CANONICAL_USERNAME",
]

