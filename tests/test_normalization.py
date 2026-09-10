"""
Unit tests for tools/normalization.py.
Tests URL cleaning, requisition ID extraction, metro hub normalization,
canonical job ID generation, and multi-source deduplication merging.
"""

import unittest
from tools.normalization import (
    clean_url,
    normalize_slug,
    normalize_metro,
    extract_requisition_id,
    normalize_title,
    generate_canonical_job_id,
    merge_job_records,
    is_employer_source
)

class TestNormalization(unittest.TestCase):

    def test_clean_url_strips_tracking_and_fragments(self):
        dirty = "https://cisco.wd5.myworkdayjobs.com/Cisco_Careers/job/Bangalore-India/Software-Engineer_2023887-1?utm_source=freehire.me&utm_medium=aggregator&ref=123#overview"
        expected = "https://cisco.wd5.myworkdayjobs.com/Cisco_Careers/job/Bangalore-India/Software-Engineer_2023887-1"
        self.assertEqual(clean_url(dirty), expected)

    def test_extract_requisition_id_workday(self):
        url = "https://barclays.wd3.myworkdayjobs.com/External_Career_Site_Barclays/job/Bengaluru/Software-Engineer-Confluent-Kafka_JR-0000103140"
        req_id = extract_requisition_id(url)
        self.assertEqual(req_id, "JR-0000103140")

    def test_extract_requisition_id_numeric_workday(self):
        url = "https://cisco.wd5.myworkdayjobs.com/Cisco_Careers/job/Bangalore-India/Software-Engineer_2023887-1"
        req_id = extract_requisition_id(url)
        self.assertEqual(req_id, "2023887-1")

    def test_extract_requisition_id_lever(self):
        url = "https://jobs.lever.co/zimperium/6b50bb8b-2a86-4e93-8c17-39b66f3e0789"
        req_id = extract_requisition_id(url)
        self.assertEqual(req_id, "6b50bb8b-2a86-4e93-8c17-39b66f3e0789")

    def test_extract_requisition_id_smartrecruiters(self):
        url = "https://jobs.smartrecruiters.com/Nexthink/743999741970976-java-engineer"
        req_id = extract_requisition_id(url)
        self.assertEqual(req_id, "743999741970976")

    def test_extract_requisition_id_linkedin(self):
        url = "https://in.linkedin.com/jobs/view/java-backend-software-engineer-at-bluehost-4442549466"
        req_id = extract_requisition_id(url)
        self.assertEqual(req_id, "LI_4442549466")

    def test_normalize_metro(self):
        self.assertEqual(normalize_metro("Bengaluru, Karnataka, India"), "bengaluru")
        self.assertEqual(normalize_metro("Bangalore Urban"), "bengaluru")
        self.assertEqual(normalize_metro("Mumbai Metropolitan Region"), "mumbai")
        self.assertEqual(normalize_metro("Navi Mumbai, Maharashtra"), "mumbai")
        self.assertEqual(normalize_metro("Pune - Hinjewadi"), "pune")
        self.assertEqual(normalize_metro("Hyderabad, Telangana"), "hyderabad")
        self.assertEqual(normalize_metro("Remote - India"), "remote")

    def test_canonical_job_id_deterministic(self):
        id1 = generate_canonical_job_id("Cisco", "Software Engineer - Java/Go", "Bengaluru", "https://cisco.wd5.myworkdayjobs.com/job/123", req_id="2023887-1")
        id2 = generate_canonical_job_id("Cisco Systems", "Software Engineer (Java/Go) 4 to 8 Years", "Bangalore", "https://linkedin.com/jobs/view/999", req_id="2023887-1")
        self.assertEqual(id1, "cisco::req::2023887_1")
        self.assertEqual(id2, "cisco_systems::req::2023887_1")

    def test_merge_job_records_prefers_ats_url(self):
        existing = {
            "title": "Software Engineer – Java/Go",
            "company": "Cisco",
            "url": "https://in.linkedin.com/jobs/view/4446805994",
            "canonical_url": "https://in.linkedin.com/jobs/view/4446805994",
            "source": "linkedin-search",
            "source_urls": ["https://in.linkedin.com/jobs/view/4446805994"],
            "discovered_from": ["linkedin-search"],
            "first_seen": "2026-08-30",
            "last_seen": "2026-08-30"
        }
        incoming = {
            "title": "Software Engineer – Java/Go | Distributed Systems",
            "company": "Cisco",
            "url": "https://cisco.wd5.myworkdayjobs.com/Cisco_Careers/job/Bangalore-India/Software-Engineer---Java-Go---Distributed-Systems---Microservices---Kafka---Cloud---4-8-Years_2023887-1",
            "source": "freehire-search",
            "portal": "workday",
            "first_seen": "2026-09-01",
            "date": "2026-09-01",
            "description": "Full JD text with 2000 chars..."
        }

        merged = merge_job_records(existing, incoming)
        self.assertTrue(is_employer_source(merged["canonical_url"]))
        self.assertIn("cisco.wd5.myworkdayjobs.com", merged["canonical_url"])
        self.assertIn("https://in.linkedin.com/jobs/view/4446805994", merged["source_urls"])
        self.assertIn("https://cisco.wd5.myworkdayjobs.com/Cisco_Careers/job/Bangalore-India/Software-Engineer---Java-Go---Distributed-Systems---Microservices---Kafka---Cloud---4-8-Years_2023887-1", merged["source_urls"])
        self.assertIn("linkedin-search", merged["discovered_from"])
        self.assertIn("freehire-search", merged["discovered_from"])
        self.assertEqual(merged["first_seen"], "2026-08-30")
        self.assertEqual(merged["last_seen"], "2026-09-01")

if __name__ == "__main__":
    unittest.main()
