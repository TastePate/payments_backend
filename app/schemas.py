from datetime import datetime
from decimal import Decimal
from typing import Literal, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: Literal["RUB", "USD", "EUR"]
    description: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    webhook_url: HttpUrl

class PaymentAccepted(BaseModel):
    payment_id: UUID
    status: Literal["pending", "succeeded", "failed"]
    created_at: datetime

class PaymentDetails(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payment_id: UUID = Field(validation_alias="id")
    amount: Decimal
    currency: Literal["RUB", "USD", "EUR"]
    description: str | None
    metadata: dict[str, Any] = Field(validation_alias="payment_metadata")
    status: Literal["pending", "succeeded", "failed"]
    idempotency_key: str
    webhook_url: HttpUrl
    created_at: datetime
    processed_at: datetime | None