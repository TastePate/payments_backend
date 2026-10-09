# Асинхронный сервис процессинга платежей

Микросервис принимает платежи через HTTP API, обрабатывает их через RabbitMQ и отправляет результат на webhook клиента. Шлюз эмулируется: 2–5 секунд обработки, 90% результатов `succeeded`, 10% — `failed`.

## Стек технологий

Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2.0, PostgreSQL 17, RabbitMQ 4, FastStream, Alembic, HTTPX и Docker Compose. Версии Python-зависимостей зафиксированы в `requirements.txt`.

## Архитектура

1. API сохраняет платёж `pending` и событие `outbox_events` одной транзакцией, возвращает `202 Accepted`.
2. Outbox publisher в процессе API публикует событие в `payments.new`.
3. Consumer эмулирует обработку, сохраняет результат и отправляет webhook. Уже завершённый платёж повторно не обрабатывается шлюзом.
4. После успешного webhook consumer отправляет ACK. После трёх ошибок сохраняет задачу в `dlq_tasks` и делает ACK **после commit**.
5. Фоновый отправитель в процессе consumer публикует сохранённые задачи в `payments.dlq` и заполняет `published_at` после подтверждения RabbitMQ.

Таблицы: `payments` — платежи, `outbox_events` — события создания, `dlq_tasks` — задачи доставки в DLQ.

## Запуск через Docker Compose

Нужны Git и Docker с Compose v2. В Docker Desktop используйте Linux containers. Для запуска основных сервисов локальный Python не требуется.

Первый запуск в PowerShell:

```powershell
git clone https://github.com/TastePate/payments_backend.git
cd payments_backend
Copy-Item .env.example .env
```

В Linux/macOS используйте `cp .env.example .env`. Если `.env` уже настроен, сохраните существующий файл.

Заполните в `.env` ключ `API_KEY` (минимум 16 символов) и учётные данные PostgreSQL/RabbitMQ. Замените `your_password` у `RABBITMQ_PASSWORD`.

Из корня проекта:

```shell
docker compose config --quiet
docker compose up --build -d
docker compose ps -a
```

Compose запускает PostgreSQL, RabbitMQ, API и consumer. Сервис `migrate` автоматически применяет миграции; его состояние `Exited (0)` ожидаемо.

- API: [http://127.0.0.1:8000](http://127.0.0.1:8000).
- RabbitMQ Management: [http://127.0.0.1:15672](http://127.0.0.1:15672). Вход — `RABBITMQ_USER` и `RABBITMQ_PASSWORD`.
- PostgreSQL доступен с компьютера на `127.0.0.1:55432`, RabbitMQ AMQP — на `127.0.0.1:5672` при стандартных настройках.

Все endpoints требуют `X-API-Key`. Ниже используется пример `local-development-key`; замените его своим ключом. API работает по HTTP, Swagger/ReDoc отключены.

## API платежей: примеры для Postman

### Проверка доступности

```http
GET http://127.0.0.1:8000/health
X-API-Key: local-development-key
```

Ответ `200 OK`: `{"status":"ok","database":"ok"}`. Проверяется API и PostgreSQL.

### Создание платежа

```http
POST http://127.0.0.1:8000/api/v1/payments
Content-Type: application/json
X-API-Key: local-development-key
Idempotency-Key: order-demo-001
```

В Postman выберите **Body → raw → JSON**:

```json
{
  "amount": "100.00",
  "currency": "RUB",
  "description": "Оплата заказа",
  "metadata": {"order_id": "demo-001"},
  "webhook_url": "http://host.docker.internal:9000/webhook"
}
```

`amount` — положительное число, до 18 цифр и 2 знаков после запятой; `currency` — RUB/USD/EUR; `webhook_url` — HTTP/HTTPS URL. `description` необязателен, допускает `null`, до 1000 символов; `metadata` — JSON-объект, по умолчанию `{}`. Неизвестные поля отклоняются.

Пример ответа `202 Accepted`:

```json
{
  "payment_id": "e895116f-ab09-471b-b1ee-ae2dadb2151c",
  "status": "pending",
  "created_at": "2026-10-09T09:43:30Z"
}
```

`202` означает, что запрос принят и сохранён. Итоговый статус появится после обработки.

### Получение платежа

Подставьте `payment_id` из ответа создания:

```http
GET http://127.0.0.1:8000/api/v1/payments/e895116f-ab09-471b-b1ee-ae2dadb2151c
X-API-Key: local-development-key
```

Ответ `200 OK` содержит сумму, валюту, описание, metadata, статус, ключ идемпотентности, webhook URL и временные метки. До обработки `processed_at = null`, после — время завершения.

### Идемпотентность и ошибки

Клиент создаёт новый `Idempotency-Key` для каждой новой оплаты и повторно использует его при повторе того же запроса. Заголовок обязателен, длина — 1–255 символов.

- Тот же ключ и тело → `202` с прежним `payment_id`, без нового платежа и события.
- Тот же ключ, изменённая сумма или другие данные → `409 Conflict`.
- Неверный/отсутствующий API key → `401`.
- Некорректные поля, UUID или отсутствие `Idempotency-Key` → `422`.
- Несуществующий платёж → `404`; недоступная БД на `/health` → `503`.

## Webhook, повторные попытки и DLQ

Consumer отправляет POST на `webhook_url`:

```json
{
  "payment_id": "e895116f-ab09-471b-b1ee-ae2dadb2151c",
  "status": "succeeded",
  "processed_at": "2026-10-09T09:43:33.662696+00:00"
}
```

Ответ HTTP `2xx` подтверждает доставку; остальные статусы и сетевые ошибки вызывают повторные попытки. Всего три попытки, с паузами 1 и 2 секунды. Таймауты сетевых операций — 5 секунд.

После третьей ошибки consumer сохраняет исходное тело, число попыток и причину ошибки в `dlq_tasks`. Уникальный `source_key` предотвращает повторную запись одной задачи. ACK исходного сообщения выполняется после успешного сохранения.

Фоновый отправитель независимо публикует задачи с `published_at = NULL` в `payments.dlq`. При ошибке публикации ждёт 3 секунды и повторяет попытку. При ошибке сохранения задачи consumer не делает ACK и повторяет запись в БД.

- `failed` — допустимый результат шлюза: он тоже отправляется через webhook.
- Ошибка webhook не меняет статус платежа; платёж может быть `succeeded`, а сообщение попасть в DLQ.
- Автоматического повторного запуска сообщений из DLQ нет.
- Публикация выполняется по модели **at least once**: возможны дубликаты сообщений и webhook. Приёмнику следует учитывать повторные уведомления по `payment_id`.
- Три попытки считаются в памяти текущей доставки; после перезапуска или потери соединения счётчик может начаться заново.

## Ручная проверка через Postman

Для временного приёмника в Windows нужен Python 3.13. Подготовьте локальное окружение, если его ещё нет: `python -m venv .venv`, затем `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.

В отдельном PowerShell из корня проекта:

```powershell
@'
from fastapi import FastAPI, Request
import uvicorn

receiver = FastAPI()

@receiver.post("/webhook")
async def webhook(request: Request):
    print(await request.json(), flush=True)
    return {"received": True}

uvicorn.run(receiver, host="0.0.0.0", port=9000)
'@ | .\.venv\Scripts\python.exe -B -
```

Для consumer в Docker Desktop укажите `http://host.docker.internal:9000/webhook`. При локальном запуске consumer — `http://127.0.0.1:9000/webhook`.

1. Создайте платёж с новым ключом: ожидайте `202`, уведомление в терминале и итоговый статус через GET.
2. Повторите запрос с прежним ключом: должен вернуться тот же платёж. Измените сумму с прежним ключом: ожидайте `409`.
3. Остановите приёмник через `Ctrl+C` и создайте новый платёж. После трёх ошибок задача сохраняется в БД и публикуется в `payments.dlq`; проверьте её в RabbitMQ Management.

## Структура проекта

```text
payments_backend/
├── app/
│   ├── main.py          # API, авторизация, запуск outbox
│   ├── config.py        # Настройки окружения
│   ├── db.py            # Engine, сессии, Base
│   ├── models.py        # Payment, OutboxEvent, DlqTask
│   ├── schemas.py       # Валидация запросов и сообщений
│   ├── services.py      # Транзакции и обработка платежей
│   ├── outbox.py        # Публикация событий создания
│   ├── broker.py        # RabbitMQ и очереди
│   ├── consumer.py      # Обработка, retry, ACK, запуск DLQ publisher
│   ├── dlq.py           # Сохранение задач и фоновая отправка в DLQ
│   ├── gateway.py       # Эмуляция шлюза
│   └── webhooks.py      # Отправка уведомлений
├── migrations/
│   └── versions/
├── alembic.ini
├── compose.yaml
├── Dockerfile
├── .dockerignore
├── .env.example
├── requirements.txt
└── README.md
```

## Логи и остановка

```shell
docker compose logs -f api consumer
```

`Ctrl+C` завершает просмотр логов. Для остановки сервисов используйте `docker compose down`; именованные volumes сохраняются. После изменения кода повторите `docker compose up --build -d`.
