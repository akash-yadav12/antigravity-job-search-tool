"""
LinkedIn Easy Apply adapter for the /submit workflow.

LinkedIn Easy Apply uses a modal overlay with 2–4 steps:
1. Contact info (pre-filled from LinkedIn profile)
2. Resume upload
3. Additional questions
4. Review & Submit

IMPORTANT: LinkedIn Easy Apply requires the user to be logged in.
This adapter always starts with BLOCKED_AUTH if the user is not
already authenticated in the browser session.
"""

from __future__ import annotations

from tools.submit_adapters.base_adapter import BaseAdapter, PortalType


class LinkedInAdapter(BaseAdapter):
    """Adapter for LinkedIn Easy Apply."""

    portal_type = PortalType.LINKEDIN

    def get_browser_task_description(self) -> str:
        fields = self.build_field_map()
        cv_path = str(self.cv_pdf_path)

        return f"""
TASK: Fill out the LinkedIn Easy Apply for {self.context.company} — {self.context.role}.

PORTAL: LinkedIn Easy Apply
APPLICATION URL: {self.context.job_url}

=== CRITICAL SAFETY RULES ===
1. The user MUST already be logged into LinkedIn in this browser session.
   If you see a login page, STOP immediately and report "BLOCKED_AUTH: LinkedIn login required."
2. NEVER enter any LinkedIn credentials (email, password).
3. NEVER click the final "Submit application" button. STOP at the review step.
4. For unknown questions, STOP and report "BLOCKED_MISSING_ANSWER".

=== FIELD VALUES ===
{chr(10).join(f'  {k}: {v}' for k, v in fields.items())}

=== FILE UPLOADS ===
- Resume: "{cv_path}"

=== INSTRUCTIONS ===
1. Navigate to the job URL.
2. Click "Easy Apply" if visible.
3. If a login prompt appears, STOP (BLOCKED_AUTH).
4. The contact info step is usually pre-filled from the LinkedIn profile. Verify it matches.
5. Upload the CV PDF when prompted.
6. Answer additional questions using the field values. STOP for unknown questions.
7. Do NOT click Submit. Report "READY_FOR_REVIEW".

=== REPORTING ===
Report: reason code, current URL, populated fields, uploaded files, unanswered questions.
"""
