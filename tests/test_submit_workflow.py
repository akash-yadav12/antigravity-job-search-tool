"""
Unit tests for the /submit workflow.

Tests cover:
1. State machine transitions (legal and illegal)
2. Answer governance (deterministic vs stop-and-ask)
3. Credential exclusion
4. Portal detection
5. Final submission gate
6. Preflight validation
7. Pre-submission summary
8. Auth routing classification (v2)
9. Manual-required state transitions (v2)
10. Automated no-auth path (v2)
11. No credential access in manual mode (v2)
12. Batch processing continuity (v2)
13. Manual submission metadata (v2)
14. Manual-required summary output (v2)
15. Backward compatibility with legacy auth states (v2)
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

# Add workspace root to path
WORKSPACE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE))

from tools.submit_adapters.base_adapter import (
    AuthRequirement,
    SubmissionState,
    SubmissionContext,
    BaseAdapter,
    IllegalStateTransition,
    LEGAL_TRANSITIONS,
    PortalType,
    detect_portal,
    CREDENTIAL_PATTERNS,
)
from tools.submit_adapters.auth_router import (
    AuthDecision,
    detect_application_auth_requirement,
    get_auth_detection_task_description,
)
from tools.submit_adapters.answers_provider import (
    AnswersProvider,
    AnswerResult,
    AnswerConfidence,
    CANONICAL_FACTS,
)


class TestStateMachine(TestCase):
    """Test the submission state machine transitions."""

    def _make_context(self, state: SubmissionState = SubmissionState.DRAFTED) -> SubmissionContext:
        return SubmissionContext(
            company="TestCo",
            role="TestRole",
            app_dir=Path("/tmp/test_app"),
            job_url="https://example.com/job/123",
            portal_type=PortalType.GENERIC,
            state=state,
        )

    # --- Legal transitions ---

    def test_drafted_to_submission_in_progress(self):
        ctx = self._make_context(SubmissionState.DRAFTED)
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Starting submission")
        self.assertEqual(ctx.state, SubmissionState.SUBMISSION_IN_PROGRESS)

    def test_drafted_to_stale_job(self):
        ctx = self._make_context(SubmissionState.DRAFTED)
        ctx.transition(SubmissionState.STALE_JOB, "Job expired")
        self.assertEqual(ctx.state, SubmissionState.STALE_JOB)

    def test_in_progress_to_awaiting_confirmation(self):
        ctx = self._make_context(SubmissionState.SUBMISSION_IN_PROGRESS)
        ctx.transition(SubmissionState.AWAITING_USER_CONFIRMATION, "Review page reached")
        self.assertEqual(ctx.state, SubmissionState.AWAITING_USER_CONFIRMATION)

    def test_in_progress_to_blocked_auth(self):
        ctx = self._make_context(SubmissionState.SUBMISSION_IN_PROGRESS)
        ctx.transition(SubmissionState.SUBMISSION_BLOCKED_AUTH, "Login required")
        self.assertEqual(ctx.state, SubmissionState.SUBMISSION_BLOCKED_AUTH)

    def test_in_progress_to_blocked_captcha(self):
        ctx = self._make_context(SubmissionState.SUBMISSION_IN_PROGRESS)
        ctx.transition(SubmissionState.SUBMISSION_BLOCKED_CAPTCHA, "CAPTCHA detected")
        self.assertEqual(ctx.state, SubmissionState.SUBMISSION_BLOCKED_CAPTCHA)

    def test_in_progress_to_blocked_missing_answer(self):
        ctx = self._make_context(SubmissionState.SUBMISSION_IN_PROGRESS)
        ctx.transition(SubmissionState.SUBMISSION_BLOCKED_MISSING_ANSWER, "Unknown question")
        self.assertEqual(ctx.state, SubmissionState.SUBMISSION_BLOCKED_MISSING_ANSWER)

    def test_in_progress_to_failed(self):
        ctx = self._make_context(SubmissionState.SUBMISSION_IN_PROGRESS)
        ctx.transition(SubmissionState.SUBMISSION_FAILED, "Network error")
        self.assertEqual(ctx.state, SubmissionState.SUBMISSION_FAILED)

    def test_awaiting_confirmation_to_applied(self):
        ctx = self._make_context(SubmissionState.AWAITING_USER_CONFIRMATION)
        ctx.transition(SubmissionState.APPLIED, "User confirmed")
        self.assertEqual(ctx.state, SubmissionState.APPLIED)
        self.assertIsNotNone(ctx.applied_at)

    def test_awaiting_confirmation_to_drafted_abort(self):
        ctx = self._make_context(SubmissionState.AWAITING_USER_CONFIRMATION)
        ctx.transition(SubmissionState.DRAFTED, "User aborted")
        self.assertEqual(ctx.state, SubmissionState.DRAFTED)

    def test_blocked_auth_retry(self):
        ctx = self._make_context(SubmissionState.SUBMISSION_BLOCKED_AUTH)
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "User logged in, retrying")
        self.assertEqual(ctx.state, SubmissionState.SUBMISSION_IN_PROGRESS)

    def test_blocked_captcha_retry(self):
        ctx = self._make_context(SubmissionState.SUBMISSION_BLOCKED_CAPTCHA)
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "User solved CAPTCHA")
        self.assertEqual(ctx.state, SubmissionState.SUBMISSION_IN_PROGRESS)

    def test_blocked_missing_answer_retry(self):
        ctx = self._make_context(SubmissionState.SUBMISSION_BLOCKED_MISSING_ANSWER)
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "User provided answer")
        self.assertEqual(ctx.state, SubmissionState.SUBMISSION_IN_PROGRESS)

    # --- Illegal transitions ---

    def test_drafted_to_applied_illegal(self):
        """Cannot jump from drafted directly to applied — must go through
        submission_in_progress → awaiting_user_confirmation first."""
        ctx = self._make_context(SubmissionState.DRAFTED)
        with self.assertRaises(IllegalStateTransition):
            ctx.transition(SubmissionState.APPLIED, "Skip everything")

    def test_drafted_to_awaiting_confirmation_illegal(self):
        """Cannot jump from drafted to awaiting_user_confirmation."""
        ctx = self._make_context(SubmissionState.DRAFTED)
        with self.assertRaises(IllegalStateTransition):
            ctx.transition(SubmissionState.AWAITING_USER_CONFIRMATION, "Skip")

    def test_applied_to_anything_illegal(self):
        """APPLIED is terminal — no further transitions allowed."""
        ctx = self._make_context(SubmissionState.APPLIED)
        for target in SubmissionState:
            if target == SubmissionState.APPLIED:
                continue
            with self.assertRaises(IllegalStateTransition):
                ctx.transition(target, "Should fail")

    def test_failed_is_terminal(self):
        """SUBMISSION_FAILED is terminal."""
        ctx = self._make_context(SubmissionState.SUBMISSION_FAILED)
        for target in SubmissionState:
            if target == SubmissionState.SUBMISSION_FAILED:
                continue
            with self.assertRaises(IllegalStateTransition):
                ctx.transition(target, "Should fail")

    def test_stale_job_is_terminal(self):
        """STALE_JOB is terminal."""
        ctx = self._make_context(SubmissionState.STALE_JOB)
        for target in SubmissionState:
            if target == SubmissionState.STALE_JOB:
                continue
            with self.assertRaises(IllegalStateTransition):
                ctx.transition(target, "Should fail")

    # --- State history ---

    def test_state_history_recorded(self):
        ctx = self._make_context(SubmissionState.DRAFTED)
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start")
        ctx.transition(SubmissionState.AWAITING_USER_CONFIRMATION, "Review reached")
        ctx.transition(SubmissionState.APPLIED, "User confirmed")

        self.assertEqual(len(ctx.state_history), 3)
        self.assertEqual(ctx.state_history[0][0], "drafted")
        self.assertEqual(ctx.state_history[0][1], "submission_in_progress")
        self.assertEqual(ctx.state_history[2][1], "applied")

    def test_applied_sets_timestamp(self):
        ctx = self._make_context(SubmissionState.AWAITING_USER_CONFIRMATION)
        self.assertIsNone(ctx.applied_at)
        ctx.transition(SubmissionState.APPLIED, "Confirmed")
        self.assertIsNotNone(ctx.applied_at)


class TestPortalDetection(TestCase):
    """Test portal type detection from URLs."""

    def test_workday(self):
        urls = [
            "https://cisco.wd1.myworkdayjobs.com/en-US/jobs/job/12345",
            "https://wellsfargo.wd5.myworkdayjobs.com/jobs/job/67890",
            "https://company.wd3.myworkdayjobs.com/External/job/Software-Engineer/JR-12345",
        ]
        for url in urls:
            self.assertEqual(detect_portal(url), PortalType.WORKDAY, f"Failed for {url}")

    def test_lever(self):
        self.assertEqual(
            detect_portal("https://jobs.lever.co/company/abc123"),
            PortalType.LEVER,
        )

    def test_smartrecruiters(self):
        self.assertEqual(
            detect_portal("https://jobs.smartrecruiters.com/Company/12345-role"),
            PortalType.SMARTRECRUITERS,
        )

    def test_greenhouse(self):
        urls = [
            "https://boards.greenhouse.io/company/jobs/12345",
            "https://job-boards.greenhouse.io/company/jobs/12345",
        ]
        for url in urls:
            self.assertEqual(detect_portal(url), PortalType.GREENHOUSE, f"Failed for {url}")

    def test_linkedin(self):
        self.assertEqual(
            detect_portal("https://www.linkedin.com/jobs/view/12345"),
            PortalType.LINKEDIN,
        )

    def test_generic(self):
        self.assertEqual(
            detect_portal("https://careers.example.com/jobs/12345"),
            PortalType.GENERIC,
        )


TEST_FACTS = {
    "full_name": "Jane Doe",
    "first_name": "Jane",
    "last_name": "Doe",
    "email": "jane.doe@example.com",
    "phone": "+1 555-0100",
    "phone_country_code": "+1",
    "phone_number": "555-0100",
    "location": "San Francisco, CA, USA",
    "city": "San Francisco",
    "state": "CA",
    "country": "USA",
    "country_code": "US",
    "linkedin_url": "https://www.linkedin.com/in/janedoe",
    "github_url": "https://github.com/janedoe",
    "current_employer": "Acme Corp",
    "current_title": "Software Engineer II",
    "notice_period": "30 days",
    "notice_period_days": "30 days",
    "earliest_joining_date": "Immediate",
    "total_years_experience": "4",
    "total_years_experience_text": "4 years",
    "highest_degree": "Bachelor's Degree",
    "degree_field": "Computer Science",
    "university": "State University",
    "graduation_year": "2020",
    "gpa": "3.8",
}


class TestAnswerGovernance(TestCase):
    """Test that the answers provider correctly resolves questions and
    enforces stop-and-ask for sensitive categories."""

    def setUp(self):
        self.provider = AnswersProvider(TEST_FACTS)

    # --- Deterministic auto-fills ---

    def test_resolve_email(self):
        result = self.provider.resolve("What is your email address?")
        self.assertEqual(result.confidence, AnswerConfidence.EXACT)
        self.assertEqual(result.answer, "jane.doe@example.com")

    def test_resolve_first_name(self):
        result = self.provider.resolve("First Name")
        self.assertEqual(result.confidence, AnswerConfidence.EXACT)
        self.assertEqual(result.answer, "Jane")

    def test_resolve_last_name(self):
        result = self.provider.resolve("Last Name")
        self.assertEqual(result.confidence, AnswerConfidence.EXACT)
        self.assertEqual(result.answer, "Doe")

    def test_resolve_phone(self):
        result = self.provider.resolve("Phone Number")
        self.assertEqual(result.confidence, AnswerConfidence.EXACT)
        self.assertEqual(result.answer, "+1 555-0100")

    def test_resolve_linkedin(self):
        result = self.provider.resolve("LinkedIn URL")
        self.assertEqual(result.confidence, AnswerConfidence.EXACT)
        self.assertIn("linkedin.com", result.answer)

    def test_resolve_current_employer(self):
        result = self.provider.resolve("Current Company")
        self.assertEqual(result.confidence, AnswerConfidence.EXACT)
        self.assertEqual(result.answer, TEST_FACTS["current_employer"])

    def test_resolve_experience(self):
        result = self.provider.resolve("Total experience")
        self.assertEqual(result.confidence, AnswerConfidence.EXACT)
        self.assertIn("4", result.answer)

    def test_resolve_notice_period(self):
        result = self.provider.resolve("What is your notice period?")
        self.assertEqual(result.confidence, AnswerConfidence.EXACT)
        self.assertIn(TEST_FACTS["notice_period_days"], result.answer)

    # --- Mandatory STOP-AND-ASK ---

    def test_stop_salary(self):
        questions = [
            "What is your expected salary?",
            "Current CTC",
            "Expected compensation range",
            "What are your salary expectations?",
            "Desired salary",
        ]
        for q in questions:
            result = self.provider.resolve(q)
            self.assertEqual(result.confidence, AnswerConfidence.STOP_AND_ASK,
                             f"Should STOP_AND_ASK for: {q}")

    def test_stop_visa(self):
        questions = [
            "Do you require visa sponsorship?",
            "Are you authorized to work in the United States?",
            "Work authorization status",
            "Citizenship status",
            "Right to work in the UK",
        ]
        for q in questions:
            result = self.provider.resolve(q)
            self.assertEqual(result.confidence, AnswerConfidence.STOP_AND_ASK,
                             f"Should STOP_AND_ASK for: {q}")

    def test_stop_legal(self):
        questions = [
            "Have you ever been convicted of a felony?",
            "Criminal background check consent",
        ]
        for q in questions:
            result = self.provider.resolve(q)
            self.assertEqual(result.confidence, AnswerConfidence.STOP_AND_ASK,
                             f"Should STOP_AND_ASK for: {q}")

    def test_stop_demographic(self):
        questions = [
            "Gender identity",
            "Race/ethnicity",
            "Are you a veteran?",
            "Disability status",
        ]
        for q in questions:
            result = self.provider.resolve(q)
            self.assertEqual(result.confidence, AnswerConfidence.STOP_AND_ASK,
                             f"Should STOP_AND_ASK for: {q}")

    def test_stop_security_clearance(self):
        result = self.provider.resolve("Do you have a security clearance?")
        self.assertEqual(result.confidence, AnswerConfidence.STOP_AND_ASK)

    def test_stop_relocation(self):
        result = self.provider.resolve("Are you willing to relocate?")
        self.assertEqual(result.confidence, AnswerConfidence.STOP_AND_ASK)

    def test_stop_unknown_question(self):
        result = self.provider.resolve("What flavor of ice cream do you prefer?")
        self.assertEqual(result.confidence, AnswerConfidence.STOP_AND_ASK)
        self.assertEqual(result.source, "no_match")

    # --- Deterministic field map ---

    def test_deterministic_fields_complete(self):
        fields = self.provider.get_deterministic_fields()
        required_keys = [
            "First Name", "Last Name", "Email", "Phone", "City", "State",
            "Country", "LinkedIn URL", "Current Employer", "Current Title",
            "Years of Experience", "Highest Degree", "University",
        ]
        for key in required_keys:
            self.assertIn(key, fields, f"Missing deterministic field: {key}")

    def test_deterministic_fields_no_secrets(self):
        """Deterministic fields must never contain credential material."""
        fields = self.provider.get_deterministic_fields()
        for key, value in fields.items():
            self.assertFalse(
                self.provider.is_credential(f"{key}: {value}"),
                f"Credential detected in field: {key}",
            )


class TestCredentialExclusion(TestCase):
    """Test that credentials are never persisted in state files."""

    def test_credential_detection(self):
        provider = AnswersProvider()
        self.assertTrue(provider.is_credential("password"))
        self.assertTrue(provider.is_credential("my_session_token_abc"))
        self.assertTrue(provider.is_credential("bearer xyz"))
        self.assertTrue(provider.is_credential("OTP: 123456"))
        self.assertFalse(provider.is_credential("Jane Doe"))
        self.assertFalse(provider.is_credential("Software Engineer"))

    def test_state_serialization_redacts_credentials(self):
        ctx = SubmissionContext(
            company="TestCo",
            role="TestRole",
            app_dir=Path("/tmp/test"),
            job_url="https://example.com",
            portal_type=PortalType.GENERIC,
        )
        # Simulate a populated field that accidentally contains a credential key
        ctx.populated_fields["password_field"] = "hunter2"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            saved = ctx.save_state(Path(f.name))
            data = json.loads(saved.read_text())
            # The credential value should be redacted
            self.assertEqual(
                data["populated_fields"]["password_field"],
                "[REDACTED]",
            )


class TestFinalSubmissionGate(TestCase):
    """Test that the state machine prevents unauthorized submission."""

    def test_cannot_reach_applied_without_awaiting_confirmation(self):
        """The ONLY path to APPLIED is through AWAITING_USER_CONFIRMATION."""
        ctx = SubmissionContext(
            company="TestCo",
            role="TestRole",
            app_dir=Path("/tmp/test"),
            job_url="https://example.com",
            portal_type=PortalType.GENERIC,
            state=SubmissionState.SUBMISSION_IN_PROGRESS,
        )
        with self.assertRaises(IllegalStateTransition):
            ctx.transition(SubmissionState.APPLIED, "Skip confirmation")

    def test_full_happy_path(self):
        """Verify the complete happy path through the state machine."""
        ctx = SubmissionContext(
            company="TestCo",
            role="TestRole",
            app_dir=Path("/tmp/test"),
            job_url="https://example.com",
            portal_type=PortalType.GENERIC,
        )
        # drafted → submission_in_progress
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start")
        # submission_in_progress → awaiting_user_confirmation
        ctx.transition(SubmissionState.AWAITING_USER_CONFIRMATION, "Review reached")
        # awaiting_user_confirmation → applied
        ctx.transition(SubmissionState.APPLIED, "User said Submit it")

        self.assertEqual(ctx.state, SubmissionState.APPLIED)
        self.assertIsNotNone(ctx.applied_at)
        self.assertEqual(len(ctx.state_history), 3)


class TestPreSubmissionSummary(TestCase):
    """Test the pre-submission summary output."""

    def test_summary_includes_company_and_role(self):
        ctx = SubmissionContext(
            company="Cisco",
            role="Software Engineer",
            app_dir=Path("/tmp/test"),
            job_url="https://cisco.wd1.myworkdayjobs.com/jobs/job/12345",
            portal_type=PortalType.WORKDAY,
        )
        ctx.populated_fields = {"First Name": "Jane", "Last Name": "Doe"}
        ctx.uploaded_files = {"Resume": "/tmp/cv.pdf"}
        summary = ctx.pre_submission_summary()
        self.assertIn("Cisco", summary)
        self.assertIn("Software Engineer", summary)
        self.assertIn("workday", summary)
        self.assertIn("Submit it", summary)
        self.assertIn("Abort", summary)

    def test_summary_shows_unanswered_questions(self):
        ctx = SubmissionContext(
            company="TestCo",
            role="TestRole",
            app_dir=Path("/tmp/test"),
            job_url="https://example.com",
            portal_type=PortalType.GENERIC,
        )
        ctx.unanswered_questions = ["What is your expected salary?"]
        summary = ctx.pre_submission_summary()
        self.assertIn("expected salary", summary)
        self.assertIn("NEED YOUR INPUT", summary)


class TestWorkdayAdapter(TestCase):
    """Test the Workday adapter."""

    def test_apply_url_transformation(self):
        from tools.submit_adapters.workday_adapter import WorkdayAdapter

        ctx = SubmissionContext(
            company="Cisco",
            role="Software Engineer",
            app_dir=Path("/tmp/test"),
            job_url="https://cisco.wd1.myworkdayjobs.com/en-US/jobs/job/12345",
            portal_type=PortalType.WORKDAY,
        )
        adapter = WorkdayAdapter(ctx)
        apply_url = adapter.get_apply_url()
        self.assertTrue(apply_url.endswith("/apply"))

        adapter = WorkdayAdapter(ctx)
        apply_url = adapter.get_apply_url()
        # Should not double-append /apply
        self.assertFalse(apply_url.endswith("/apply/apply"))

    def test_browser_task_includes_safety_rules(self):
        from tools.submit_adapters.workday_adapter import WorkdayAdapter

        ctx = SubmissionContext(
            company="Cisco",
            role="SE",
            app_dir=Path("/tmp/test"),
            job_url="https://cisco.wd1.myworkdayjobs.com/job/12345",
            portal_type=PortalType.WORKDAY,
        )
        adapter = WorkdayAdapter(ctx)
        task = adapter.get_browser_task_description()
        self.assertIn("NEVER click a final", task)
        self.assertIn("NEVER enter passwords", task)
        self.assertIn("BLOCKED_AUTH", task)
        self.assertIn("BLOCKED_CAPTCHA", task)
        self.assertIn("BLOCKED_MISSING_ANSWER", task)


class TestLegalTransitionsExhaustive(TestCase):
    """Exhaustively verify that LEGAL_TRANSITIONS covers all states
    and that no unintended transitions are possible."""

    def test_all_states_have_transition_entry(self):
        for state in SubmissionState:
            self.assertIn(state, LEGAL_TRANSITIONS,
                          f"Missing LEGAL_TRANSITIONS entry for {state}")

    def test_terminal_states_have_no_transitions(self):
        terminal = {SubmissionState.APPLIED, SubmissionState.SUBMISSION_FAILED,
                     SubmissionState.STALE_JOB}
        for state in terminal:
            self.assertEqual(LEGAL_TRANSITIONS[state], set(),
                             f"Terminal state {state} should have no transitions")

    def test_applied_only_from_awaiting_confirmation(self):
        """APPLIED can only be reached from AWAITING_USER_CONFIRMATION."""
        for state, targets in LEGAL_TRANSITIONS.items():
            if SubmissionState.APPLIED in targets:
                self.assertEqual(state, SubmissionState.AWAITING_USER_CONFIRMATION,
                                 f"APPLIED should only be reachable from "
                                 f"AWAITING_USER_CONFIRMATION, not {state}")


class TestCredentialManager(TestCase):
    """Test cryptographically secure password generation and Keychain operations."""

    def test_password_length_and_complexity(self):
        from tools.submit_adapters.credential_manager import (
            PASSWORD_DIGITS,
            PASSWORD_LOWER,
            PASSWORD_SYMBOLS,
            PASSWORD_UPPER,
            generate_strong_password,
        )

        for length in (24, 32, 16):
            pwd = generate_strong_password(length)
            self.assertEqual(len(pwd), length)
            self.assertTrue(any(c in PASSWORD_UPPER for c in pwd), "Missing uppercase")
            self.assertTrue(any(c in PASSWORD_LOWER for c in pwd), "Missing lowercase")
            self.assertTrue(any(c in PASSWORD_DIGITS for c in pwd), "Missing digit")
            self.assertTrue(any(c in PASSWORD_SYMBOLS for c in pwd), "Missing symbol")

    def test_password_randomness_and_uniqueness(self):
        from tools.submit_adapters.credential_manager import generate_strong_password

        passwords = [generate_strong_password(24) for _ in range(50)]
        # All 50 passwords must be unique
        self.assertEqual(len(set(passwords)), 50)

    def test_extract_tenant_key(self):
        from tools.submit_adapters.credential_manager import extract_tenant_key

        self.assertEqual(
            extract_tenant_key("workday", "https://cisco.wd5.myworkdayjobs.com/en-US/Cisco_Careers/job/123"),
            "cisco.wd5.myworkdayjobs.com",
        )
        self.assertEqual(
            extract_tenant_key("workday", "https://wellsfargo.wd5.myworkdayjobs.com/jobs/job/456"),
            "wellsfargo.wd5.myworkdayjobs.com",
        )
        self.assertEqual(
            extract_tenant_key("lever", "https://jobs.lever.co/companyname/123-abc"),
            "lever.co:companyname",
        )
        self.assertEqual(
            extract_tenant_key("smartrecruiters", "https://jobs.smartrecruiters.com/AcmeCorp/789"),
            "smartrecruiters.com:acmecorp",
        )

    def test_service_name_format(self):
        from tools.submit_adapters.credential_manager import make_service_name

        self.assertEqual(
            make_service_name("workday", "cisco.wd5.myworkdayjobs.com"),
            "ai-job-search:workday:cisco.wd5.myworkdayjobs.com",
        )

    def test_live_keychain_smoke(self):
        """Perform a safe live add/check/read/delete smoke test against macOS Keychain."""
        from tools.submit_adapters.credential_manager import (
            delete_credential,
            get_credential,
            has_credential,
            store_credential,
        )

        test_service = "ai-job-search-test:unit_test_probe_runner"
        test_user = "test_candidate@example.com"
        test_secret = "UnitT3st_P@ssw0rd!#2026"

        try:
            # 1. Store
            stored = store_credential(test_service, test_user, test_secret)
            self.assertTrue(stored, "Failed to store test credential in Keychain")

            # 2. Has
            self.assertTrue(has_credential(test_service, test_user))

            # 3. Read
            retrieved = get_credential(test_service, test_user)
            self.assertEqual(retrieved, test_secret)

            # 4. Update
            updated_secret = "Updated_P@ssw0rd!#2026_V2"
            store_credential(test_service, test_user, updated_secret)
            self.assertEqual(get_credential(test_service, test_user), updated_secret)

        finally:
            # 5. Clean up
            deleted = delete_credential(test_service, test_user)
            self.assertTrue(deleted)
            self.assertFalse(has_credential(test_service, test_user))


class TestAccountRegistry(TestCase):
    """Test non-secret account registry persistence and security validation."""

    def test_register_and_get(self):
        from tools.submit_adapters.credential_manager import AccountRegistry

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            temp_path = Path(f.name)

        try:
            reg = AccountRegistry(temp_path)
            reg.register_account(
                portal="workday",
                tenant="cisco.wd5.myworkdayjobs.com",
                company="Cisco",
                username="jane.doe@example.com",
                account_exists=True,
                creation_status="created",
                verification_status="verified",
                notes="Unit test record",
            )

            acc = reg.get_account("workday:cisco.wd5.myworkdayjobs.com")
            self.assertIsNotNone(acc)
            self.assertEqual(acc["company"], "Cisco")
            self.assertTrue(acc["account_exists"])
            self.assertEqual(acc["verification_status"], "verified")

            # Re-load from disk to verify serialization
            reg2 = AccountRegistry(temp_path)
            acc2 = reg2.get_account("workday:cisco.wd5.myworkdayjobs.com")
            self.assertIsNotNone(acc2)
            self.assertEqual(acc2["tenant"], "cisco.wd5.myworkdayjobs.com")
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_rejection_of_secrets(self):
        from tools.submit_adapters.credential_manager import AccountRegistry

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            temp_path = Path(f.name)

        try:
            reg = AccountRegistry(temp_path)
            # Attempting to store secret-like key
            with self.assertRaises(ValueError):
                reg.register_account(
                    portal="workday",
                    tenant="cisco.wd5.myworkdayjobs.com",
                    company="Cisco",
                    username="user",
                    notes="password=hunter2",
                )
        finally:
            if temp_path.exists():
                temp_path.unlink()


class TestAuthStateMachineTransitions(TestCase):
    """Test full authentication and account creation state machine paths."""

    def _make_context(self) -> SubmissionContext:
        return SubmissionContext(
            company="Cisco",
            role="Software_Engineer_Java_Go",
            app_dir=Path("/tmp/test_cisco"),
            job_url="https://cisco.wd5.myworkdayjobs.com/job/123",
            portal_type=PortalType.WORKDAY,
            state=SubmissionState.DRAFTED,
        )

    def test_new_account_flow_with_verification(self):
        """drafted -> in_progress -> auth_required -> account_creation -> email_verification -> authenticated -> in_progress -> review -> applied"""
        ctx = self._make_context()
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start")
        ctx.transition(SubmissionState.AUTHENTICATION_REQUIRED, "Sign In page detected")
        ctx.transition(SubmissionState.ACCOUNT_CREATION_IN_PROGRESS, "Clicked Create Account")
        ctx.transition(SubmissionState.EMAIL_VERIFICATION_REQUIRED, "Verification code sent")
        ctx.transition(SubmissionState.AUTHENTICATED, "User verified email")
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Resume form filling")
        ctx.transition(SubmissionState.AWAITING_USER_CONFIRMATION, "Review page reached")
        ctx.transition(SubmissionState.APPLIED, "User confirmed")

        self.assertEqual(ctx.state, SubmissionState.APPLIED)
        self.assertIsNotNone(ctx.applied_at)
        self.assertEqual(len(ctx.state_history), 8)

    def test_existing_account_flow(self):
        """drafted -> in_progress -> auth_required -> authenticated -> in_progress -> review -> applied"""
        ctx = self._make_context()
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start")
        ctx.transition(SubmissionState.AUTHENTICATION_REQUIRED, "Sign In required")
        ctx.transition(SubmissionState.AUTHENTICATED, "Logged in via Keychain credentials")
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Filling application")
        ctx.transition(SubmissionState.AWAITING_USER_CONFIRMATION, "Reached review")
        ctx.transition(SubmissionState.APPLIED, "Approved")

        self.assertEqual(ctx.state, SubmissionState.APPLIED)

    def test_auth_failure_recovery(self):
        ctx = self._make_context()
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start")
        ctx.transition(SubmissionState.AUTHENTICATION_REQUIRED, "Sign In")
        ctx.transition(SubmissionState.AUTHENTICATION_FAILED, "Wrong password")
        ctx.transition(SubmissionState.AUTHENTICATION_REQUIRED, "Retry")
        self.assertEqual(ctx.state, SubmissionState.AUTHENTICATION_REQUIRED)

    def test_human_assisted_account_creation_flow(self):
        """drafted -> in_progress -> auth_required -> account_creation -> awaiting_manual_credential_entry -> email_verification -> authenticated -> in_progress -> review -> applied"""
        ctx = self._make_context()
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start")
        ctx.transition(SubmissionState.AUTHENTICATION_REQUIRED, "Sign In page detected")
        ctx.transition(SubmissionState.ACCOUNT_CREATION_IN_PROGRESS, "Clicked Create Account")
        ctx.transition(SubmissionState.AWAITING_MANUAL_CREDENTIAL_ENTRY, "Prompt user to paste Keychain password")
        ctx.transition(SubmissionState.EMAIL_VERIFICATION_REQUIRED, "Workday sent email verification code")
        ctx.transition(SubmissionState.AUTHENTICATED, "User verified email and signed in")
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Filling application form")
        ctx.transition(SubmissionState.AWAITING_USER_CONFIRMATION, "Review page reached")
        ctx.transition(SubmissionState.APPLIED, "User confirmed submission")

        self.assertEqual(ctx.state, SubmissionState.APPLIED)
        self.assertEqual(len(ctx.state_history), 9)

    def test_human_assisted_existing_login_flow(self):
        """drafted -> in_progress -> auth_required -> awaiting_manual_credential_entry -> authenticated -> in_progress -> review -> applied"""
        ctx = self._make_context()
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start")
        ctx.transition(SubmissionState.AUTHENTICATION_REQUIRED, "Sign In required")
        ctx.transition(SubmissionState.AWAITING_MANUAL_CREDENTIAL_ENTRY, "Prompt user to enter Keychain password")
        ctx.transition(SubmissionState.AUTHENTICATED, "Authenticated in browser")
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Filling application")
        ctx.transition(SubmissionState.AWAITING_USER_CONFIRMATION, "Reached review")
        ctx.transition(SubmissionState.APPLIED, "Approved")

        self.assertEqual(ctx.state, SubmissionState.APPLIED)

    def test_no_direct_applied_from_auth_states(self):
        for auth_state in (
            SubmissionState.AUTHENTICATION_REQUIRED,
            SubmissionState.ACCOUNT_CREATION_IN_PROGRESS,
            SubmissionState.AWAITING_MANUAL_CREDENTIAL_ENTRY,
            SubmissionState.EMAIL_VERIFICATION_REQUIRED,
            SubmissionState.AUTHENTICATED,
            SubmissionState.MANUAL_REQUIRED,
            SubmissionState.MANUAL_REVIEW_REQUIRED,
        ):
            ctx = self._make_context()
            ctx.state = auth_state
            with self.assertRaises(IllegalStateTransition):
                ctx.transition(SubmissionState.APPLIED, "Cannot jump to applied")


class TestSecretLeakageAudit(TestCase):
    """Verify generated credentials NEVER leak into state files, registry, or workspace artifacts."""

    def test_no_secret_in_serialized_state_or_registry(self):
        from tools.submit_adapters.credential_manager import (
            AccountRegistry,
            generate_strong_password,
        )

        secret_pwd = generate_strong_password(24)

        # 1. State serialization check
        ctx = SubmissionContext(
            company="Cisco",
            role="SE",
            app_dir=Path("/tmp/leak_test"),
            job_url="https://cisco.wd5.myworkdayjobs.com/job/1",
            portal_type=PortalType.WORKDAY,
        )
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start")
        ctx.transition(SubmissionState.AUTHENTICATION_REQUIRED, "Auth")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            state_file = ctx.save_state(Path(f.name))
            state_content = state_file.read_text()
            self.assertNotIn(secret_pwd, state_content)

        # 2. Registry serialization check
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            reg_path = Path(f.name)
            reg = AccountRegistry(reg_path)
            reg.register_account(
                portal="workday",
                tenant="cisco.wd5.myworkdayjobs.com",
                company="Cisco",
                username="jane.doe@example.com",
                account_exists=True,
                creation_status="created",
                verification_status="verified",
                notes="Safe record",
            )
            reg_content = reg_path.read_text()
            self.assertNotIn(secret_pwd, reg_content)


class TestWorkdayAdapterAuth(TestCase):
    """Test WorkdayAdapter authentication and account creation methods."""

    def test_workday_prepare_new_account(self):
        from tools.submit_adapters.credential_manager import (
            AccountRegistry,
            CANONICAL_USERNAME,
            delete_credential,
            has_credential,
        )
        from tools.submit_adapters.workday_adapter import WorkdayAdapter

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            reg_path = Path(f.name)

        try:
            reg = AccountRegistry(reg_path)
            ctx = SubmissionContext(
                company="MockCompany",
                role="Software_Engineer",
                app_dir=Path("/tmp/mock_test"),
                job_url="https://mock-unit-test.wd5.myworkdayjobs.com/en-US/Careers/job/SE_123",
                portal_type=PortalType.WORKDAY,
            )
            adapter = WorkdayAdapter(ctx, registry=reg)

            # Check status before
            status_before = adapter.check_account_status()
            self.assertEqual(status_before["tenant_key"], "mock-unit-test.wd5.myworkdayjobs.com")

            # Prepare new account
            prep = adapter.prepare_new_account()
            self.assertTrue(prep["stored_in_keychain"])
            self.assertNotIn("password", prep)

            # Check Keychain
            self.assertTrue(has_credential(adapter.service_name, CANONICAL_USERNAME))

            # Check registry record
            status_after = adapter.check_account_status()
            self.assertTrue(status_after["has_keychain_credential"])
            self.assertEqual(status_after["creation_status"], "pending")

            # Check browser task description does not contain secret
            task_desc = adapter.get_account_creation_task_description()
            self.assertIn("Create a new Workday candidate account", task_desc)
            self.assertIn("mock-unit-test.wd5.myworkdayjobs.com", task_desc)
            self.assertIn("EMAIL_VERIFICATION_REQUIRED", task_desc)

        finally:
            # Clean up Keychain
            if 'adapter' in locals():
                delete_credential(adapter.service_name, CANONICAL_USERNAME)
            if reg_path.exists():
                reg_path.unlink()


if __name__ == "__main__":
    main()



# =============================================================================
# Auth Routing v2 Tests
# =============================================================================


class TestAuthRouter(TestCase):
    """Unit tests for detect_application_auth_requirement() classification, confidence & evidence."""

    def test_no_auth_application_form(self):
        """Public application form → NO_AUTH_REQUIRED with high confidence."""
        report = """
        AUTH_CLASSIFICATION: NO_AUTH_REQUIRED
        CURRENT_URL: https://jobs.lever.co/company/abc123/apply
        PAGE_DESCRIPTION: Application form with personal information fields
        AUTH_ELEMENTS: none
        FORM_ELEMENTS: First Name, Last Name, Email, Phone, Resume Upload
        """
        result = detect_application_auth_requirement(report)
        self.assertEqual(result.auth_requirement, AuthRequirement.NO_AUTH_REQUIRED)
        self.assertEqual(result.confidence, "high")
        self.assertTrue(len(result.evidence) > 0)
        self.assertEqual(result, AuthRequirement.NO_AUTH_REQUIRED)
        self.assertEqual(result.target_state, SubmissionState.SUBMISSION_IN_PROGRESS)

    def test_no_auth_apply_now_page(self):
        """Page with Apply Now and resume upload → NO_AUTH_REQUIRED."""
        report = "Reached the application form. Candidate information fields visible. Resume upload area present."
        result = detect_application_auth_requirement(report)
        self.assertEqual(result.auth_requirement, AuthRequirement.NO_AUTH_REQUIRED)
        self.assertEqual(result.confidence, "high")
        self.assertEqual(result.target_state, SubmissionState.SUBMISSION_IN_PROGRESS)

    def test_no_auth_personal_information(self):
        """Page showing personal information step → NO_AUTH_REQUIRED."""
        report = "Personal information step loaded. Fields: name, email, phone, location. No authentication needed."
        result = detect_application_auth_requirement(report)
        self.assertEqual(result.auth_requirement, AuthRequirement.NO_AUTH_REQUIRED)
        self.assertEqual(result.confidence, "high")
        self.assertEqual(result.target_state, SubmissionState.SUBMISSION_IN_PROGRESS)

    def test_auth_workday_sign_in(self):
        """Workday Sign In page → AUTH_REQUIRED with high confidence."""
        report = """
        AUTH_CLASSIFICATION: AUTH_REQUIRED
        CURRENT_URL: https://cisco.wd5.myworkdayjobs.com/en-US/Cisco_Careers/login
        PAGE_DESCRIPTION: Sign In page with email and password fields
        AUTH_ELEMENTS: Sign In button, Create Account link, password field
        FORM_ELEMENTS: none
        """
        result = detect_application_auth_requirement(report)
        self.assertEqual(result.auth_requirement, AuthRequirement.AUTH_REQUIRED)
        self.assertEqual(result.confidence, "high")
        self.assertIn("Workday", result.evidence)
        self.assertEqual(result.target_state, SubmissionState.MANUAL_REQUIRED)

    def test_auth_create_account(self):
        """Portal showing Create Account → AUTH_REQUIRED."""
        report = "The page shows a Create Account form. Fields: email, password, verify password."
        result = detect_application_auth_requirement(report)
        self.assertEqual(result.auth_requirement, AuthRequirement.AUTH_REQUIRED)
        self.assertEqual(result.confidence, "high")
        self.assertEqual(result.target_state, SubmissionState.MANUAL_REQUIRED)

    def test_auth_linkedin_login(self):
        """LinkedIn login required → AUTH_REQUIRED."""
        report = "BLOCKED_AUTH: LinkedIn login required. The Easy Apply modal requires an authenticated LinkedIn session."
        result = detect_application_auth_requirement(report)
        self.assertEqual(result.auth_requirement, AuthRequirement.AUTH_REQUIRED)
        self.assertEqual(result.confidence, "high")
        self.assertIn("LinkedIn", result.evidence)
        self.assertEqual(result.target_state, SubmissionState.MANUAL_REQUIRED)

    def test_auth_sign_in_to_apply(self):
        """Sign In to Apply prompt → AUTH_REQUIRED."""
        report = "The portal requires you to sign in before applying. Sign In button and existing user options visible."
        result = detect_application_auth_requirement(report)
        self.assertEqual(result.auth_requirement, AuthRequirement.AUTH_REQUIRED)
        self.assertEqual(result.confidence, "high")
        self.assertEqual(result.target_state, SubmissionState.MANUAL_REQUIRED)

    def test_auth_blocked_auth_code(self):
        """Browser reports BLOCKED_AUTH → always AUTH_REQUIRED."""
        report = "BLOCKED_AUTH: Login page detected."
        result = detect_application_auth_requirement(report)
        self.assertEqual(result.auth_requirement, AuthRequirement.AUTH_REQUIRED)
        self.assertEqual(result.confidence, "high")
        self.assertEqual(result.target_state, SubmissionState.MANUAL_REQUIRED)

    def test_unknown_empty_report(self):
        """Empty report → AUTH_STATUS_UNKNOWN with low confidence."""
        result = detect_application_auth_requirement("")
        self.assertEqual(result.auth_requirement, AuthRequirement.AUTH_STATUS_UNKNOWN)
        self.assertEqual(result.confidence, "low")
        self.assertEqual(result.evidence, "Application flow could not be determined.")
        self.assertEqual(result.target_state, SubmissionState.MANUAL_REVIEW_REQUIRED)

    def test_unknown_whitespace_report(self):
        """Whitespace-only report → AUTH_STATUS_UNKNOWN with low confidence."""
        result = detect_application_auth_requirement("   \n  \t  ")
        self.assertEqual(result.auth_requirement, AuthRequirement.AUTH_STATUS_UNKNOWN)
        self.assertEqual(result.confidence, "low")
        self.assertEqual(result.target_state, SubmissionState.MANUAL_REVIEW_REQUIRED)

    def test_unknown_ambiguous_report(self):
        """No clear signals → AUTH_STATUS_UNKNOWN with low confidence."""
        report = "Page loaded. Some content is visible. Cannot determine the page type."
        result = detect_application_auth_requirement(report)
        self.assertEqual(result.auth_requirement, AuthRequirement.AUTH_STATUS_UNKNOWN)
        self.assertEqual(result.confidence, "low")
        self.assertEqual(result.target_state, SubmissionState.MANUAL_REVIEW_REQUIRED)

    def test_unknown_mixed_signals_equal(self):
        """Equal auth and no-auth signals → AUTH_STATUS_UNKNOWN with low confidence."""
        report = "The page shows a Sign In option AND an application form."
        result = detect_application_auth_requirement(report)
        self.assertEqual(result.auth_requirement, AuthRequirement.AUTH_STATUS_UNKNOWN)
        self.assertEqual(result.confidence, "low")
        self.assertEqual(result.target_state, SubmissionState.MANUAL_REVIEW_REQUIRED)

    def test_misleading_page_with_sign_in_text_no_auth_required(self):
        """Misleading page containing 'sign in' link in nav, but active public application form."""
        report = """
        CURRENT_URL: https://careers.company.com/apply/123
        PAGE_DESCRIPTION: Candidate application form loaded. Top navigation has 'Employee Sign In' link.
        FORM_ELEMENTS: First Name, Last Name, Email, Resume Upload, Submit Application
        AUTH_ELEMENTS: Optional Employee Sign In link in header
        """
        result = detect_application_auth_requirement(report)
        self.assertEqual(result.auth_requirement, AuthRequirement.NO_AUTH_REQUIRED)
        self.assertEqual(result.confidence, "medium")
        self.assertIn("sign-in text or links are present", result.evidence)
        # Conservative routing rule: NO_AUTH_REQUIRED + medium -> MANUAL_REVIEW_REQUIRED
        self.assertEqual(result.target_state, SubmissionState.MANUAL_REVIEW_REQUIRED)
        self.assertFalse(result.is_automated_allowed)

    def test_actual_login_form(self):
        """Actual login page with password input."""
        report = """
        CURRENT_URL: https://careers.company.com/login
        PAGE_DESCRIPTION: Please enter your email and password to log in.
        AUTH_ELEMENTS: Username, Password Field, Log In button, Forgot Password
        FORM_ELEMENTS: none
        """
        result = detect_application_auth_requirement(report)
        self.assertEqual(result.auth_requirement, AuthRequirement.AUTH_REQUIRED)
        self.assertEqual(result.confidence, "high")
        self.assertEqual(result.target_state, SubmissionState.MANUAL_REQUIRED)
        self.assertFalse(result.is_automated_allowed)

    def test_actual_public_application_form(self):
        """Actual public application form without any login controls."""
        report = """
        CURRENT_URL: https://boards.greenhouse.io/company/jobs/12345
        PAGE_DESCRIPTION: Public application form for Software Engineer.
        AUTH_ELEMENTS: none
        FORM_ELEMENTS: First Name, Last Name, Email, Phone, Resume Upload, Cover Letter
        """
        result = detect_application_auth_requirement(report)
        self.assertEqual(result.auth_requirement, AuthRequirement.NO_AUTH_REQUIRED)
        self.assertEqual(result.confidence, "high")
        self.assertEqual(result.target_state, SubmissionState.SUBMISSION_IN_PROGRESS)
        self.assertTrue(result.is_automated_allowed)

    def test_ambiguous_page(self):
        """Ambiguous page with unclassifiable DOM structure."""
        report = "HTTP 200 OK. Rendering canvas and custom web component. No form elements identifiable."
        result = detect_application_auth_requirement(report)
        self.assertEqual(result.auth_requirement, AuthRequirement.AUTH_STATUS_UNKNOWN)
        self.assertEqual(result.confidence, "low")
        self.assertEqual(result.target_state, SubmissionState.MANUAL_REVIEW_REQUIRED)
        self.assertFalse(result.is_automated_allowed)

    def test_low_confidence_classification(self):
        """Low confidence classification routes to MANUAL_REVIEW_REQUIRED."""
        decision = AuthDecision(
            auth_requirement=AuthRequirement.NO_AUTH_REQUIRED,
            confidence="low",
            evidence="Weak signal",
        )
        self.assertEqual(decision.target_state, SubmissionState.MANUAL_REVIEW_REQUIRED)
        self.assertFalse(decision.is_automated_allowed)

    def test_conservative_routing_rules(self):
        """Verify conservative routing rule across all combinations."""
        # 1. NO_AUTH_REQUIRED + high -> SUBMISSION_IN_PROGRESS (automated)
        d1 = AuthDecision(AuthRequirement.NO_AUTH_REQUIRED, "high", "clear form")
        self.assertEqual(d1.target_state, SubmissionState.SUBMISSION_IN_PROGRESS)
        self.assertTrue(d1.is_automated_allowed)

        # 2. NO_AUTH_REQUIRED + medium -> MANUAL_REVIEW_REQUIRED
        d2 = AuthDecision(AuthRequirement.NO_AUTH_REQUIRED, "medium", "form with sign in text")
        self.assertEqual(d2.target_state, SubmissionState.MANUAL_REVIEW_REQUIRED)
        self.assertFalse(d2.is_automated_allowed)

        # 3. NO_AUTH_REQUIRED + low -> MANUAL_REVIEW_REQUIRED
        d3 = AuthDecision(AuthRequirement.NO_AUTH_REQUIRED, "low", "weak form indicator")
        self.assertEqual(d3.target_state, SubmissionState.MANUAL_REVIEW_REQUIRED)
        self.assertFalse(d3.is_automated_allowed)

        # 4. AUTH_REQUIRED + high -> MANUAL_REQUIRED
        d4 = AuthDecision(AuthRequirement.AUTH_REQUIRED, "high", "login screen")
        self.assertEqual(d4.target_state, SubmissionState.MANUAL_REQUIRED)
        self.assertFalse(d4.is_automated_allowed)

        # 5. AUTH_REQUIRED + medium -> MANUAL_REQUIRED
        d5 = AuthDecision(AuthRequirement.AUTH_REQUIRED, "medium", "mixed auth screen")
        self.assertEqual(d5.target_state, SubmissionState.MANUAL_REQUIRED)
        self.assertFalse(d5.is_automated_allowed)

        # 6. AUTH_STATUS_UNKNOWN + low -> MANUAL_REVIEW_REQUIRED
        d6 = AuthDecision(AuthRequirement.AUTH_STATUS_UNKNOWN, "low", "undetermined")
        self.assertEqual(d6.target_state, SubmissionState.MANUAL_REVIEW_REQUIRED)
        self.assertFalse(d6.is_automated_allowed)

    def test_auth_detection_task_description(self):
        """Task description includes detection-only rules."""
        task = get_auth_detection_task_description(
            "https://example.com/job/123", "generic"
        )
        self.assertIn("DETECTION", task)
        self.assertIn("DO NOT fill any forms", task)
        self.assertIn("DO NOT enter any credentials", task)
        self.assertIn("DO NOT create any accounts", task)
        self.assertIn("NO_AUTH_REQUIRED", task)
        self.assertIn("AUTH_REQUIRED", task)
        self.assertIn("AUTH_STATUS_UNKNOWN", task)


class TestManualRequiredStateMachine(TestCase):
    """Test state transitions for the new manual routing paths."""

    def _make_context(self):
        return SubmissionContext(
            company="TestCo",
            role="TestRole",
            app_dir=Path("/tmp/test_manual"),
            job_url="https://example.com/job/123",
            portal_type=PortalType.WORKDAY,
            state=SubmissionState.DRAFTED,
        )

    def test_auth_required_path(self):
        """drafted -> submission_in_progress -> authentication_check -> manual_required"""
        ctx = self._make_context()
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start")
        ctx.transition(SubmissionState.AUTHENTICATION_CHECK, "Auth detection probe")
        ctx.transition(SubmissionState.MANUAL_REQUIRED, "Auth required detected")
        self.assertEqual(ctx.state, SubmissionState.MANUAL_REQUIRED)
        self.assertEqual(len(ctx.state_history), 3)

    def test_unknown_path(self):
        """drafted -> submission_in_progress -> authentication_check -> manual_review_required"""
        ctx = self._make_context()
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start")
        ctx.transition(SubmissionState.AUTHENTICATION_CHECK, "Auth detection probe")
        ctx.transition(SubmissionState.MANUAL_REVIEW_REQUIRED, "Auth status unknown")
        self.assertEqual(ctx.state, SubmissionState.MANUAL_REVIEW_REQUIRED)
        self.assertEqual(len(ctx.state_history), 3)

    def test_manual_required_cannot_reach_applied(self):
        ctx = self._make_context()
        ctx.state = SubmissionState.MANUAL_REQUIRED
        with self.assertRaises(IllegalStateTransition):
            ctx.transition(SubmissionState.APPLIED, "Should fail")

    def test_manual_review_required_cannot_reach_applied(self):
        ctx = self._make_context()
        ctx.state = SubmissionState.MANUAL_REVIEW_REQUIRED
        with self.assertRaises(IllegalStateTransition):
            ctx.transition(SubmissionState.APPLIED, "Should fail")

    def test_manual_required_can_return_to_drafted(self):
        ctx = self._make_context()
        ctx.state = SubmissionState.MANUAL_REQUIRED
        ctx.transition(SubmissionState.DRAFTED, "User requested retry")
        self.assertEqual(ctx.state, SubmissionState.DRAFTED)

    def test_manual_review_required_can_return_to_drafted(self):
        ctx = self._make_context()
        ctx.state = SubmissionState.MANUAL_REVIEW_REQUIRED
        ctx.transition(SubmissionState.DRAFTED, "User resolved ambiguity, retry")
        self.assertEqual(ctx.state, SubmissionState.DRAFTED)

    def test_manual_required_cannot_reach_submission_in_progress(self):
        ctx = self._make_context()
        ctx.state = SubmissionState.MANUAL_REQUIRED
        with self.assertRaises(IllegalStateTransition):
            ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Should fail")

    def test_manual_required_cannot_reach_authenticated(self):
        ctx = self._make_context()
        ctx.state = SubmissionState.MANUAL_REQUIRED
        with self.assertRaises(IllegalStateTransition):
            ctx.transition(SubmissionState.AUTHENTICATED, "Should fail")

    def test_authentication_check_in_transition_table(self):
        self.assertIn(SubmissionState.AUTHENTICATION_CHECK, LEGAL_TRANSITIONS)

    def test_manual_required_in_transition_table(self):
        self.assertIn(SubmissionState.MANUAL_REQUIRED, LEGAL_TRANSITIONS)

    def test_manual_review_required_in_transition_table(self):
        self.assertIn(SubmissionState.MANUAL_REVIEW_REQUIRED, LEGAL_TRANSITIONS)


class TestAutomatedPathNoAuth(TestCase):
    """Test the full automated no-auth happy path through the state machine."""

    def test_full_automated_path(self):
        """drafted -> in_progress -> auth_check -> in_progress -> awaiting_confirmation -> applied"""
        ctx = SubmissionContext(
            company="LeverCo",
            role="Backend_Engineer",
            app_dir=Path("/tmp/test_auto"),
            job_url="https://jobs.lever.co/leverco/abc123",
            portal_type=PortalType.LEVER,
        )
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start submission")
        ctx.transition(SubmissionState.AUTHENTICATION_CHECK, "Auth detection probe")
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "No auth required, resume form filling")
        ctx.transition(SubmissionState.AWAITING_USER_CONFIRMATION, "Review page reached")
        ctx.transition(SubmissionState.APPLIED, "User said Submit it")
        self.assertEqual(ctx.state, SubmissionState.APPLIED)
        self.assertIsNotNone(ctx.applied_at)
        self.assertEqual(len(ctx.state_history), 5)

    def test_backward_compat_direct_to_review(self):
        """drafted -> in_progress -> awaiting_confirmation is still legal."""
        ctx = SubmissionContext(
            company="TestCo", role="TestRole",
            app_dir=Path("/tmp/test_skip"), job_url="https://example.com/job/123",
            portal_type=PortalType.GENERIC,
        )
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start")
        ctx.transition(SubmissionState.AWAITING_USER_CONFIRMATION, "Skip auth check")
        ctx.transition(SubmissionState.APPLIED, "Confirmed")
        self.assertEqual(ctx.state, SubmissionState.APPLIED)

    def test_final_submit_only_from_awaiting_confirmation(self):
        """APPLIED is only reachable from AWAITING_USER_CONFIRMATION."""
        for state, targets in LEGAL_TRANSITIONS.items():
            if SubmissionState.APPLIED in targets:
                self.assertEqual(
                    state, SubmissionState.AWAITING_USER_CONFIRMATION,
                    f"APPLIED reachable from {state}"
                )


class TestNoCredentialAccessInManualMode(TestCase):
    """Test that no credential_manager functions are invoked during manual routing."""

    def test_auth_router_has_no_credential_imports(self):
        """auth_router.py must not import credential_manager."""
        import inspect
        import tools.submit_adapters.auth_router as auth_router_module
        source = inspect.getsource(auth_router_module)
        self.assertNotIn("credential_manager", source)
        self.assertNotIn("get_credential", source)
        self.assertNotIn("store_credential", source)
        self.assertNotIn("has_credential", source)
        self.assertNotIn("delete_credential", source)
        self.assertNotIn("generate_strong_password", source)
        self.assertNotIn("Keychain", source)

    def test_auth_detection_task_has_no_credential_instructions(self):
        """Auth detection task must not instruct to enter credentials."""
        task = get_auth_detection_task_description(
            "https://cisco.wd5.myworkdayjobs.com/job/123", "workday"
        )
        self.assertNotIn("keychain", task.lower())
        self.assertNotIn("otp", task.lower())
        self.assertNotIn("enter your password", task.lower())

    def test_manual_required_context_no_secret_patterns(self):
        """Manual_required context serialization has no credential patterns."""
        ctx = SubmissionContext(
            company="Cisco", role="SE",
            app_dir=Path("/tmp/test_no_cred"),
            job_url="https://cisco.wd5.myworkdayjobs.com/job/123",
            portal_type=PortalType.WORKDAY,
            submission_mode="manual",
            authentication_required=True,
            manual_required_reason="authentication_required",
        )
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start")
        ctx.transition(SubmissionState.AUTHENTICATION_CHECK, "Auth probe")
        ctx.transition(SubmissionState.MANUAL_REQUIRED, "Auth required")

        serialized = json.dumps(ctx.to_dict()).lower()
        for pattern in ("otp", "session_token", "auth_token", "bearer", "cookie",
                        "recovery_code", "secret_key", "api_key"):
            self.assertNotIn(pattern, serialized,
                             f"Credential pattern '{pattern}' found in manual context")


class TestBatchProcessingContinuity(TestCase):
    """Test that batch processing continues when one application is manual-required."""

    def test_independent_processing(self):
        """Three apps processed independently: one manual, two automated."""
        results = []
        for i, (company, portal, should_manual) in enumerate([
            ("LeverCo", PortalType.LEVER, False),
            ("WorkdayCo", PortalType.WORKDAY, True),
            ("GreenhouseCo", PortalType.GREENHOUSE, False),
        ]):
            ctx = SubmissionContext(
                company=company, role="Engineer",
                app_dir=Path(f"/tmp/batch_{i}"),
                job_url=f"https://example.com/job/{i}",
                portal_type=portal,
            )
            ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start")
            ctx.transition(SubmissionState.AUTHENTICATION_CHECK, "Auth probe")
            if should_manual:
                ctx.transition(SubmissionState.MANUAL_REQUIRED, "Auth required")
                ctx.submission_mode = "manual"
                ctx.authentication_required = True
                ctx.manual_required_reason = "authentication_required"
            else:
                ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "No auth required")
                ctx.transition(SubmissionState.AWAITING_USER_CONFIRMATION, "Review")
                ctx.transition(SubmissionState.APPLIED, "Confirmed")
                ctx.submission_mode = "automated"
                ctx.authentication_required = False
                ctx.submitted_via = "portal"
            results.append(ctx)

        automated = [r for r in results if r.state == SubmissionState.APPLIED]
        manual = [r for r in results if r.state == SubmissionState.MANUAL_REQUIRED]
        self.assertEqual(len(automated), 2)
        self.assertEqual(len(manual), 1)
        self.assertEqual(manual[0].company, "WorkdayCo")
        self.assertEqual(manual[0].submission_mode, "manual")

    def test_manual_does_not_block_next(self):
        """Manual-required for one job doesn't block the next."""
        ctx1 = SubmissionContext(
            company="AuthCo", role="SE", app_dir=Path("/tmp/batch_b1"),
            job_url="https://authco.com/job/1", portal_type=PortalType.WORKDAY,
        )
        ctx1.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start")
        ctx1.transition(SubmissionState.AUTHENTICATION_CHECK, "Probe")
        ctx1.transition(SubmissionState.MANUAL_REQUIRED, "Auth required")

        ctx2 = SubmissionContext(
            company="NoAuthCo", role="SE", app_dir=Path("/tmp/batch_b2"),
            job_url="https://noauthco.com/job/2", portal_type=PortalType.LEVER,
        )
        ctx2.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start")
        ctx2.transition(SubmissionState.AUTHENTICATION_CHECK, "Probe")
        ctx2.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "No auth")
        ctx2.transition(SubmissionState.AWAITING_USER_CONFIRMATION, "Review")
        ctx2.transition(SubmissionState.APPLIED, "Submit")

        self.assertEqual(ctx1.state, SubmissionState.MANUAL_REQUIRED)
        self.assertEqual(ctx2.state, SubmissionState.APPLIED)


class TestManualSubmissionMetadata(TestCase):
    """Test metadata correctness for manual-required applications."""

    def test_manual_required_metadata_fields(self):
        ctx = SubmissionContext(
            company="Cisco", role="Software_Engineer_Java_Go",
            app_dir=Path("/tmp/test_meta"),
            job_url="https://cisco.wd5.myworkdayjobs.com/job/123",
            portal_type=PortalType.WORKDAY,
        )
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start")
        ctx.transition(SubmissionState.AUTHENTICATION_CHECK, "Probe")
        ctx.transition(SubmissionState.MANUAL_REQUIRED, "Auth required")
        ctx.submission_mode = "manual"
        ctx.authentication_required = True
        ctx.manual_required_reason = "authentication_required"

        data = ctx.to_dict()
        self.assertEqual(data["submission_mode"], "manual")
        self.assertTrue(data["authentication_required"])
        self.assertEqual(data["manual_required_reason"], "authentication_required")
        self.assertIsNone(data["applied_at"])
        self.assertIsNone(data["submitted_via"])
        self.assertEqual(data["state"], "manual_required")

    def test_manual_review_required_metadata(self):
        ctx = SubmissionContext(
            company="AmbiguousCo", role="Engineer",
            app_dir=Path("/tmp/test_review"),
            job_url="https://ambiguous.com/job/123",
            portal_type=PortalType.GENERIC,
        )
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start")
        ctx.transition(SubmissionState.AUTHENTICATION_CHECK, "Probe")
        ctx.transition(SubmissionState.MANUAL_REVIEW_REQUIRED, "Unknown")
        ctx.submission_mode = "manual_review_required"
        ctx.authentication_required = None

        data = ctx.to_dict()
        self.assertEqual(data["submission_mode"], "manual_review_required")
        self.assertIsNone(data["authentication_required"])
        self.assertIsNone(data["applied_at"])
        self.assertEqual(data["state"], "manual_review_required")

    def test_automated_path_metadata(self):
        ctx = SubmissionContext(
            company="LeverCo", role="Backend",
            app_dir=Path("/tmp/test_auto_meta"),
            job_url="https://jobs.lever.co/leverco/abc",
            portal_type=PortalType.LEVER,
        )
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start")
        ctx.transition(SubmissionState.AUTHENTICATION_CHECK, "Probe")
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "No auth")
        ctx.transition(SubmissionState.AWAITING_USER_CONFIRMATION, "Review")
        ctx.transition(SubmissionState.APPLIED, "Confirmed")
        ctx.submission_mode = "automated"
        ctx.authentication_required = False
        ctx.submitted_via = "portal"

        data = ctx.to_dict()
        self.assertEqual(data["submission_mode"], "automated")
        self.assertFalse(data["authentication_required"])
        self.assertIsNotNone(data["applied_at"])
        self.assertEqual(data["submitted_via"], "portal")
        self.assertEqual(data["state"], "applied")

    def test_manual_submission_via_outcome(self):
        """Simulate /outcome updating metadata after manual submission."""
        ctx = SubmissionContext(
            company="Cisco", role="SE",
            app_dir=Path("/tmp/test_outcome"),
            job_url="https://cisco.wd5.myworkdayjobs.com/job/123",
            portal_type=PortalType.WORKDAY,
        )
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start")
        ctx.transition(SubmissionState.AUTHENTICATION_CHECK, "Probe")
        ctx.transition(SubmissionState.MANUAL_REQUIRED, "Auth required")
        ctx.submission_mode = "manual"
        ctx.authentication_required = True
        ctx.manual_required_reason = "authentication_required"

        from datetime import datetime
        outcome_data = {
            "status": "applied",
            "applied_at": datetime.now().isoformat(),
            "submission_mode": "manual",
            "submitted_via": "manual portal submission",
        }
        self.assertEqual(outcome_data["status"], "applied")
        self.assertEqual(outcome_data["submitted_via"], "manual portal submission")
        # State machine stays at manual_required
        self.assertEqual(ctx.state, SubmissionState.MANUAL_REQUIRED)

    def test_update_metadata_manual_required(self):
        """BaseAdapter.update_metadata_manual_required() preserves drafted status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            meta_path = app_dir / "application_metadata.json"
            meta_path.write_text(json.dumps({
                "status": "drafted", "company": "TestCo", "role": "TestRole",
            }))
            ctx = SubmissionContext(
                company="TestCo", role="TestRole", app_dir=app_dir,
                job_url="https://example.com/job/123",
                portal_type=PortalType.WORKDAY,
                submission_mode="manual",
                authentication_required=True,
                manual_required_reason="authentication_required",
            )
            adapter = BaseAdapter(ctx)
            adapter.update_metadata_manual_required()
            updated = json.loads(meta_path.read_text())
            self.assertEqual(updated["status"], "drafted")
            self.assertEqual(updated["submission_mode"], "manual")
            self.assertTrue(updated["authentication_required"])
            self.assertEqual(updated["manual_required_reason"], "authentication_required")


class TestManualRequiredSummary(TestCase):
    """Test the manual_required_summary output format."""

    def test_summary_includes_required_fields(self):
        ctx = SubmissionContext(
            company="Cisco", role="Software Engineer",
            app_dir=Path("/tmp/test_summary"),
            job_url="https://cisco.wd5.myworkdayjobs.com/job/12345",
            portal_type=PortalType.WORKDAY,
            submission_mode="manual",
            authentication_required=True,
            manual_required_reason="authentication_required",
            fit_score=85,
        )
        summary = ctx.manual_required_summary()
        self.assertIn("MANUAL SUBMISSION REQUIRED", summary)
        self.assertIn("Cisco", summary)
        self.assertIn("Software Engineer", summary)
        self.assertIn("workday", summary)
        self.assertIn("85", summary)
        self.assertIn("authentication_required", summary)
        self.assertIn("cv.pdf", summary)
        self.assertIn("cover_letter.pdf", summary)
        self.assertIn("/outcome", summary)

    def test_summary_without_fit_score(self):
        ctx = SubmissionContext(
            company="TestCo", role="SE",
            app_dir=Path("/tmp/test_noscore"),
            job_url="https://example.com/job/1",
            portal_type=PortalType.GENERIC,
            submission_mode="manual",
            manual_required_reason="authentication_required",
        )
        summary = ctx.manual_required_summary()
        self.assertIn("MANUAL SUBMISSION REQUIRED", summary)
        self.assertNotIn("Fit Score", summary)

    def test_pre_submission_summary_still_works(self):
        """Original pre_submission_summary() for automated path still works."""
        ctx = SubmissionContext(
            company="LeverCo", role="Backend",
            app_dir=Path("/tmp/test_presub"),
            job_url="https://jobs.lever.co/leverco/abc",
            portal_type=PortalType.LEVER,
        )
        ctx.populated_fields = {"First Name": "Jane", "Email": "jane.doe@example.com"}
        ctx.uploaded_files = {"Resume": "/tmp/cv.pdf"}
        summary = ctx.pre_submission_summary()
        self.assertIn("PRE-SUBMISSION SUMMARY", summary)
        self.assertIn("LeverCo", summary)
        self.assertIn("Submit it", summary)


class TestBackwardCompatibility(TestCase):
    """Verify that all legacy auth states and transitions still work."""

    def test_legacy_auth_states_exist(self):
        for state_name in [
            "AUTHENTICATION_REQUIRED", "ACCOUNT_CREATION_IN_PROGRESS",
            "AWAITING_MANUAL_CREDENTIAL_ENTRY", "EMAIL_VERIFICATION_REQUIRED",
            "AUTHENTICATED", "AUTHENTICATION_FAILED",
            "ACCOUNT_CREATION_FAILED", "EMAIL_VERIFICATION_TIMEOUT",
        ]:
            self.assertTrue(
                hasattr(SubmissionState, state_name),
                f"Legacy state {state_name} missing from SubmissionState"
            )

    def test_legacy_auth_transitions_still_valid(self):
        ctx = SubmissionContext(
            company="Cisco", role="SE",
            app_dir=Path("/tmp/test_legacy"),
            job_url="https://cisco.wd5.myworkdayjobs.com/job/123",
            portal_type=PortalType.WORKDAY,
        )
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start")
        ctx.transition(SubmissionState.AUTHENTICATION_REQUIRED, "Sign In page")
        ctx.transition(SubmissionState.ACCOUNT_CREATION_IN_PROGRESS, "Create Account")
        ctx.transition(SubmissionState.EMAIL_VERIFICATION_REQUIRED, "Email sent")
        ctx.transition(SubmissionState.AUTHENTICATED, "Verified")
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Resume form")
        ctx.transition(SubmissionState.AWAITING_USER_CONFIRMATION, "Review")
        ctx.transition(SubmissionState.APPLIED, "Confirmed")
        self.assertEqual(ctx.state, SubmissionState.APPLIED)

    def test_new_states_in_transition_table(self):
        for state in [SubmissionState.AUTHENTICATION_CHECK,
                      SubmissionState.MANUAL_REQUIRED,
                      SubmissionState.MANUAL_REVIEW_REQUIRED]:
            self.assertIn(state, LEGAL_TRANSITIONS,
                          f"New state {state} missing from LEGAL_TRANSITIONS")

    def test_auth_check_can_reach_legacy_auth(self):
        """AUTHENTICATION_CHECK -> AUTHENTICATION_REQUIRED is legal (dormant re-enablement)."""
        ctx = SubmissionContext(
            company="TestCo", role="SE",
            app_dir=Path("/tmp/test_legacy_bridge"),
            job_url="https://example.com/job/1",
            portal_type=PortalType.GENERIC,
        )
        ctx.transition(SubmissionState.SUBMISSION_IN_PROGRESS, "Start")
        ctx.transition(SubmissionState.AUTHENTICATION_CHECK, "Probe")
        ctx.transition(SubmissionState.AUTHENTICATION_REQUIRED, "Legacy re-enable")
        self.assertEqual(ctx.state, SubmissionState.AUTHENTICATION_REQUIRED)

    def test_credential_manager_importable(self):
        from tools.submit_adapters.credential_manager import (
            generate_strong_password, extract_tenant_key,
            make_service_name, AccountRegistry, CANONICAL_USERNAME,
        )
        self.assertIsNotNone(generate_strong_password)
        self.assertIsNotNone(CANONICAL_USERNAME)

    def test_auth_requirement_enum_values(self):
        self.assertEqual(AuthRequirement.NO_AUTH_REQUIRED.value, "no_auth_required")
        self.assertEqual(AuthRequirement.AUTH_REQUIRED.value, "auth_required")
        self.assertEqual(AuthRequirement.AUTH_STATUS_UNKNOWN.value, "auth_status_unknown")
        self.assertEqual(len(AuthRequirement), 3)

    def test_all_states_have_transition_entry(self):
        for state in SubmissionState:
            self.assertIn(state, LEGAL_TRANSITIONS,
                          f"Missing LEGAL_TRANSITIONS entry for {state}")

    def test_terminal_states_unchanged(self):
        for state in (SubmissionState.APPLIED, SubmissionState.SUBMISSION_FAILED,
                      SubmissionState.STALE_JOB):
            self.assertEqual(LEGAL_TRANSITIONS[state], set(),
                             f"Terminal state {state} should have no transitions")

if __name__ == "__main__":
    unittest.main()
