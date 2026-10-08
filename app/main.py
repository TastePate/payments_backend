import asyncio
import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Security, HTTPException, FastAPI, Depends
from fastapi.security import APIKeyHeader
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import engine, get_session

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
    try:
        yield
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

