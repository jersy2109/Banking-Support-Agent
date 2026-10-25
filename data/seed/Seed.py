"""
JBank — synthetic data seed script.

Populates customers, accounts, cards, and transactions with fake data
via Faker. Never writes real personal data. Safe to re-run against a
fresh database (run schema.sql first).

Usage:
    python seed.py

Env vars (match .env.example):
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
    (defaults target the Docker container published on host port 5433)
"""

import os
import random
from datetime import date, timedelta

import psycopg2
from faker import Faker

fake = Faker()
Faker.seed(42)  # reproducible fake data across runs
random.seed(42)

NUM_CUSTOMERS = 30
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


def seed_customers(cur, n):
    customer_ids = []
    for _ in range(n):
        first = fake.first_name()
        last = fake.last_name()
        email = f"{first.lower()}.{last.lower()}{random.randint(1,999)}@example.com"
        phone = f"+1-{random.randint(200, 999)}-{random.randint(200, 999)}-{random.randint(0, 9999):04d}"  # fixed short format (Faker's can exceed 20 chars)
        dob = fake.date_of_birth(minimum_age=18, maximum_age=85)
        last4_ssn = f"{random.randint(0,9999):04d}"

        cur.execute(
            """
            INSERT INTO customers (first_name, last_name, email, phone, date_of_birth, last4_ssn)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING customer_id
            """,
            (first, last, email, phone, dob, last4_ssn),
        )
        customer_ids.append(cur.fetchone()[0])
    return customer_ids


def seed_accounts(cur, customer_ids):
    account_ids = []
    for cust_id in customer_ids:
        # each customer gets 1-2 accounts
        for account_type in random.sample(ACCOUNT_TYPES, k=random.choice([1, 2])):
            balance_cents = random.randint(500, 2_500_000)  # $5 to $25,000
            cur.execute(
                """
                INSERT INTO accounts (customer_id, account_type, account_number, balance_cents, status)
                VALUES (%s, %s, %s, %s, 'active')
                RETURNING account_id
                """,
                (cust_id, account_type, random_account_number(), balance_cents),
            )
            account_ids.append(cur.fetchone()[0])
    return account_ids


def seed_cards(cur, account_ids):
    card_ids = []
    for acct_id in account_ids:
        expires = date.today() + timedelta(days=random.randint(180, 1095))
        last4 = f"{random.randint(0,9999):04d}"
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
    for acct_id in account_ids:
        for _ in range(per_account):
            category = random.choice(TXN_CATEGORIES)
            merchant = random.choice(MERCHANTS_BY_CATEGORY[category])

            if category == "deposit":
                amount_cents = random.randint(1000, 300000)  # positive = credit
            else:
                amount_cents = -random.randint(300, 20000)  # negative = debit

            days_ago = random.randint(0, 90)
            occurred_at = fake.date_time_between(start_date=f"-{days_ago}d", end_date="now")

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


def main():
    conn = get_connection()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            print(f"Seeding {NUM_CUSTOMERS} customers...")
            customer_ids = seed_customers(cur, NUM_CUSTOMERS)

            print(f"Seeding accounts for {len(customer_ids)} customers...")
            account_ids = seed_accounts(cur, customer_ids)

            print(f"Seeding cards for {len(account_ids)} accounts...")
            seed_cards(cur, account_ids)

            print(f"Seeding transactions for {len(account_ids)} accounts...")
            seed_transactions(cur, account_ids)

        conn.commit()
        print(f"Done. {len(customer_ids)} customers, {len(account_ids)} accounts seeded.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()