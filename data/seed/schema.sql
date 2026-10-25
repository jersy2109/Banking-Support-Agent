-- JBank — schema for the mock banking API
-- All data is synthetic. Run this once to set up tables before seeding.

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