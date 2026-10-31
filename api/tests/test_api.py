"""
Integration tests for the mock bank API. They run against the real database, so seed it first.

    python -m pytest api/tests -q        (from the project root)

They write to the development database (audit entries, verification attempts) and undo the
card and dispute changes they make. Do not run them against anything you care about.
"""

import psycopg2
import pytest
from fastapi.testclient import TestClient
from psycopg2.extras import RealDictCursor

from api import config, security
from api.main import app

client = TestClient(app)
KEY_A = config.API_KEYS[0][0]
KEY_B = config.API_KEYS[1][0]


# ----------------------------------------------------------------- helpers


@pytest.fixture(scope="session")
def db():
    conn = psycopg2.connect(
        host=config.DB_HOST, port=config.DB_PORT, dbname=config.DB_NAME,
        user=config.DB_USER, password=config.DB_PASSWORD, cursor_factory=RealDictCursor,
    )
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def clean_state(db):
    """Each test starts with no lockouts and a fresh rate-limit window."""
    with db.cursor() as cur:
        cur.execute("DELETE FROM verification_attempts")
    security.limiter.reset()
    yield
    security.limiter.reset()


def q(db, sql, params=()):
    with db.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def h(key=KEY_A, token=None):
    headers = {"X-API-Key": key}
    if token:
        headers["X-Verification-Token"] = token
    return headers


def verify(customer, key=KEY_A):
    response = client.post(
        "/v1/identity/verify",
        headers=h(key),
        json={"customer_id": customer["customer_id"], "date_of_birth": str(customer["date_of_birth"]), "last4_ssn": customer["last4_ssn"]},
    )
    assert response.status_code == 200, response.text
    return response.json()["verification_token"]


@pytest.fixture(scope="session")
def customers(db):
    rows = q(db, "SELECT customer_id, date_of_birth, last4_ssn FROM customers ORDER BY customer_id LIMIT 2")
    assert len(rows) == 2, "seed the database first: python data/seed/seed.py"
    return rows


@pytest.fixture
def alice(customers):
    return customers[0]


@pytest.fixture
def bob(customers):
    return customers[1]


def first_account(db, customer):
    return q(db, "SELECT * FROM accounts WHERE customer_id = %s ORDER BY account_id LIMIT 1", (customer["customer_id"],))[0]


# ------------------------------------------------------- health and API keys


def test_health_needs_no_key():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "up"}


def test_missing_api_key_is_rejected():
    response = client.get("/v1/customers/me/accounts")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_api_key"


def test_wrong_api_key_is_rejected():
    response = client.get("/v1/customers/me/accounts", headers=h("not-a-real-key"))
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_api_key"


def test_rate_limit(monkeypatch):
    monkeypatch.setattr(security.limiter, "limit", 3)
    codes = [client.get("/v1/customers/me/accounts", headers=h()).status_code for _ in range(4)]
    assert codes[:3] == [401, 401, 401]  # allowed through to the verification check, which refuses them
    assert codes[3] == 429
    blocked = client.get("/v1/customers/me/accounts", headers=h())
    assert blocked.json()["detail"]["code"] == "rate_limited"
    assert int(blocked.headers["Retry-After"]) >= 1


# ----------------------------------------------------- identity verification


def test_verify_success(alice):
    response = client.post(
        "/v1/identity/verify", headers=h(),
        json={"customer_id": alice["customer_id"], "date_of_birth": str(alice["date_of_birth"]), "last4_ssn": alice["last4_ssn"]},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["verified"] is True and body["customer_id"] == alice["customer_id"]
    assert body["verification_token"] and body["expires_in_seconds"] == config.TOKEN_TTL_SECONDS


def test_wrong_details_fail_with_attempts_remaining(alice):
    response = client.post(
        "/v1/identity/verify", headers=h(),
        json={"customer_id": alice["customer_id"], "date_of_birth": "1900-01-01", "last4_ssn": alice["last4_ssn"]},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "verification_failed"
    assert response.json()["detail"]["attempts_remaining"] == config.MAX_FAILED_VERIFICATIONS - 1


def test_unknown_customer_looks_identical_to_wrong_details(alice):
    wrong = client.post(
        "/v1/identity/verify", headers=h(),
        json={"customer_id": alice["customer_id"], "date_of_birth": "1900-01-01", "last4_ssn": "0000"},
    )
    unknown = client.post(
        "/v1/identity/verify", headers=h(),
        json={"customer_id": 999999, "date_of_birth": "1900-01-01", "last4_ssn": "0000"},
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()  # same code, message, and attempts_remaining


def test_lockout_after_repeated_failures(alice):
    bad = {"customer_id": alice["customer_id"], "date_of_birth": "1900-01-01", "last4_ssn": "0000"}
    statuses = [client.post("/v1/identity/verify", headers=h(), json=bad).status_code for _ in range(3)]
    assert statuses == [401, 401, 423]  # the third failure locks the customer
    locked = client.post(
        "/v1/identity/verify", headers=h(),
        json={"customer_id": alice["customer_id"], "date_of_birth": str(alice["date_of_birth"]), "last4_ssn": alice["last4_ssn"]},
    )
    assert locked.status_code == 423  # even the correct details are refused now
    assert locked.json()["detail"]["code"] == "verification_locked"
    assert locked.json()["detail"]["escalate"] is True


def test_invalid_input_is_rejected():
    response = client.post("/v1/identity/verify", headers=h(), json={"customer_id": 1, "date_of_birth": "1990-01-01", "last4_ssn": "12"})
    assert response.status_code == 422


# ------------------------------------------------------- verification tokens


def test_account_endpoints_need_a_token():
    response = client.get("/v1/customers/me/accounts", headers=h())
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "verification_required"


def test_tampered_token_is_rejected(alice, bob):
    token = verify(alice)
    _, expires, signature = token.split(".")
    forged = f"{bob['customer_id']}.{expires}.{signature}"  # try to reuse alice's signature for bob
    response = client.get("/v1/customers/me/accounts", headers=h(token=forged))
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "verification_invalid"


def test_token_only_works_for_the_key_it_was_issued_to(alice):
    token = verify(alice, key=KEY_A)
    assert client.get("/v1/customers/me/accounts", headers=h(KEY_A, token)).status_code == 200
    stolen = client.get("/v1/customers/me/accounts", headers=h(KEY_B, token))
    assert stolen.status_code == 401
    assert stolen.json()["detail"]["code"] == "verification_invalid"


def test_expired_token_is_rejected(alice, monkeypatch):
    monkeypatch.setattr(config, "TOKEN_TTL_SECONDS", -10)  # issue a token that is already expired
    token = verify(alice)
    response = client.get("/v1/customers/me/accounts", headers=h(token=token))
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "verification_expired"


# ------------------------------------------------------------ account data


def test_lists_only_own_accounts_and_masks_numbers(db, alice):
    response = client.get("/v1/customers/me/accounts", headers=h(token=verify(alice)))
    assert response.status_code == 200
    expected = {r["account_id"] for r in q(db, "SELECT account_id FROM accounts WHERE customer_id = %s", (alice["customer_id"],))}
    assert {a["account_id"] for a in response.json()} == expected
    assert all(a["account_number_masked"].startswith("****") and len(a["account_number_masked"]) == 8 for a in response.json())
    text = response.text
    assert "date_of_birth" not in text and "last4_ssn" not in text and "account_number\"" not in text


def test_balance_matches_database(db, alice):
    account = first_account(db, alice)
    response = client.get(f"/v1/accounts/{account['account_id']}/balance", headers=h(token=verify(alice)))
    body = response.json()
    assert response.status_code == 200
    assert body["balance_cents"] == account["balance_cents"]
    assert body["balance"] == f"{account['balance_cents'] / 100:.2f}"
    assert body["currency"] == account["currency"]


def test_cannot_read_another_customers_account(db, alice, bob):
    bobs = first_account(db, bob)
    response = client.get(f"/v1/accounts/{bobs['account_id']}/balance", headers=h(token=verify(alice)))
    missing = client.get("/v1/accounts/99999999/balance", headers=h(token=verify(alice)))
    assert response.status_code == missing.status_code == 404  # same answer as a nonexistent account
    assert response.json() == missing.json()


def test_transactions_newest_first_with_limit_and_filter(db, alice):
    account = first_account(db, alice)
    token = verify(alice)
    rows = client.get(f"/v1/accounts/{account['account_id']}/transactions?limit=5", headers=h(token=token)).json()
    assert 1 <= len(rows) <= 5
    assert [r["occurred_at"] for r in rows] == sorted((r["occurred_at"] for r in rows), reverse=True)
    category = rows[0]["category"]
    filtered = client.get(f"/v1/accounts/{account['account_id']}/transactions?category={category}", headers=h(token=token)).json()
    assert filtered and all(r["category"] == category for r in filtered)
    assert client.get(f"/v1/accounts/{account['account_id']}/transactions?limit=500", headers=h(token=token)).status_code == 422


# ------------------------------------------------------------------- cards


def test_freeze_card_is_repeatable_and_scoped(db, alice, bob):
    account = first_account(db, alice)
    card = q(db, "SELECT card_id, status FROM cards WHERE account_id = %s ORDER BY card_id LIMIT 1", (account["account_id"],))[0]
    token = verify(alice)
    try:
        first = client.post(f"/v1/cards/{card['card_id']}/freeze", headers=h(token=token))
        assert first.status_code == 200 and first.json()["changed"] is True
        assert q(db, "SELECT status FROM cards WHERE card_id = %s", (card["card_id"],))[0]["status"] == "frozen"
        again = client.post(f"/v1/cards/{card['card_id']}/freeze", headers=h(token=token))
        assert again.status_code == 200 and again.json()["changed"] is False
        assert client.post(f"/v1/cards/{card['card_id']}/freeze", headers=h(token=verify(bob))).status_code == 404
    finally:
        q_status = card["status"]
        with db.cursor() as cur:
            cur.execute("UPDATE cards SET status = %s WHERE card_id = %s", (q_status, card["card_id"]))


def test_cannot_freeze_an_expired_card(db, alice):
    account = first_account(db, alice)
    card = q(db, "SELECT card_id, status FROM cards WHERE account_id = %s ORDER BY card_id LIMIT 1", (account["account_id"],))[0]
    try:
        with db.cursor() as cur:
            cur.execute("UPDATE cards SET status = 'expired' WHERE card_id = %s", (card["card_id"],))
        response = client.post(f"/v1/cards/{card['card_id']}/freeze", headers=h(token=verify(alice)))
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "card_not_freezable"
    finally:
        with db.cursor() as cur:
            cur.execute("UPDATE cards SET status = %s WHERE card_id = %s", (card["status"], card["card_id"]))


# ---------------------------------------------------------------- disputes


def find_transaction(db, condition):
    """Any customer's transaction matching an SQL condition, with that customer's details."""
    rows = q(
        db,
        f"""
        SELECT t.transaction_id, c.customer_id, c.date_of_birth, c.last4_ssn
        FROM transactions t JOIN accounts a ON a.account_id = t.account_id JOIN customers c ON c.customer_id = a.customer_id
        WHERE {condition} AND NOT EXISTS (SELECT 1 FROM disputes d WHERE d.transaction_id = t.transaction_id)
        ORDER BY t.transaction_id LIMIT 1
        """,
    )
    if not rows:
        pytest.skip("no suitable transaction in the seed data")
    return rows[0]


def remove_dispute(db, transaction_id):
    with db.cursor() as cur:
        cur.execute("DELETE FROM disputes WHERE transaction_id = %s", (transaction_id,))
        cur.execute("UPDATE transactions SET status = 'posted' WHERE transaction_id = %s", (transaction_id,))


def test_open_and_check_a_dispute(db):
    txn = find_transaction(db, "t.amount_cents < 0 AND t.status = 'posted' AND t.occurred_at > now() - interval '50 days'")
    token = verify(txn)
    try:
        created = client.post("/v1/disputes", headers=h(token=token), json={"transaction_id": txn["transaction_id"], "reason": "I did not make this purchase"})
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["status"] == "open" and body["case_number"] == f"D-{body['dispute_id']:06d}"
        assert q(db, "SELECT status FROM transactions WHERE transaction_id = %s", (txn["transaction_id"],))[0]["status"] == "disputed"

        status = client.get(f"/v1/disputes/{body['dispute_id']}", headers=h(token=token))
        assert status.status_code == 200 and status.json()["transaction_id"] == txn["transaction_id"]
        assert body["dispute_id"] in [d["dispute_id"] for d in client.get("/v1/disputes", headers=h(token=token)).json()]

        duplicate = client.post("/v1/disputes", headers=h(token=token), json={"transaction_id": txn["transaction_id"], "reason": "Trying again"})
        assert duplicate.status_code == 409 and duplicate.json()["detail"]["code"] == "already_disputed"
    finally:
        remove_dispute(db, txn["transaction_id"])


def test_dispute_outside_window_is_refused(db):
    txn = find_transaction(db, f"t.amount_cents < 0 AND t.status = 'posted' AND t.occurred_at < now() - interval '{config.DISPUTE_WINDOW_DAYS + 5} days'")
    response = client.post("/v1/disputes", headers=h(token=verify(txn)), json={"transaction_id": txn["transaction_id"], "reason": "Too old to dispute"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "outside_dispute_window"


def test_deposits_cannot_be_disputed(db):
    txn = find_transaction(db, "t.amount_cents > 0")
    response = client.post("/v1/disputes", headers=h(token=verify(txn)), json={"transaction_id": txn["transaction_id"], "reason": "This is a deposit"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "not_disputable"


def test_cannot_dispute_or_view_someone_elses_case(db, alice):
    others = q(db, "SELECT t.transaction_id FROM transactions t JOIN accounts a ON a.account_id = t.account_id WHERE a.customer_id <> %s AND t.amount_cents < 0 LIMIT 1", (alice["customer_id"],))[0]
    token = verify(alice)
    response = client.post("/v1/disputes", headers=h(token=token), json={"transaction_id": others["transaction_id"], "reason": "Not my transaction"})
    assert response.status_code == 404
    foreign = q(db, "SELECT dispute_id FROM disputes WHERE customer_id <> %s LIMIT 1", (alice["customer_id"],))
    if foreign:
        assert client.get(f"/v1/disputes/{foreign[0]['dispute_id']}", headers=h(token=token)).status_code == 404


# ------------------------------------------------------------------- audit


def test_audit_log_records_success_failure_and_denial(db, alice, bob):
    start = q(db, "SELECT COALESCE(MAX(audit_id), 0) AS m FROM audit_log")[0]["m"]
    client.get("/v1/customers/me/accounts")  # no key -> denied, caller unauthenticated
    client.post("/v1/identity/verify", headers=h(), json={"customer_id": alice["customer_id"], "date_of_birth": "1900-01-01", "last4_ssn": "0000"})  # failed
    token = verify(alice)  # success
    bobs = first_account(db, bob)
    client.get(f"/v1/accounts/{bobs['account_id']}/balance", headers=h(token=token))  # denied: not alice's account
    rows = q(db, "SELECT caller_label, action, outcome, customer_id FROM audit_log WHERE audit_id > %s ORDER BY audit_id", (start,))
    seen = {(r["action"], r["outcome"]) for r in rows}
    assert ("authenticate", "denied") in seen
    assert ("identity.verify", "failed") in seen
    assert ("identity.verify", "success") in seen
    assert ("account.balance", "denied") in seen
    assert rows[0]["caller_label"] == "unauthenticated"
    assert all(r["caller_label"] == "dev-agent" for r in rows[1:])
