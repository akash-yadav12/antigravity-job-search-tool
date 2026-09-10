"""
Cryptographically secure credential manager and non-secret account registry
for portal authentication and account creation in the /submit workflow.

SECURITY INVARIANTS:
1. Passwords are stored ONLY in the native macOS Keychain (/usr/bin/security).
2. Passwords, OTPs, session tokens, and secrets are NEVER persisted to disk,
   repository files, JSON, Markdown, logs, state files, or command outputs.
3. Every portal tenant receives a unique, cryptographically generated password.
4. Plaintext passwords are NEVER printed or embedded in task descriptions.
5. All exceptions and error messages redact sensitive strings.
"""

from __future__ import annotations

import json
import re
import secrets
import string
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Default paths
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY_PATH = WORKSPACE_ROOT / "tools" / "submit_adapters" / "account_registry.json"

# Non-secret candidate identifier
try:
    from tools.profile_loader import get_identity_fact
    CANONICAL_USERNAME = get_identity_fact("email", "candidate@example.com")
except Exception:
    CANONICAL_USERNAME = "candidate@example.com"

# Sensitive patterns that must NEVER appear in registry or serialized state
SECRET_PATTERNS = frozenset(
    {
        "password",
        "passwd",
        "otp",
        "one-time",
        "session_token",
        "auth_token",
        "bearer",
        "cookie",
        "recovery_code",
        "secret_key",
        "api_key",
        "private_key",
    }
)

# Character sets for strong password generation
PASSWORD_UPPER = string.ascii_uppercase
PASSWORD_LOWER = string.ascii_lowercase
PASSWORD_DIGITS = string.digits
PASSWORD_SYMBOLS = "!@#$%^&*()_+-=[]{}|;:,.<>?"
PASSWORD_ALL = PASSWORD_UPPER + PASSWORD_LOWER + PASSWORD_DIGITS + PASSWORD_SYMBOLS


def generate_strong_password(length: int = 24) -> str:
    """Generate a cryptographically secure, unique strong password.

    Guarantees:
    - Minimum length of 24 characters (or specified length >= 16)
    - At least 3 uppercase letters
    - At least 3 lowercase letters
    - At least 3 digits
    - At least 3 special characters
    - Cryptographically secure randomness via the secrets module
    - No deterministic or shared default patterns
    """
    if length < 16:
        length = 16

    # Ensure required composition
    required = [
        secrets.choice(PASSWORD_UPPER) for _ in range(3)
    ] + [
        secrets.choice(PASSWORD_LOWER) for _ in range(3)
    ] + [
        secrets.choice(PASSWORD_DIGITS) for _ in range(3)
    ] + [
        secrets.choice(PASSWORD_SYMBOLS) for _ in range(3)
    ]

    # Fill remainder with random choices from full set
    remaining_length = length - len(required)
    remaining = [secrets.choice(PASSWORD_ALL) for _ in range(remaining_length)]

    combined = required + remaining
    # Cryptographically secure in-place shuffle
    for i in range(len(combined) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        combined[i], combined[j] = combined[j], combined[i]

    return "".join(combined)


def extract_tenant_key(portal_type: str, url: str) -> str:
    """Extract a canonical tenant key from a job application URL.

    Examples:
    - Workday: "https://cisco.wd5.myworkdayjobs.com/..." -> "cisco.wd5.myworkdayjobs.com"
    - Lever: "https://jobs.lever.co/company/..." -> "lever.co:company"
    - SmartRecruiters: "https://jobs.smartrecruiters.com/Company/..." -> "smartrecruiters.com:company"
    - Greenhouse: "https://boards.greenhouse.io/company/..." -> "greenhouse.io:company"
    - Generic: hostname
    """
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]

    portal = portal_type.lower()
    if portal == "workday" or "myworkdayjobs.com" in hostname or "myworkdaysite.com" in hostname:
        return hostname or "unknown.workday"

    if "lever.co" in hostname and path_parts:
        return f"lever.co:{path_parts[0].lower()}"

    if "smartrecruiters.com" in hostname and path_parts:
        return f"smartrecruiters.com:{path_parts[0].lower()}"

    if "greenhouse.io" in hostname and path_parts:
        return f"greenhouse.io:{path_parts[0].lower()}"

    return hostname or "unknown.tenant"


def make_service_name(portal_type: str, tenant_key: str) -> str:
    """Generate the deterministic macOS Keychain service name."""
    portal = portal_type.lower().strip()
    tenant = tenant_key.lower().strip()
    return f"ai-job-search:{portal}:{tenant}"


def store_credential(service_name: str, username: str, password: str) -> bool:
    """Store a password in the macOS Keychain via /usr/bin/security.

    Uses -U to update if the entry already exists.
    Redacts secrets from any exception or error output.
    """
    if not service_name or not username or not password:
        raise ValueError("service_name, username, and password must not be empty")

    cmd = [
        "/usr/bin/security",
        "add-generic-password",
        "-a",
        username,
        "-s",
        service_name,
        "-w",
        password,
        "-U",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return res.returncode == 0
    except Exception as e:
        # Redact any accidental credential leak in exception text
        safe_msg = re.sub(re.escape(password), "[REDACTED]", str(e))
        raise RuntimeError(f"Keychain storage failed: {safe_msg}") from None


def get_credential(service_name: str, username: str) -> str | None:
    """Retrieve a password from the macOS Keychain via /usr/bin/security.

    Returns the stripped password string if found, None otherwise.
    """
    if not service_name or not username:
        return None

    cmd = [
        "/usr/bin/security",
        "find-generic-password",
        "-a",
        username,
        "-s",
        service_name,
        "-w",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode == 0 and res.stdout:
            return res.stdout.rstrip("\r\n")
        return None
    except Exception:
        return None


def has_credential(service_name: str, username: str) -> bool:
    """Check if a credential exists in macOS Keychain without returning it."""
    return get_credential(service_name, username) is not None


def delete_credential(service_name: str, username: str) -> bool:
    """Delete a credential from the macOS Keychain."""
    if not service_name or not username:
        return False

    cmd = [
        "/usr/bin/security",
        "delete-generic-password",
        "-a",
        username,
        "-s",
        service_name,
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return res.returncode == 0
    except Exception:
        return False


class AccountRegistry:
    """Non-secret JSON registry tracking candidate portal accounts.

    STRICT INVARIANT: This registry NEVER stores passwords, OTPs, session
    cookies, or tokens. Any attempt to write secret-like keys or values
    triggers an immediate ValueError.
    """

    def __init__(self, registry_file: Path | None = None):
        self.registry_file = registry_file or REGISTRY_PATH
        self.data: dict[str, Any] = {"accounts": {}}
        self.load()

    def load(self) -> None:
        """Load registry from disk if it exists, otherwise initialize empty."""
        if self.registry_file.exists():
            try:
                raw = json.loads(self.registry_file.read_text())
                if isinstance(raw, dict) and "accounts" in raw:
                    self._validate_non_secret(raw)
                    self.data = raw
                else:
                    self.data = {"accounts": {}}
            except Exception:
                self.data = {"accounts": {}}
        else:
            self.data = {"accounts": {}}

    def get_account(self, registry_key: str) -> dict[str, Any] | None:
        """Look up an account by its unique registry key (e.g. workday:cisco.wd5.myworkdayjobs.com)."""
        return self.data.get("accounts", {}).get(registry_key)

    def register_account(
        self,
        portal: str,
        tenant: str,
        company: str,
        username: str = CANONICAL_USERNAME,
        account_exists: bool = False,
        creation_status: str = "pending",
        verification_status: str = "unverified",
        notes: str = "",
    ) -> dict[str, Any]:
        """Create or update a non-secret account record."""
        registry_key = f"{portal.lower()}:{tenant.lower()}"
        record = {
            "portal": portal.lower(),
            "tenant": tenant.lower(),
            "company": company,
            "username": username,
            "account_exists": bool(account_exists),
            "creation_status": creation_status,
            "verification_status": verification_status,
            "last_verified": datetime.now().isoformat(),
            "notes": notes,
        }
        self._validate_non_secret(record)
        self.data.setdefault("accounts", {})[registry_key] = record
        self.save()
        return record

    def update_status(
        self,
        registry_key: str,
        creation_status: str | None = None,
        verification_status: str | None = None,
        account_exists: bool | None = None,
        notes: str | None = None,
    ) -> dict[str, Any] | None:
        """Update statuses for an existing account record."""
        record = self.get_account(registry_key)
        if not record:
            return None

        if creation_status is not None:
            record["creation_status"] = creation_status
        if verification_status is not None:
            record["verification_status"] = verification_status
        if account_exists is not None:
            record["account_exists"] = bool(account_exists)
        if notes is not None:
            record["notes"] = notes

        record["last_verified"] = datetime.now().isoformat()
        self._validate_non_secret(record)
        self.save()
        return record

    def save(self) -> None:
        """Serialize and save the registry to disk, asserting non-secret content."""
        self._validate_non_secret(self.data)
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        self.registry_file.write_text(json.dumps(self.data, indent=2) + "\n")

    @staticmethod
    def _validate_non_secret(obj: Any) -> None:
        """Recursively scan an object and raise ValueError if any secret patterns are found."""
        if isinstance(obj, dict):
            for k, v in obj.items():
                k_lower = str(k).lower()
                for pattern in SECRET_PATTERNS:
                    if pattern in k_lower:
                        raise ValueError(f"Security violation: key '{k}' matches secret pattern '{pattern}'")
                AccountRegistry._validate_non_secret(v)
        elif isinstance(obj, list):
            for item in obj:
                AccountRegistry._validate_non_secret(item)
        elif isinstance(obj, str):
            str_lower = obj.lower()
            for pattern in SECRET_PATTERNS:
                if pattern in str_lower:
                    raise ValueError(f"Security violation: string value contains secret pattern '{pattern}'")
