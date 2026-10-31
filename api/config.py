"""Settings for the mock bank API. Defaults suit running on your machine against the Docker containers."""

import os

# --- Database (same variable names and defaults as data/seed/seed.py) ---
DB_HOST = os.environ.get("POSTGRES_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("POSTGRES_PORT", "5433"))
DB_NAME = os.environ.get("POSTGRES_DB", "banking_db")
DB_USER = os.environ.get("POSTGRES_USER", "banking_user")
DB_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "banking_pass")

# --- Who may call the API ---
# Entries are "label:role:key", separated by commas. The key identifies the caller and the
# role decides what they are. These defaults are for local development with synthetic data only.
VALID_ROLES = {"support_agent", "executive", "compliance_officer"}
_DEFAULT_KEYS = (
    "dev-agent:support_agent:dev-agent-key,"
    "dev-exec:executive:dev-exec-key,"
    "dev-compliance:compliance_officer:dev-compliance-key"
)


def _parse_api_keys(raw):
    entries = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        parts = item.split(":", 2)
        if len(parts) != 3 or not all(parts):
            raise ValueError(f"BANK_API_KEYS entry must look like label:role:key, got {item!r}")
        label, role, key = parts
        if role not in VALID_ROLES:
            raise ValueError(f"BANK_API_KEYS: unknown role {role!r}; expected one of {sorted(VALID_ROLES)}")
        entries.append((key, label, role))
    if not entries:
        raise ValueError("BANK_API_KEYS must contain at least one key")
    return entries


API_KEYS = _parse_api_keys(os.environ.get("BANK_API_KEYS", _DEFAULT_KEYS))

# --- Identity verification ---
TOKEN_SECRET = os.environ.get("BANK_API_SECRET", "dev-only-secret-change-me")  # signs verification tokens
TOKEN_TTL_SECONDS = int(os.environ.get("VERIFICATION_TTL_SECONDS", "900"))  # a verification lasts 15 minutes
MAX_FAILED_VERIFICATIONS = 3  # failed checks allowed before the customer is locked out
LOCKOUT_MINUTES = 15

# --- Limits ---
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "60"))  # per API key
DISPUTE_WINDOW_DAYS = 60  # matches the dispute policy document
DEFAULT_TRANSACTION_LIMIT = 10
MAX_TRANSACTION_LIMIT = 50
