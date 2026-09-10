"""
Unit tests for tools/ats_verifier.py.
Tests ATS type classification, closed-state marker detection, and HTML content verification.
"""

import unittest
from tools.ats_verifier import (
    detect_ats_type,
    verify_html_content
)

class TestAtsVerifier(unittest.TestCase):

    def test_detect_ats_type(self):
        self.assertEqual(detect_ats_type("https://cisco.wd5.myworkdayjobs.com/job/1"), "workday")
        self.assertEqual(detect_ats_type("https://boards.greenhouse.io/razorpay/jobs/123"), "greenhouse")
        self.assertEqual(detect_ats_type("https://jobs.lever.co/cred/abc"), "lever")
        self.assertEqual(detect_ats_type("https://jobs.smartrecruiters.com/Nexthink/123"), "smartrecruiters")
        self.assertEqual(detect_ats_type("https://jobs.ashbyhq.com/zepto/456"), "ashby")
        self.assertEqual(detect_ats_type("https://jobs.apple.com/en-us/details/123"), "apple_careers")
        self.assertEqual(detect_ats_type("https://in.linkedin.com/jobs/view/999"), "linkedin")

    def test_verify_html_content_active(self):
        html = """
        <html>
          <body>
            <h1>Senior Java Developer</h1>
            <p>Join our team building distributed systems.</p>
            <button class="btn-primary">Apply Now</button>
          </body>
        </html>
        """
        is_active, status, reason = verify_html_content(html)
        self.assertTrue(is_active)
        self.assertEqual(status, "active")
        self.assertIn("Active application CTA", reason)

    def test_verify_html_content_closed_marker_overrides_200(self):
        html = """
        <html>
          <body>
            <div class="banner">No longer accepting applications</div>
            <h1>Senior Java Developer</h1>
            <p>Role description...</p>
          </body>
        </html>
        """
        is_active, status, reason = verify_html_content(html)
        self.assertFalse(is_active)
        self.assertEqual(status, "closed")
        self.assertIn("Closed marker detected", reason)

    def test_verify_html_content_job_expired_marker(self):
        html = "<html><body><h1>This job has expired</h1><p>Check out our other openings.</p></body></html>"
        is_active, status, reason = verify_html_content(html)
        self.assertFalse(is_active)
        self.assertEqual(status, "closed")

    def test_verify_html_content_empty(self):
        is_active, status, reason = verify_html_content("")
        self.assertFalse(is_active)
        self.assertEqual(status, "closed")

if __name__ == "__main__":
    unittest.main()
