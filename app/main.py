import asyncio
import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Annotated
from uuid import UUID

from fastapi import Security, HTTPException, FastAPI, Depends, Header
from fastapi.security import APIKeyHeader
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import engine, get_session
from app.outbox import run_outbox_publisher
from app.schemas import PaymentAccepted, PaymentCreate, PaymentDetails
from app.services import create_payment, IdempotencyConflictError, get_payment

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
)

def require_api_key(provided_key: str | None = Security(api_key_header)):
    expected_key = settings.api_key.get_secret_value()

    if provided_key is None or not hmac.compare_digest(
        provided_key.encode("utf-8"),
        expected_key.encode("utf-8")
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key"
        )

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    publisher_task = asyncio.create_task(run_outbox_publisher())

    try:
        yield
    finally:
        publisher_task.cancel()

        try:
            with suppress(asyncio.CancelledError):
                await publisher_task
        finally:
            await engine.dispose()



app = FastAPI(
    title="Payment Processing Service",
    version="0.1.0",
    dependencies=[Depends(require_api_key)],
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

@app.get("/health")
async def health(session: Annotated[AsyncSession, Depends(get_session)]) -> dict[str, str]:
    try:
        async with asyncio.timeout(5):
            await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError, TimeoutError):
        logger.exception("Database health check failed")
        raise HTTPException(
            status_code=503,
            detail="Database is unavailable"
        ) from None

    return {
        "status": "ok",
        "database": "ok"
    }

@app.post("/api/v1/payments", status_code=202, response_model=PaymentAccepted)
async def post_payment(
        data: PaymentCreate,
        idempotency_key: Annotated[
            str,
            Header(alias="Idempotency-Key", min_length=1, max_length=255)
        ],
        session: Annotated[AsyncSession, Depends(get_session)]
) -> PaymentAccepted:
    try:
        payment = await create_payment(session, data, idempotency_key)
    except IdempotencyConflictError as e:
        raise HTTPException(
            status_code=409,
            detail=str(e)
        ) from e

    return PaymentAccepted(
        payment_id=payment.id,
        status=payment.status,
        created_at=payment.created_at
    )

@app.get("/api/v1/payments/{payment_id}", response_model=PaymentDetails)
async def get_payment_details(
        payment_id: UUID,
        session: Annotated[AsyncSession, Depends(get_session)]
) -> PaymentDetails:
    payment = await get_payment(session, payment_id)

    if payment is None:
        raise HTTPException(
            status_code=404,
            detail="Payments not found"
        )

    return PaymentDetails.model_validate(payment)