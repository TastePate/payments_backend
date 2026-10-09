import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.broker import broker, dead_letter_queue

from hashlib import sha256

from faststream.rabbit.annotations import RabbitMessage
from sqlalchemy.dialects.postgresql import insert

from app.db import SessionFactory
from app.models import DlqTask


def get_source_key(message: RabbitMessage) -> str:
    message_id = message.raw_message.message_id

    if message_id:
        identity = b"id:" + message_id.encode("utf-8")
    else:
        identity = b"body:" + message.body

    return sha256(identity).hexdigest()


async def save_dlq_task(
    message: RabbitMessage,
    error: Exception,
) -> None:
    statement = (
        insert(DlqTask)
        .values(
            source_key=get_source_key(message),
            payload={
                "original_body": message.body.decode(
                    "utf-8", errors="replace"
                ),
                "attempts": 3,
                "error": f"{type(error).__name__}: {error}",
            },
        )
        .on_conflict_do_nothing(index_elements=["source_key"])
    )

    async with SessionFactory() as session:
        async with session.begin():
            await session.execute(statement)


logger = logging.getLogger(__name__)


async def publish_next_dlq_task() -> bool:
    async with SessionFactory() as session:
        async with session.begin():
            query = (
                select(DlqTask)
                .where(DlqTask.published_at.is_(None))
                .order_by(DlqTask.created_at, DlqTask.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            task = await session.scalar(query)

            if task is None:
                return False

            await broker.publish(
                task.payload,
                queue=dead_letter_queue,
                persist=True,
                mandatory=True,
                timeout=5,
                message_id=str(task.id),
            )

            task.published_at = datetime.now(UTC)

        logger.info("DLQ task %s published", task.id)
        return True


async def run_dlq_publisher() -> None:
    while True:
        try:
            await broker.declare_queue(dead_letter_queue)
            published = await publish_next_dlq_task()

            if not published:
                await asyncio.sleep(1)
        except Exception:
            logger.exception(
                "DLQ publisher failed; retrying in 3 seconds"
            )
            await asyncio.sleep(3)