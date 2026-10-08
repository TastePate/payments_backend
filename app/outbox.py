import asyncio
import logging
from datetime import datetime, UTC

from sqlalchemy import select

from app.broker import broker, payments_queue
from app.db import SessionFactory
from app.models import OutboxEvent


async def publish_next_event() -> bool:
    async with SessionFactory() as session:
        async with session.begin():
            query = (
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.created_at, OutboxEvent.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            event = await session.scalar(query)

            if event is None:
                return False

            await broker.publish(
                event.payload,
                queue=payments_queue,
                persist=True,
                mandatory=True,
                timeout=5,
                message_id=str(event.id),
            )

            event.published_at = datetime.now(UTC)

        return True


logger = logging.getLogger(__name__)


async def run_outbox_publisher() -> None:
    while True:
        try:
            async with broker:
                await broker.declare_queue(payments_queue)

                while True:
                    published = await publish_next_event()

                    if not published:
                        await asyncio.sleep(1)
        except Exception:
            logger.exception("Outbox publisher failed; retrying in 3 seconds")
            await asyncio.sleep(3)