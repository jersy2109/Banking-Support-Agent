-- JBank — schema for the mock banking API
-- All data is synthetic. Run this once to set up tables before seeding.

DROP TABLE IF EXISTS audit_log CASCADE;
DROP TABLE IF EXISTS verification_attempts CASCADE;
DROP TABLE IF EXISTS disputes CASCADE;
DROP TABLE IF EXISTS transactions CASCADE;
DROP TABLE IF EXISTS cards CASCADE;
DROP TABLE IF EXISTS accounts CASCADE;
DROP TABLE IF EXISTS customers CASCADE;

-- ---------------------------------------------------------------
-- customers: one row per person. Identity verification fields
-- (dob, last4_ssn) are synthetic and used only to simulate the
-- "verify identity" step the agent must perform before sensitive actions.
-- ---------------------------------------------------------------
CREATE TABLE customers (
    customer_id     SERIAL PRIMARY KEY,
    first_name      VARCHAR(50)  NOT NULL,
    last_name       VARCHAR(50)  NOT NULL,
    email           VARCHAR(100) NOT NULL UNIQUE,
    phone           VARCHAR(20)  NOT NULL,
    country         CHAR(2)      NOT NULL DEFAULT 'US' CHECK (country IN ('US', 'MX', 'ES')),  -- client jurisdiction; drives which documents may be retrieved
    date_of_birth   DATE         NOT NULL,
    last4_ssn       CHAR(4)      NOT NULL,  -- synthetic, for identity verification simulation only
    created_at      TIMESTAMP    NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------
-- accounts: a customer can have multiple accounts (checking, savings).
-- ---------------------------------------------------------------
CREATE TABLE accounts (
    account_id      SERIAL PRIMARY KEY,
    customer_id     INTEGER NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    account_type    VARCHAR(30) NOT NULL CHECK (account_type IN (
                        'essential_checking', 'premier_checking',
                        'standard_savings', 'high_yield_savings'
                    )),
    account_number  VARCHAR(20) NOT NULL UNIQUE,  -- synthetic, masked in API responses
    balance_cents   BIGINT      NOT NULL DEFAULT 0,  -- stored in cents to avoid float rounding issues
    currency        CHAR(3)     NOT NULL DEFAULT 'USD',
    status          VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'frozen', 'closed')),
    opened_at       TIMESTAMP   NOT NULL DEFAULT now()
);

CREATE INDEX idx_accounts_customer_id ON accounts(customer_id);

-- ---------------------------------------------------------------
-- cards: one or more cards per account (debit card, etc.)
-- ---------------------------------------------------------------
CREATE TABLE cards (
    card_id         SERIAL PRIMARY KEY,
    account_id      INTEGER NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    card_last4      CHAR(4)     NOT NULL,  -- synthetic, only last 4 digits ever stored/returned
    card_type       VARCHAR(20) NOT NULL DEFAULT 'debit' CHECK (card_type IN ('debit', 'credit')),
    status          VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'frozen', 'replaced', 'expired')),
    issued_at       TIMESTAMP   NOT NULL DEFAULT now(),
    expires_at      DATE        NOT NULL
);

CREATE INDEX idx_cards_account_id ON cards(account_id);

-- ---------------------------------------------------------------
-- transactions: transaction history per account.
-- ---------------------------------------------------------------
CREATE TABLE transactions (
    transaction_id  SERIAL PRIMARY KEY,
    account_id      INTEGER NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    amount_cents    BIGINT      NOT NULL,  -- negative = debit/purchase, positive = credit/deposit
    merchant_name   VARCHAR(100),
    category        VARCHAR(50),  -- e.g. 'groceries', 'transfer', 'atm_withdrawal', 'deposit'
    description     VARCHAR(255),
    status          VARCHAR(20) NOT NULL DEFAULT 'posted' CHECK (status IN ('pending', 'posted', 'disputed', 'reversed')),
    occurred_at     TIMESTAMP   NOT NULL DEFAULT now()
);

CREATE INDEX idx_transactions_account_id ON transactions(account_id);
CREATE INDEX idx_transactions_occurred_at ON transactions(occurred_at);

-- ---------------------------------------------------------------
-- disputes: a customer-raised challenge to one transaction.
-- One dispute per transaction. Outcomes are decided by humans, never by the API.
-- ---------------------------------------------------------------
CREATE TABLE disputes (
    dispute_id      SERIAL PRIMARY KEY,
    transaction_id  INTEGER NOT NULL UNIQUE REFERENCES transactions(transaction_id) ON DELETE CASCADE,
    customer_id     INTEGER NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    reason          VARCHAR(255) NOT NULL,
    status          VARCHAR(30)  NOT NULL DEFAULT 'open' CHECK (status IN (
                        'open', 'under_review', 'resolved_customer', 'resolved_merchant', 'escalated'
                    )),
    opened_at       TIMESTAMP    NOT NULL DEFAULT now(),
    updated_at      TIMESTAMP    NOT NULL DEFAULT now()
);

CREATE INDEX idx_disputes_customer_id ON disputes(customer_id);

-- ---------------------------------------------------------------
-- verification_attempts: every identity check, used to lock out guessing.
-- customer_id has no foreign key on purpose: attempts against IDs that do not
-- exist are recorded too, so the API never reveals which customers exist.
-- ---------------------------------------------------------------
CREATE TABLE verification_attempts (
    attempt_id      SERIAL PRIMARY KEY,
    customer_id     INTEGER   NOT NULL,
    attempted_at    TIMESTAMP NOT NULL DEFAULT now(),
    success         BOOLEAN   NOT NULL
);

CREATE INDEX idx_verification_attempts_customer ON verification_attempts(customer_id, attempted_at);

-- ---------------------------------------------------------------
-- audit_log: who asked for what, and what happened.
-- ---------------------------------------------------------------
CREATE TABLE audit_log (
    audit_id        SERIAL PRIMARY KEY,
    occurred_at     TIMESTAMP   NOT NULL DEFAULT now(),
    caller_label    VARCHAR(50) NOT NULL,   -- which API key was used ('unauthenticated' if none valid)
    caller_role     VARCHAR(30),
    action          VARCHAR(50) NOT NULL,   -- e.g. 'identity.verify', 'account.balance'
    customer_id     INTEGER,
    resource        VARCHAR(100),           -- e.g. 'account:12'
    outcome         VARCHAR(20) NOT NULL CHECK (outcome IN ('success', 'denied', 'failed')),
    detail          VARCHAR(255)
);

CREATE INDEX idx_audit_log_occurred_at ON audit_log(occurred_at);