"""
Freshness Classification & Lifecycle Engine.
Strictly distinguishes:
- discovery_date: when our system first ingested the record
- posting_date: actual employer/platform published date
- last_verified_at: timestamp of authoritative live employer verification

States:
- closed: confirmed closed or expired
- fresh: verified on ATS <= 7 days ago, OR published <= 7 days ago
- recently_verified: verified on ATS 8-21 days ago, OR published 8-21 days ago
- stale: last verified or published > 21 days ago
- unknown: posting date cannot be determined and not verified on authoritative ATS
"""

from datetime import datetime
from typing import Dict, Any, Tuple, Optional

def parse_iso_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parses ISO or YYYY-MM-DD date strings safely."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00").split("+")[0])
    except Exception:
        try:
            return datetime.strptime(date_str[:10], "%Y-%m-%d")
        except Exception:
            return None

def calculate_age_days(date_str: Optional[str], reference_date: Optional[datetime] = None) -> int:
    """Calculates elapsed days from date string to now. Returns 999 if invalid/missing."""
    if not date_str:
        return 999
    ref = reference_date or datetime.now()
    parsed = parse_iso_date(date_str)
    if not parsed:
        return 999
    delta = ref - parsed
    return max(0, delta.days)

def evaluate_freshness(job: Dict[str, Any], verification_result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Evaluates freshness state and score for a job posting.
    Enforces that discovery_date != posting_date.
    Platform-only jobs with unknown posting date receive 'unknown'.
    """
    # 1. Check direct verification result if provided
    if verification_result:
        v_status = verification_result.get("status")
        if v_status in ("closed", "expired", "404", "failed_verification"):
            return {
                "freshness": "closed",
                "freshness_score": 0,
                "can_apply": False,
                "last_verified_at": verification_result.get("verified_at"),
                "reason": f"Closed on ATS: {verification_result.get('reason', 'inactive')}"
            }

    # 2. Check stored status in job
    current_status = job.get("status")
    if current_status in ("closed", "expired"):
        return {
            "freshness": "closed",
            "freshness_score": 0,
            "can_apply": False,
            "last_verified_at": job.get("last_verified_at"),
            "reason": "Stored status is closed/expired"
        }

    # 3. Extract distinct date attributes
    verified_at_str = (verification_result.get("verified_at") if verification_result else None) or job.get("last_verified_at")
    posting_date_str = (
        job.get("posting_date") or
        job.get("posted_at") or
        job.get("date_posted") or
        (job.get("date") if job.get("date_type") == "posting_date" else None)
    )
    discovery_date_str = job.get("discovery_date") or job.get("first_seen")

    v_age = calculate_age_days(verified_at_str)
    p_age = calculate_age_days(posting_date_str)

    # 4. Authority Level 1: Live Employer ATS Verification
    if v_age != 999:
        if v_age <= 7:
            # If posting date is explicitly known and older than 60 days, it is STALE!
            if p_age != 999 and p_age > 60:
                return {
                    "freshness": "stale",
                    "freshness_score": 20,
                    "can_apply": False,
                    "last_verified_at": verified_at_str,
                    "age_days": p_age,
                    "reason": f"Stale requisition: published {p_age} days ago (exceeds 60-day lifecycle)"
                }
            elif p_age != 999 and p_age > 21:
                return {
                    "freshness": "recently_verified",
                    "freshness_score": 50,
                    "can_apply": True,
                    "last_verified_at": verified_at_str,
                    "age_days": v_age,
                    "reason": f"Verified active on ATS {v_age} days ago (posting age: {p_age} days, approaching stale)"
                }
            return {
                "freshness": "fresh",
                "freshness_score": 100 if v_age <= 3 else 85,
                "can_apply": True,
                "last_verified_at": verified_at_str,
                "age_days": v_age,
                "reason": f"Verified active on employer ATS {v_age} days ago"
            }
        elif v_age <= 21:
            return {
                "freshness": "recently_verified",
                "freshness_score": 70 if v_age <= 14 else 50,
                "can_apply": True,
                "last_verified_at": verified_at_str,
                "age_days": v_age,
                "reason": f"Verified active on ATS {v_age} days ago"
            }
        else:
            return {
                "freshness": "stale",
                "freshness_score": 20,
                "can_apply": False,
                "last_verified_at": verified_at_str,
                "age_days": v_age,
                "reason": f"Stale verification ({v_age} days since last employer ATS check)"
            }

    # 5. Authority Level 2: Known Posting Date (Without ATS Verification)
    if p_age != 999:
        if p_age <= 7:
            return {
                "freshness": "fresh",
                "freshness_score": 75,
                "can_apply": False,  # Needs employer verification before apply per Section 9
                "last_verified_at": None,
                "age_days": p_age,
                "reason": f"Posted {p_age} days ago (unverified on employer ATS)"
            }
        elif p_age <= 21:
            return {
                "freshness": "recently_verified",
                "freshness_score": 55,
                "can_apply": False,
                "last_verified_at": None,
                "age_days": p_age,
                "reason": f"Posted {p_age} days ago (unverified on employer ATS)"
            }
        else:
            return {
                "freshness": "stale",
                "freshness_score": 20,
                "can_apply": False,
                "last_verified_at": None,
                "age_days": p_age,
                "reason": f"Stale posting ({p_age} days since publication)"
            }

    # 6. Authority Level 3: Posting Date Unknown and Not Employer Verified
    # Platform discovery does NOT imply freshness!
    return {
        "freshness": "unknown",
        "freshness_score": 30,
        "can_apply": False,
        "last_verified_at": None,
        "age_days": 999,
        "reason": "Posting date unknown and unverified on authoritative employer ATS"
    }
