"""Read-only account data for the verified customer."""

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query

from .. import audit, config, db
from ..errors import api_error
from ..schemas import AccountSummary, BalanceResponse, CardItem, TransactionItem
from ..security import Session, require_verified

router = APIRouter(tags=["accounts"])


def _not_found(session, action, account_id):
    """Same answer whether the account doesn't exist or belongs to someone else."""
    audit.record(session.caller, action, "denied", session.customer_id, f"account:{account_id}", "not found for this customer")
    return api_error(404, "account_not_found", "Account not found.")


def _owned_account(conn, session, account_id, action):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT account_id, account_type, currency, balance_cents, status, now() AS as_of "
            "FROM accounts WHERE account_id = %s AND customer_id = %s",
            (account_id, session.customer_id),
        )
        row = cur.fetchone()
    if row is None:
        raise _not_found(session, action, account_id)
    return row


@router.get("/customers/me/accounts", response_model=list[AccountSummary])
def list_accounts(session: Session = Depends(require_verified), conn=Depends(db.get_conn)):
    """The verified customer's accounts (account numbers are masked)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT account_id, account_type, account_number, currency, status "
            "FROM accounts WHERE customer_id = %s ORDER BY account_id",
            (session.customer_id,),
        )
        rows = cur.fetchall()
    audit.record(session.caller, "account.list", "success", session.customer_id)
    return [
        AccountSummary(
            account_id=r["account_id"],
            account_type=r["account_type"],
            account_number_masked="****" + r["account_number"][-4:],
            currency=r["currency"],
            status=r["status"],
        )
        for r in rows
    ]


@router.get("/accounts/{account_id}/balance", response_model=BalanceResponse)
def get_balance(account_id: int, session: Session = Depends(require_verified), conn=Depends(db.get_conn)):
    row = _owned_account(conn, session, account_id, "account.balance")
    audit.record(session.caller, "account.balance", "success", session.customer_id, f"account:{account_id}")
    return BalanceResponse(
        account_id=row["account_id"],
        account_type=row["account_type"],
        currency=row["currency"],
        balance_cents=row["balance_cents"],
        balance=f"{Decimal(row['balance_cents']) / 100:.2f}",
        status=row["status"],
        as_of=row["as_of"],
    )


@router.get("/accounts/{account_id}/transactions", response_model=list[TransactionItem])
def list_transactions(
    account_id: int,
    limit: int = Query(config.DEFAULT_TRANSACTION_LIMIT, ge=1, le=config.MAX_TRANSACTION_LIMIT),
    days: Optional[int] = Query(None, ge=1, le=365, description="Only transactions from the last N days"),
    category: Optional[str] = Query(None, description="e.g. groceries, dining, deposit"),
    session: Session = Depends(require_verified),
    conn=Depends(db.get_conn),
):
    """Most recent transactions first."""
    _owned_account(conn, session, account_id, "account.transactions")
    conditions, params = ["t.account_id = %s"], [account_id]
    if days is not None:
        conditions.append("t.occurred_at > now() - make_interval(days => %s)")
        params.append(days)
    if category:
        conditions.append("t.category = %s")
        params.append(category)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT t.transaction_id, t.occurred_at, t.amount_cents, a.currency,
                   t.merchant_name, t.category, t.description, t.status
            FROM transactions t JOIN accounts a ON a.account_id = t.account_id
            WHERE {' AND '.join(conditions)}
            ORDER BY t.occurred_at DESC, t.transaction_id DESC
            LIMIT %s
            """,
            params + [limit],
        )
        rows = cur.fetchall()
    audit.record(session.caller, "account.transactions", "success", session.customer_id, f"account:{account_id}")
    return rows


@router.get("/accounts/{account_id}/cards", response_model=list[CardItem])
def list_cards(account_id: int, session: Session = Depends(require_verified), conn=Depends(db.get_conn)):
    _owned_account(conn, session, account_id, "account.cards")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT card_id, card_last4, card_type, status, expires_at FROM cards WHERE account_id = %s ORDER BY card_id",
            (account_id,),
        )
        rows = cur.fetchall()
    audit.record(session.caller, "account.cards", "success", session.customer_id, f"account:{account_id}")
    return rows
