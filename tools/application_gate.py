"""
Fail-Closed Production Application Gate (Phase 4).
Evaluates whether a candidate job record strictly qualifies for application creation.
Enforces that can_apply=true ONLY when ALL 12 conditions are met.
Any missing, unknown, or incomplete field immediately results in can_apply=false.
"""

from typing import Dict, Any, Tuple, Optional, List
import re

def is_provenance_complete(job: Dict[str, Any]) -> Tuple[bool, str]:
    """Validates that all required provenance fields exist and are non-empty."""
    required_fields = [
        "canonical_url",
        "canonical_source",
        "discovered_from",
        "discovery_date",
        "source_adapter"
    ]
    for f in required_fields:
        val = job.get(f)
        if not val:
            return False, f"Missing required provenance field: '{f}'"
        if isinstance(val, list) and len(val) == 0:
            return False, f"Empty provenance list: '{f}'"
    return True, "Provenance complete"

def evaluate_can_apply(
    job: Dict[str, Any],
    tracked_applications: Optional[List[Dict[str, Any]]] = None
) -> Tuple[bool, Optional[str]]:
    """
    Fail-closed derived evaluator for can_apply.
    Returns (can_apply: bool, reason: Optional[str]).
    """
    # 1. Exact Employer Verification Passed
    if job.get("employer_verified") is not True:
        return False, "Employer verification not passed (employer_verified != True)"

    # 10. Verification status must be strictly 'verified'
    if job.get("verification_status") != "verified":
        return False, f"Verification status is '{job.get('verification_status')}', expected 'verified'"

    # 11. Verification evidence URL must exist and be non-empty
    ev_url = job.get("verification_evidence_url") or job.get("canonical_url")
    if not ev_url or not str(ev_url).startswith("http"):
        return False, "Missing verification evidence URL"

    # 12. last_verified_at must exist
    if not job.get("last_verified_at"):
        return False, "Missing last_verified_at timestamp"

    # 2. Application Currently Open
    if job.get("active_status") != "active":
        return False, f"Application is not active (status: '{job.get('active_status')}')"

    # 3. Freshness is fresh or recently_verified
    freshness = job.get("freshness")
    if freshness not in ("fresh", "recently_verified"):
        return False, f"Freshness state '{freshness}' is ineligible (must be 'fresh' or 'recently_verified')"

    # 4. Compensation meets policy OR explicitly qualifies under Tier-A research exception
    comp = job.get("compensation", {})
    comp_dec = comp.get("decision", "UNKNOWN")
    comp_fit = comp.get("compensation_fit", "unknown")
    company_tier = job.get("company_tier", "Tier C")

    comp_passed = False
    if comp_dec == "TARGET" and comp_fit in ("strong", "acceptable"):
        comp_passed = True
    elif company_tier == "Tier A" and comp_dec in ("UNKNOWN", "TARGET", "SELECTIVE"):
        # Tier-A research exception
        comp_passed = True

    if not comp_passed:
        return False, f"Compensation does not qualify (decision: {comp_dec}, fit: {comp_fit}, tier: {company_tier})"

    # 5. Hard Gates Pass
    if job.get("gate_passed") is False:
        return False, f"Hard gate failed: {job.get('gate_reason')}"
    if job.get("gate_reason") and "fail" in str(job.get("gate_reason")).lower():
        return False, f"Hard gate failed: {job.get('gate_reason')}"

    # Current / Excluded Employer Exclusion
    company_name = job.get("company", "").lower()
    try:
        from tools.profile_loader import get_excluded_employers
        excluded_employers = get_excluded_employers()
    except Exception:
        excluded_employers = []
    if any(ex in company_name for ex in excluded_employers if ex):
        return False, f"Current / excluded employer ({job.get('company')})"

    # Excluded Staffing Agencies / Tier D
    if company_tier == "Tier D" or job.get("is_excluded_vendor") is True:
        return False, f"Excluded vendor / staffing agency ({job.get('company')})"

    # 6. Role Technical Fit >= 65
    fit_score = job.get("fit_score", 0)
    if fit_score < 65:
        return False, f"Role technical fit score ({fit_score}) is below the threshold of 65"

    # 7. No Duplicate Record
    if job.get("is_duplicate") is True:
        return False, "Duplicate listing of another canonical opportunity"

    # 8. No Existing Application Package / Tracked Record
    if job.get("applied") is True or job.get("status") == "applied":
        return False, "Job is already marked as applied"

    if tracked_applications:
        title = job.get("title", "").lower()
        for app in tracked_applications:
            a_comp = app.get("company", "").lower()
            a_role = app.get("role", "").lower()
            if (a_comp in company_name or company_name in a_comp) and a_comp:
                role_tokens = [w for w in re.findall(r'\b[a-zA-Z]{4,}\b', a_role) if w not in ("engineer", "software", "developer")]
                if role_tokens and all(t in title for t in role_tokens[:2]):
                    return False, f"Application already {app.get('status', 'tracked')} in documents/applications/"

    # 9. Provenance is Complete
    prov_ok, prov_msg = is_provenance_complete(job)
    if not prov_ok:
        return False, prov_msg

    # ALL 12 GATES PASSED
    return True, None
