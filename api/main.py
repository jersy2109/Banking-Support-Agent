"""
JBank mock bank API (synthetic data only).

Run from the project root:
    uvicorn api.main:app --reload --port 8000
Interactive docs: http://localhost:8000/docs
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from . import db
from .routers import accounts, cards, disputes, identity

app = FastAPI(
    title="JBank Mock Bank API",
    version="0.1.0",
    description=(
        "A simulated core-banking API with synthetic data.\n\n"
        "**Flow:** send `X-API-Key` on every request; call `POST /v1/identity/verify` to verify a customer "
        "and get a token; send that token as `X-Verification-Token` on every customer-specific request.\n\n"
        "Errors look like `{\"detail\": {\"code\": ..., \"message\": ...}}`; branch on `code`."
    ),
)

for router in (identity.router, accounts.router, cards.router, disputes.router):
    app.include_router(router, prefix="/v1")


@app.get("/health", tags=["health"])
def health():
    """Liveness check (no authentication). Reports whether the database answers."""
    try:
        with db.short_transaction() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return {"status": "ok", "database": "up"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "degraded", "database": "down"})
