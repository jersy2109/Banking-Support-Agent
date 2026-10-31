"""Audit trail: every sensitive action is recorded with who did it and what happened."""

from . import db


def record(caller, action, outcome="success", customer_id=None, resource=None, detail=None):
    """Write one audit entry in its own transaction. `caller` is None when authentication failed."""
    label = caller.label if caller else "unauthenticated"
    role = caller.role if caller else None
    with db.short_transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_log (caller_label, caller_role, action, customer_id, resource, outcome, detail)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (label, role, action, customer_id, resource, outcome, detail),
            )
