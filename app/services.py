import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Payment, OutboxEvent
from app.schemas import PaymentCreate

async def _get_payment_by_key(
        session: AsyncSession,
        idempotency_key: str
) -> Payment | None:
    query = select(Payment).where(
        Payment.idempotency_key == idempotency_key
    )

    return await session.scalar(query)


async def _insert_payment(
        session: AsyncSession,
        data: PaymentCreate,
        idempotency_key: str
) -> Payment:
    async with session.begin():
        payment = Payment(
            amount=data.amount,
            currency=data.currency,
            description=data.description,
            payment_metadata=data.metadata,
            webhook_url=str(data.webhook_url),
            idempotency_key=idempotency_key
        )
        session.add(payment)
        await session.flush()

        event = OutboxEvent(
            payment_id=payment.id,
            payload={
                "payment_id": str(payment.id)
            }
        )
        session.add(event)
    return payment


class IdempotencyConflictError(Exception):
    pass


async def create_payment(
        session: AsyncSession,
        data: PaymentCreate,
        idempotency_key: str
) -> Payment:
    try:
        return await _insert_payment(session, data, idempotency_key)
    except IntegrityError:
        async with session.begin():
            payment = await _get_payment_by_key(session, idempotency_key)

            if payment is None:
                 raise

            stored_metadata = json.dumps(
                payment.payment_metadata,
                sort_keys=True
            )

            requested_metadata = json.dumps(
                data.metadata,
                sort_keys=True
            )

            same_request = (
                payment.amount == data.amount
                and payment.currency == data.currency
                and payment.description == data.description
                and payment.webhook_url == str(data.webhook_url)
                and stored_metadata == requested_metadata
            )

            if not same_request:
                raise IdempotencyConflictError("Idempotency-Key already used with different data")

            return payment