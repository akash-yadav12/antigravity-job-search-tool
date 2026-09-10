"""
Unit and benchmark tests for tools/compensation_engine.py.
Covers salary regex extraction, benchmark lookups, and the required canonical benchmark scenarios.
"""

import unittest
from tools.compensation_engine import (
    extract_disclosed_salary,
    lookup_company_benchmark,
    evaluate_compensation,
    PREFERRED_BASE_TARGET,
    COMFORTABLE_MIN_BASE,
    MIN_ACCEPTABLE_TOTAL,
    PREFERRED_TOTAL_TARGET
)

class TestCompensationEngine(unittest.TestCase):

    def test_extract_disclosed_salary_lpa(self):
        text = "Compensation range: 40 - 55 LPA based on experience."
        res = extract_disclosed_salary(text)
        self.assertIsNotNone(res)
        self.assertEqual(res["salary_status"], "disclosed")
        self.assertEqual(res["total_comp_min"], 40.0)
        self.assertEqual(res["total_comp_max"], 55.0)

    def test_extract_disclosed_salary_raw_inr(self):
        text = "Fixed CTC: ₹38,00,000 - ₹48,00,000 per year."
        res = extract_disclosed_salary(text)
        self.assertIsNotNone(res)
        self.assertEqual(res["salary_status"], "disclosed")
        self.assertEqual(res["total_comp_min"], 38.0)
        self.assertEqual(res["total_comp_max"], 48.0)

    def test_extract_disclosed_salary_usd(self):
        text = "Salary: $120k - $150k USD for India remote."
        res = extract_disclosed_salary(text)
        self.assertIsNotNone(res)
        self.assertEqual(res["salary_status"], "disclosed")
        # 120 * 1000 * 84 / 100000 = 100.8 LPA
        self.assertGreaterEqual(res["total_comp_min"], 100.0)

    # -------------------------------------------------------------
    # Required Benchmark Scenarios
    # -------------------------------------------------------------

    def test_scenario_1_reject_below_42l(self):
        """Scenario 1: ₹30–35L -> REJECT (Below ₹42L minimum floor)"""
        job = {
            "title": "Java Backend Developer",
            "company": "Some Consultancy",
            "description": "Offering 30 - 35 LPA CTC"
        }
        res = evaluate_compensation(job, company_tier="Tier D")
        self.assertEqual(res["decision"], "REJECT")
        self.assertEqual(res["compensation_score"], 0.0)
        self.assertIn("below the ₹42.0L minimum", res["decision_reason"])

    def test_scenario_2_target_37l_base_plus_5l_var(self):
        """Scenario 2: ₹37L base + ₹5L variable (= ₹42L) -> TARGET"""
        job = {
            "title": "Software Engineer II",
            "company": "Fintech Firm",
            "description": "Base salary 37 to 42 LPA plus variable bonus"
        }
        res = evaluate_compensation(job, company_tier="Tier B")
        self.assertEqual(res["decision"], "TARGET")
        self.assertGreaterEqual(res["compensation_score"], 80.0)

    def test_scenario_3_tolerance_36l_base_plus_10l_equity(self):
        """Scenario 3: ₹36L expected base + equity (= ₹51L Total) -> TARGET (Base in ₹35-37L tolerance band & Total >= 42L)"""
        job = {
            "title": "Backend Engineer",
            "company": "Swiggy",
            "description": "" # resolves via Swiggy benchmark (Base: 32-40L [exp: 36L], Total: 43-60L [exp: 51.5L])
        }
        res = evaluate_compensation(job, company_tier="Tier A")
        self.assertEqual(res["decision"], "TARGET")
        self.assertEqual(res["compensation_fit"], "acceptable")
        self.assertGreaterEqual(res["total_comp_max"], 42.0)

    def test_scenario_4_target_45_to_55l_total(self):
        """Scenario 4: ₹45–55L total -> TARGET"""
        job = {
            "title": "Senior Backend Engineer",
            "company": "Product Co",
            "description": "Package is 45 - 55 LPA"
        }
        res = evaluate_compensation(job, company_tier="Tier B")
        self.assertEqual(res["decision"], "TARGET")
        self.assertGreaterEqual(res["compensation_score"], 90.0)

    def test_scenario_5_tier_a_unknown_labelled_unknown(self):
        """Scenario 5: Tier A unknown -> retain as SELECTIVE / labelled COMPENSATION UNKNOWN"""
        job = {
            "title": "Software Engineer II",
            "company": "Unknown New Big Tech Corp", # not in benchmark DB
            "description": "Competitive salary based on market standards"
        }
        res = evaluate_compensation(job, company_tier="Tier A")
        self.assertEqual(res["decision"], "SELECTIVE")
        self.assertEqual(res["salary_status"], "unknown")
        self.assertEqual(res["compensation_score"], 70.0)
        self.assertIn("retained for", res["decision_reason"])

    def test_benchmark_lookup_google_and_cisco(self):
        google_res = lookup_company_benchmark("Google", "Software Engineer III")
        self.assertIsNotNone(google_res)
        self.assertEqual(google_res["salary_status"], "estimated")
        self.assertGreaterEqual(google_res["total_comp_min"], 70.0)

        cisco_res = lookup_company_benchmark("Cisco", "Software Engineer")
        self.assertIsNotNone(cisco_res)
        self.assertGreaterEqual(cisco_res["total_comp_max"], 45.0)

if __name__ == "__main__":
    unittest.main()
