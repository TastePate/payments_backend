import asyncio
import logging

from faststream import FastStream, AckPolicy
from faststream.rabbit.annotations import RabbitMessage

from app.broker import broker, payments_queue, dead_letter_queue
from app.db import SessionFactory
from app.schemas import PaymentMessage
from app.services import process_payment
from app.webhooks import send_webhook

app = FastStream(broker)
logger = logging.getLogger(__name__)


async def send_to_dlq(
        message: RabbitMessage,
        error: Exception
) -> None:
    while True:
        try:
            await broker.declare_queue(dead_letter_queue)

            await broker.publish(
                {
                    "original_body": message.body.decode(
                        "utf-8", errors="replace"
                    ),
                    "attempts": 3,
                    "error": f"{type(error).__name__}: {error}",
                },
                queue=dead_letter_queue,
                persist=True,
                mandatory=True,
                timeout=5,
            )
        except Exception:
            logger.exception("DLQ transfer failed; retrying in 3 seconds")
            await asyncio.sleep(3)
        else:
            break

    await message.ack()


@broker.subscriber(payments_queue, ack_policy=AckPolicy.MANUAL, decoder=lambda msg: msg.body)
async def consume_payment(message: RabbitMessage) -> None:
    for attempt in range(1, 4):
        try:
            data = PaymentMessage.model_validate_json(message.body)

            async with SessionFactory() as session:
                payment = await process_payment(session, data.payment_id)

            if payment is None:
                raise ValueError(f"Payment {data.payment_id} not found")

            await send_webhook(payment)

        except Exception as e:
            logger.exception(f"Attempt {attempt}/3 failed")

            if attempt < 3:
                await asyncio.sleep(2 ** (attempt - 1))
                continue

            await send_to_dlq(message, e)

            return
        else:
            await message.ack()
            logger.info(
                "Payment %s completed with status %s",
                payment.id,
                payment.status,
            )
            return

