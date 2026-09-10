"""
Company Quality & Startup Qualification Engine.
Resolves company quality tiers (Tier A, Tier B, Tier C, Tier D), manual overrides,
and enforces the startup qualification policy.
"""

import json
import os
import re
from typing import Dict, Any, Tuple, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHLIST_PATH = os.path.join(WORKSPACE_DIR, "data/company_watchlist.json")

def load_watchlist() -> Dict[str, Any]:
    """Loads company watchlist and tier configurations."""
    if os.path.exists(WATCHLIST_PATH):
        try:
            with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"tier_a": [], "tier_b": [], "tier_c": [], "tier_d_exclude": [], "manual_overrides": {}}

def match_company_in_list(company: str, company_list: list) -> Optional[Dict[str, Any]]:
    """Helper to find a company in a watchlist list by name or alias."""
    c_lower = company.lower().strip()
    for entry in company_list:
        name_lower = entry["name"].lower()
        if name_lower == c_lower or name_lower in c_lower or c_lower in name_lower:
            return entry
        aliases = [a.lower() for a in entry.get("aliases", [])]
        if any(a == c_lower or a in c_lower for a in aliases):
            return entry
    return None

def resolve_company_tier(company: str, watchlist: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Resolves the company quality tier, quality score, and qualification metadata.
    """
    if not company:
        return {
            "tier": "Tier C",
            "quality_score": 60,
            "category": "unknown",
            "is_target": False,
            "is_excluded": False,
            "reason": "Unspecified company name"
        }

    wl = watchlist or load_watchlist()
    c_lower = company.lower().strip()

    # 1. Check Manual Overrides
    overrides = wl.get("manual_overrides", {})
    for k, v in overrides.items():
        if k in c_lower or c_lower in k:
            return {
                "tier": v.get("tier", "Tier C"),
                "quality_score": v.get("quality_score", 60),
                "category": "manual_override",
                "is_target": v.get("tier") in ("Tier A", "Tier B"),
                "is_excluded": v.get("tier") == "Tier D",
                "reason": f"Manual Override: {v.get('notes', '')}"
            }

    # 2. Check Tier D Exclusions (Consultancies / Staffing / IT Services)
    tier_d_excludes = wl.get("tier_d_exclude", [])
    if any(d in c_lower for d in tier_d_excludes):
        return {
            "tier": "Tier D",
            "quality_score": 20,
            "category": "it_services_consulting",
            "is_target": False,
            "is_excluded": True,
            "reason": "IT Service / Consulting vendor structure (High compensation ceiling risk)"
        }

    # 3. Check Tier A (Global Big Tech / Fintech / Top Indian Unicorns)
    tier_a_match = match_company_in_list(company, wl.get("tier_a", []))
    if tier_a_match:
        return {
            "tier": "Tier A",
            "quality_score": 100,
            "category": tier_a_match.get("category", "tier_a_target"),
            "is_target": True,
            "is_excluded": False,
            "reason": f"Tier A Target ({tier_a_match.get('name')})"
        }

    # 4. Check Tier B (Enterprise SaaS / Top GCCs)
    tier_b_match = match_company_in_list(company, wl.get("tier_b", []))
    if tier_b_match:
        return {
            "tier": "Tier B",
            "quality_score": 80,
            "category": tier_b_match.get("category", "enterprise_saas"),
            "is_target": True,
            "is_excluded": False,
            "reason": f"Tier B Target ({tier_b_match.get('name')})"
        }

    # 5. Check Tier C (Funded Product Startups / Mid-tier SaaS)
    tier_c_match = match_company_in_list(company, wl.get("tier_c", []))
    if tier_c_match:
        return {
            "tier": "Tier C",
            "quality_score": 60,
            "category": tier_c_match.get("category", "product_startup"),
            "is_target": True,
            "is_excluded": False,
            "reason": f"Tier C Startup ({tier_c_match.get('name')})"
        }

    # 6. Default Tier C Classification for unlisted product/tech firms
    return {
        "tier": "Tier C",
        "quality_score": 60,
        "category": "general_product",
        "is_target": False,
        "is_excluded": False,
        "reason": "Standard product / technology employer"
    }

def evaluate_startup_qualification(company: str, description: str = "", disclosed_base: Optional[float] = None) -> Dict[str, Any]:
    """
    Evaluates a startup against the qualification policy:
    - Unicorn / Series B+: Target
    - Series A: Selective (requires strong funding/engineering evidence, base >= 37L)
    - Seed: Exclude by default unless base >= 37L and exceptional evidence
    """
    d_lower = description.lower()
    c_lower = company.lower()
    full_text = f"{c_lower} {d_lower}"

    # Detect Funding Stage
    is_unicorn = any(k in full_text for k in ["unicorn", "soonicorn", "valuation >", "billion dollar"])
    is_series_b_plus = any(k in full_text for k in ["series b", "series c", "series d", "series e", "growth stage", "pre-ipo"])
    is_series_a = any(k in full_text for k in ["series a", "early stage product"])
    is_seed = any(k in full_text for k in ["seed stage", "pre-seed", "angel funded", "stealth"])

    if is_unicorn or is_series_b_plus:
        return {
            "stage": "Series B+ / Unicorn",
            "qualified": True,
            "tier": "Tier A" if is_unicorn else "Tier B",
            "reason": "High-growth scale-up / Unicorn stage"
        }
    elif is_series_a:
        if disclosed_base is not None and disclosed_base >= 37.0:
            return {
                "stage": "Series A",
                "qualified": True,
                "tier": "Tier C",
                "reason": f"Series A qualified with disclosed base ₹{disclosed_base}L (>= ₹37L floor)"
            }
        else:
            return {
                "stage": "Series A",
                "qualified": True,
                "tier": "Tier C",
                "reason": "Series A selective review required (Compensation unconfirmed)"
            }
    elif is_seed:
        if disclosed_base is not None and disclosed_base >= 37.0:
            return {
                "stage": "Seed Stage",
                "qualified": True,
                "tier": "Tier C",
                "reason": f"Seed stage exception granted (Disclosed base ₹{disclosed_base}L >= ₹37L)"
            }
        else:
            return {
                "stage": "Seed Stage",
                "qualified": False,
                "tier": "Tier D",
                "reason": "Seed stage without verified ₹37L+ base pay floor (Excluded)"
            }

    return {
        "stage": "Standard / Growth",
        "qualified": True,
        "tier": "Tier C",
        "reason": "Standard growth-stage tech company"
    }
