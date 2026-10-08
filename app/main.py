import hmac

from fastapi import Security, HTTPException, FastAPI, Depends
from fastapi.security import APIKeyHeader

from app.config import settings


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


app = FastAPI(
    title="Payment Processing Service",
    version="0.1.0",
    dependencies=[Depends(require_api_key)],
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}