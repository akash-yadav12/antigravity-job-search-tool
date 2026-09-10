"""
Generic fallback adapter for the /submit workflow.

Used when the portal type cannot be determined from the URL.
Provides conservative, portal-agnostic browser instructions that
attempt to find and fill common form fields.
"""

from __future__ import annotations

from tools.submit_adapters.base_adapter import BaseAdapter, PortalType


class GenericAdapter(BaseAdapter):
    """Fallback adapter for unrecognized application portals."""

    portal_type = PortalType.GENERIC

    def get_browser_task_description(self) -> str:
        fields = self.build_field_map()
        cv_path = str(self.cv_pdf_path)
        cl_path = str(self.cover_letter_pdf_path)

        return f"""
TASK: Fill out the job application form for {self.context.company} — {self.context.role}.

PORTAL: Unknown / Generic
APPLICATION URL: {self.context.job_url}

=== SAFETY RULES (MANDATORY) ===
1. NEVER click any button labeled "Submit", "Send Application", or equivalent.
   STOP before the final submission step.
2. NEVER enter passwords, OTPs, or login credentials.
3. If login/account creation is required, STOP and report "BLOCKED_AUTH".
4. If a CAPTCHA is required, STOP and report "BLOCKED_CAPTCHA".
5. For any question you cannot answer from the field values below, STOP and
   report "BLOCKED_MISSING_ANSWER: [question text]".

=== FIELD VALUES ===
{chr(10).join(f'  {k}: {v}' for k, v in fields.items())}

=== FILE UPLOADS ===
- Resume/CV: "{cv_path}"
- Cover Letter: "{cl_path}" (if upload field exists)

=== INSTRUCTIONS ===
1. Navigate to the application URL.
2. Look for an "Apply" or "Apply Now" button and click it.
3. Identify all form fields on the page(s).
4. Fill in fields that match the provided field values.
5. Upload documents when file upload fields are found.
6. Navigate through multi-step forms using "Next" / "Continue" buttons.
7. STOP at the final review or submit step.
8. Report "READY_FOR_REVIEW" with all details.

=== REPORTING ===
Report: reason code, current URL, step description, populated fields,
uploaded files, unanswered questions, any error messages.
"""
