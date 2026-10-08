from faststream.rabbit import RabbitBroker, RabbitQueue, Channel
from faststream.security import SASLPlaintext

from app.config import settings

broker = RabbitBroker(
    host=settings.rabbitmq_host,
    port=settings.rabbitmq_port,
    security=SASLPlaintext(
        username=settings.rabbitmq_user,
        password=settings.rabbitmq_password.get_secret_value(),
    ),
    default_channel=Channel(
        publisher_confirms=True,
        on_return_raises=True,
    )
)

payments_queue = RabbitQueue(
    "payments.new",
    durable=True
)
