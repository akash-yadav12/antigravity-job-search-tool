"""
Lever portal adapter for the /submit workflow.

Lever applications typically use a single-page form:
- Personal Information (name, email, phone, LinkedIn, etc.)
- Resume/CV upload
- Cover letter upload or text area
- Custom questions
- Submit button

This adapter generates browser_subagent task descriptions for Lever forms.
"""

from __future__ import annotations

from tools.submit_adapters.base_adapter import BaseAdapter, PortalType


class LeverAdapter(BaseAdapter):
    """Adapter for Lever (jobs.lever.co) application portals."""

    portal_type = PortalType.LEVER

    def get_apply_url(self) -> str:
        base_url = self.context.job_url.rstrip("/")
        if base_url.endswith("/apply"):
            return base_url
        return f"{base_url}/apply"

    def get_browser_task_description(self) -> str:
        fields = self.build_field_map()
        cv_path = str(self.cv_pdf_path)
        cl_path = str(self.cover_letter_pdf_path)

        return f"""
TASK: Fill out the Lever job application form for {self.context.company} — {self.context.role}.

PORTAL: Lever (lever.co)
APPLICATION URL: {self.get_apply_url()}

=== SAFETY RULES (MANDATORY) ===
1. NEVER click the final "Submit application" button. STOP after filling all fields.
2. NEVER enter passwords, OTPs, or login credentials.
3. If you encounter a login page, STOP and report "BLOCKED_AUTH".
4. If you encounter a CAPTCHA, STOP and report "BLOCKED_CAPTCHA".
5. For unknown questions, STOP and report "BLOCKED_MISSING_ANSWER: [question text]".
6. Do NOT click "Apply with LinkedIn" or any social login.

=== FIELD VALUES ===
{chr(10).join(f'  {k}: {v}' for k, v in fields.items())}

=== FILE UPLOADS ===
- Resume: Upload "{cv_path}"
- Cover Letter: Upload "{cl_path}" (if field exists)

=== INSTRUCTIONS ===
1. Navigate to the apply URL.
2. Fill in all standard fields using the field values above.
3. Upload the resume and cover letter PDFs.
4. For any custom questions:
   - If the question matches a known field, use that value.
   - Otherwise STOP and report BLOCKED_MISSING_ANSWER.
5. Do NOT click Submit. Report "READY_FOR_REVIEW" with all populated fields.

=== REPORTING ===
Report: reason code, current URL, populated fields, uploaded files, unanswered questions.
"""
