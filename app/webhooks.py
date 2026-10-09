import httpx

from app.models import Payment


async def send_webhook(payment: Payment) -> None:
    if payment.status == "pending" or payment.processed_at is None:
        raise ValueError("Payment has not been processed")

    payload = {
        "payment_id": str(payment.id),
        "status": payment.status,
        "processed_at": payment.processed_at.isoformat()
    }

    async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
        response = await client.post(
            payment.webhook_url,
            json=payload
        )

        response.raise_for_status()