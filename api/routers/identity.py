"""Identity verification: the gate in front of every customer-specific endpoint."""

import secrets

from fastapi import APIRouter, Depends

from .. import audit, config, db
from ..errors import api_error
from ..schemas import VerifyRequest, VerifyResponse
from ..security import Caller, authenticate, issue_token

router = APIRouter(tags=["identity"])


def _recent_failures(cur, customer_id):
    """Failed checks in the lockout window that came after the last successful one."""
    cur.execute(
        """
        SELECT COUNT(*) AS failures FROM verification_attempts
        WHERE customer_id = %s AND success = false
          AND attempted_at > now() - make_interval(mins => %s)
          AND attempted_at > COALESCE(
                (SELECT MAX(attempted_at) FROM verification_attempts WHERE customer_id = %s AND success = true),
                'epoch'::timestamp)
        """,
        (customer_id, config.LOCKOUT_MINUTES, customer_id),
    )
    return cur.fetchone()["failures"]


def _record_attempt(customer_id, success):
    with db.short_transaction() as conn:  # saved even though the request may end in an error
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO verification_attempts (customer_id, success) VALUES (%s, %s)",
                (customer_id, success),
            )


def _locked():
    return api_error(
        423,
        "verification_locked",
        "Too many failed verification attempts. Hand this customer to a human representative.",
        escalate=True,
        lockout_minutes=config.LOCKOUT_MINUTES,
    )


@router.post("/identity/verify", response_model=VerifyResponse)
def verify_identity(
    body: VerifyRequest,
    caller: Caller = Depends(authenticate),
    conn=Depends(db.get_conn),
):
    """Check a customer's date of birth and last four SSN digits; on success, issue a short-lived token.

    A wrong answer and an unknown customer ID produce the *same* response, so the API never
    confirms whether a customer exists. Three failures lock the customer out for 15 minutes.
    """
    with conn.cursor() as cur:
        failures_before = _recent_failures(cur, body.customer_id)
        if failures_before >= config.MAX_FAILED_VERIFICATIONS:
            audit.record(caller, "identity.verify", "denied", body.customer_id, detail="locked out")
            raise _locked()
        cur.execute(
            "SELECT date_of_birth, last4_ssn FROM customers WHERE customer_id = %s",
            (body.customer_id,),
        )
        row = cur.fetchone()

    # Do the same comparisons even when the customer doesn't exist, so timing doesn't give it away.
    expected_dob = row["date_of_birth"] if row else None
    expected_last4 = row["last4_ssn"] if row else "0000"
    dob_matches = expected_dob == body.date_of_birth
    last4_matches = secrets.compare_digest(expected_last4.encode(), body.last4_ssn.encode())

    if row is None or not (dob_matches and last4_matches):
        _record_attempt(body.customer_id, success=False)
        audit.record(caller, "identity.verify", "failed", body.customer_id)
        remaining = config.MAX_FAILED_VERIFICATIONS - (failures_before + 1)
        if remaining <= 0:
            raise _locked()
        raise api_error(
            401,
            "verification_failed",
            "Could not verify identity with the details provided.",
            attempts_remaining=remaining,
        )

    _record_attempt(body.customer_id, success=True)
    token, _ = issue_token(body.customer_id, caller.label)
    audit.record(caller, "identity.verify", "success", body.customer_id)
    return VerifyResponse(
        verified=True,
        customer_id=body.customer_id,
        verification_token=token,
        expires_in_seconds=config.TOKEN_TTL_SECONDS,
    )
