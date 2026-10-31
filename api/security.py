"""
Authentication and verification.

Two checks stack on every account endpoint:
  1. X-API-Key         identifies the caller (and their role) and is rate limited.
  2. X-Verification-Token  proves the *customer* passed identity verification, and says which
                        customer. It is signed, expires, and only works for the API key it was issued to.
"""

import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader

from . import audit, config
from .errors import api_error

_api_key_header = APIKeyHeader(name="X-API-Key", scheme_name="ApiKey", auto_error=False, description="Identifies the calling service or staff member.")
_token_header = APIKeyHeader(
    name="X-Verification-Token",
    scheme_name="VerificationToken",
    auto_error=False,
    description="Issued by POST /v1/identity/verify after the customer's identity is confirmed.",
)


@dataclass(frozen=True)
class Caller:
    label: str
    role: str


@dataclass(frozen=True)
class Session:
    """An authenticated caller acting for one verified customer."""

    caller: Caller
    customer_id: int


class RateLimiter:
    """Sliding window: at most `limit` requests per `window` seconds for each key (in memory)."""

    def __init__(self, limit, window=60.0):
        self.limit = limit
        self.window = window
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key):
        """Returns 0 if the request is allowed, otherwise the seconds to wait before retrying."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(1, int(self.window - (now - hits[0])) + 1)
            hits.append(now)
            return 0

    def reset(self):
        with self._lock:
            self._hits.clear()


limiter = RateLimiter(config.RATE_LIMIT_PER_MINUTE)


def authenticate(api_key: Optional[str] = Depends(_api_key_header)) -> Caller:
    """Identify the caller from X-API-Key and apply the rate limit."""
    caller = None
    if api_key:
        for key, label, role in config.API_KEYS:  # compare against every key, in constant time
            if secrets.compare_digest(key.encode(), api_key.encode()):
                caller = Caller(label=label, role=role)
    if caller is None:
        audit.record(None, "authenticate", outcome="denied", detail="missing or invalid API key")
        raise api_error(401, "invalid_api_key", "A valid X-API-Key header is required.")

    retry_after = limiter.check(caller.label)
    if retry_after:
        audit.record(caller, "authenticate", outcome="denied", detail="rate limit exceeded")
        raise api_error(
            429,
            "rate_limited",
            f"Too many requests. Retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
            retry_after_seconds=retry_after,
        )
    return caller


# --- verification tokens: "<customer_id>.<expires_at>.<signature>" ---


def _sign(customer_id, expires_at, label):
    message = f"{customer_id}.{expires_at}.{label}".encode()
    return hmac.new(config.TOKEN_SECRET.encode(), message, hashlib.sha256).hexdigest()


def issue_token(customer_id, label):
    """Returns (token, expires_at_unix_seconds)."""
    expires_at = int(time.time()) + config.TOKEN_TTL_SECONDS
    return f"{customer_id}.{expires_at}.{_sign(customer_id, expires_at, label)}", expires_at


def read_token(token, label):
    """Returns (customer_id, None) if the token is good, or (None, 'invalid' | 'expired')."""
    try:
        customer_id_text, expires_text, signature = token.split(".")
        customer_id, expires_at = int(customer_id_text), int(expires_text)
    except ValueError:
        return None, "invalid"
    if not hmac.compare_digest(signature.encode(), _sign(customer_id, expires_at, label).encode()):
        return None, "invalid"
    if expires_at < time.time():
        return None, "expired"
    return customer_id, None


def require_verified(
    caller: Caller = Depends(authenticate),
    token: Optional[str] = Depends(_token_header),
) -> Session:
    """Dependency for every endpoint that touches a customer's data."""
    if not token:
        audit.record(caller, "verification.check", outcome="denied", detail="no verification token")
        raise api_error(
            401,
            "verification_required",
            "Customer identity must be verified first. Call POST /v1/identity/verify.",
        )
    customer_id, problem = read_token(token, caller.label)
    if problem:
        audit.record(caller, "verification.check", outcome="denied", detail=f"token {problem}")
        code = "verification_expired" if problem == "expired" else "verification_invalid"
        raise api_error(401, code, "The verification token is not valid. Verify the customer's identity again.")
    return Session(caller=caller, customer_id=customer_id)
