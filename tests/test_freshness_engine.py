"""
Unit tests for tools/freshness_engine.py.
Tests freshness state classification, freshness score calculation, and /apply gating.
"""

import unittest
from datetime import datetime, timedelta
from tools.freshness_engine import (
    evaluate_freshness,
    calculate_age_days
)

class TestFreshnessEngine(unittest.TestCase):

    def test_fresh_active_job(self):
        job = {
            "first_seen": datetime.now().strftime("%Y-%m-%d"),
            "last_verified_at": datetime.now().strftime("%Y-%m-%d"),
            "status": "ranked"
        }
        res = evaluate_freshness(job)
        self.assertEqual(res["freshness"], "fresh")
        self.assertTrue(res["can_apply"])
        self.assertGreaterEqual(res["freshness_score"], 85)

    def test_unknown_freshness_without_posting_or_verification_date(self):
        job = {
            "first_seen": datetime.now().strftime("%Y-%m-%d"),
            "status": "ranked"
        }
        res = evaluate_freshness(job)
        self.assertEqual(res["freshness"], "unknown")
        self.assertFalse(res["can_apply"])
        self.assertEqual(res["freshness_score"], 30)

    def test_recently_verified_job(self):
        ten_days_ago = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        job = {
            "first_seen": ten_days_ago,
            "last_verified_at": ten_days_ago,
            "status": "ranked"
        }
        res = evaluate_freshness(job)
        self.assertEqual(res["freshness"], "recently_verified")
        self.assertTrue(res["can_apply"])
        self.assertEqual(res["freshness_score"], 70)

    def test_stale_job_cannot_apply(self):
        thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        job = {
            "first_seen": thirty_days_ago,
            "last_verified_at": thirty_days_ago,
            "status": "ranked"
        }
        res = evaluate_freshness(job)
        self.assertEqual(res["freshness"], "stale")
        self.assertFalse(res["can_apply"])
        self.assertEqual(res["freshness_score"], 20)

    def test_closed_verification_overrides_to_closed(self):
        job = {
            "first_seen": datetime.now().strftime("%Y-%m-%d"),
            "status": "ranked"
        }
        v_res = {
            "status": "closed",
            "reason": "404 Not Found on Workday",
            "verified_at": datetime.now().isoformat()
        }
        res = evaluate_freshness(job, verification_result=v_res)
        self.assertEqual(res["freshness"], "closed")
        self.assertFalse(res["can_apply"])
        self.assertEqual(res["freshness_score"], 0)

if __name__ == "__main__":
    unittest.main()
