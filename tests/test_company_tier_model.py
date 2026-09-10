"""
Unit tests for tools/company_tier_model.py.
Tests company tier resolution, manual overrides, and startup qualification policies.
"""

import unittest
from tools.company_tier_model import (
    resolve_company_tier,
    evaluate_startup_qualification
)

class TestCompanyTierModel(unittest.TestCase):

    def test_tier_a_resolution(self):
        res = resolve_company_tier("Google")
        self.assertEqual(res["tier"], "Tier A")
        self.assertEqual(res["quality_score"], 100)
        self.assertTrue(res["is_target"])

        res_razorpay = resolve_company_tier("Razorpay Software")
        self.assertEqual(res_razorpay["tier"], "Tier A")

    def test_tier_b_resolution(self):
        res_cisco = resolve_company_tier("Cisco Systems")
        self.assertEqual(res_cisco["tier"], "Tier B")
        self.assertEqual(res_cisco["quality_score"], 85) # manual override / Tier B

        res_barclays = resolve_company_tier("Barclays")
        self.assertEqual(res_barclays["tier"], "Tier B")

    def test_tier_d_exclusions(self):
        res_tcs = resolve_company_tier("Tata Consultancy Services")
        self.assertEqual(res_tcs["tier"], "Tier D")
        self.assertTrue(res_tcs["is_excluded"])

        res_synechron = resolve_company_tier("Synechron Technologies")
        self.assertEqual(res_synechron["tier"], "Tier D")
        self.assertTrue(res_synechron["is_excluded"])

    def test_startup_qualification_series_b_plus(self):
        res = evaluate_startup_qualification("Growth Startup", "Series B funded AI startup with $50M ARR")
        self.assertTrue(res["qualified"])
        self.assertEqual(res["tier"], "Tier B")

    def test_startup_qualification_series_a_with_base(self):
        res = evaluate_startup_qualification("AI Platform Inc", "Series A AI infrastructure startup", disclosed_base=40.0)
        self.assertTrue(res["qualified"])
        self.assertEqual(res["tier"], "Tier C")

    def test_startup_qualification_seed_stage_without_base_excluded(self):
        res = evaluate_startup_qualification("Stealth Seed Co", "Early seed stage pre-revenue team", disclosed_base=None)
        self.assertFalse(res["qualified"])
        self.assertEqual(res["tier"], "Tier D")
        self.assertIn("Excluded", res["reason"])

    def test_startup_qualification_seed_stage_with_high_base_exception(self):
        res = evaluate_startup_qualification("Stealth AI", "Seed stage AI research lab", disclosed_base=42.0)
        self.assertTrue(res["qualified"])
        self.assertEqual(res["tier"], "Tier C")

if __name__ == "__main__":
    unittest.main()
