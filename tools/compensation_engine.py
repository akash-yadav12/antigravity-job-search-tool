"""
Dedicated Compensation Intelligence & Qualification Engine.
Implements multi-dimensional salary tracking, benchmark lookups, recency decay,
and the canonical candidate compensation decision matrix.
"""

import json
import os
import re
from datetime import datetime
from typing import Dict, Any, Tuple, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCHMARKS_PATH = os.path.join(WORKSPACE_DIR, "data/compensation_benchmarks.json")

# Candidate Targets (loaded dynamically from candidate profile)
def _load_targets():
    try:
        from tools.profile_loader import get_compensation_targets
        return get_compensation_targets()
    except Exception:
        return {
            "current_ctc": 31.0,
            "comfortable_min_base": 35.0,
            "preferred_base_target": 37.0,
            "min_acceptable_total": 42.0,
            "preferred_total_target": 45.0
        }

_targets = _load_targets()
CURRENT_CANDIDATE_CTC = _targets.get("current_ctc", 31.0)
PREFERRED_BASE_TARGET = _targets.get("preferred_base_target", 37.0)
COMFORTABLE_MIN_BASE = _targets.get("comfortable_min_base", 35.0)
MIN_ACCEPTABLE_TOTAL = _targets.get("min_acceptable_total", 42.0)
PREFERRED_TOTAL_TARGET = _targets.get("preferred_total_target", 45.0)
# Backward compatibility alias
CURRENT_JPMC_CTC = CURRENT_CANDIDATE_CTC

def load_benchmarks() -> Dict[str, Any]:
    """Loads the benchmark database from data/compensation_benchmarks.json."""
    if os.path.exists(BENCHMARKS_PATH):
        try:
            with open(BENCHMARKS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"companies": {}}

def extract_disclosed_salary(text: str) -> Optional[Dict[str, Any]]:
    """
    Extracts explicit salary disclosures from job posting description or salary strings.
    Handles INR Lakhs (e.g. 40-55 LPA, ₹45,00,000 - ₹60,00,000, 35-50 Lakhs per annum)
    and USD ranges (e.g. $120k-$160k USD converted to INR @ 84).
    """
    if not text:
        return None

    # 1. INR LPA patterns (e.g., "40 - 55 LPA", "35 to 50 lpa", "42-60 Lakhs")
    lpa_m = re.search(r'(?:₹|INR|Rs\.?)?\s*(\d+(?:\.\d+)?)\s*[-–—to]+\s*(\d+(?:\.\d+)?)\s*(?:LPA|Lacs?|Lakhs?|L)\b', text, re.IGNORECASE)
    if lpa_m:
        min_v = float(lpa_m.group(1))
        max_v = float(lpa_m.group(2))
        if 5.0 <= min_v <= 200.0:
            return {
                "salary_status": "disclosed",
                "base_min": min_v if min_v < 60 else None,
                "base_max": max_v if max_v < 60 else None,
                "variable_min": 0.0,
                "variable_max": 0.0,
                "equity_min": 0.0,
                "equity_max": 0.0,
                "total_comp_min": min_v,
                "total_comp_max": max_v,
                "currency": "INR",
                "compensation_type": "annual_lpa",
                "confidence": "high",
                "source": "employer_disclosed",
                "source_date": datetime.now().strftime("%Y-%m-%d"),
                "source_recency_days": 0,
                "level_assumption": "Employer Posted Range"
            }

    # 2. Raw INR Numbers (e.g., "₹40,00,000 - ₹60,00,000")
    raw_inr = re.search(r'(?:₹|INR|Rs\.?)?\s*(\d{2}),?(\d{2}),?(\d{3})\s*[-–—to]+\s*(?:₹|INR|Rs\.?)?\s*(\d{2}),?(\d{2}),?(\d{3})', text)
    if raw_inr:
        min_v = float(f"{raw_inr.group(1)}.{raw_inr.group(2)}")
        max_v = float(f"{raw_inr.group(4)}.{raw_inr.group(5)}")
        if 5.0 <= min_v <= 200.0:
            return {
                "salary_status": "disclosed",
                "base_min": min_v,
                "base_max": max_v,
                "variable_min": 0.0,
                "variable_max": 0.0,
                "equity_min": 0.0,
                "equity_max": 0.0,
                "total_comp_min": min_v,
                "total_comp_max": max_v,
                "currency": "INR",
                "compensation_type": "annual_lpa",
                "confidence": "high",
                "source": "employer_disclosed",
                "source_date": datetime.now().strftime("%Y-%m-%d"),
                "source_recency_days": 0,
                "level_assumption": "Employer Posted Range"
            }

    # 3. USD Ranges (e.g., "$120,000 - $160,000 USD" -> normalized to INR LPA @ 84)
    usd_m = re.search(r'\$\s*(\d{2,3})(?:,\d{3}|k)\s*[-–—to]+\s*\$\s*(\d{2,3})(?:,\d{3}|k)', text, re.IGNORECASE)
    if usd_m:
        usd_min = float(usd_m.group(1))
        usd_max = float(usd_m.group(2))
        inr_min = round((usd_min * 1000 * 84) / 100000, 1) # USD to LPA
        inr_max = round((usd_max * 1000 * 84) / 100000, 1)
        return {
            "salary_status": "disclosed",
            "base_min": inr_min,
            "base_max": inr_max,
            "variable_min": 0.0,
            "variable_max": 0.0,
            "equity_min": 0.0,
            "equity_max": 0.0,
            "total_comp_min": inr_min,
            "total_comp_max": inr_max,
            "currency": "INR",
            "compensation_type": "annual_lpa",
            "confidence": "high",
            "source": "employer_disclosed",
            "source_date": datetime.now().strftime("%Y-%m-%d"),
            "source_recency_days": 0,
            "level_assumption": f"Converted from USD (${usd_min}k-${usd_max}k @ ₹84/USD)"
        }

    return None

def lookup_company_benchmark(company: str, title: str = "", benchmarks_db: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Looks up compensation evidence from data/compensation_benchmarks.json.
    Matches company and title level (SWE II vs Senior vs Staff).
    """
    if not company:
        return None

    db = benchmarks_db or load_benchmarks()
    companies = db.get("companies", {})
    comp_key = company.lower().strip()

    # Find matching company
    matched_entry = None
    for k, v in companies.items():
        if k in comp_key or comp_key in k:
            matched_entry = v
            break

    if not matched_entry:
        return None

    levels = matched_entry.get("levels", {})
    t_lower = title.lower()

    # Select level based on title
    selected_level = None
    if any(s in t_lower for s in ["senior", "sr", "sde 3", "swe iii", "ict4", "l5", "avp", "grade 10"]):
        for lk, lv in levels.items():
            if any(s in lk for s in ["senior", "sde_3", "ict4", "l5", "avp", "grade_10"]):
                selected_level = lv
                break
    
    if not selected_level:
        # Default to standard SWE 2 / Mid level
        for lk, lv in levels.items():
            if any(s in lk for s in ["swe2", "sde_2", "ict3", "l4", "ba4", "grade_8", "associate", "se2"]):
                selected_level = lv
                break

    if not selected_level and levels:
        selected_level = list(levels.values())[0]

    if selected_level:
        recency = selected_level.get("source_recency_days", 30)
        conf = "high" if recency <= 90 else ("medium" if recency <= 270 else "low")
        return {
            "salary_status": "estimated",
            "base_min": selected_level.get("base_min"),
            "base_max": selected_level.get("base_max"),
            "variable_min": selected_level.get("variable_min", 0.0),
            "variable_max": selected_level.get("variable_max", 0.0),
            "equity_min": selected_level.get("equity_min", 0.0),
            "equity_max": selected_level.get("equity_max", 0.0),
            "total_comp_min": selected_level.get("total_min"),
            "total_comp_max": selected_level.get("total_max"),
            "currency": "INR",
            "compensation_type": "annual_lpa",
            "confidence": conf,
            "source": selected_level.get("source", "company_benchmark"),
            "source_date": selected_level.get("source_date"),
            "source_recency_days": recency,
            "level_assumption": selected_level.get("level_name", "SWE II / Mid-Senior SWE")
        }

    return None

def evaluate_compensation(job: Dict[str, Any], company_tier: str = "Tier C", benchmarks_db: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Main compensation evaluation entrypoint.
    Applies source hierarchy, parses disclosed or benchmark compensation,
    and classifies against the canonical candidate decision matrix.
    """
    title = job.get("title", "")
    company = job.get("company", "")
    desc = job.get("description", "")
    existing_salary = job.get("salary") or ""

    # 1. Try Employer Disclosed Range (Highest Tier)
    comp_data = extract_disclosed_salary(f"{desc} {existing_salary}")

    # 2. Try Company / Level Benchmark (Tier 2/3)
    if not comp_data:
        comp_data = lookup_company_benchmark(company, title, benchmarks_db)

    # 3. Fallback for Unknown Compensation
    if not comp_data:
        comp_data = {
            "salary_status": "unknown",
            "base_min": None,
            "base_max": None,
            "variable_min": None,
            "variable_max": None,
            "equity_min": None,
            "equity_max": None,
            "total_comp_min": None,
            "total_comp_max": None,
            "currency": "INR",
            "compensation_type": "annual_lpa",
            "confidence": "low",
            "source": "role_inference",
            "source_date": None,
            "source_recency_days": 999,
            "level_assumption": "Unknown compensation"
        }

    # Extract discrete values
    status = comp_data["salary_status"]
    total_min = comp_data.get("total_comp_min")
    total_max = comp_data.get("total_comp_max")
    base_min = comp_data.get("base_min")
    base_max = comp_data.get("base_max")

    # Compute conservative expected compensation values
    base_exp = None
    if base_min is not None and base_max is not None:
        base_exp = round((base_min + base_max) / 2.0, 1)
    elif base_min is not None:
        base_exp = base_min

    tot_exp = None
    if total_min is not None and total_max is not None:
        tot_exp = round((total_min + total_max) / 2.0, 1)
    elif total_min is not None:
        tot_exp = total_min

    decision = "UNKNOWN"
    reason = "No reliable compensation evidence"
    comp_fit = "unknown"
    comp_score = 50.0

    if status in ("disclosed", "estimated"):
        # 1. REJECT: Credible total compensation < ₹42L
        if total_max is not None and total_max < MIN_ACCEPTABLE_TOTAL:
            decision = "REJECT"
            comp_fit = "below_target"
            reason = f"Total compensation maximum (₹{total_max}L) is below the ₹{MIN_ACCEPTABLE_TOTAL}L minimum threshold"
            comp_score = 0.0

        # 2. STRONG TARGET: Base >= ₹37L (or expected >= ₹37L) AND Total expected >= ₹45L
        elif (
            ((base_min is not None and base_min >= PREFERRED_BASE_TARGET) or (base_exp is not None and base_exp >= PREFERRED_BASE_TARGET)) and
            ((tot_exp is not None and tot_exp >= PREFERRED_TOTAL_TARGET) or (total_min is not None and total_min >= PREFERRED_TOTAL_TARGET))
        ):
            decision = "TARGET"
            comp_fit = "strong"
            reason = f"Meets strong target compensation (Total: ₹{total_min}–{total_max}L [exp: ₹{tot_exp}L], Base: ₹{base_min}–{base_max}L [exp: ₹{base_exp}L])"
            if total_min is not None and total_min >= 55.0:
                comp_score = 100.0
            else:
                comp_score = 90.0

        # 3. TARGET / ACCEPTABLE: Base >= ₹35L (or expected >= ₹35L) AND (Total expected >= ₹42L OR Total Max >= ₹42L)
        elif (
            ((base_min is not None and base_min >= COMFORTABLE_MIN_BASE) or (base_exp is not None and base_exp >= COMFORTABLE_MIN_BASE)) and
            ((tot_exp is not None and tot_exp >= MIN_ACCEPTABLE_TOTAL) or (total_min is not None and total_min >= MIN_ACCEPTABLE_TOTAL) or (total_max is not None and total_max >= MIN_ACCEPTABLE_TOTAL))
        ):
            decision = "TARGET"
            comp_fit = "acceptable"
            reason = f"Meets acceptable target compensation within tolerance band (Total: ₹{total_min}–{total_max}L [exp: ₹{tot_exp}L], Base: ₹{base_min}–{base_max}L [exp: ₹{base_exp}L])"
            comp_score = 85.0 if (tot_exp is not None and tot_exp >= 45.0) else 80.0

        # 4. SELECTIVE: Base < ₹35L but Total >= ₹42L OR significant equity/variable
        elif total_max is not None and total_max >= MIN_ACCEPTABLE_TOTAL:
            decision = "SELECTIVE"
            comp_fit = "selective"
            reason = f"Total compensation qualifies (₹{total_min}–{total_max}L), but Base pay expected (₹{base_exp}L) is below ₹{COMFORTABLE_MIN_BASE}L or equity-heavy"
            comp_score = 75.0

        # 5. Fallback REJECT
        else:
            decision = "REJECT"
            comp_fit = "below_target"
            reason = f"Compensation does not clear the ₹{MIN_ACCEPTABLE_TOTAL}L total CTC gate"
            comp_score = 0.0

    elif status == "unknown":
        comp_fit = "unknown"
        if company_tier == "Tier A":
            decision = "SELECTIVE"
            reason = "Compensation unknown, but Tier A product employer retained for active research"
            comp_score = 70.0
        elif company_tier == "Tier B":
            decision = "SELECTIVE"
            reason = "Compensation unknown, but Tier B product/GCC employer retained for selective review"
            comp_score = 55.0
        else:
            decision = "UNKNOWN"
            reason = f"Compensation unknown for {company_tier} employer (Historical record only)"
            comp_score = 20.0

    result = dict(comp_data)
    result["base_expected"] = base_exp
    result["total_comp_expected"] = tot_exp
    result["compensation_fit"] = comp_fit
    result["decision"] = decision
    result["decision_reason"] = reason
    result["compensation_score"] = comp_score
    return result
