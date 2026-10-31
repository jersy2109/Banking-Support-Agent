"""Request and response shapes. Responses list their fields explicitly, so nothing sensitive
(full account numbers, date of birth, SSN digits) can leak out by accident."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class VerifyRequest(BaseModel):
    customer_id: int = Field(gt=0)
    date_of_birth: date
    last4_ssn: str = Field(pattern=r"^\d{4}$")


class VerifyResponse(BaseModel):
    verified: bool
    customer_id: int
    verification_token: str
    expires_in_seconds: int


class AccountSummary(BaseModel):
    account_id: int
    account_type: str
    account_number_masked: str
    currency: str
    status: str


class BalanceResponse(BaseModel):
    account_id: int
    account_type: str
    currency: str
    balance_cents: int
    balance: str  # the same amount as a decimal string, e.g. "1234.56"
    status: str
    as_of: datetime


class TransactionItem(BaseModel):
    transaction_id: int
    occurred_at: datetime
    amount_cents: int  # negative = money out, positive = money in
    currency: str
    merchant_name: Optional[str]
    category: Optional[str]
    description: Optional[str]
    status: str


class CardItem(BaseModel):
    card_id: int
    card_last4: str
    card_type: str
    status: str
    expires_at: date


class FreezeResponse(BaseModel):
    card_id: int
    status: str
    changed: bool  # False if the card was already frozen
    message: str


class DisputeCreate(BaseModel):
    transaction_id: int = Field(gt=0)
    reason: str = Field(min_length=5, max_length=255)


class DisputeItem(BaseModel):
    dispute_id: int
    case_number: str
    transaction_id: int
    status: str
    status_description: str
    reason: str
    opened_at: datetime
    updated_at: datetime
    amount_cents: int
    currency: str
    merchant_name: Optional[str]
