"""
SmartRecruiters portal adapter for the /submit workflow.

SmartRecruiters uses a multi-step form similar to Workday but with
a different DOM structure.  Steps typically include:
1. Profile (name, email, phone)
2. Resume upload
3. Custom questions
4. Review and submit
"""

from __future__ import annotations

from tools.submit_adapters.base_adapter import BaseAdapter, PortalType


class SmartRecruitersAdapter(BaseAdapter):
    """Adapter for SmartRecruiters application portals."""

    portal_type = PortalType.SMARTRECRUITERS

    def get_browser_task_description(self) -> str:
        fields = self.build_field_map()
        cv_path = str(self.cv_pdf_path)
        cl_path = str(self.cover_letter_pdf_path)

        return f"""
TASK: Fill out the SmartRecruiters job application for {self.context.company} — {self.context.role}.

PORTAL: SmartRecruiters
APPLICATION URL: {self.context.job_url}

=== SAFETY RULES (MANDATORY) ===
1. NEVER click the final "Submit" button. STOP at the review step.
2. NEVER enter passwords, OTPs, or login credentials.
3. If login/CAPTCHA is required, STOP and report the appropriate code.
4. For unknown questions, STOP and report "BLOCKED_MISSING_ANSWER".

=== FIELD VALUES ===
{chr(10).join(f'  {k}: {v}' for k, v in fields.items())}

=== FILE UPLOADS ===
- Resume: "{cv_path}"
- Cover Letter: "{cl_path}" (if field exists)

=== INSTRUCTIONS ===
1. Navigate to the application URL.
2. Click "Apply" if a button is visible.
3. Fill all standard profile fields.
4. Upload resume and cover letter.
5. Answer screening questions using field values. STOP for unknown questions.
6. Do NOT click Submit. Report "READY_FOR_REVIEW".

=== REPORTING ===
Report: reason code, current URL, populated fields, uploaded files, unanswered questions.
"""
