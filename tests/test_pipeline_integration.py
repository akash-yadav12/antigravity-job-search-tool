"""
Integration tests for the decoupled 8-stage production job-search pipeline.
Tests end-to-end flow across:
DISCOVERY -> NORMALIZATION -> ATS VERIFICATION -> FRESHNESS -> COMPENSATION -> HARD GATES -> FIT EVALUATION -> APPLICATION PRIORITY.
"""

import unittest
from tools.normalization import (
    clean_url,
    extract_requisition_id,
    generate_canonical_job_id,
    merge_job_records
)
from tools.company_tier_model import resolve_company_tier
from tools.compensation_engine import evaluate_compensation
from tools.freshness_engine import evaluate_freshness
from tools.evaluator import evaluate_hard_gates, evaluate_job_calibrated, calculate_application_priority

class TestPipelineIntegration(unittest.TestCase):

    def test_tier_a_role_high_fit_and_high_comp_becomes_p0(self):
        """A Tier-A company with strong technical fit and >= ₹45L comp qualifies for P0 (Apply Now)."""
        raw_job = {
            "title": "Software Engineer II - Java, Spring, Kafka",
            "company": "Apple",
            "location": "Bengaluru, Karnataka, India",
            "url": "https://jobs.apple.com/en-us/details/200675619-0321/software-development-engineer",
            "first_seen": "2026-09-01",
            "skills": ["java 17", "spring boot", "kafka", "distributed systems", "aws", "docker", "ai"],
            "description": "5+ years of experience with Core Java 17/21, Spring Boot, and Kafka distributed architectures."
        }

        # 1. Normalization
        req_id = extract_requisition_id(raw_job["url"], raw_job["title"])
        can_id = generate_canonical_job_id(raw_job["company"], raw_job["title"], raw_job["location"], raw_job["url"], req_id)
        self.assertEqual(can_id, "apple::req::200675619_0321")

        # 2. Company Tier
        tier_info = resolve_company_tier(raw_job["company"])
        self.assertEqual(tier_info["tier"], "Tier A")
        self.assertEqual(tier_info["quality_score"], 100)

        # 3. Freshness
        fresh_info = evaluate_freshness(raw_job)
        self.assertEqual(fresh_info["freshness"], "fresh")
        self.assertTrue(fresh_info["can_apply"])

        # 4. Compensation
        comp_info = evaluate_compensation(raw_job, company_tier=tier_info["tier"])
        self.assertIn(comp_info["decision"], ("TARGET", "SELECTIVE"))
        self.assertGreaterEqual(comp_info["compensation_score"], 80.0)

        # 5. Hard Gates
        passed_gates, reason = evaluate_hard_gates(raw_job["title"], raw_job["description"], raw_job["location"])
        self.assertTrue(passed_gates)

        # 6. Calibrated Technical Fit
        fit_eval = evaluate_job_calibrated(raw_job)
        fit_score = fit_eval["rank_score"]
        self.assertGreaterEqual(fit_score, 80)

        # 7. Application Priority
        priority_score, priority_tier, priority_label = calculate_application_priority(
            fit_score=fit_score,
            comp_score=comp_info["compensation_score"],
            quality_score=tier_info["quality_score"],
            freshness_score=fresh_info["freshness_score"],
            comp_fit=comp_info.get("compensation_fit", "strong")
        )

        self.assertGreaterEqual(priority_score, 88)
        self.assertEqual(priority_tier, "P0")
        self.assertIn("P0 — Apply Now", priority_label)

    def test_low_comp_consultancy_job_is_hard_rejected_despite_high_fit(self):
        """A ₹25L role from a consultancy fails the compensation hard gate regardless of technical keyword overlap."""
        consultancy_job = {
            "title": "Java Spring Boot Microservices Developer",
            "company": "TCS",
            "location": "Mumbai, Maharashtra, India",
            "url": "https://careers.tcs.com/job/123",
            "skills": ["java", "spring boot", "kafka", "mysql"],
            "description": "Offering standard package 20 - 25 LPA CTC for experienced Java developers."
        }

        tier_info = resolve_company_tier(consultancy_job["company"])
        self.assertEqual(tier_info["tier"], "Tier D")
        self.assertTrue(tier_info["is_excluded"])

        comp_info = evaluate_compensation(consultancy_job, company_tier=tier_info["tier"])
        self.assertEqual(comp_info["decision"], "REJECT")
        self.assertEqual(comp_info["compensation_score"], 0.0)

    def test_tier_a_role_with_weak_technical_fit_does_not_become_p0(self):
        """A Tier A company (Google) with a weak technical fit (e.g. mobile/iOS) is rejected at hard gate."""
        weak_tech_job = {
            "title": "iOS Developer - Swift / Mobile UI",
            "company": "Google",
            "location": "Bengaluru, India",
            "url": "https://careers.google.com/jobs/results/999",
            "description": "5+ years building native iOS apps in Swift and UIKit."
        }

        tier_info = resolve_company_tier(weak_tech_job["company"])
        self.assertEqual(tier_info["tier"], "Tier A")

        passed_gates, reason = evaluate_hard_gates(weak_tech_job["title"], weak_tech_job["description"], weak_tech_job["location"])
        self.assertFalse(passed_gates)
        self.assertIn("Pure mobile development role", reason)

if __name__ == "__main__":
    unittest.main()
