import asyncio
import logging
from contextlib import suppress

from faststream import FastStream, AckPolicy
from faststream.rabbit.annotations import RabbitMessage

from app.broker import broker, payments_queue
from app.db import SessionFactory
from app.dlq import save_dlq_task, run_dlq_publisher
from app.schemas import PaymentMessage
from app.services import process_payment
from app.webhooks import send_webhook

app = FastStream(broker)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

dlq_publisher_task: asyncio.Task[None] | None = None


@app.after_startup
async def start_dlq_publisher() -> None:
    global dlq_publisher_task

    dlq_publisher_task = asyncio.create_task(
        run_dlq_publisher(),
        name="dlq-publisher",
    )


@app.on_shutdown
async def stop_dlq_publisher() -> None:
    if dlq_publisher_task is None:
        return

    dlq_publisher_task.cancel()

    with suppress(asyncio.CancelledError):
        await dlq_publisher_task


async def save_failed_message(
    message: RabbitMessage,
    error: Exception,
) -> None:
    while True:
        try:
            await save_dlq_task(message, error)
        except Exception:
            logger.exception(
                "Saving DLQ task failed; retrying in 3 seconds"
            )
            await asyncio.sleep(3)
        else:
            break

    await message.ack()
    logger.info("Failed message saved for DLQ delivery")


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

            await save_failed_message(message, e)

            return
        else:
            await message.ack()
            logger.info(
                "Payment %s completed with status %s",
                payment.id,
                payment.status,
            )
            return

