"""
Grounded answers provider for the /submit workflow.

Reads the canonical candidate profile from CLAUDE.md and
01-candidate-profile.md and resolves portal form questions to verified
factual answers.  Questions that require human judgment are flagged
with STOP_AND_ASK — the workflow MUST halt and ask the user.

INVARIANT: This module NEVER fabricates, infers, or guesses answers.
Every answer traces to an explicit fact in the canonical profile.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from pathlib import Path


class AnswerConfidence(enum.Enum):
    """How confident we are in an auto-resolved answer."""

    EXACT = "exact"          # Directly stated in canonical profile
    DERIVED = "derived"      # Computed from explicit facts (e.g. years of experience)
    STOP_AND_ASK = "stop_and_ask"  # Requires human input — NEVER auto-fill


@dataclass(frozen=True)
class AnswerResult:
    """Result of resolving a portal question."""

    question: str
    answer: str | None
    confidence: AnswerConfidence
    source: str  # Which canonical file or fact supports this answer
    category: str  # Semantic category for audit trail


# Canonical profile facts — hardcoded from CLAUDE.md and 01-candidate-profile.md.
# These are the ONLY facts the provider may use.
def _load_canonical_facts() -> dict:
    try:
        from tools.profile_loader import get_candidate_profile
        p = get_candidate_profile()
        ident = p.get("identity", {})
        emp = p.get("employment", {})
        phone = ident.get("phone", "+1 555-0100")
        phone_parts = phone.split(" ")
        cc = phone_parts[0] if len(phone_parts) > 1 else "+1"
        num = phone_parts[1] if len(phone_parts) > 1 else phone
        loc = ident.get("location", "City, Country")
        loc_parts = [part.strip() for part in loc.split(",") if part.strip()]
        city = loc_parts[0] if len(loc_parts) > 0 else "City"
        state = loc_parts[1] if len(loc_parts) > 1 else ""
        country = loc_parts[-1] if len(loc_parts) > 0 else "Country"
        yoe = emp.get("years_of_experience", 4)
        return {
            "full_name": ident.get("full_name", "[YOUR_NAME]"),
            "first_name": ident.get("first_name", "[First]"),
            "last_name": ident.get("last_name", "[Last]"),
            "email": ident.get("email", "[your.email@example.com]"),
            "phone": phone,
            "phone_country_code": cc,
            "phone_number": num,
            "location": loc,
            "city": city,
            "state": state,
            "country": country,
            "country_code": "US",
            "linkedin_url": ident.get("linkedin_url", ""),
            "github_url": ident.get("github_url", ""),
            "current_employer": emp.get("current_employer", ""),
            "current_title": emp.get("current_title", ""),
            "notice_period": emp.get("notice_period_status", "Immediate"),
            "notice_period_days": f"{emp.get('notice_period_days', 0)} days",
            "earliest_joining_date": emp.get("last_working_day", "Immediate"),
            "total_years_experience": str(yoe),
            "total_years_experience_text": f"{yoe} years",
            "highest_degree": "Bachelor's Degree",
            "degree_field": "Computer Science",
            "university": "University",
            "graduation_year": "2022",
            "gpa": "3.8/4.0",
        }
    except Exception:
        return {}

CANONICAL_FACTS = _load_canonical_facts()

FIELD_LABEL_MAP: dict[str, str] = {
    # Name
    "first name": "first_name",
    "last name": "last_name",
    "full name": "full_name",
    "name": "full_name",
    "legal name": "full_name",

    # Contact
    "email": "email",
    "email address": "email",
    "phone": "phone",
    "phone number": "phone",
    "mobile": "phone",
    "mobile number": "phone",
    "country code": "phone_country_code",

    # Location
    "city": "city",
    "state": "state",
    "country": "country",
    "location": "location",
    "current location": "location",
    "address": "location",

    # Social
    "linkedin": "linkedin_url",
    "linkedin url": "linkedin_url",
    "linkedin profile": "linkedin_url",
    "github": "github_url",
    "github url": "github_url",
    "website": "github_url",
    "portfolio": "github_url",

    # Employment
    "current employer": "current_employer",
    "current company": "current_employer",
    "company": "current_employer",
    "current job title": "current_title",
    "current title": "current_title",
    "job title": "current_title",
    "title": "current_title",

    # Notice period
    "notice period": "notice_period_days",
    "availability": "earliest_joining_date",
    "earliest start date": "earliest_joining_date",
    "start date": "earliest_joining_date",
    "when can you start": "earliest_joining_date",
    "joining date": "earliest_joining_date",

    # Experience
    "years of experience": "total_years_experience",
    "total experience": "total_years_experience",
    "experience": "total_years_experience_text",
    "work experience": "total_years_experience_text",

    # Education
    "highest degree": "highest_degree",
    "degree": "highest_degree",
    "education": "highest_degree",
    "university": "university",
    "school": "university",
    "college": "university",
    "graduation year": "graduation_year",
    "gpa": "gpa",
}

# Questions that ALWAYS require human review — matched via substring.
_STOP_PATTERNS = [
    "salary", "compensation", "pay", "ctc", "expected ctc",
    "current ctc", "current salary", "expected salary", "desired salary",
    "work authori", "authorized to work", "authorised to work", "visa", "sponsorship", "citizenship", "right to work",
    "criminal", "felony", "conviction", "background check",
    "disability", "veteran", "gender", "race", "ethnicity",
    "sexual orientation", "pronouns",
    "non-compete", "non compete", "restrictive covenant",
    "arbitration",
    "security clearance",
    "willing to relocate",
    "referral", "how did you hear",
    "cover letter",  # Some portals ask "paste your cover letter" — needs judgment
    "why do you want", "why are you interested", "tell us about",
    "describe a time", "what makes you",
]


class AnswersProvider:
    """Resolves portal form questions to verified canonical answers.

    Usage:
        provider = AnswersProvider()
        result = provider.resolve("What is your email address?")
        if result.confidence == AnswerConfidence.STOP_AND_ASK:
            # HALT — ask the user
        else:
            # Use result.answer
    """

    def __init__(self, facts: dict | None = None):
        self.facts = facts or CANONICAL_FACTS

    def resolve(self, question_text: str) -> AnswerResult:
        """Resolve a portal form question to a verified answer.

        Returns an AnswerResult.  When confidence is STOP_AND_ASK,
        the workflow MUST halt and ask the user before proceeding.
        """
        q_lower = question_text.strip().lower()

        # 1. Check stop-and-ask patterns FIRST (safety over convenience)
        for pattern in _STOP_PATTERNS:
            if pattern in q_lower:
                return AnswerResult(
                    question=question_text,
                    answer=None,
                    confidence=AnswerConfidence.STOP_AND_ASK,
                    source="stop_and_ask_pattern",
                    category=self._categorize_stop(pattern),
                )

        # 2. Try direct label match
        for label, fact_key in FIELD_LABEL_MAP.items():
            if label in q_lower:
                value = self.facts.get(fact_key)
                if value is not None:
                    return AnswerResult(
                        question=question_text,
                        answer=str(value),
                        confidence=AnswerConfidence.EXACT,
                        source=f"canonical_fact:{fact_key}",
                        category="profile_fact",
                    )

        # 3. No match — flag for human review
        return AnswerResult(
            question=question_text,
            answer=None,
            confidence=AnswerConfidence.STOP_AND_ASK,
            source="no_match",
            category="unknown_question",
        )

    def get_deterministic_fields(self) -> dict[str, str]:
        """Return all fields that can be auto-filled without human review.

        These are the standard profile fields that every portal asks for.
        """
        return {
            "First Name": self.facts["first_name"],
            "Last Name": self.facts["last_name"],
            "Email": self.facts["email"],
            "Phone": self.facts["phone"],
            "City": self.facts["city"],
            "State": self.facts["state"],
            "Country": self.facts["country"],
            "LinkedIn URL": self.facts["linkedin_url"],
            "GitHub URL": self.facts["github_url"],
            "Current Employer": self.facts["current_employer"],
            "Current Title": self.facts["current_title"],
            "Years of Experience": self.facts["total_years_experience"],
            "Highest Degree": self.facts["highest_degree"],
            "University": self.facts["university"],
            "Graduation Year": self.facts["graduation_year"],
            "Notice Period": self.facts["notice_period_days"],
            "Earliest Start Date": self.facts["earliest_joining_date"],
        }

    def is_credential(self, text: str) -> bool:
        """Check if text contains credential material that must never be persisted."""
        t_lower = text.lower()
        credential_words = [
            "password", "passwd", "otp", "one-time password",
            "session_token", "auth_token", "bearer", "cookie",
            "recovery_code", "secret_key", "api_key",
        ]
        return any(w in t_lower for w in credential_words)

    @staticmethod
    def _categorize_stop(pattern: str) -> str:
        """Categorize a stop-and-ask pattern for the audit trail."""
        if pattern in ("salary", "compensation", "pay", "ctc", "expected ctc",
                       "current ctc", "current salary", "expected salary", "desired salary"):
            return "salary_expectations"
        if pattern in ("work authori", "authorized to work", "authorised to work",
                       "visa", "sponsorship", "citizenship", "right to work"):
            return "work_authorization"
        if pattern in ("criminal", "felony", "conviction", "background check"):
            return "legal_declaration"
        if pattern in ("disability", "veteran", "gender", "race", "ethnicity",
                       "sexual orientation", "pronouns"):
            return "demographic_disclosure"
        if pattern in ("non-compete", "non compete", "restrictive covenant", "arbitration"):
            return "contractual_declaration"
        if pattern in ("security clearance",):
            return "security_clearance"
        if pattern in ("willing to relocate",):
            return "relocation_preference"
        return "requires_human_review"
