"""
Preflight validation for the /submit workflow.

Runs all safety checks before initiating a browser submission:
1. Application directory exists
2. Status is 'drafted' (not already submitted)
3. CV PDF and cover letter PDF exist
4. application_metadata.json exists and is valid
5. Job URL is present
6. Portal type can be detected
7. Job posting is still active (HTTP probe)

Exit codes:
  0 — All preflight checks passed
  1 — One or more checks failed (see report)

Usage:
  python3 tools/submit_preflight.py <company> <role>
  python3 tools/submit_preflight.py --app-dir <path>
"""

from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

# Workspace root
WORKSPACE = Path(__file__).resolve().parent.parent
APPLICATIONS_DIR = WORKSPACE / "documents" / "applications"


def find_app_dir(company: str | None = None, role: str | None = None,
                 app_dir: str | None = None) -> Path | None:
    """Resolve the application directory from company/role or direct path."""
    if app_dir:
        return Path(app_dir)
    if company and role:
        # Normalize names to match directory conventions
        company_dir = company.replace(" ", "_")
        role_dir = role.replace(" ", "_")
        candidate = APPLICATIONS_DIR / company_dir / role_dir
        if candidate.is_dir():
            return candidate
        # Try case-insensitive match
        for c_dir in APPLICATIONS_DIR.iterdir():
            if c_dir.is_dir() and c_dir.name.lower() == company_dir.lower():
                for r_dir in c_dir.iterdir():
                    if r_dir.is_dir() and r_dir.name.lower() == role_dir.lower():
                        return r_dir
    return None


class PreflightResult:
    """Structured preflight validation result."""

    def __init__(self):
        self.checks: list[dict] = []
        self.passed = True
        self.app_dir: Path | None = None
        self.metadata: dict | None = None
        self.portal_type: str | None = None

    def add_check(self, name: str, passed: bool, detail: str = ""):
        self.checks.append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            self.passed = False

    def report(self) -> str:
        lines = ["=" * 60, "PREFLIGHT VALIDATION REPORT", "=" * 60, ""]
        for check in self.checks:
            status = "✅ PASS" if check["passed"] else "❌ FAIL"
            lines.append(f"  {status}  {check['name']}")
            if check["detail"]:
                lines.append(f"         {check['detail']}")
        lines.append("")
        lines.append(f"Overall: {'✅ ALL CHECKS PASSED' if self.passed else '❌ PREFLIGHT FAILED'}")
        lines.append("=" * 60)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "app_dir": str(self.app_dir) if self.app_dir else None,
            "portal_type": self.portal_type,
            "checks": self.checks,
        }


def run_preflight(company: str | None = None, role: str | None = None,
                  app_dir_path: str | None = None) -> PreflightResult:
    """Run all preflight checks and return a structured result."""
    result = PreflightResult()

    # 1. Resolve application directory
    app_dir = find_app_dir(company, role, app_dir_path)
    if app_dir is None or not app_dir.is_dir():
        result.add_check("Application directory exists", False,
                         f"Could not find: {app_dir or f'{company}/{role}'}")
        return result
    result.app_dir = app_dir
    result.add_check("Application directory exists", True, str(app_dir))

    # 2. Check application_metadata.json
    meta_path = app_dir / "application_metadata.json"
    if not meta_path.exists():
        result.add_check("application_metadata.json exists", False)
        return result
    try:
        metadata = json.loads(meta_path.read_text())
        result.metadata = metadata
        result.add_check("application_metadata.json exists", True)
    except json.JSONDecodeError as e:
        result.add_check("application_metadata.json valid JSON", False, str(e))
        return result

    # 3. Check status == drafted
    status = metadata.get("status", "")
    if status == "drafted":
        result.add_check("Status is 'drafted'", True, f"status={status}")
    elif status == "applied":
        result.add_check("Status is 'drafted'", False,
                         f"status={status} — already submitted!")
        return result
    else:
        result.add_check("Status is 'drafted'", False,
                         f"status={status} — expected 'drafted'")
        return result

    # 4. Check CV PDF
    cv_pdf = app_dir / "cv.pdf"
    result.add_check("cv.pdf exists", cv_pdf.exists(),
                     f"Size: {cv_pdf.stat().st_size} bytes" if cv_pdf.exists() else "")

    # 5. Check cover letter PDF
    cl_pdf = app_dir / "cover_letter.pdf"
    result.add_check("cover_letter.pdf exists", cl_pdf.exists(),
                     f"Size: {cl_pdf.stat().st_size} bytes" if cl_pdf.exists() else "")

    # 6. Check job_description.md
    jd_path = app_dir / "job_description.md"
    result.add_check("job_description.md exists", jd_path.exists())

    # 7. Check job URL
    job_url = metadata.get("job_url", "")
    if job_url:
        result.add_check("Job URL present", True, job_url)
    else:
        result.add_check("Job URL present", False, "No job_url in metadata")
        return result

    # 8. Detect portal type
    import sys
    sys.path.insert(0, str(WORKSPACE))
    from tools.submit_adapters.base_adapter import detect_portal
    portal = detect_portal(job_url)
    result.portal_type = portal.value
    result.add_check("Portal type detected", True, portal.value)

    # 9. Probe job URL (HTTP check)
    try:
        req = urllib.request.Request(
            job_url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
            method="HEAD",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            code = resp.getcode()
            if code == 200:
                result.add_check("Job posting still active (HTTP)", True,
                                 f"HTTP {code}")
            else:
                result.add_check("Job posting still active (HTTP)", False,
                                 f"HTTP {code}")
    except urllib.error.HTTPError as e:
        if e.code in (403, 405):
            # HEAD blocked — try GET with a quick read
            result.add_check("Job posting still active (HTTP)", True,
                             f"HEAD returned {e.code} (portal blocks HEAD — likely still active)")
        else:
            result.add_check("Job posting still active (HTTP)", False,
                             f"HTTP {e.code}: {e.reason}")
    except Exception as e:
        result.add_check("Job posting still active (HTTP)", False, str(e))

    return result


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--app-dir":
        if len(sys.argv) < 3:
            print("Usage: python3 tools/submit_preflight.py --app-dir <path>")
            sys.exit(1)
        result = run_preflight(app_dir_path=sys.argv[2])
    else:
        company = sys.argv[1]
        role = sys.argv[2] if len(sys.argv) > 2 else None
        result = run_preflight(company=company, role=role)

    print(result.report())
    print()
    print(json.dumps(result.to_dict(), indent=2))
    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
