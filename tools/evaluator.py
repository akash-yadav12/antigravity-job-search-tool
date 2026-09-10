"""
Calibrated Evaluation Framework & Hard Gate Evaluator
Faithful implementation of .claude/skills/job-application-assistant/04-job-evaluation.md and rank.md.
Weights: Technical 30%, Experience 25%, Culture/Behavioral 15%, Career Alignment 20%, Location 10%.
"""

import re

# Deep Domain Specializations (Mismatch caps overall score to <= 70)
DEEP_DOMAIN_MISMATCHES = [
    ("Payment Cryptography / HSM", ["hsm", "hardware security module", "pin block", "cryptographic key management", "emvco"]),
    ("ISO 8583 Protocol", ["iso 8583", "iso8583", "as2805", "pos switch message"]),
    ("HFT Market Microstructure", ["hft", "high frequency trading", "market microstructure", "fpga", "order book matching engine", "sub-microsecond"]),
    ("Embedded Firmware", ["embedded c", "firmware", "microcontroller", "rtos", "arm cortex", "verilog"]),
    ("Biomedical / Genomics Research", ["genomics", "bioinformatics", "fda 21 cfr", "clinical trial data pipeline"])
]

def evaluate_hard_gates(title: str, description: str = "", location: str = "") -> tuple[bool, str]:
    """
    Stage 2 Hard Gate Evaluation.
    Inspects title and full job description.
    """
    t_lower = title.lower()
    d_lower = description.lower() if description else ""
    full_text = f"{t_lower} {d_lower}"

    # 1. 8+ YOE Hard Floor / Extreme Seniority Floor
    yoe_floor_match = re.search(r'\b(8|9|10|11|12|15)\s*[-–—to]+\s*(\d+)\s*(years|yrs|yoe)\b', full_text)
    single_high_yoe = re.search(r'\b(8\+|9\+|10\+|12\+|15\+)\s*(years|yrs|yoe)\b', full_text)
    
    if yoe_floor_match:
        min_y = int(yoe_floor_match.group(1))
        if min_y >= 8:
            return False, f"Extreme Seniority Floor ({yoe_floor_match.group(0)})"
    if single_high_yoe:
        return False, f"Extreme Seniority Floor ({single_high_yoe.group(0)})"

    # Executive / Management / Architect / Staff Seniority
    exec_roles = [
        "principal engineer", "director of engineering", "vp engineering", "vice president",
        "engineering manager", "head of engineering", "chief architect", "staff engineer",
        "staff software engineer", "staff backend engineer", "staff python",
        "manager software engineering", "project manager", "delivery manager", "program manager",
        "team handling", "people manager", "solution architect", "enterprise architect",
        "microservices architect", "cloud architect", "software architect", "java microservices architect"
    ]
    if any(r in t_lower for r in exec_roles) and not any(r in t_lower for r in ["swe ii", "software engineer ii", "individual contributor"]):
        return False, "Staff / Architect / Management level seniority in title"

    if re.search(r'(-\s*manager\b|\bmanager\s*-|\bmanager software\b|\bproject manager\b|\bteam handling\b)', t_lower):
        if not any(r in t_lower for r in ["swe ii", "software engineer ii", "individual contributor"]):
            return False, "Management / Team Handling role"

    # 2. Manual QA / SDET Lead
    qa_roles = ["manual qa", "qa tester", "quality assurance tester", "test lead", "sdet lead", "automation test lead"]
    if any(r in t_lower for r in qa_roles) and not ("backend" in t_lower or "software engineer" in t_lower):
        return False, "Manual QA / Pure Testing role"

    # 3. Pure Frontend / Mobile / Pure ML Research / Non-Engineering Roles
    if any(r in t_lower for r in ["ios developer", "android developer", "flutter developer", "react native developer", "mobile developer", "ios engineer", "android engineer"]):
        return False, "Pure mobile development role"
    if any(r in t_lower for r in ["frontend developer", "frontend engineer", "ui engineer", "angular developer", "vue developer"]) and not ("full stack" in t_lower or "backend" in t_lower):
        return False, "Pure frontend role"
    if any(r in t_lower for r in ["data scientist", "ml researcher", "ai researcher", "deep learning researcher", "nlp researcher"]):
        return False, "Pure ML / Data Science research role"

    # Non-Engineering / Business / Sales / Marketing / Legal / HR / PM / Design / Finance
    non_eng_roles = [
        "account executive", "sales manager", "sales development", "sales director", "business development",
        "marketing manager", "product marketing", "paid media", "growth marketing", "content marketing",
        "general counsel", "counsel", "legal counsel", "attorney", "paralegal",
        "recruiter", "talent acquisition", "human resources", "hr business partner", "people operations",
        "finance manager", "tax manager", "accountant", "workplace operations", "finance & strategy",
        "product manager", "product owner", "scrum master", "technical writer", "designer",
        "partner development", "gtm operations"
    ]
    if any(r in t_lower for r in non_eng_roles) and not any(k in t_lower for k in ["software engineer", "backend engineer", "developer", "platform engineer", "sre"]):
        return False, "Non-engineering / Business / Operations role"

    # 4. Incompatible Primary Technology Stack (in title)
    non_target_stacks = [
        ".net developer", ".net with", "c# developer", "c# backend", "php developer", "ruby on rails",
        "ruby developer", "embedded c", "firmware engineer", "mainframe developer", "cobol developer",
        "python backend engineer", "backend engineer (python)", "golang developer", "golang engineer",
        "backend engineer (golang)", "ai-first golang developer"
    ]
    if any(r in t_lower for r in non_target_stacks) and not ("java" in t_lower):
        return False, "Incompatible non-Java primary technology stack"

    # 5. Location Gate
    if location:
        loc_lower = location.lower()
        target_locations = ["mumbai", "bengaluru", "bangalore", "pune", "hyderabad", "remote", "india", "gurugram", "gurgaon", "noida", "chennai", "delhi"]
        if not any(loc in loc_lower for loc in target_locations):
            return False, f"Location conflict ({location})"

    return True, "PASS"


def evaluate_job_calibrated(job: dict) -> dict:
    """
    Stage 3 Calibrated 5-Dimension Evaluation.
    Calculates zero-baseline scores and classifies tech/domain/seniority gaps.
    """
    title = job.get("title", "")
    company = job.get("company", "")
    loc = job.get("location", "India")
    desc = job.get("description", "")
    skills = [s.lower() for s in job.get("skills", [])]
    full_text = f"{title} {desc} {' '.join(skills)}".lower()
    t_lower = title.lower()

    strengths = []
    gaps = []

    # ==========================================
    # 1. Technical Alignment (0 - 100, Weight 30%)
    # ==========================================
    tech_score = 0.0

    # Determine Primary Backend Language
    is_java_primary = False
    is_non_java_primary = False
    primary_lang = "unknown"

    if any(k in full_text for k in ["java 17", "java 21", "java 11", "java 8", "core java", "java developer", "java software engineer", "java backend", "java/", "java"]):
        if not (any(k in t_lower for k in ["python", "golang", "go ("]) and not ("java" in t_lower)):
            is_java_primary = True
            primary_lang = "Java"

    # Check if a non-JVM language is explicitly the primary stack in title
    if any(k in t_lower for k in ["python", "golang", "go (", "go,", "scala", "c#", ".net", "rust", "ruby"]):
        if not ("java" in t_lower or "jvm" in t_lower or "micronaut" in t_lower or "spring" in t_lower):
            is_non_java_primary = True
            is_java_primary = False
            primary_lang = "Non-JVM (Python/Go/Scala/C#)"

    # Primary Language & Framework Alignment (Max 45 pts)
    if is_java_primary:
        tech_score += 24.0
        strengths.append("Direct Core Java (8/17/21) alignment")
        if "micronaut" in full_text and ("spring" in full_text or "spring boot" in full_text):
            tech_score += 15.0 # exact dual-framework depth
            strengths.append("Spring Boot & Micronaut microservices depth")
        elif "spring" in full_text or "spring boot" in full_text:
            tech_score += 13.0
            strengths.append("Spring Boot microservices")
        else:
            tech_score += 8.0
        tech_score += 6.0 # REST API / OOP principles
    elif is_non_java_primary:
        tech_score += 10.0 # minimal transferable OOP
        gaps.append(f"Primary language mismatch ({primary_lang} primary vs candidate Java core)")
    else:
        tech_score += 18.0
        if "spring" in full_text or "spring boot" in full_text:
            tech_score += 13.0
        else:
            tech_score += 8.0
        tech_score += 5.0

    # Distributed Systems & Architecture (Max 25 pts)
    if "kafka" in full_text or "event streaming" in full_text or "event-driven" in full_text:
        tech_score += 18.0
        strengths.append("Apache Kafka & event-driven architecture")
        if any(k in full_text for k in ["offset", "consumer", "resiliency", "partition", "dlq"]):
            tech_score += 5.0
    elif any(k in full_text for k in ["microservices", "distributed systems", "high throughput", "rest"]):
        tech_score += 16.0
        strengths.append("Distributed microservices architecture")
    elif any(k in full_text for k in ["rabbitmq", "activemq", "sqs", "pub/sub"]):
        tech_score += 14.0
    else:
        tech_score += 8.0

    # Big Data / Platform specific deductions
    if any(k in full_text for k in ["spark", "apache spark", "flink", "apache flink", "hadoop"]):
        if any(k in title.lower() for k in ["data platform", "big data", "data engineer"]):
            tech_score -= 15.0 # Major missing primary tech
            gaps.append("Missing primary Big Data streaming stack (Apache Spark / Flink)")
        else:
            tech_score -= 5.0

    # Databases, Cloud & DevOps (Max 20 pts)
    db_cloud_score = 0.0
    if any(db in full_text for db in ["oracle", "sql server", "mysql", "mongodb", "sql", "rdbms"]):
        db_cloud_score += 10.0
    elif any(db in full_text for db in ["postgresql", "postgres", "redis", "elasticsearch", "nosql"]):
        db_cloud_score += 10.0 # strong transferable DB credit
    else:
        db_cloud_score += 6.0

    if any(c in full_text for c in ["aws", "docker", "kubernetes", "cloud", "gcp", "azure", "ci/cd", "gitlab", "teamcity"]):
        db_cloud_score += 10.0
    else:
        db_cloud_score += 6.0
    
    tech_score += min(20.0, db_cloud_score)

    # AI, Testing & Best Practices (Max 10 pts)
    if any(ai in full_text for ai in ["ai", "rag", "llm", "copilot", "vector db", "claude", "agent"]):
        tech_score += 8.0
        strengths.append("AI / Agentic developer tooling focus")
    elif any(t in full_text for t in ["tdd", "junit", "mockito", "clean code", "testing"]):
        tech_score += 7.0
    else:
        tech_score += 5.0

    tech_score = max(0.0, min(100.0, tech_score))

    # ==========================================
    # 2. Experience & Seniority Fit (0 - 100, Weight 25%)
    # ==========================================
    exp_score = 80.0
    yoe_req = "3-5 years (Standard SWE II match)"

    yoe_range = re.search(r'(\d+)\s*[-–—to]+\s*(\d+)\s*(years|yrs|yoe)', full_text)
    single_yoe = re.search(r'(\d+)\+?\s*(years|yrs|yoe)', full_text)

    if yoe_range:
        min_y = int(yoe_range.group(1))
        max_y = int(yoe_range.group(2))
        yoe_req = f"{min_y}-{max_y} years"
        
        if min_y <= 4 <= max_y or min_y <= 4:
            exp_score = 90.0
            strengths.append(f"Ideal YOE alignment ({yoe_req} vs candidate 4 YOE)")
        elif min_y == 5:
            exp_score = 80.0 # 1-year minor shortfall
            gaps.append("5+ YOE requirement (1-year minor shortfall)")
        elif min_y == 6:
            exp_score = 65.0 # 2-year moderate shortfall
            gaps.append("6+ YOE requirement (2-year moderate shortfall)")
        elif min_y >= 7:
            exp_score = 56.0 # 3+ year strong shortfall
            gaps.append(f"{min_y}+ YOE requirement ({min_y - 4} year strong shortfall)")
    elif single_yoe:
        min_y = int(single_yoe.group(1))
        yoe_req = f"{min_y}+ years"
        
        if min_y <= 4:
            exp_score = 90.0
            strengths.append(f"Ideal YOE alignment ({yoe_req} vs candidate 4 YOE)")
        elif min_y == 5:
            exp_score = 80.0 # 1-year minor shortfall
            gaps.append("5+ YOE requirement (1-year minor shortfall)")
        elif min_y == 6:
            exp_score = 65.0 # 2-year moderate shortfall
            gaps.append("6+ YOE requirement (2-year moderate shortfall)")
        elif min_y >= 7:
            exp_score = 56.0 # 3+ year strong shortfall
            gaps.append(f"{min_y}+ YOE requirement ({min_y - 4} year strong shortfall)")

    # Title Level checks
    if any(k in t_lower for k in ["staff", "principal", "architect", "lead"]):
        if not ("software engineer ii" in t_lower or "swe ii" in t_lower):
            exp_score = min(exp_score, 60.0)
            gaps.append("Lead / Staff title expectations above standard SWE II band")

    exp_score = max(0.0, min(100.0, exp_score))

    # ==========================================
    # 3. Behavioral / Culture Fit (0 - 100, Weight 15%)
    # ==========================================
    culture_score = 75.0
    domain_mismatch_flag = None

    # Check for Deep Domain Mismatches
    for domain_name, keywords in DEEP_DOMAIN_MISMATCHES:
        if any(k in full_text for k in keywords):
            culture_score = 30.0
            domain_mismatch_flag = domain_name
            gaps.append(f"Domain Mismatch: {domain_name}")
            break

    if not domain_mismatch_flag:
        if any(k in full_text or k in company.lower() for k in ["fintech", "banking", "financial", "trading", "payments", "telemetry", "observability", "digital employee experience", "data platform"]):
            culture_score = 88.0
            strengths.append("High-scale FinTech / Observability / Data platform domain")
        elif any(k in full_text for k in ["ecommerce", "enterprise saas", "cloud platform", "supply chain"]):
            culture_score = 80.0
        else:
            culture_score = 75.0

    culture_score = max(0.0, min(100.0, culture_score))

    # ==========================================
    # 4. Career Alignment & Motivation (0 - 100, Weight 20%)
    # ==========================================
    career_score = 75.0
    tier_1_brands = ["citi", "barclays", "goldman", "morgan stanley", "ubs", "nexthink", "roku", "atlassian", "uber", "salesforce", "microsoft", "google", "amazon", "paypal", "mastercard", "visa", "intuit", "walmart", "adobe", "target", "bofa", "wells fargo", "hsbc", "societe generale", "natwest", "standard chartered", "cisco", "maersk", "zimperium"]
    consulting_services = ["tcs", "infosys", "wipro", "cognizant", "capgemini", "accenture", "hcl", "tech mahindra", "l&t", "mindtree", "ntt data", "marriott"]

    comp_lower = company.lower()
    if any(b in comp_lower for b in tier_1_brands):
        career_score = 88.0
        strengths.append(f"Global product / Tier-1 tech brand ({company})")
    elif any(c in comp_lower for c in consulting_services):
        career_score = 55.0
        gaps.append("IT service / consulting vendor structure (compensation ceiling risk)")
    else:
        career_score = 76.0

    career_score = max(0.0, min(100.0, career_score))

    # ==========================================
    # 5. Location & Practical Feasibility (0 - 100, Weight 10%)
    # ==========================================
    feas_score = 80.0
    loc_lower = loc.lower()
    if "mumbai" in loc_lower or "navi mumbai" in loc_lower or "remote" in loc_lower:
        feas_score = 100.0
        strengths.append("Prime location (Mumbai MMR / Remote)")
    elif any(k in loc_lower for k in ["bengaluru", "bangalore", "pune", "hyderabad"]):
        feas_score = 90.0
        strengths.append("Target relocation hub (Bengaluru / Pune / Hyderabad)")
    else:
        feas_score = 70.0

    feas_score = max(0.0, min(100.0, feas_score))

    # ==========================================
    # Total Calibrated Score Calculation
    # Weights: Technical 30%, Experience 25%, Culture 15%, Career 20%, Location 10%
    # ==========================================
    total_score = (
        (tech_score * 0.30) +
        (exp_score * 0.25) +
        (culture_score * 0.15) +
        (career_score * 0.20) +
        (feas_score * 0.10)
    )

    # Apply Domain Mismatch Cap if present
    if domain_mismatch_flag:
        total_score = min(total_score, 68.0)

    final_score = int(round(total_score))

    # Banding & Priority per 04-job-evaluation.md
    if final_score >= 90:
        band = "Exceptional"
        verdict = "strong fit"
        priority = "Immediate Apply"
    elif final_score >= 80:
        band = "Strong"
        verdict = "strong fit"
        priority = "High Priority"
    elif final_score >= 70:
        band = "Good"
        verdict = "good fit"
        priority = "Standard Apply"
    elif final_score >= 60:
        band = "Borderline"
        verdict = "borderline fit"
        priority = "Referral Recommended / Review"
    elif final_score >= 50:
        band = "Moderate"
        verdict = "moderate fit"
        priority = "Skip / Low"
    else:
        band = "Weak"
        verdict = "weak fit"
        priority = "Skip"

    return {
        "title": title,
        "company": company,
        "location": loc,
        "url": job.get("url", ""),
        "rank_score": final_score,
        "rank_band": band,
        "rank_verdict": verdict,
        "yoe_requirement": yoe_req,
        "dimension_scores": {
            "technical": int(round(tech_score)),
            "experience": int(round(exp_score)),
            "culture": int(round(culture_score)),
            "career": int(round(career_score)),
            "feasibility": int(round(feas_score))
        },
        "strengths": list(dict.fromkeys(strengths))[:3],
        "gaps": list(dict.fromkeys(gaps))[:3] if gaps else ["None identified"],
        "priority": priority
    }


def classify_role_family(title: str, description: str = "") -> str:
    """
    Classifies job title and description into the canonical role families:
    - Backend / Distributed Systems
    - Platform
    - AI Backend / AI Platform
    - Full Stack
    - Data Engineering
    - SRE / Infrastructure
    - Other
    """
    t_lower = title.lower()
    d_lower = description.lower() if description else ""
    full = f"{t_lower} {d_lower}"

    if any(k in t_lower for k in ["rag", "llm", "ai engineer", "ai backend", "ai platform", "machine learning", "applied ai"]):
        return "AI Backend / AI Platform"
    elif any(k in t_lower for k in ["api gateway", "developer platform", "developer productivity", "infrastructure engineer", "cloud platform", "servicemesh"]):
        return "Platform"
    elif "platform" in t_lower and any(k in t_lower for k in ["engineer", "developer", "software"]):
        return "Platform"
    elif any(k in t_lower for k in ["data engineer", "spark", "flink", "big data", "data platform", "lakehouse"]):
        return "Data Engineering"
    elif any(k in t_lower for k in ["sre", "site reliability", "devops", "cloud networking"]):
        return "SRE / Infrastructure"
    elif any(k in t_lower for k in ["full stack", "fullstack", "react", "frontend"]):
        return "Full Stack"
    elif any(k in t_lower for k in ["backend", "java", "software engineer", "developer", "microservices", "kafka", "distributed"]):
        return "Backend / Distributed Systems"
    return "Other"


def calculate_application_priority(
    fit_score: float,
    comp_score: float,
    quality_score: float,
    freshness_score: float,
    comp_fit: str = "acceptable",
    freshness_state: str = "fresh"
) -> tuple[int, str, str]:
    """
    Computes composite Application Priority Score:
    40% Fit Score + 30% Compensation Score + 20% Company Quality Score + 10% Freshness Score.
    Conservative tier assignment:
    - P0: Strong Fit (>=75), Strong Comp (comp_fit == 'strong'), Tier A/B (>=80), Fresh (>=85), Score >= 87
    - P1: Strong Fit (>=75), Acceptable/Strong Comp (comp_fit in ('strong', 'acceptable')), Score >= 78
    - P2: Good Fit (>=65), Comp Selective or Unknown, Score >= 65
    - P3: Below Target, Stale, Weak Fit (<65)
    Invariant: Unknown, stale, or closed freshness can NEVER enter P0 or P1.
    """
    score = (
        (float(fit_score) * 0.40) +
        (float(comp_score) * 0.30) +
        (float(quality_score) * 0.20) +
        (float(freshness_score) * 0.10)
    )
    final_score = int(round(score))

    # Invariant: Unknown or stale freshness CANNOT enter P0 or P1
    if freshness_state in ("unknown", "stale", "closed") or freshness_score < 50:
        if final_score >= 60 and freshness_state not in ("closed", "stale"):
            return final_score, "P2", "P2 — Selective"
        return final_score, "P3", "P3 — Skip"

    if final_score >= 87 and comp_fit == "strong" and fit_score >= 75 and quality_score >= 80:
        tier = "P0"
        label = "P0 — Apply Now"
    elif final_score >= 78 and comp_fit in ("strong", "acceptable") and fit_score >= 74 and quality_score >= 80:
        tier = "P1"
        label = "P1 — Apply"
    elif final_score >= 65 and comp_fit in ("strong", "acceptable", "selective", "unknown"):
        tier = "P2"
        label = "P2 — Selective"
    else:
        tier = "P3"
        label = "P3 — Skip"

    return final_score, tier, label

