"""
JBank — synthetic data seed script.

Populates customers, accounts, cards, and transactions with fake data
via Faker. Never writes real personal data. Run schema.sql first; the
script is not idempotent (re-running it without resetting the schema
duplicates data).

Customers are spread across three jurisdictions (US, MX, ES). Each
customer's country drives their name/phone style and their accounts'
currency, and later determines which policy documents may be retrieved
for them.

Usage:
    python seed.py

Env vars (match .env.example):
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
    (defaults target the Docker container published on host port 5433)
"""

import os
import random
import re
import unicodedata
from collections import Counter
from datetime import date, timedelta

import psycopg2
from faker import Faker

Faker.seed(42)  # reproducible fake data across runs
random.seed(42)

NUM_CUSTOMERS = 30

# country code -> (Faker locale, phone dial code, currency, sampling weight)
COUNTRIES = {
    "US": ("en_US", "+1", "USD", 0.6),
    "MX": ("es_MX", "+52", "MXN", 0.2),
    "ES": ("es_ES", "+34", "EUR", 0.2),
}
FAKERS = {code: Faker(cfg[0]) for code, cfg in COUNTRIES.items()}

DISPUTE_REASONS = [
    "I did not make this purchase",
    "I was charged twice for the same item",
    "The item I ordered never arrived",
    "The amount charged is different from what I agreed to",
    "I cancelled this subscription but was still charged",
]
DISPUTE_STATUSES = ["open", "under_review", "resolved_customer", "resolved_merchant", "escalated"]

ACCOUNT_TYPES = ["essential_checking", "premier_checking", "standard_savings", "high_yield_savings"]
TXN_CATEGORIES = ["groceries", "dining", "transfer", "atm_withdrawal", "deposit", "subscription", "utilities", "online_shopping"]
MERCHANTS_BY_CATEGORY = {
    "groceries": ["Green Valley Market", "Corner Grocer", "Fresh Fields"],
    "dining": ["Blue Plate Diner", "Taco Loft", "Riverside Cafe"],
    "transfer": [None],
    "atm_withdrawal": [None],
    "deposit": [None],
    "subscription": ["StreamBox", "CloudNotes", "FitPass"],
    "utilities": ["City Power & Light", "Metro Water Co"],
    "online_shopping": ["ShopHaven", "QuickCart", "ByteGoods"],
}


def get_connection():
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        port=os.environ.get("POSTGRES_PORT", "5433"),
        dbname=os.environ.get("POSTGRES_DB", "banking_db"),
        user=os.environ.get("POSTGRES_USER", "banking_user"),
        password=os.environ.get("POSTGRES_PASSWORD", "banking_pass"),
    )


def random_account_number():
    return "".join(str(random.randint(0, 9)) for _ in range(12))


def slug(text):
    """Lowercase ASCII-only version of a name, safe for use in an email address."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", folded.lower())


def make_customer(seen_emails):
    """Build one fake customer (no DB access, so it can be tested on its own)."""
    country = random.choices(
        list(COUNTRIES), weights=[cfg[3] for cfg in COUNTRIES.values()]
    )[0]
    fk = FAKERS[country]
    dial_code = COUNTRIES[country][1]

    first, last = fk.first_name(), fk.last_name()
    while True:
        email = f"{slug(first)}.{slug(last)}{random.randint(1, 999)}@example.com"
        if email not in seen_emails:
            seen_emails.add(email)
            break

    return {
        "first_name": first,
        "last_name": last,
        "email": email,
        # fixed short format; Faker's phone_number() can exceed the VARCHAR(20) column
        "phone": f"{dial_code}-{random.randint(200, 999)}-{random.randint(200, 999)}-{random.randint(0, 9999):04d}",
        "country": country,
        "date_of_birth": fk.date_of_birth(minimum_age=18, maximum_age=85),
        "last4_ssn": f"{random.randint(0, 9999):04d}",  # synthetic, identity-verification simulation only
    }


def seed_customers(cur, n):
    seen_emails = set()
    customers = []  # list of (customer_id, country)
    for _ in range(n):
        c = make_customer(seen_emails)
        cur.execute(
            """
            INSERT INTO customers (first_name, last_name, email, phone, country, date_of_birth, last4_ssn)
            VALUES (%(first_name)s, %(last_name)s, %(email)s, %(phone)s, %(country)s, %(date_of_birth)s, %(last4_ssn)s)
            RETURNING customer_id
            """,
            c,
        )
        customers.append((cur.fetchone()[0], c["country"]))
    return customers


def seed_accounts(cur, customers):
    account_ids = []
    for cust_id, country in customers:
        currency = COUNTRIES[country][2]
        # each customer gets 1-2 accounts
        for account_type in random.sample(ACCOUNT_TYPES, k=random.choice([1, 2])):
            balance_cents = random.randint(500, 2_500_000)  # 5.00 to 25,000.00 in the account's currency
            cur.execute(
                """
                INSERT INTO accounts (customer_id, account_type, account_number, balance_cents, currency, status)
                VALUES (%s, %s, %s, %s, %s, 'active')
                RETURNING account_id
                """,
                (cust_id, account_type, random_account_number(), balance_cents, currency),
            )
            account_ids.append(cur.fetchone()[0])
    return account_ids


def seed_cards(cur, account_ids):
    card_ids = []
    for acct_id in account_ids:
        expires = date.today() + timedelta(days=random.randint(180, 1095))
        last4 = f"{random.randint(0, 9999):04d}"
        cur.execute(
            """
            INSERT INTO cards (account_id, card_last4, card_type, status, expires_at)
            VALUES (%s, %s, 'debit', 'active', %s)
            RETURNING card_id
            """,
            (acct_id, last4, expires),
        )
        card_ids.append(cur.fetchone()[0])
    return card_ids


def seed_transactions(cur, account_ids, per_account=15):
    fk = FAKERS["US"]  # only used for timestamps, so the locale doesn't matter
    for acct_id in account_ids:
        for _ in range(per_account):
            category = random.choice(TXN_CATEGORIES)
            merchant = random.choice(MERCHANTS_BY_CATEGORY[category])

            if category == "deposit":
                amount_cents = random.randint(1000, 300000)  # positive = credit
            else:
                amount_cents = -random.randint(300, 20000)  # negative = debit

            days_ago = random.randint(0, 90)
            occurred_at = fk.date_time_between(start_date=f"-{days_ago}d", end_date="now")

            cur.execute(
                """
                INSERT INTO transactions (account_id, amount_cents, merchant_name, category, description, status, occurred_at)
                VALUES (%s, %s, %s, %s, %s, 'posted', %s)
                """,
                (
                    acct_id,
                    amount_cents,
                    merchant,
                    category,
                    f"{category.replace('_', ' ').title()}" + (f" - {merchant}" if merchant else ""),
                    occurred_at,
                ),
            )


def seed_disputes(cur, n=8):
    """Open a few disputes on older card purchases, so there is dispute data to look up."""
    cur.execute(
        """
        SELECT t.transaction_id, a.customer_id
        FROM transactions t JOIN accounts a ON a.account_id = t.account_id
        WHERE t.amount_cents < 0 AND t.status = 'posted' AND t.occurred_at < now() - interval '5 days'
        ORDER BY t.transaction_id
        """
    )
    candidates = cur.fetchall()  # ordered, so the seeded random.sample below is reproducible
    chosen = random.sample(candidates, k=min(n, len(candidates)))
    for txn_id, cust_id in chosen:
        cur.execute(
            "INSERT INTO disputes (transaction_id, customer_id, reason, status) VALUES (%s, %s, %s, %s)",
            (txn_id, cust_id, random.choice(DISPUTE_REASONS), random.choice(DISPUTE_STATUSES)),
        )
        cur.execute("UPDATE transactions SET status = 'disputed' WHERE transaction_id = %s", (txn_id,))
    return len(chosen)


def main():
    conn = get_connection()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            print(f"Seeding {NUM_CUSTOMERS} customers...")
            customers = seed_customers(cur, NUM_CUSTOMERS)

            print(f"Seeding accounts for {len(customers)} customers...")
            account_ids = seed_accounts(cur, customers)

            print(f"Seeding cards for {len(account_ids)} accounts...")
            seed_cards(cur, account_ids)

            print(f"Seeding transactions for {len(account_ids)} accounts...")
            seed_transactions(cur, account_ids)

            print("Seeding disputes...")
            dispute_count = seed_disputes(cur)

        conn.commit()
        by_country = dict(Counter(country for _, country in customers))
        print(f"Done. {len(customers)} customers, {len(account_ids)} accounts, {dispute_count} disputes seeded. Customers by country: {by_country}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()