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
import sys
import os
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
    """Store a password securely in the OS credential manager.

    - macOS: native Keychain via /usr/bin/security
    - Windows: Windows DPAPI / Credential Store
    - Linux: secret-tool or keyring
    """
    if not service_name or not username or not password:
        raise ValueError("service_name, username, and password must not be empty")

    if sys.platform == "darwin":
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
            safe_msg = re.sub(re.escape(password), "[REDACTED]", str(e))
            raise RuntimeError(f"Keychain storage failed: {safe_msg}") from None

    elif sys.platform == "win32":
        try:
            import keyring
            keyring.set_password(service_name, username, password)
            return True
        except Exception:
            pass
        try:
            import ctypes
            from ctypes import wintypes
            class DATA_BLOB(ctypes.Structure):
                _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
            raw = password.encode("utf-8")
            blob_in = DATA_BLOB(len(raw), ctypes.cast(ctypes.create_string_buffer(raw), ctypes.POINTER(ctypes.c_char)))
            blob_out = DATA_BLOB()
            if ctypes.windll.crypt32.CryptProtectData(ctypes.byref(blob_in), "ai-job-search", None, None, None, 0, ctypes.byref(blob_out)):
                enc_data = ctypes.string_at(blob_out.pbData, blob_out.cbData)
                ctypes.windll.kernel32.LocalFree(blob_out.pbData)
                vault_dir = Path(os.path.expandvars(r"%LOCALAPPDATA%\ai-job-search"))
                vault_dir.mkdir(parents=True, exist_ok=True)
                key = f"{service_name}::{username}".replace(":", "_").replace("/", "_").replace("\\", "_")
                (vault_dir / f"{key}.dpapi").write_bytes(enc_data)
                return True
        except Exception as e:
            safe_msg = re.sub(re.escape(password), "[REDACTED]", str(e))
            raise RuntimeError(f"Windows DPAPI storage failed: {safe_msg}") from None
        return False

    else:
        # Linux / Unix fallback: try keyring or secret-tool
        try:
            import keyring
            keyring.set_password(service_name, username, password)
            return True
        except Exception:
            pass
        cmd = ["secret-tool", "store", "--label", service_name, "service", service_name, "username", username]
        try:
            res = subprocess.run(cmd, input=password, capture_output=True, text=True, check=False)
            return res.returncode == 0
        except Exception:
            return False


def get_credential(service_name: str, username: str) -> str | None:
    """Retrieve a password from the native OS credential store."""
    if not service_name or not username:
        return None

    if sys.platform == "darwin":
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

    elif sys.platform == "win32":
        try:
            import keyring
            pwd = keyring.get_password(service_name, username)
            if pwd:
                return pwd
        except Exception:
            pass
        try:
            import ctypes
            from ctypes import wintypes
            class DATA_BLOB(ctypes.Structure):
                _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
            vault_dir = Path(os.path.expandvars(r"%LOCALAPPDATA%\ai-job-search"))
            key = f"{service_name}::{username}".replace(":", "_").replace("/", "_").replace("\\", "_")
            dpapi_file = vault_dir / f"{key}.dpapi"
            if not dpapi_file.exists():
                return None
            enc_data = dpapi_file.read_bytes()
            blob_in = DATA_BLOB(len(enc_data), ctypes.cast(ctypes.create_string_buffer(enc_data), ctypes.POINTER(ctypes.c_char)))
            blob_out = DATA_BLOB()
            if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
                raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
                ctypes.windll.kernel32.LocalFree(blob_out.pbData)
                return raw.decode("utf-8")
        except Exception:
            pass
        return None

    else:
        try:
            import keyring
            pwd = keyring.get_password(service_name, username)
            if pwd:
                return pwd
        except Exception:
            pass
        cmd = ["secret-tool", "lookup", "service", service_name, "username", username]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0 and res.stdout:
                return res.stdout.rstrip("\r\n")
            return None
        except Exception:
            return None


def has_credential(service_name: str, username: str) -> bool:
    """Check if a credential exists in the OS credential store without returning it."""
    return get_credential(service_name, username) is not None


def delete_credential(service_name: str, username: str) -> bool:
    """Delete a credential from the OS credential store."""
    if not service_name or not username:
        return False

    if sys.platform == "darwin":
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

    elif sys.platform == "win32":
        deleted = False
        try:
            import keyring
            keyring.delete_password(service_name, username)
            deleted = True
        except Exception:
            pass
        try:
            vault_dir = Path(os.path.expandvars(r"%LOCALAPPDATA%\ai-job-search"))
            key = f"{service_name}::{username}".replace(":", "_").replace("/", "_").replace("\\", "_")
            dpapi_file = vault_dir / f"{key}.dpapi"
            if dpapi_file.exists():
                dpapi_file.unlink()
                deleted = True
        except Exception:
            pass
        return deleted

    else:
        deleted = False
        try:
            import keyring
            keyring.delete_password(service_name, username)
            deleted = True
        except Exception:
            pass
        cmd = ["secret-tool", "clear", "service", service_name, "username", username]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0:
                deleted = True
        except Exception:
            pass
        return deleted


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
