"""
Canonical Job Normalization & Deduplication Engine.
Implements the multi-tier canonical identity hierarchy:
1. employer + requisition ID
2. employer + normalized canonical ATS URL
3. employer + normalized title + metro
4. fuzzy fallback
"""

import re
import urllib.parse
from typing import Optional, Dict, Any, List, Tuple

# Supported Metro Hubs in priority order
METRO_HUBS = {
    "mumbai": ["mumbai", "navi mumbai", "thane", "mmr"],
    "bengaluru": ["bengaluru", "bangalore", "whitefield", "electronic city", "bellandur"],
    "pune": ["pune", "hinjewadi", "magarpatta", "kharadi"],
    "hyderabad": ["hyderabad", "secunderabad", "cyberabad", "gachibowli", "hitec city"],
    "delhi_ncr": ["gurugram", "gurgaon", "noida", "delhi", "new delhi", "ncr"],
    "chennai": ["chennai", "omr"],
    "remote": ["remote", "work from home", "anywhere in india", "remote india", "virtual"]
}

# Tracking query parameters to strip
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "refid", "source", "src", "trk", "trackingid", "gh_jid", "lever-source",
    "mode", "iis", "iisc", "sessionId", "originalSubdomain"
}

def normalize_slug(text: str) -> str:
    """Normalize any string to a lowercase alphanumeric slug with underscores."""
    if not text:
        return "unknown"
    s = text.lower().strip()
    # Replace non-alphanumeric with underscores
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    return s or "unknown"

def normalize_metro(location_str: str) -> str:
    """Classify a location string into a canonical metro hub."""
    if not location_str:
        return "india"
    loc_lower = location_str.lower().strip()
    for hub, variants in METRO_HUBS.items():
        if any(v in loc_lower for v in variants):
            return hub
    return "india"

def clean_url(url: str) -> str:
    """
    Strips tracking query parameters and fragment anchors from a URL while preserving
    canonical path and genuine query parameters.
    """
    if not url:
        return ""
    url = url.strip()
    try:
        parsed = urllib.parse.urlparse(url)
        # Drop fragment
        fragment = ""
        # Filter query params
        query_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
        filtered_params = [
            (k, v) for k, v in query_params
            if k.lower() not in TRACKING_PARAMS
        ]
        new_query = urllib.parse.urlencode(filtered_params)
        clean = urllib.parse.urlunparse((
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            parsed.params,
            new_query,
            fragment
        ))
        return clean
    except Exception:
        return url.split("?")[0].split("#")[0].rstrip("/")

def extract_requisition_id(url: str, title: str = "", description: str = "") -> Optional[str]:
    """
    Extracts a stable requisition ID from URL structure, title, or job description.
    Handles Workday (JR-XXXXX, R-XXXXX, 2023887-1), Greenhouse (numeric ID),
    Lever (UUID), SmartRecruiters (UUID), Ashby (UUID/slug), and LinkedIn numeric ID.
    """
    full_text = f"{url} {title} {description}"

    # 1. Direct explicit prefix patterns anywhere in URL or text (e.g. JR-0000103140, R-537630, JR0610837, R192175)
    pref_m = re.search(r'\b(JR[-_]?\d{4,10})\b', full_text, re.IGNORECASE)
    if pref_m:
        return pref_m.group(1).upper()

    pref_r = re.search(r'\b(R[-_]?\d{4,10})\b', full_text, re.IGNORECASE)
    if pref_r:
        return pref_r.group(1).upper()

    # 2. Workday URL slug suffix after underscore (e.g. /Software-Engineer_2023887-1 -> 2023887-1)
    wd_suffix = re.search(r'/job/[^/]+/[^/]+_([A-Za-z0-9_-]*\d{4,}[A-Za-z0-9_-]*)', url)
    if wd_suffix:
        cand = wd_suffix.group(1).strip("-_ ")
        if cand and len(cand) >= 4:
            return cand

    # 3. Workday direct numeric / alphanumeric job path (e.g. /job/Location/2023887-1 or reqId=...)
    wd_path = re.search(r'/job/[^/]+/(\d{5,}[A-Za-z0-9_-]*)', url)
    if wd_path:
        cand = wd_path.group(1).strip("-_ ")
        if cand and len(cand) >= 4:
            return cand

    # 4. Explicit Req ID / Job Code text patterns
    text_patterns = [
        r'[?&]reqId=([A-Za-z0-9_-]+)',
        r'\bReq(?:uisition)?\s*(?:ID|#|Number)?\s*[:\-]?\s*([A-Za-z0-9_-]{5,20})\b',
        r'\bJob\s*(?:ID|#|Code)\s*[:\-]?\s*([A-Za-z0-9_-]{5,20})\b',
        r'details/(\d{6,12}[-_]\d{2,6})/', # Apple format
        r'/(\d{6,10})-(?:java|software|senior|backend|engineer)'
    ]
    for pattern in text_patterns:
        m = re.search(pattern, full_text, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip("-_ ")
            if candidate and len(candidate) >= 4 and not candidate.lower().startswith("http"):
                return candidate.upper() if candidate.startswith(("jr", "r", "JR", "R")) else candidate

    # 5. Lever UUID in URL (e.g. jobs.lever.co/company/6b50bb8b-2a86-4e93-8c17-39b66f3e0789)
    lever_m = re.search(r'jobs\.lever\.co/[^/]+/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', url, re.IGNORECASE)
    if lever_m:
        return lever_m.group(1).lower()

    # 6. SmartRecruiters ID in URL (e.g. jobs.smartrecruiters.com/Company/743999741970976-java)
    sr_m = re.search(r'jobs\.smartrecruiters\.com/[^/]+/(\d{10,20})', url, re.IGNORECASE)
    if sr_m:
        return sr_m.group(1)

    # 7. Greenhouse Numeric ID in URL (e.g. boards.greenhouse.io/company/jobs/1234567)
    gh_m = re.search(r'boards\.greenhouse\.io/[^/]+/jobs/(\d{5,12})', url, re.IGNORECASE)
    if gh_m:
        return gh_m.group(1)

    # 8. Ashby UUID in URL (e.g. jobs.ashbyhq.com/company/3c4d5e...)
    ashby_m = re.search(r'jobs\.ashbyhq\.com/[^/]+/([0-9a-f-]{8,36})', url, re.IGNORECASE)
    if ashby_m:
        return ashby_m.group(1)

    # 9. LinkedIn Numeric ID in URL (e.g. linkedin.com/jobs/view/4444936956)
    li_m = re.search(r'linkedin\.com/jobs/view/(?:[^/]+-)?(\d{8,12})', url, re.IGNORECASE)
    if li_m:
        return f"LI_{li_m.group(1)}"

    return None

def normalize_title(title: str) -> str:
    """Clean and standardize job titles for robust fuzzy matching."""
    if not title:
        return "software_engineer"
    t = title.lower()
    # Strip common parentheticals like "(Java, Spring)", "(4-8 Years)", "(Bangalore)"
    t = re.sub(r'\(.*?\)', ' ', t)
    t = re.sub(r'\[.*?\]', ' ', t)
    t = re.sub(r'\b\d+\s*[-–—to]+\s*\d+\s*(?:years?|yrs?|yoe)\b', ' ', t)
    t = re.sub(r'\b\d+\+?\s*(?:years?|yrs?|yoe)\b', ' ', t)
    t = re.sub(r'\|\s*.*$', ' ', t) # strip anything after pipe
    t = re.sub(r'[-–—]\s*(?:bangalore|bengaluru|mumbai|pune|hyderabad|remote|india).*$', ' ', t)
    # Normalize core role phrases
    words = re.findall(r'[a-z0-9]+', t)
    core_words = [w for w in words if w not in {"at", "in", "with", "for", "and", "or", "to", "years", "yrs", "yoe", "experience"}]
    return "_".join(core_words) or "software_engineer"

def generate_canonical_job_id(company: str, title: str, location: str, url: str, req_id: Optional[str] = None) -> str:
    """
    Generates a deterministic canonical job ID following the multi-tier hierarchy:
    1. employer_slug::req::{requisition_id}
    2. employer_slug::url::{clean_ats_url_hash}
    3. employer_slug::title::{normalized_title}::metro::{normalized_metro}
    """
    comp_slug = normalize_slug(company)
    
    # Tier 1: Requisition ID
    if req_id:
        clean_req = normalize_slug(req_id)
        return f"{comp_slug}::req::{clean_req}"
    
    # Tier 2: Direct ATS URL
    c_url = clean_url(url)
    if any(ats in c_url.lower() for ats in ["myworkdayjobs.com", "greenhouse.io", "lever.co", "smartrecruiters.com", "ashbyhq.com"]):
        # Extract last path token or hash
        path_slug = normalize_slug(c_url.split("/")[-1])
        if len(path_slug) >= 4:
            return f"{comp_slug}::url::{path_slug}"

    # Tier 3: Normalized title + Metro Hub
    norm_title = normalize_title(title)
    norm_metro = normalize_metro(location)
    return f"{comp_slug}::title::{norm_title}::metro::{norm_metro}"

def is_employer_source(url: str) -> bool:
    """Returns True if the URL points directly to an employer careers portal or ATS."""
    if not url:
        return False
    u = url.lower()
    # Known ATS domains
    if any(ats in u for ats in ["myworkdayjobs.com", "myworkdaysite.com", "greenhouse.io", "lever.co", "smartrecruiters.com", "ashbyhq.com", "oraclecloud.com", "icims.com"]):
        return True
    # Known Direct employer career subdomains
    if any(d in u for d in ["jobs.apple.com", "careers.google.com", "careers.microsoft.com", "uber.com/careers", "stripe.com/jobs", "careers.jpmorgan.com", "goldmansachs.com/careers", "endurance.com/careers"]):
        return True
    return False

def merge_job_records(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merges an incoming job record into an existing canonical job record.
    Maintains:
    - Canonical URL: Employer ATS > Verified Aggregator ATS > LinkedIn
    - source_urls[] (union)
    - discovered_from[] (union)
    - first_seen (earliest)
    - last_seen (latest)
    - descriptions (keeps longest non-empty)
    """
    merged = dict(existing)
    
    # 1. Source URLs & Discovered Channels
    s_urls = list(dict.fromkeys(existing.get("source_urls", []) + incoming.get("source_urls", []) + [existing.get("url", ""), incoming.get("url", "")]))
    s_urls = [u for u in s_urls if u]
    merged["source_urls"] = s_urls

    d_from = list(dict.fromkeys(existing.get("discovered_from", []) + incoming.get("discovered_from", []) + [existing.get("source", ""), incoming.get("source", ""), existing.get("portal", ""), incoming.get("portal", "")]))
    d_from = [d for d in d_from if d]
    merged["discovered_from"] = d_from

    # 2. Canonical URL Precedence
    incoming_url = incoming.get("url", "")
    existing_url = existing.get("canonical_url", existing.get("url", ""))

    if is_employer_source(incoming_url) and not is_employer_source(existing_url):
        merged["canonical_url"] = incoming_url
        merged["canonical_source"] = "employer_ats"
    elif is_employer_source(existing_url):
        merged["canonical_url"] = existing_url
        merged["canonical_source"] = "employer_ats"
    elif "freehire.me" in existing_url and "linkedin.com" in incoming_url:
        merged["canonical_url"] = existing_url
        merged["canonical_source"] = "freehire"
    elif is_employer_source(incoming_url):
        merged["canonical_url"] = incoming_url
        merged["canonical_source"] = "employer_ats"
    else:
        merged["canonical_url"] = existing_url or incoming_url
        merged["canonical_source"] = existing.get("canonical_source") or incoming.get("canonical_source") or "aggregator"

    merged["url"] = merged["canonical_url"]

    # 3. Dates
    first_seen_dates = [d for d in [existing.get("first_seen"), incoming.get("first_seen")] if d]
    if first_seen_dates:
        merged["first_seen"] = min(first_seen_dates)
    
    last_seen_dates = [d for d in [existing.get("last_seen"), incoming.get("last_seen"), incoming.get("date"), existing.get("date")] if d]
    if last_seen_dates:
        merged["last_seen"] = max(last_seen_dates)

    # 4. Description (preserve longest)
    desc_ex = existing.get("description", "") or ""
    desc_in = incoming.get("description", "") or ""
    merged["description"] = desc_in if len(desc_in) > len(desc_ex) else desc_ex

    # 5. Requisition ID
    if not merged.get("requisition_id"):
        merged["requisition_id"] = incoming.get("requisition_id") or extract_requisition_id(incoming_url, incoming.get("title", ""), desc_in)

    # 6. Skills (union)
    skills = list(dict.fromkeys((existing.get("skills") or []) + (incoming.get("skills") or [])))
    merged["skills"] = skills

    return merged
