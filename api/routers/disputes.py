"""Dispute cases. The API can open a case and report its status; humans decide the outcome."""

import psycopg2.errors
from fastapi import APIRouter, Depends

from .. import audit, config, db
from ..errors import api_error
from ..schemas import DisputeCreate, DisputeItem
from ..security import Session, require_verified

router = APIRouter(tags=["disputes"])

STATUS_DESCRIPTIONS = {
    "open": "The case has been opened and has not been reviewed yet.",
    "under_review": "A specialist is investigating the transaction.",
    "resolved_customer": "Resolved in the customer's favor.",
    "resolved_merchant": "Resolved in the merchant's favor.",
    "escalated": "Escalated to a human specialist for manual review.",
}

_DISPUTE_SELECT = """
    SELECT d.dispute_id, d.transaction_id, d.status, d.reason, d.opened_at, d.updated_at,
           t.amount_cents, t.merchant_name, a.currency
    FROM disputes d
    JOIN transactions t ON t.transaction_id = d.transaction_id
    JOIN accounts a ON a.account_id = t.account_id
"""


def _to_item(row):
    return DisputeItem(
        case_number=f"D-{row['dispute_id']:06d}",
        status_description=STATUS_DESCRIPTIONS[row["status"]],
        **row,
    )


@router.post("/disputes", response_model=DisputeItem, status_code=201)
def open_dispute(body: DisputeCreate, session: Session = Depends(require_verified), conn=Depends(db.get_conn)):
    """Open a dispute on one of the verified customer's card purchases."""
    resource = f"transaction:{body.transaction_id}"
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.transaction_id, t.amount_cents,
                   (now() - t.occurred_at) > make_interval(days => %s) AS outside_window,
                   EXISTS (SELECT 1 FROM disputes d WHERE d.transaction_id = t.transaction_id) AS already_disputed
            FROM transactions t JOIN accounts a ON a.account_id = t.account_id
            WHERE t.transaction_id = %s AND a.customer_id = %s
            FOR UPDATE OF t
            """,
            (config.DISPUTE_WINDOW_DAYS, body.transaction_id, session.customer_id),
        )
        txn = cur.fetchone()

        problem = None
        if txn is None:
            problem = api_error(404, "transaction_not_found", "Transaction not found.")
        elif txn["amount_cents"] >= 0:
            problem = api_error(422, "not_disputable", "Only charges and withdrawals can be disputed, not deposits.")
        elif txn["already_disputed"]:
            problem = api_error(409, "already_disputed", "This transaction already has a dispute case.")
        elif txn["outside_window"]:
            problem = api_error(
                422,
                "outside_dispute_window",
                f"Disputes must be filed within {config.DISPUTE_WINDOW_DAYS} days of the transaction.",
            )
        if problem:
            conn.rollback()
            audit.record(session.caller, "dispute.open", "denied", session.customer_id, resource, problem.detail["code"])
            raise problem

        try:
            cur.execute(
                "INSERT INTO disputes (transaction_id, customer_id, reason) VALUES (%s, %s, %s) RETURNING dispute_id",
                (body.transaction_id, session.customer_id, body.reason),
            )
        except psycopg2.errors.UniqueViolation:  # two requests raced; the database says only one wins
            conn.rollback()
            audit.record(session.caller, "dispute.open", "denied", session.customer_id, resource, "already_disputed")
            raise api_error(409, "already_disputed", "This transaction already has a dispute case.")
        dispute_id = cur.fetchone()["dispute_id"]
        cur.execute("UPDATE transactions SET status = 'disputed' WHERE transaction_id = %s", (body.transaction_id,))
    conn.commit()  # saved before the response goes out

    audit.record(session.caller, "dispute.open", "success", session.customer_id, f"dispute:{dispute_id}")
    with conn.cursor() as cur:
        cur.execute(_DISPUTE_SELECT + "WHERE d.dispute_id = %s", (dispute_id,))
        return _to_item(cur.fetchone())


@router.get("/disputes", response_model=list[DisputeItem])
def list_disputes(session: Session = Depends(require_verified), conn=Depends(db.get_conn)):
    """All of the verified customer's dispute cases, newest first."""
    with conn.cursor() as cur:
        cur.execute(_DISPUTE_SELECT + "WHERE d.customer_id = %s ORDER BY d.opened_at DESC, d.dispute_id DESC", (session.customer_id,))
        rows = cur.fetchall()
    audit.record(session.caller, "dispute.list", "success", session.customer_id)
    return [_to_item(r) for r in rows]


@router.get("/disputes/{dispute_id}", response_model=DisputeItem)
def get_dispute(dispute_id: int, session: Session = Depends(require_verified), conn=Depends(db.get_conn)):
    with conn.cursor() as cur:
        cur.execute(_DISPUTE_SELECT + "WHERE d.dispute_id = %s AND d.customer_id = %s", (dispute_id, session.customer_id))
        row = cur.fetchone()
    if row is None:
        audit.record(session.caller, "dispute.status", "denied", session.customer_id, f"dispute:{dispute_id}", "not found for this customer")
        raise api_error(404, "dispute_not_found", "Dispute case not found.")
    audit.record(session.caller, "dispute.status", "success", session.customer_id, f"dispute:{dispute_id}")
    return _to_item(row)
