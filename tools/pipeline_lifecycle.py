"""
Pipeline Lifecycle & Execution States (Phase 3).
Defines and enforces explicit transitions across the entire pipeline:
DISCOVERED
→ NORMALIZED
→ DEDUPLICATED
→ EMPLOYER_VERIFIED
→ FRESHNESS_VERIFIED
→ COMPENSATION_EVALUATED
→ FIT_EVALUATED
→ APPLICATION_ELIGIBLE
→ AUTH_PROBED
→ (AUTOMATABLE / MANUAL_REQUIRED / MANUAL_REVIEW_REQUIRED)
→ APPLICATION_DRAFTED
→ AWAITING_USER_APPROVAL
→ SUBMISSION

Invariant:
Submission mode (AUTOMATABLE, MANUAL_REQUIRED, MANUAL_REVIEW_REQUIRED)
MUST ONLY be determined by live auth probe results — NEVER by ATS type,
domain name, or discovery source.
"""

from typing import Dict, Any, Optional
from tools.submit_adapters.auth_router import AuthDecision
from tools.submit_adapters.base_adapter import AuthRequirement

class LifecycleState:
    DISCOVERED = "DISCOVERED"
    NORMALIZED = "NORMALIZED"
    DEDUPLICATED = "DEDUPLICATED"
    EMPLOYER_VERIFIED = "EMPLOYER_VERIFIED"
    FRESHNESS_VERIFIED = "FRESHNESS_VERIFIED"
    COMPENSATION_EVALUATED = "COMPENSATION_EVALUATED"
    FIT_EVALUATED = "FIT_EVALUATED"
    APPLICATION_ELIGIBLE = "APPLICATION_ELIGIBLE"
    AUTH_PROBED = "AUTH_PROBED"
    APPLICATION_DRAFTED = "APPLICATION_DRAFTED"
    AWAITING_USER_APPROVAL = "AWAITING_USER_APPROVAL"
    SUBMISSION = "SUBMISSION"

class SubmissionMode:
    PENDING_PROBE = "pending_probe"
    AUTOMATABLE = "AUTOMATABLE"
    MANUAL_REQUIRED = "MANUAL_REQUIRED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"

def determine_submission_mode(auth_decision: Optional[AuthDecision]) -> str:
    """
    Classifies submission mode strictly from an AuthDecision object.
    Never infers from ATS vendor, URL, or scraper metadata.
    """
    if not auth_decision:
        return SubmissionMode.PENDING_PROBE

    if (auth_decision.auth_requirement == AuthRequirement.NO_AUTH_REQUIRED and 
        auth_decision.confidence == "high"):
        return SubmissionMode.AUTOMATABLE

    if auth_decision.auth_requirement == AuthRequirement.AUTH_REQUIRED:
        return SubmissionMode.MANUAL_REQUIRED

    return SubmissionMode.MANUAL_REVIEW_REQUIRED

def determine_lifecycle_stage(job: Dict[str, Any]) -> str:
    """
    Determines the current lifecycle stage of a job record based on verified evidence.
    Fail-closed: Returns the furthest stage that has fully passed verification.
    """
    if job.get("status") == "applied" or job.get("applied") is True:
        return LifecycleState.SUBMISSION

    if job.get("status") == "drafted" or job.get("application_package_path"):
        return LifecycleState.AWAITING_USER_APPROVAL

    if job.get("auth_probe_completed"):
        return LifecycleState.AUTH_PROBED

    if job.get("can_apply") is True and job.get("ready_for_application") is True:
        return LifecycleState.APPLICATION_ELIGIBLE

    if job.get("fit_score", 0) > 0 and job.get("fit_evaluation"):
        return LifecycleState.FIT_EVALUATED

    if job.get("compensation") and job.get("compensation", {}).get("decision") != "UNKNOWN":
        return LifecycleState.COMPENSATION_EVALUATED

    if job.get("freshness") and job.get("freshness") != "unknown":
        return LifecycleState.FRESHNESS_VERIFIED

    if job.get("employer_verified") is True:
        return LifecycleState.EMPLOYER_VERIFIED

    if job.get("canonical_job_id"):
        return LifecycleState.DEDUPLICATED

    return LifecycleState.DISCOVERED
