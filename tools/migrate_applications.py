import sys
from tools.profile_loader import get_identity_fact
#!/usr/bin/env python3
"""
Migrates application packages into canonical company/role-based directory structure:
documents/applications/<Company>/<Role>/
"""

import os
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent

APPLICATIONS = [
    {
        "company": "Cisco",
        "company_slug": "Cisco",
        "role": "Software Engineer – Java/Go (Microservices, Kafka, Cloud)",
        "role_slug": "Software_Engineer_Java_Go",
        "job_url": "https://cisco.wd5.myworkdayjobs.com/Cisco_Careers/job/Bangalore-India/Software-Engineer---Java-Go---Distributed-Systems---Microservices---Kafka---Cloud---4-8-Years_2023887-1?utm_source=freehire.me",
        "source": "freehire.me / Workday",
        "location": "Bengaluru, India",
        "fit_score": 85,
        "rank_band": "Strong Fit",
        "resume_narrative": "Backend / Distributed Systems",
        "cv_src": WORKSPACE / "cv/main_Cisco_Software_Engineer_Java_Go.tex",
        "cl_src": WORKSPACE / "cover_letters/cover_Cisco_Software_Engineer_Java_Go.tex",
        "jd_src": WORKSPACE / "job_descriptions/Cisco_Software_Engineer_Java_Go.md",
        "tailoring_summary": "Prioritized Core Java (17/21) concurrency, Apache Kafka offset management, DLQ handling, and 2M+ record AWS S3 cloud data migration. Secondary Go requirement treated as transferable from JVM multithreading.",
        "gaps_risk": "Secondary mention of Go in requisition title. No material gap identified on core distributed systems and JVM backend requirements."
    },
    {
        "company": "Wells Fargo",
        "company_slug": "Wells_Fargo",
        "role": "Senior Software Engineer – Java, Spring Boot, Microservices",
        "role_slug": "Senior_Software_Engineer_Java",
        "job_url": "https://wd1.myworkdaysite.com/recruiting/wf/WellsFargoJobs/job/Bengaluru-India/Senior-Software-Engineer---Java---Spring-boot--Microservices_R-537630?utm_source=freehire.me",
        "source": "freehire.me / Workday",
        "location": "Bengaluru, India",
        "fit_score": 81,
        "rank_band": "Strong Fit",
        "resume_narrative": "Backend / Distributed Systems (FinTech & Banking Focus)",
        "cv_src": WORKSPACE / "cv/main_Wells_Fargo_Senior_Software_Engineer_Java.tex",
        "cl_src": WORKSPACE / "cover_letters/cover_Wells_Fargo_Senior_Software_Engineer_Java.tex",
        "jd_src": WORKSPACE / "job_descriptions/Wells_Fargo_Senior_Software_Engineer_Java_Microservices.md",
        "tailoring_summary": "Framed around enterprise banking microservices, DMN rules engine ownership at JPMC, Oracle DB synchronization, and strict test-driven development (TDD).",
        "gaps_risk": "Standard US banking screening process. No material gap identified on technical stack or enterprise financial governance."
    },
    {
        "company": "Barclays",
        "company_slug": "Barclays",
        "role": "Software Engineer – Confluent Kafka on AWS",
        "role_slug": "Software_Engineer_Confluent_Kafka_AWS",
        "job_url": "https://barclays.wd3.myworkdayjobs.com/External_Career_Site_Barclays/job/Bengaluru-Maruthi-Onyx---TESCO-TSA/Software-Engineer-Confluent-Kafka-on-AWS_JR-0000103140?utm_source=freehire.me",
        "source": "freehire.me / Workday",
        "location": "Bengaluru, India",
        "fit_score": 83,
        "rank_band": "Strong Fit",
        "resume_narrative": "Backend / Distributed Systems (Event-Driven & Cloud Focus)",
        "cv_src": WORKSPACE / "cv/main_Barclays_Software_Engineer_Kafka_AWS.tex",
        "cl_src": WORKSPACE / "cover_letters/cover_Barclays_Software_Engineer_Kafka_AWS.tex",
        "jd_src": WORKSPACE / "job_descriptions/Barclays_Software_Engineer_Confluent_Kafka_AWS.md",
        "tailoring_summary": "Emphasized Apache/Confluent Kafka consumer/producer internals, partition rebalancing, offset commits, dead-letter queues, and high-volume data streaming directly to AWS S3.",
        "gaps_risk": "No material gap identified across technical, cloud, domain, and experience dimensions."
    },
    {
        "company": "Zimperium",
        "company_slug": "Zimperium",
        "role": "Java Engineer (Back-End & Microservices)",
        "role_slug": "Java_Engineer_Backend",
        "job_url": "https://jobs.lever.co/zimperium/6b50bb8b-2a86-4e93-8c17-39b66f3e0789?utm_source=freehire.me",
        "source": "freehire.me / Lever",
        "location": "Bangalore, India",
        "fit_score": 82,
        "rank_band": "Strong Fit",
        "resume_narrative": "Backend / Distributed Systems (High-Performance Cloud Security / SaaS)",
        "cv_src": WORKSPACE / "cv/main_Zimperium_Java_Engineer_Backend.tex",
        "cl_src": WORKSPACE / "cover_letters/cover_Zimperium_Java_Engineer_Backend.tex",
        "jd_src": WORKSPACE / "job_descriptions/Zimperium_Java_Engineer_Backend_Microservices.md",
        "tailoring_summary": "Focused on high-throughput microservices architecture, REST API design, shared exception handling libraries (18% boilerplate reduction), and automated testing with JUnit/Mockito.",
        "gaps_risk": "Mobile endpoint security domain learning curve, readily bridged by general distributed telemetry foundations."
    },
    {
        "company": "Worldpay",
        "company_slug": "Worldpay",
        "role": "Java Fullstack Developer (Spring Boot, REST API, Angular)",
        "role_slug": "Java_Fullstack_Developer",
        "job_url": "https://worldpay.wd5.myworkdayjobs.com/Worldpay_External_Careers_Site/job/BENGALURU--INDIA/Java-Fullstack-Developer--Spring-boot--Rest-API--Angular--4-Yrs-Bangalore-Pune-Indore_JR0610837?utm_source=freehire.me",
        "source": "freehire.me / Workday",
        "location": "Bengaluru / Pune, India",
        "fit_score": 85,
        "rank_band": "Strong Fit",
        "resume_narrative": "Full Stack / Platform (Java Backend Core + Web UI)",
        "cv_src": WORKSPACE / "cv/main_Worldpay_Java_Fullstack_Developer.tex",
        "cl_src": WORKSPACE / "cover_letters/cover_Worldpay_Java_Fullstack_Developer.tex",
        "jd_src": WORKSPACE / "job_descriptions/Worldpay_Java_Fullstack_Developer_Spring_Angular.md",
        "tailoring_summary": "Balanced Core Java (17/21) and Spring Boot backend microservices with frontend component design (React.js, TypeScript, Redux workshop leadership).",
        "gaps_risk": "Posting lists Angular; candidate's production React/TypeScript background provides clean transferable full-stack frontend capability."
    }
]

def migrate():
    print("Starting canonical application storage migration...")
    
    apps_base = WORKSPACE / "documents/applications"
    apps_base.mkdir(parents=True, exist_ok=True)
    
    results = []

    for app in APPLICATIONS:
        target_dir = apps_base / app["company_slug"] / app["role_slug"]
        target_dir.mkdir(parents=True, exist_ok=True)
        print(f"\nProcessing {app['company']} -> {target_dir}")

        # 1. Job Description
        shutil.copyfile(app["jd_src"], target_dir / "job_description.md")

        # 2. Metadata JSON
        metadata = {
            "company": app["company"],
            "role": app["role"],
            "job_url": app["job_url"],
            "source": app["source"],
            "location": app["location"],
            "fit_score": app["fit_score"],
            "rank_band": app["rank_band"],
            "resume_narrative": app["resume_narrative"],
            "status": "drafted",
            "applied_date": None,
            "notice_status": "currently serving notice",
            "last_working_day": "2026-10-06",
            "earliest_joining_date": "after 2026-10-06",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        with open(target_dir / "application_metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

        # 3. Tailoring Notes
        tailoring_md = f"""# Application Tailoring Notes: {app['company']} — {app['role']}

- **Fit Score:** {app['fit_score']} ({app['rank_band']})
- **Selected Narrative:** {app['resume_narrative']}
- **Status:** Drafted (Review Completed)
- **Notice Period / Availability:** Currently serving notice | LWD: 6 October 2026 | Joining: after 6 October 2026

## Tailoring Rationale
{app['tailoring_summary']}

## Gaps & Risk Analysis
{app['gaps_risk']}
"""
        with open(target_dir / "tailoring_notes.md", "w") as f:
            f.write(tailoring_md)

        # 4. CV LaTeX & Compilation
        shutil.copyfile(app["cv_src"], target_dir / "cv.tex")
        lualatex_cmd = ["/usr/local/texlive/2026/bin/universal-darwin/lualatex", "-interaction=nonstopmode", "-halt-on-error", "cv.tex"]
        res_cv = subprocess.run(lualatex_cmd, cwd=target_dir, capture_output=True, text=True)
        cv_compiled = (res_cv.returncode == 0 and (target_dir / "cv.pdf").exists())

        # 5. Cover Letter LaTeX, Symlinks & Compilation
        cover_cls_symlink = target_dir / "cover.cls"
        openfonts_symlink = target_dir / "OpenFonts"
        if cover_cls_symlink.is_symlink() or cover_cls_symlink.exists(): cover_cls_symlink.unlink()
        if openfonts_symlink.is_symlink() or openfonts_symlink.exists(): openfonts_symlink.unlink()
        
        cover_cls_symlink.symlink_to("../../../../cover_letters/cover.cls")
        openfonts_symlink.symlink_to("../../../../cover_letters/OpenFonts")

        shutil.copyfile(app["cl_src"], target_dir / "cover_letter.tex")
        xelatex_cmd = ["/usr/local/texlive/2026/bin/universal-darwin/xelatex", "-interaction=nonstopmode", "-halt-on-error", "cover_letter.tex"]
        res_cl = subprocess.run(xelatex_cmd, cwd=target_dir, capture_output=True, text=True)
        cl_compiled = (res_cl.returncode == 0 and (target_dir / "cover_letter.pdf").exists())

        # 6. PDF Verification
        cv_verify = subprocess.run([sys.executable, str(WORKSPACE / "tools/verify_pdf.py"), str(target_dir / "cv.pdf"), "--pages", "1", "--contains", get_identity_fact("full_name", "Candidate")], capture_output=True, text=True)
        cl_verify = subprocess.run([sys.executable, str(WORKSPACE / "tools/verify_pdf.py"), str(target_dir / "cover_letter.pdf"), "--pages", "1", "--contains", get_identity_fact("full_name", "Candidate"), "--contains", app["company"]], capture_output=True, text=True)

        results.append({
            "company": app["company"],
            "role": app["role"],
            "dir": str(target_dir.relative_to(WORKSPACE)),
            "cv_compiled": cv_compiled,
            "cl_compiled": cl_compiled,
            "cv_verify_pass": cv_verify.returncode == 0,
            "cl_verify_pass": cl_verify.returncode == 0,
        })

    # 7. Clean up old application-specific files
    for app in APPLICATIONS:
        for p in [app["cv_src"], app["cl_src"], app["jd_src"]]:
            if p.exists():
                p.unlink()
        # Remove aux/log/out/pdf from cv/ and cover_letters/
        stem_cv = app["cv_src"].stem
        for ext in [".pdf", ".log", ".aux", ".out"]:
            old_cv_file = WORKSPACE / f"cv/{stem_cv}{ext}"
            if old_cv_file.exists(): old_cv_file.unlink()
        stem_cl = app["cl_src"].stem
        for ext in [".pdf", ".log", ".aux", ".out"]:
            old_cl_file = WORKSPACE / f"cover_letters/{stem_cl}{ext}"
            if old_cl_file.exists(): old_cl_file.unlink()

    # 8. Update job_search_tracker.csv
    tracker_path = WORKSPACE / "job_search_tracker.csv"
    with open(tracker_path, "w") as f:
        f.write("date,company,sector,role,role_type,channel,status,contact_person,fit_rating,notes,cv_file,cover_letter_file,source,deadline\n")
        f.write("2026-08-30,Gloify,Technology,Java Software Engineer,Engineering,portal,drafted,,82,Tailored for core Java and Spring microservices,cv/main_Gloify_Java_Software_Engineer.tex,cover_letters/cover_Gloify_Java_Software_Engineer.tex,https://jobs.smartrecruiters.com/Gloify/743999741970976-java,\n")
        f.write("2026-08-30,Nexthink,Technology,Senior Backend Software Engineer (Java),Engineering,portal,drafted,,86,Tailored for Java 17 Micronaut Kafka Streams and AI tooling,cv/main_Nexthink_Senior_Backend_Software_Engineer.tex,cover_letters/cover_Nexthink_Senior_Backend_Software_Engineer.tex,https://in.linkedin.com/jobs/view/senior-backend-software-engineer-java-at-nexthink-4436183162,\n")
        for app in APPLICATIONS:
            rel_dir = f"documents/applications/{app['company_slug']}/{app['role_slug']}"
            f.write(f"2026-08-30,{app['company']},Technology,{app['role']},Engineering,portal,drafted,,{app['fit_score']},{app['tailoring_summary'][:80]},{rel_dir}/cv.tex,{rel_dir}/cover_letter.tex,{app['job_url']},\n")

    print("\n--- Migration Results ---")
    for r in results:
        print(f"[{r['company']}] {r['role']}")
        print(f"  Directory: {r['dir']}")
        print(f"  CV: Compiled={r['cv_compiled']}, Verify={r['cv_verify_pass']}")
        print(f"  Cover Letter: Compiled={r['cl_compiled']}, Verify={r['cl_verify_pass']}")

if __name__ == "__main__":
    migrate()
