"""Transactional webhook outbox and asynchronous delivery worker."""
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

import httpx
from loguru import logger
from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session, aliased

from ..config import settings
from ..database import SessionLocal
from ..models import Message, Relay, Webhook, WebhookDelivery, WebhookOutbox
from ..utils.safe_http_transport import SafeAsyncHTTPTransport
from ..utils.url_validator import validate_webhook_url


_http_client: Optional[httpx.AsyncClient] = None
_dispatcher_task: Optional[asyncio.Task[None]] = None
_stop_event: Optional[asyncio.Event] = None
_wake_event: Optional[asyncio.Event] = None


def _utcnow() -> datetime:
    """Return UTC matching the database's timezone-naive DateTime columns."""
    return datetime.utcnow()


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=5)
        _http_client = httpx.AsyncClient(
            timeout=settings.webhook_timeout_seconds,
            limits=limits,
            transport=SafeAsyncHTTPTransport(limits=limits),
        )
    return _http_client


class WebhookService:
    """Persist and deliver webhook events with at-least-once semantics."""

    @staticmethod
    def enqueue_webhooks(
        db: Session,
        relay: Relay,
        message: Message,
        target_agent_index: int,
    ) -> int:
        """Add matching webhook events to the caller's transaction."""
        webhooks = db.query(Webhook).filter(
            Webhook.relay_id == relay.id,
            Webhook.agent_index == target_agent_index,
        ).all()
        payload = {
            "relay_id": message.relay_id,
            "agent": message.agent_name,
            "content": message.content,
            "data": message.data,
            "type": message.type,
            "message_id": message.id,
            "created_at": message.created_at.isoformat(),
        }
        now = _utcnow()
        for webhook in webhooks:
            db.add(
                WebhookOutbox(
                    webhook_id=webhook.id,
                    message_id=message.id,
                    relay_id=message.relay_id,
                    target_url=webhook.url,
                    payload=payload,
                    status="pending",
                    attempts=0,
                    next_attempt_at=now,
                    created_at=now,
                )
            )
        return len(webhooks)

    @staticmethod
    def notify_dispatcher() -> None:
        """Wake the local dispatcher after an outbox transaction commits."""
        if _wake_event is not None:
            _wake_event.set()

    @staticmethod
    def _claim_batch() -> list[dict]:
        """Claim due or abandoned events with compare-and-swap updates."""
        db = SessionLocal()
        now = _utcnow()
        stale_before = now - timedelta(seconds=settings.webhook_outbox_lease_seconds)
        claimed: list[dict] = []
        try:
            exhausted = db.query(WebhookOutbox).filter(
                WebhookOutbox.status == "processing",
                WebhookOutbox.locked_at < stale_before,
                WebhookOutbox.attempts >= settings.webhook_max_retries,
            ).update(
                {
                    "status": "dead",
                    "locked_at": None,
                    "lock_token": None,
                    "last_error": "Delivery worker lease expired at retry limit",
                },
                synchronize_session=False,
            )
            if exhausted:
                logger.error("Dead-lettered {} expired webhook deliveries", exhausted)
            older = aliased(WebhookOutbox)
            no_earlier_event = ~db.query(older.id).filter(
                older.webhook_id == WebhookOutbox.webhook_id,
                older.id < WebhookOutbox.id,
                older.status.in_(("pending", "processing")),
            ).exists()
            candidates = db.query(WebhookOutbox).filter(
                or_(
                    and_(
                        WebhookOutbox.status == "pending",
                        WebhookOutbox.next_attempt_at <= now,
                    ),
                    and_(
                        WebhookOutbox.status == "processing",
                        WebhookOutbox.locked_at < stale_before,
                    ),
                ),
                no_earlier_event,
                WebhookOutbox.attempts < settings.webhook_max_retries,
            ).order_by(WebhookOutbox.next_attempt_at, WebhookOutbox.id).limit(
                settings.webhook_outbox_batch_size
            ).all()

            for candidate in candidates:
                token = str(uuid4())
                eligible = or_(
                    and_(
                        WebhookOutbox.status == "pending",
                        WebhookOutbox.next_attempt_at <= now,
                    ),
                    and_(
                        WebhookOutbox.status == "processing",
                        WebhookOutbox.locked_at < stale_before,
                    ),
                )
                result = db.execute(
                    update(WebhookOutbox)
                    .where(
                        WebhookOutbox.id == candidate.id,
                        eligible,
                        no_earlier_event,
                        WebhookOutbox.attempts < settings.webhook_max_retries,
                    )
                    .values(
                        status="processing",
                        attempts=WebhookOutbox.attempts + 1,
                        locked_at=now,
                        lock_token=token,
                    )
                    .execution_options(synchronize_session=False)
                )
                if result.rowcount == 1:
                    claimed.append(
                        {
                            "id": candidate.id,
                            "webhook_id": candidate.webhook_id,
                            "message_id": candidate.message_id,
                            "target_url": candidate.target_url,
                            "payload": candidate.payload,
                            "attempts": candidate.attempts + 1,
                            "lock_token": token,
                        }
                    )
            db.commit()
            return claimed
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _complete_attempt(
        event: dict,
        *,
        delivered: bool,
        retryable: bool,
        error_message: str | None = None,
    ) -> None:
        """Persist one attempt result only when this worker still owns the lease."""
        db = SessionLocal()
        now = _utcnow()
        attempts = event["attempts"]
        terminal = delivered or not retryable or attempts >= settings.webhook_max_retries
        if delivered:
            status = "delivered"
            next_attempt_at = now
        elif terminal:
            status = "dead"
            next_attempt_at = now
        else:
            status = "pending"
            delay = settings.webhook_outbox_retry_base_seconds * (2 ** (attempts - 1))
            next_attempt_at = now + timedelta(seconds=delay)

        try:
            result = db.execute(
                update(WebhookOutbox)
                .where(
                    WebhookOutbox.id == event["id"],
                    WebhookOutbox.status == "processing",
                    WebhookOutbox.lock_token == event["lock_token"],
                )
                .values(
                    status=status,
                    attempts=attempts,
                    next_attempt_at=next_attempt_at,
                    locked_at=None,
                    lock_token=None,
                    last_error=error_message,
                    delivered_at=now if delivered else None,
                )
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                db.rollback()
                logger.warning("Webhook outbox event {} lost its lease", event["id"])
                return
            webhook_exists = db.get(Webhook, event["webhook_id"]) is not None
            message_exists = db.get(Message, event["message_id"]) is not None
            if webhook_exists and message_exists:
                db.add(
                    WebhookDelivery(
                        webhook_id=event["webhook_id"],
                        message_id=event["message_id"],
                        status=(
                            "success"
                            if delivered
                            else ("failed" if terminal else "retrying")
                        ),
                        attempts=attempts,
                        error_message=error_message,
                    )
                )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    async def _deliver_event(event: dict) -> None:
        if not await asyncio.to_thread(validate_webhook_url, event["target_url"]):
            await asyncio.to_thread(
                WebhookService._complete_attempt,
                event,
                delivered=False,
                retryable=False,
                error_message="Webhook URL no longer resolves to a public address",
            )
            logger.warning("Blocked unsafe webhook outbox event {}", event["id"])
            return

        try:
            response = await _get_client().post(
                event["target_url"],
                json=event["payload"],
                headers={
                    "X-Agent-Relay-Event-ID": str(event["id"]),
                    "X-Agent-Relay-Attempt": str(event["attempts"]),
                },
            )
            delivered = 200 <= response.status_code < 300
            retryable = response.status_code >= 500 or response.status_code in (408, 429)
            error = None if delivered else f"HTTP {response.status_code}"
        except Exception as exc:
            delivered = False
            retryable = True
            error = str(exc)

        await asyncio.to_thread(
            WebhookService._complete_attempt,
            event,
            delivered=delivered,
            retryable=retryable,
            error_message=error,
        )

    @staticmethod
    async def _dispatcher() -> None:
        assert _stop_event is not None
        assert _wake_event is not None
        while not _stop_event.is_set():
            try:
                events = await asyncio.to_thread(WebhookService._claim_batch)
                if events:
                    await asyncio.gather(
                        *(WebhookService._deliver_event(event) for event in events)
                    )
                    continue
                _wake_event.clear()
                try:
                    await asyncio.wait_for(
                        _wake_event.wait(), timeout=settings.webhook_outbox_poll_seconds
                    )
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Webhook outbox dispatcher iteration failed")
                await asyncio.sleep(settings.webhook_outbox_poll_seconds)


async def start_webhook_dispatcher() -> None:
    """Start one dispatcher for this application process."""
    global _dispatcher_task, _stop_event, _wake_event
    if _dispatcher_task is not None and not _dispatcher_task.done():
        return
    _stop_event = asyncio.Event()
    _wake_event = asyncio.Event()
    _dispatcher_task = asyncio.create_task(
        WebhookService._dispatcher(), name="webhook-outbox-dispatcher"
    )


async def close_webhook_dispatcher() -> None:
    """Stop claiming work, finish the active batch, then close HTTP resources."""
    global _dispatcher_task, _stop_event, _wake_event, _http_client
    if _stop_event is not None:
        _stop_event.set()
    if _wake_event is not None:
        _wake_event.set()
    if _dispatcher_task is not None:
        try:
            await asyncio.wait_for(
                _dispatcher_task,
                timeout=(
                    settings.webhook_timeout_seconds
                    + settings.webhook_outbox_lease_seconds
                ),
            )
        except asyncio.TimeoutError:
            _dispatcher_task.cancel()
            await asyncio.gather(_dispatcher_task, return_exceptions=True)
        _dispatcher_task = None
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
    _stop_event = None
    _wake_event = None