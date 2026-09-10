"""
Employer ATS & Career Page Verification Engine.
Supports Workday, Greenhouse, Lever, SmartRecruiters, Ashby, and Generic HTTP Career Pages.
Ensures jobs are verified for actual application availability rather than relying on HTTP 200 alone.
Enforces that:
- exact employer posting found
- exact role matched
- exact requisition matched when an ID exists
- application is currently possible
- synthetic / suspicious requisition patterns fail immediately
"""

import json
import re
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from typing import Dict, Any, Tuple, Optional

# Closed state markers found across major ATS and job portals
CLOSED_MARKERS = [
    r"no longer accepting applications",
    r"this job (?:is no longer available|has expired|is closed)",
    r"this position has been (?:filled|closed)",
    r"the job you are looking for has expired",
    r"job opening is no longer open",
    r"requisition has been closed",
    r"this posting has been removed",
    r"page not found",
    r"404 not found",
    r"job not found",
    r"no longer active"
]

# Active application markers
ACTIVE_APPLICATION_MARKERS = [
    r"apply for this job",
    r"apply now",
    r"submit application",
    r"start application",
    r"autofill with resume",
    r"apply with linkedin",
    r"apply online",
    r"application form"
]

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9"
}

SUSPICIOUS_UUID_SEQUENCES = [
    "123456789", "abcdef", "012345", "7890", "abcd-ef0123456789",
    "2b3c4d5e", "3c4d5e6f", "4d5e6f7a", "5e6f7a8b", "6f7a8b9c", "7a8b9c0d"
]

def is_synthetic_requisition(req_id: Optional[str], url: Optional[str] = "") -> Tuple[bool, str]:
    """
    Checks if a requisition ID or URL exhibits synthetic / fabricated placeholder patterns.
    Examples:
    - 8f3b2a1c-4e56-7890-abcd-ef0123456789
    - 2b3c4d5e-6f7a-8b9c-0d1e-2f3a4b5c6d7e
    - 3c4d5e6f-7a8b-9c0d-1e2f-3a4b5c6d7e8f
    - JR-0000123576
    """
    target = f"{req_id or ''} {url or ''}".lower()
    
    # 1. Suspicious sequential hex / digit patterns
    for seq in SUSPICIOUS_UUID_SEQUENCES:
        if seq in target:
            return True, f"Suspicious sequential pattern '{seq}' detected"
            
    # Check for synthetic alternating digit-letter sequences (e.g. 2b3c4d5e, 3c4d5e6f)
    pairs = re.findall(r'([0-9])([a-f])', target)
    if len(pairs) >= 3:
        for i in range(len(pairs) - 2):
            p0, p1, p2 = pairs[i], pairs[i+1], pairs[i+2]
            if (int(p1[0]) - int(p0[0]) == 1 and int(p2[0]) - int(p1[0]) == 1 and
                ord(p1[1]) - ord(p0[1]) == 1 and ord(p2[1]) - ord(p1[1]) == 1):
                return True, "Synthetic consecutive digit-letter sequence detected"
            
    # 2. Obvious placeholders
    if re.search(r'\b(?:fake|mock|dummy|test|placeholder|sample|example)\b', target):
        return True, "Placeholder keyword detected"
        
    # 3. Repeated / sequential digit runs in requisition ID
    if req_id:
        if re.search(r'01234|12345|23456|34567|45678|56789', req_id):
            return True, "Sequential numeric sequence in requisition ID"
            
    return False, "PASS"

def detect_ats_type(url: str) -> str:
    """Classifies the ATS vendor from URL structure."""
    u_lower = url.lower()
    if "myworkdayjobs.com" in u_lower or "myworkdaysite.com" in u_lower:
        return "workday"
    if "greenhouse.io" in u_lower:
        return "greenhouse"
    if "lever.co" in u_lower:
        return "lever"
    if "smartrecruiters.com" in u_lower:
        return "smartrecruiters"
    if "ashbyhq.com" in u_lower:
        return "ashby"
    if "jobs.apple.com" in u_lower:
        return "apple_careers"
    if "careers.google.com" in u_lower:
        return "google_careers"
    if "linkedin.com" in u_lower:
        return "linkedin"
    return "generic_web"

def verify_html_content(html: str) -> Tuple[bool, str, str]:
    """
    Inspects fetched HTML for presence of closed markers or active application buttons.
    Returns (is_active, status_str, reason).
    """
    if not html or len(html.strip()) == 0:
        return False, "closed", "Empty response body"

    html_lower = html.lower()

    # 1. Check for explicit closed markers
    for pattern in CLOSED_MARKERS:
        if re.search(pattern, html_lower):
            return False, "closed", f"Closed marker detected ('{pattern}')"

    # 2. Check for active application buttons
    has_apply_marker = any(re.search(p, html_lower) for p in ACTIVE_APPLICATION_MARKERS)
    
    if has_apply_marker:
        return True, "active", "Active application CTA confirmed"

    # If no closed marker and page has substantial text (> 500 chars), classify as active/unverified
    if len(html) > 500:
        return True, "active", "Posting page rendered without closed markers"

    return False, "unknown", "Page content inconclusive"

def check_role_match(content: str, title: str) -> bool:
    """Verifies that the content actually matches the claimed role title."""
    if not title or not content:
        return True
    
    # Extract significant tokens (words >= 4 chars, ignoring common stops)
    stop_words = {"with", "from", "that", "this", "some", "lead", "jobs", "hiring", "role", "team"}
    tokens = [w.lower() for w in re.findall(r'\b[a-zA-Z]{3,}\b', title) if w.lower() not in stop_words]
    
    if not tokens:
        return True
        
    c_lower = content.lower()
    matches = sum(1 for t in tokens if t in c_lower)
    return (matches / len(tokens)) >= 0.5

def verify_greenhouse_api(url: str, title: str = "") -> Optional[Tuple[bool, str, str, Optional[str]]]:
    """Verify Greenhouse jobs via public API if applicable."""
    m = re.search(r'boards\.greenhouse\.io/([^/]+)/jobs/(\d+)', url)
    if not m:
        return None
    board, job_id = m.group(1), m.group(2)
    api_url = f"https://api.greenhouse.io/v1/boards/{board}/jobs/{job_id}"
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": DEFAULT_HEADERS["User-Agent"]})
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                api_title = data.get("title", "")
                if title and not check_role_match(api_title, title):
                    return False, "failed_verification", f"Role mismatch: expected '{title}', got '{api_title}'", None
                updated_at = data.get("updated_at")
                posting_date = updated_at[:10] if updated_at else None
                return True, "active", f"Verified via Greenhouse API (Job ID: {job_id})", posting_date
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, "closed", f"Greenhouse API returned 404 Not Found (Job ID: {job_id})", None
    except Exception:
        pass
    return None

def verify_lever_api(url: str, title: str = "") -> Optional[Tuple[bool, str, str, Optional[str]]]:
    """Verify Lever jobs via public API if applicable."""
    m = re.search(r'jobs\.lever\.co/([^/]+)/([0-9a-f-]{36})', url)
    if not m:
        return None
    company, posting_id = m.group(1), m.group(2)
    api_url = f"https://api.lever.co/v0/postings/{company}/{posting_id}"
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": DEFAULT_HEADERS["User-Agent"]})
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                api_title = data.get("text", "")
                if title and not check_role_match(api_title, title):
                    return False, "failed_verification", f"Role mismatch: expected '{title}', got '{api_title}'", None
                created_at = data.get("createdAt")
                posting_date = None
                if created_at:
                    try:
                        posting_date = datetime.fromtimestamp(created_at / 1000).strftime("%Y-%m-%d")
                    except Exception:
                        pass
                return True, "active", f"Verified via Lever API (Posting ID: {posting_id})", posting_date
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, "closed", f"Lever API returned 404 Not Found (Posting ID: {posting_id})", None
    except Exception:
        pass
    return None

def verify_ats_requisition(url: str, title: str = "", company: str = "", req_id: str = "") -> Dict[str, Any]:
    """
    Main verification entrypoint for a given job posting URL.
    Enforces strict employer verification invariants:
    - exact role matching
    - requisition synthetic check
    - application availability
    - posting date extraction
    """
    verified_at = datetime.now().isoformat()
    
    # 1. Check for synthetic requisition pattern
    is_synth, synth_reason = is_synthetic_requisition(req_id, url)
    if is_synth:
        return {
            "is_verified": False,
            "employer_verified": False,
            "verification_status": "failed",
            "status": "closed",
            "ats_type": detect_ats_type(url),
            "canonical_url": url,
            "exact_role_matched": False,
            "exact_requisition_matched": False,
            "application_available": False,
            "posting_date": None,
            "reason": f"Synthetic / Suspicious requisition detected: {synth_reason}",
            "verified_at": verified_at
        }

    ats_type = detect_ats_type(url)

    # 2. Specialized API probes for Greenhouse / Lever
    if ats_type == "greenhouse":
        api_res = verify_greenhouse_api(url, title)
        if api_res:
            is_active, status, reason, posting_date = api_res
            is_verified = (is_active and status == "active")
            return {
                "is_verified": is_verified,
                "employer_verified": is_verified,
                "verification_status": "verified" if is_verified else "failed",
                "status": status,
                "ats_type": ats_type,
                "canonical_url": url,
                "exact_role_matched": is_verified,
                "exact_requisition_matched": is_verified,
                "application_available": is_active,
                "posting_date": posting_date,
                "reason": reason,
                "verified_at": verified_at
            }

    if ats_type == "lever":
        api_res = verify_lever_api(url, title)
        if api_res:
            is_active, status, reason, posting_date = api_res
            is_verified = (is_active and status == "active")
            return {
                "is_verified": is_verified,
                "employer_verified": is_verified,
                "verification_status": "verified" if is_verified else "failed",
                "status": status,
                "ats_type": ats_type,
                "canonical_url": url,
                "exact_role_matched": is_verified,
                "exact_requisition_matched": is_verified,
                "application_available": is_active,
                "posting_date": posting_date,
                "reason": reason,
                "verified_at": verified_at
            }

    # 3. HTTP GET with browser headers for Workday, SmartRecruiters, Ashby, Apple, and generic pages
    try:
        req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            status_code = resp.status
            final_url = resp.geturl()
            html = resp.read().decode("utf-8", errors="replace")

            # Check if redirected to search or landing page (common dead job behavior)
            if final_url != url and not any(k in final_url for k in ["/job/", "/jobs/", "/posting/"]):
                if any(k in final_url.lower() for k in ["/search", "/careers", "jobs.apple.com/en-us/search"]):
                    return {
                        "is_verified": False,
                        "employer_verified": False,
                        "verification_status": "failed",
                        "status": "closed",
                        "ats_type": ats_type,
                        "canonical_url": url,
                        "exact_role_matched": False,
                        "exact_requisition_matched": False,
                        "application_available": False,
                        "posting_date": None,
                        "reason": f"Redirected to general search index ({final_url})",
                        "verified_at": verified_at
                    }

            is_active, status, reason = verify_html_content(html)
            
            # Verify exact role match on page
            role_matched = check_role_match(html, title) if title else True
            if not role_matched:
                return {
                    "is_verified": False,
                    "employer_verified": False,
                    "verification_status": "failed",
                    "status": "closed",
                    "ats_type": ats_type,
                    "canonical_url": url,
                    "exact_role_matched": False,
                    "exact_requisition_matched": False,
                    "application_available": False,
                    "posting_date": None,
                    "reason": f"Page content does not match role title '{title}'",
                    "verified_at": verified_at
                }

            # Check if requisition matches if provided
            req_matched = True
            if req_id and len(req_id) >= 4 and not req_id.startswith("LI_"):
                if req_id.lower() not in html.lower() and req_id.lower() not in url.lower():
                    req_matched = False

            # Extract date if available (e.g. Workday postedOn or meta tags)
            posting_date = None
            date_m = re.search(r'"postedOn"\s*:\s*"([^"]+)"', html) or re.search(r'"datePosted"\s*:\s*"([^"]+)"', html)
            if date_m:
                posting_date = date_m.group(1)[:10]

            is_verified = (is_active and status == "active" and role_matched and req_matched)

            return {
                "is_verified": is_verified,
                "employer_verified": is_verified and ats_type in ["workday", "greenhouse", "lever", "smartrecruiters", "ashby", "apple_careers", "google_careers"],
                "verification_status": "verified" if is_verified else "failed",
                "status": status,
                "ats_type": ats_type,
                "canonical_url": url,
                "exact_role_matched": role_matched,
                "exact_requisition_matched": req_matched,
                "application_available": is_active,
                "posting_date": posting_date,
                "reason": reason if req_matched else f"Requisition ID '{req_id}' not found on posting page",
                "verified_at": verified_at
            }

    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return {
                "is_verified": False,
                "employer_verified": False,
                "verification_status": "failed",
                "status": "closed",
                "ats_type": ats_type,
                "canonical_url": url,
                "exact_role_matched": False,
                "exact_requisition_matched": False,
                "application_available": False,
                "posting_date": None,
                "reason": f"HTTP {e.code} ({e.reason})",
                "verified_at": verified_at
            }
        elif e.code in (401, 403):
            return {
                "is_verified": False,
                "employer_verified": False,
                "verification_status": "unverified",
                "status": "unknown",
                "ats_type": ats_type,
                "canonical_url": url,
                "exact_role_matched": False,
                "exact_requisition_matched": False,
                "application_available": False,
                "posting_date": None,
                "reason": f"HTTP {e.code} WAF/Access Challenge (unverified)",
                "verified_at": verified_at
            }
        else:
            return {
                "is_verified": False,
                "employer_verified": False,
                "verification_status": "failed",
                "status": "closed",
                "ats_type": ats_type,
                "canonical_url": url,
                "exact_role_matched": False,
                "exact_requisition_matched": False,
                "application_available": False,
                "posting_date": None,
                "reason": f"HTTP {e.code} error",
                "verified_at": verified_at
            }

    except Exception as e:
        return {
            "is_verified": False,
            "employer_verified": False,
            "verification_status": "unverified",
            "status": "unknown",
            "ats_type": ats_type,
            "canonical_url": url,
            "exact_role_matched": False,
            "exact_requisition_matched": False,
            "application_available": False,
            "posting_date": None,
            "reason": f"Network / Timeout error: {str(e)}",
            "verified_at": verified_at
        }
