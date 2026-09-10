"""
Workday portal adapter for the /submit workflow.

Workday uses a multi-step wizard with a consistent DOM structure:
1. Create Account / Sign In
2. My Information (name, contact, address)
3. My Experience (resume upload, work history, education)
4. Application Questions (screening / supplemental questions)
5. Voluntary Disclosures (EEO — always STOP_AND_ASK)
6. Self-Identify (disability/veteran — always STOP_AND_ASK)
7. Review & Submit

SECURITY INVARIANTS:
- Passwords are created uniquely per tenant and stored ONLY in macOS Keychain.
- Passwords are NEVER written to logs, task descriptions, or state files.
- The adapter strictly handles account creation, email verification pauses,
  and authentication before form completion.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.submit_adapters.base_adapter import BaseAdapter, PortalType, SubmissionContext
from tools.submit_adapters.credential_manager import (
    AccountRegistry,
    CANONICAL_USERNAME,
    extract_tenant_key,
    generate_strong_password,
    has_credential,
    make_service_name,
    store_credential,
)


class WorkdayAdapter(BaseAdapter):
    """Adapter for Workday (myworkdayjobs.com) application portals."""

    portal_type = PortalType.WORKDAY

    def __init__(self, context: SubmissionContext, registry: AccountRegistry | None = None):
        super().__init__(context)
        self.registry = registry or AccountRegistry()

    @property
    def tenant_key(self) -> str:
        """Extract the Workday tenant identifier from the job URL."""
        return extract_tenant_key("workday", self.context.job_url)

    @property
    def service_name(self) -> str:
        """macOS Keychain service name for this Workday tenant."""
        return make_service_name("workday", self.tenant_key)

    @property
    def registry_key(self) -> str:
        """Key used in account_registry.json."""
        return f"workday:{self.tenant_key}"

    def check_account_status(self) -> dict[str, Any]:
        """Check whether an account and Keychain credential exist for this tenant."""
        account_record = self.registry.get_account(self.registry_key)
        has_keychain = has_credential(self.service_name, CANONICAL_USERNAME)
        return {
            "tenant_key": self.tenant_key,
            "service_name": self.service_name,
            "username": CANONICAL_USERNAME,
            "account_record": account_record,
            "account_exists": bool(account_record and account_record.get("account_exists")),
            "has_keychain_credential": has_keychain,
            "verification_status": account_record.get("verification_status") if account_record else "unregistered",
            "creation_status": account_record.get("creation_status") if account_record else "unregistered",
        }

    def prepare_new_account(self) -> dict[str, Any]:
        """Generate a unique strong password and store it in macOS Keychain.

        SECURITY: Does NOT return or log the password. Returns non-secret metadata only.
        """
        password = generate_strong_password(length=24)
        stored = store_credential(self.service_name, CANONICAL_USERNAME, password)
        if not stored:
            raise RuntimeError(f"Failed to store credential in macOS Keychain for service {self.service_name}")

        record = self.registry.register_account(
            portal="workday",
            tenant=self.tenant_key,
            company=self.context.company,
            username=CANONICAL_USERNAME,
            account_exists=False,
            creation_status="pending",
            verification_status="unverified",
            notes=f"Workday tenant: {self.tenant_key}",
        )

        return {
            "tenant_key": self.tenant_key,
            "service_name": self.service_name,
            "username": CANONICAL_USERNAME,
            "stored_in_keychain": True,
            "creation_status": record["creation_status"],
        }

    def mark_account_authenticated(self, verified: bool = True, notes: str = "") -> dict[str, Any] | None:
        """Update account registry following successful login/registration."""
        return self.registry.update_status(
            registry_key=self.registry_key,
            creation_status="complete",
            verification_status="verified" if verified else "unverified",
            account_exists=True,
            notes=notes or f"Workday tenant authenticated: {self.tenant_key}",
        )

    def get_manual_credential_prompt(self, is_new_account: bool = True) -> str:
        """Generate human-facing instructions for entering the Keychain credential into browser."""
        action = "Create Account" if is_new_account else "Sign In"
        return (
            f"=== ACTION REQUIRED: ENTER CREDENTIAL IN BROWSER ({action}) ===\n"
            f"Portal: Workday ({self.tenant_key})\n"
            f"Account: {CANONICAL_USERNAME}\n"
            f"Keychain Service: {self.service_name}\n\n"
            f"1. A unique strong password was prepared and saved in your macOS Keychain.\n"
            f"2. Please enter or paste the password into the active browser window.\n"
            f"3. Submit the {action} form in the browser.\n"
            f"4. If email verification is requested, verify your email.\n"
            f"5. Reply 'Resume' or 'Done' once the portal is authenticated.\n"
            f"================================================================"
        )

    def get_apply_url(self) -> str:
        """Transform a Workday job page URL into the direct apply URL."""
        base_url = self.context.job_url.rstrip("/")
        if base_url.endswith("/apply"):
            return base_url
        if "/apply" not in base_url:
            return f"{base_url}/apply"
        return base_url

    def get_account_creation_task_description(self) -> str:
        """Generate a browser task to create an account on Workday.

        SECURITY: The plaintext password is NOT in this prompt.
        """
        return f"""
TASK: Create a new Workday candidate account for {self.context.company} on tenant {self.tenant_key}.

APPLICATION URL: {self.get_apply_url()}
CANDIDATE EMAIL: {CANONICAL_USERNAME}

=== CRITICAL SECURITY RULES ===
1. Plaintext passwords are not embedded in prompts. The account credential was generated
   and saved in macOS Keychain under service: {self.service_name}.
2. NEVER submit the final job application form.
3. If an email verification page/popup appears, STOP IMMEDIATELY and report
   "EMAIL_VERIFICATION_REQUIRED: Please verify the confirmation email sent to {CANONICAL_USERNAME}."
4. If a CAPTCHA appears, STOP IMMEDIATELY and report "BLOCKED_CAPTCHA".
5. If an error indicates the account already exists, STOP and report "ACCOUNT_EXISTS".

=== STEP-BY-STEP INSTRUCTIONS ===
1. Navigate to the application URL: {self.get_apply_url()}
2. If on the job page, click the "Apply" button.
3. If on the "Sign In" page, look for the "Create Account" link/button and click it.
4. On the "Create Account" form:
   - Fill "Email Address" / "Email" with: {CANONICAL_USERNAME}
   - For "Password" and "Verify New Password" fields:
     * Observe the exact password policy requirements on screen (min length, character requirements).
     * Check if a terms of service / consent checkbox is present, and check it.
5. Submit the Create Account form.
6. Observe the resulting page:
   - Case A: A screen asks to verify email (e.g. "We've sent a verification code / link to your email").
     -> STOP and report "EMAIL_VERIFICATION_REQUIRED".
   - Case B: The portal signs in directly and advances to Step 2 ("My Information" / application form).
     -> STOP and report "AUTHENTICATED: Account created and logged in. Reached Step 2."
   - Case C: An error message appears (e.g. password does not meet criteria, email already registered).
     -> STOP and report "ACCOUNT_CREATION_FAILED: [exact error message]".

=== REPORTING FORMAT ===
Report:
- Result status code (EMAIL_VERIFICATION_REQUIRED, AUTHENTICATED, ACCOUNT_CREATION_FAILED, BLOCKED_CAPTCHA)
- Current page URL
- Visible headings and messages
"""

    def get_browser_task_description(self) -> str:
        """Generate a detailed browser subagent task for Workday form filling.

        Executed after authentication is complete.
        """
        fields = self.build_field_map()
        cv_path = str(self.cv_pdf_path)
        cl_path = str(self.cover_letter_pdf_path)

        return f"""
TASK: Fill out the Workday job application form for {self.context.company} — {self.context.role}.

PORTAL: Workday (myworkdayjobs.com)
APPLICATION URL: {self.get_apply_url()}

=== SAFETY RULES (MANDATORY) ===
1. NEVER click a final "Submit Application" or "Submit" button. STOP at the Review page.
2. NEVER enter passwords or credentials into form fields.
3. If you encounter a login/sign-in page, STOP and report "BLOCKED_AUTH: Login required".
4. If you encounter a CAPTCHA, STOP and report "BLOCKED_CAPTCHA: CAPTCHA detected".
5. If you encounter a question you cannot answer from the provided field map, STOP and
   report "BLOCKED_MISSING_ANSWER: [question text]".
6. Do NOT accept cookies or marketing popups — dismiss them if possible.
7. Do NOT click "Apply with LinkedIn" or any social login.

=== FIELD VALUES (USE EXACTLY AS PROVIDED) ===
{self._format_fields(fields)}

=== FILE UPLOADS ===
- Resume / CV: Upload the file at "{cv_path}"
- Cover Letter: Upload the file at "{cl_path}" (if a cover letter field exists)

=== STEP-BY-STEP FORM FILLING ===

Step 1: My Information
- Fill in First Name, Last Name, Email, Phone, Address fields using the values above.
- For Country, select "India" or type "India" in the dropdown.
- For City, enter "Mumbai".
- For State/Province, enter "Maharashtra".
- Click "Next" or "Continue" when all visible fields are filled.

Step 2: My Experience
- Look for a "Resume" upload area. Upload the CV PDF.
- If there's a "Cover Letter" upload area, upload the Cover Letter PDF.
- If the form asks for work history entries:
  * Most Recent: {fields.get("Current Employer", "Current Employer")}, {fields.get("Current Title", "Software Engineer")}
  * Start Date: May 2025 (or 05/2025)
  * End Date: Present / Currently Working Here
- If the form asks for education:
  * School: {fields.get("School", "University")}
  * Degree: Bachelor of Technology
  * Field of Study: Information Technology
  * GPA: 9.23/10
  * Graduation: 2022
- Click "Next" or "Continue".

Step 3: Application Questions
- For each question on this page:
  * If the question matches a field in the provided field values, use that value.
  * For "Years of experience" type questions, answer "4" or "4+".
  * For "Are you legally authorized to work in [country]?" → STOP and report BLOCKED_MISSING_ANSWER.
  * For "Do you require visa sponsorship?" → STOP and report BLOCKED_MISSING_ANSWER.
  * For salary/compensation questions → STOP and report BLOCKED_MISSING_ANSWER.
  * For any question about willingness to relocate → STOP and report BLOCKED_MISSING_ANSWER.
  * For ANY other question not covered by the field values → STOP and report BLOCKED_MISSING_ANSWER.
- Click "Next" or "Continue".

Step 4: Voluntary Disclosures / EEO
- STOP. Report: "REACHED_DISCLOSURES: EEO/voluntary disclosures page reached.
  These require human judgment. Fields visible: [list the field labels you see]."
  Do NOT fill in any fields on this page.

Step 5: Review Page
- If you reach a Review / Summary page, STOP.
- Report: "REACHED_REVIEW: Application review page reached. All fields populated.
  Ready for human confirmation before final submit."
- Take note of all populated fields visible on the review page.

=== REPORTING FORMAT ===
When you STOP, report:
1. The reason code (BLOCKED_AUTH, BLOCKED_CAPTCHA, BLOCKED_MISSING_ANSWER,
   REACHED_DISCLOSURES, REACHED_REVIEW)
2. The current page URL
3. What step you're on
4. Any visible error messages
5. A list of fields that were successfully populated
6. A list of files that were successfully uploaded
7. A list of any unanswered questions
"""

    @staticmethod
    def _format_fields(fields: dict[str, str]) -> str:
        """Format the field map as a readable block for the browser task."""
        lines = []
        for key, value in fields.items():
            lines.append(f"  {key}: {value}")
        return "\n".join(lines)
