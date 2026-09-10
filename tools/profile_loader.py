"""
Centralized Profile Loader.
Provides dynamic, cached access to the candidate profile configuration,
seamlessly falling back to CLAUDE.md / 01-candidate-profile.md if needed.
"""

from __future__ import annotations
import json
import os
import re
from pathlib import Path
from typing import Dict, Any, Optional

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
PROFILE_JSON_PATH = WORKSPACE_DIR / "data" / "candidate_profile.json"
CLAUDE_MD_PATH = WORKSPACE_DIR / "CLAUDE.md"

_CACHED_PROFILE: Optional[Dict[str, Any]] = None

def get_candidate_profile(reload: bool = False) -> Dict[str, Any]:
    """Returns the loaded candidate profile dictionary."""
    global _CACHED_PROFILE
    if _CACHED_PROFILE is not None and not reload:
        return _CACHED_PROFILE

    profile: Dict[str, Any] = {}
    if PROFILE_JSON_PATH.exists():
        try:
            with open(PROFILE_JSON_PATH, "r", encoding="utf-8") as f:
                profile = json.load(f)
        except Exception:
            profile = {}

    # Ensure sections exist
    profile.setdefault("identity", {})
    profile.setdefault("employment", {})
    profile.setdefault("compensation", {})
    profile.setdefault("preferences", {})

    _CACHED_PROFILE = profile
    return _CACHED_PROFILE

def get_identity_fact(key: str, default: str = "") -> str:
    """Retrieves an identity field (e.g. full_name, email, phone)."""
    p = get_candidate_profile()
    return p.get("identity", {}).get(key, default)

def get_current_employer() -> str:
    """Returns candidate's current employer to support exclusion gates."""
    p = get_candidate_profile()
    return p.get("employment", {}).get("current_employer", "").strip()

def get_excluded_employers() -> list[str]:
    """Returns list of employers to exclude (current employer + preferences)."""
    p = get_candidate_profile()
    current = get_current_employer().lower()
    excluded = [e.lower() for e in p.get("preferences", {}).get("excluded_employers", [])]
    if current and current not in excluded:
        excluded.append(current)
    return excluded

def get_compensation_targets() -> Dict[str, float]:
    """Returns target compensation parameters."""
    p = get_candidate_profile()
    comp = p.get("compensation", {})
    return {
        "current_ctc": float(comp.get("current_ctc", 30.0)),
        "comfortable_min_base": float(comp.get("comfortable_min_base", 35.0)),
        "preferred_base_target": float(comp.get("preferred_base_target", 40.0)),
        "min_acceptable_total": float(comp.get("min_acceptable_total", 40.0)),
        "preferred_total_target": float(comp.get("preferred_total_target", 45.0)),
    }
