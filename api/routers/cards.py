"""Card actions. There is deliberately no 'unfreeze': per the card policy, a frozen card is replaced."""

from fastapi import APIRouter, Depends

from .. import audit, db
from ..errors import api_error
from ..schemas import FreezeResponse
from ..security import Session, require_verified

router = APIRouter(tags=["cards"])


@router.post("/cards/{card_id}/freeze", response_model=FreezeResponse)
def freeze_card(card_id: int, session: Session = Depends(require_verified), conn=Depends(db.get_conn)):
    """Block a card from new transactions. Safe to repeat: freezing a frozen card changes nothing."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.card_id, c.status FROM cards c
            JOIN accounts a ON a.account_id = c.account_id
            WHERE c.card_id = %s AND a.customer_id = %s
            FOR UPDATE OF c
            """,
            (card_id, session.customer_id),
        )
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            audit.record(session.caller, "card.freeze", "denied", session.customer_id, f"card:{card_id}", "not found for this customer")
            raise api_error(404, "card_not_found", "Card not found.")

        if row["status"] == "frozen":
            conn.rollback()
            audit.record(session.caller, "card.freeze", "success", session.customer_id, f"card:{card_id}", "already frozen")
            return FreezeResponse(card_id=card_id, status="frozen", changed=False, message="This card was already frozen.")

        if row["status"] in ("replaced", "expired"):
            conn.rollback()
            audit.record(session.caller, "card.freeze", "denied", session.customer_id, f"card:{card_id}", f"card is {row['status']}")
            raise api_error(409, "card_not_freezable", f"This card is {row['status']} and cannot be frozen.")

        cur.execute("UPDATE cards SET status = 'frozen' WHERE card_id = %s", (card_id,))
    conn.commit()  # saved before the response goes out
    audit.record(session.caller, "card.freeze", "success", session.customer_id, f"card:{card_id}")
    return FreezeResponse(
        card_id=card_id,
        status="frozen",
        changed=True,
        message="The card is frozen. A replacement must be issued to use the account with a card again.",
    )
