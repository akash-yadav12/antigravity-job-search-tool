#!/usr/bin/env python3
"""
Benchmark & Regression Test Suite for Calibrated Evaluator.
"""

import json
import sys
from evaluator import evaluate_hard_gates, evaluate_job_calibrated

def run_tests():
    print("=== Running Calibrated Evaluator Benchmark & Regression Tests ===")
    
    # -------------------------------------------------------------
    # 1. BENCHMARK TESTS
    # -------------------------------------------------------------
    benchmarks = [
        {
            "name": "Nexthink Senior Backend (Java)",
            "job": {
                "title": "Senior Backend Software Engineer (Java)",
                "company": "Nexthink",
                "location": "Bengaluru, India",
                "skills": ["java", "spring boot", "micronaut", "kafka", "distributed systems", "aws", "docker", "ai"],
                "description": "5+ years of experience in backend development using Java 17/21, Micronaut, Spring Boot, and Apache Kafka. Building real-time telemetry pipelines for 25M+ endpoints."
            },
            "expected_range": (84, 88),
            "expected_band": "Strong",
            "target": 86
        },
        {
            "name": "Citi Java Fullstack Developer",
            "job": {
                "title": "Java Fullstack developer",
                "company": "Citi",
                "location": "Pune, Maharashtra, India",
                "skills": ["java", "spring boot", "microservices", "oracle", "react", "rest", "junit"],
                "description": "3-5 years of experience in Core Java, Spring Boot, Microservices, Oracle DB, and React frontends in an enterprise banking environment."
            },
            "expected_range": (82, 87),
            "expected_band": "Strong",
            "target": 84
        },
        {
            "name": "Bluehost Java Backend Developer",
            "job": {
                "title": "Java Backend Software Engineer",
                "company": "Bluehost",
                "location": "Mumbai Metropolitan Region",
                "skills": ["java 17", "spring boot", "kafka", "mysql", "docker", "ai"],
                "description": "5+ years of experience with Java 17/21, Spring Boot, Spring Data JPA, Kafka event streaming, and MySQL in Mumbai."
            },
            "expected_range": (80, 84),
            "expected_band": "Strong",
            "target": 82
        },
        {
            "name": "Roku Senior Backend & Data Platform",
            "job": {
                "title": "Senior Software Engineer, Backend & Data Platform",
                "company": "Roku",
                "location": "Bengaluru, India",
                "skills": ["java", "kafka", "spark", "flink", "big data", "cloud"],
                "description": "7+ years of experience in high-throughput distributed streaming data platform systems. Mandatory deep expertise in Apache Spark, Apache Flink, and big data pipelines."
            },
            "expected_range": (70, 76),
            "expected_band": "Good",
            "target": 74
        },
        {
            "name": "Cisco 8-12 YOE Software Engineer",
            "job": {
                "title": "Software Engineer – (Java/Scala/Golang) (Microservices, Kafka & Big Data) 8 to 12 Years",
                "company": "Cisco",
                "location": "Bangalore, India",
                "skills": ["java", "scala", "golang", "kafka", "big data"],
                "description": "8 to 12 Years of experience. Mandatory Scala, Golang, and Apache Spark/Hadoop big data clusters."
            },
            "expected_hard_gate_pass": False,
            "target_max_score": 58
        },
        {
            "name": "Blue Yonder (JDA) Staff Python Engineer",
            "job": {
                "title": "Staff Software Engineer II - (Python,Microservices,Kafka,Nosql,Architect)",
                "company": "jda",
                "location": "Bangalore, India",
                "skills": ["python", "microservices", "kafka", "nosql", "architect"],
                "description": "Staff Architect role requiring 8+ years of experience designing enterprise supply chain platforms primarily in Python and NoSQL."
            },
            "expected_hard_gate_pass": False,
            "target_max_score": 52
        }
    ]

    print("\n--- Running Benchmark Tests ---")
    benchmark_results = []
    all_benchmarks_passed = True

    for b in benchmarks:
        job = b["job"]
        gate_passed, gate_reason = evaluate_hard_gates(job["title"], job["description"], job["location"])
        eval_res = evaluate_job_calibrated(job)
        score = eval_res["rank_score"]

        if "expected_hard_gate_pass" in b and not b["expected_hard_gate_pass"]:
            passed = (not gate_passed) or (score <= b["target_max_score"])
            status = "PASS" if passed else "FAIL"
            if not passed: all_benchmarks_passed = False
            benchmark_results.append({
                "benchmark": b["name"],
                "score": score if gate_passed else "REJECTED",
                "gate_passed": gate_passed,
                "gate_reason": gate_reason,
                "target": f"<= {b['target_max_score']} or Hard Reject",
                "status": status
            })
        else:
            min_s, max_s = b["expected_range"]
            passed = min_s <= score <= max_s and gate_passed
            status = "PASS" if passed else "FAIL"
            if not passed: all_benchmarks_passed = False
            benchmark_results.append({
                "benchmark": b["name"],
                "score": score,
                "gate_passed": gate_passed,
                "gate_reason": gate_reason,
                "target": f"{b['target']} (Range: {min_s}-{max_s})",
                "status": status,
                "dimensions": eval_res["dimension_scores"]
            })

    for res in benchmark_results:
        print(f"[{res['status']}] {res['benchmark']} -> Score: {res['score']} | Target: {res['target']} (Gate: {res['gate_reason']})")

    # -------------------------------------------------------------
    # 2. REGRESSION TESTS (9 Specific Scenarios)
    # -------------------------------------------------------------
    print("\n--- Running Regression Tests (9 Scenarios) ---")
    regression_tests = [
        {
            "id": 1,
            "name": "8–12 YOE Cisco role",
            "job": {
                "title": "Software Engineer (Java/Kafka) 8 to 12 Years",
                "company": "Cisco",
                "location": "Bengaluru",
                "description": "Requires 8-12 years of production experience in high scale networks."
            },
            "check": lambda g, s: (not g) or s <= 58,
            "description": "Must be hard-rejected by 8+ YOE gate or scored <= 58"
        },
        {
            "id": 2,
            "name": "7+ YOE Roku role",
            "job": {
                "title": "Senior Data Platform Engineer",
                "company": "Roku",
                "location": "Bengaluru",
                "description": "Requires 7+ years of experience in data platform streaming with Apache Spark, Flink, Kafka, and Java."
            },
            "check": lambda g, s: g and (70 <= s <= 76),
            "description": "Must pass gate but score 70-76 (3+ yr shortfall & missing Spark/Flink)"
        },
        {
            "id": 3,
            "name": "3–5 YOE Citi role",
            "job": {
                "title": "Java Developer",
                "company": "Citi",
                "location": "Pune",
                "skills": ["java", "spring boot", "microservices", "oracle", "rest"],
                "description": "Requires 3-5 years Java, Spring Boot, Microservices, Oracle DB in banking."
            },
            "check": lambda g, s: g and (82 <= s <= 88),
            "description": "Must pass gate and score 82-88 (Strong Fit / High Priority)"
        },
        {
            "id": 4,
            "name": "4+ YOE Kafka role",
            "job": {
                "title": "Backend Streaming Engineer",
                "company": "Wissen Technology",
                "location": "Mumbai",
                "skills": ["java", "kafka", "spring boot", "rest", "microservices"],
                "description": "Requires 4+ years Java, Apache Kafka, Offset Management, DLQ, Microservices."
            },
            "check": lambda g, s: g and (82 <= s <= 90),
            "description": "Must pass gate and score 82-90 in Mumbai"
        },
        {
            "id": 5,
            "name": "Python-primary Staff role",
            "job": {
                "title": "Staff Python Backend Engineer",
                "company": "Tech Corp",
                "location": "Bengaluru",
                "description": "Staff level role in pure Python/Django microservices architecture with 8+ years experience."
            },
            "check": lambda g, s: (not g) or s <= 55,
            "description": "Must be rejected or scored <= 55 (Non-Java primary & Staff title)"
        },
        {
            "id": 6,
            "name": "Specialized Crypto/HSM role",
            "job": {
                "title": "Senior Payment Security Engineer",
                "company": "Fintech Pay",
                "location": "Bengaluru",
                "skills": ["java", "spring", "hsm", "pin block"],
                "description": "Deep expertise in Hardware Security Module (HSM), cryptographic PIN blocks, and key management with Java."
            },
            "check": lambda g, s: s <= 70,
            "description": "Must be capped to <= 70 due to Domain Mismatch (HSM / Cryptography)"
        },
        {
            "id": 7,
            "name": "Role with Undisclosed Compensation",
            "job": {
                "title": "Java Software Engineer II",
                "company": "Maersk",
                "location": "Bengaluru",
                "skills": ["java", "spring boot", "microservices", "docker", "rest"],
                "description": "Standard Java microservices role with 3-5 years experience. Salary undisclosed."
            },
            "check": lambda g, s: g and s >= 82,
            "description": "Must NOT be penalized or rejected for undisclosed salary"
        },
        {
            "id": 8,
            "name": "Role with Preferred but Missing Technologies",
            "job": {
                "title": "Java Backend Engineer",
                "company": "Product Co",
                "location": "Mumbai",
                "skills": ["java", "spring boot", "mysql", "rest"],
                "description": "3-5 years Java 17, Spring Boot, MySQL, REST APIs. Nice to have / preferred: Kotlin, GraphQL."
            },
            "check": lambda g, s: g and s >= 82,
            "description": "Missing preferred tech (Kotlin/GraphQL) must not reduce score below 82"
        },
        {
            "id": 9,
            "name": "Role with Transferable Database/Cloud Technology",
            "job": {
                "title": "Backend Engineer",
                "company": "SaaS Co",
                "location": "Bengaluru",
                "skills": ["java", "spring boot", "postgresql", "redis", "gcp"],
                "description": "3-5 years Java, Spring Boot, PostgreSQL, Redis, GCP cloud services."
            },
            "check": lambda g, s: g and (80 <= s <= 88),
            "description": "Transferable DB (PostgreSQL from Oracle) and cloud must receive strong partial credit (80-88 Strong Fit)"
        }
    ]

    regression_results = []
    all_regression_passed = True

    for t in regression_tests:
        g_pass, g_reason = evaluate_hard_gates(t["job"]["title"], t["job"]["description"], t["job"]["location"])
        eval_res = evaluate_job_calibrated(t["job"])
        score = eval_res["rank_score"]
        passed = t["check"](g_pass, score)
        if not passed: all_regression_passed = False
        
        regression_results.append({
            "id": t["id"],
            "name": t["name"],
            "score": score if g_pass else "REJECTED",
            "gate_passed": g_pass,
            "gate_reason": g_reason,
            "passed": passed,
            "description": t["description"]
        })
        print(f"Test {t['id']}: [{('PASS' if passed else 'FAIL')}] {t['name']} -> Score: {score if g_pass else 'REJECTED'} (Gate: {g_reason}) | {t['description']}")

    print(f"\nBenchmark Suite Status: {'ALL PASSED' if all_benchmarks_passed else 'SOME FAILED'}")
    print(f"Regression Suite Status: {'ALL PASSED' if all_regression_passed else 'SOME FAILED'}")

    return all_benchmarks_passed and all_regression_passed

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
