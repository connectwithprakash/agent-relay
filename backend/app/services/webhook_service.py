"""
Webhook service - Webhook delivery and management
"""
import asyncio
from typing import Optional
import httpx
from loguru import logger

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Relay, Message, Webhook, WebhookDelivery
from ..database import SessionLocal
from ..utils.url_validator import validate_webhook_url
from ..utils.safe_http_transport import SafeAsyncHTTPTransport


# Shared httpx client with connection pooling to avoid per-request client overhead
_http_client: Optional[httpx.AsyncClient] = None
_delivery_tasks: set[asyncio.Task[None]] = set()


def _get_client() -> httpx.AsyncClient:
    """Get or lazily create a shared httpx.AsyncClient with connection pooling."""
    global _http_client
    if _http_client is None:
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=5)
        _http_client = httpx.AsyncClient(
            timeout=settings.webhook_timeout_seconds,
            limits=limits,
            transport=SafeAsyncHTTPTransport(limits=limits),
        )
    return _http_client


async def close_http_client() -> None:
    """Drain pending deliveries, then close and reset the shared client."""
    global _http_client
    if _delivery_tasks:
        await asyncio.gather(*tuple(_delivery_tasks), return_exceptions=True)
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


class WebhookService:
    """Service for webhook operations"""

    @staticmethod
    async def trigger_webhooks(
        db: Session,
        relay: Relay,
        message: Message,
        target_agent_index: int
    ) -> None:
        """Trigger webhooks for agents who should receive this message"""
        webhooks = db.query(Webhook).filter(
            Webhook.relay_id == relay.id,
            Webhook.agent_index == target_agent_index
        ).all()

        for webhook in webhooks:
            task = asyncio.create_task(
                WebhookService.deliver_webhook(webhook, message)
            )
            _delivery_tasks.add(task)
            task.add_done_callback(_delivery_tasks.discard)

    @staticmethod
    async def deliver_webhook(webhook: Webhook, message: Message) -> None:
        """Deliver a message to a webhook with retry logic"""
        payload = {
            "relay_id": message.relay_id,
            "agent": message.agent_name,
            "content": message.content,
            "data": message.data,
            "type": message.type,
            "message_id": message.id,
            "created_at": message.created_at.isoformat()
        }

        client = _get_client()
        for attempt in range(1, settings.webhook_max_retries + 1):
            try:
                # Resolve and validate again immediately before every connection.
                # Registration-time checks alone are vulnerable to DNS changes.
                if not validate_webhook_url(webhook.url):
                    await WebhookService._log_delivery(
                        webhook.id, message.id, "failed", attempt,
                        "Webhook URL no longer resolves to a public address",
                    )
                    logger.warning("Blocked unsafe webhook target {}", webhook.id)
                    return
                response = await client.post(webhook.url, json=payload)

                if 200 <= response.status_code < 300:
                    await WebhookService._log_delivery(
                        webhook.id, message.id, "success", attempt
                    )
                    logger.info("Webhook {} delivered (attempt {})", webhook.id, attempt)
                    return

                if 400 <= response.status_code < 500:
                    # Client error - don't retry, log as failed immediately
                    error_msg = f"HTTP {response.status_code}: client error"
                    logger.warning(
                        "Webhook {} failed with client error {}, not retrying",
                        webhook.id, response.status_code,
                    )
                    await WebhookService._log_delivery(
                        webhook.id, message.id, "failed", attempt, error_msg
                    )
                    return

                # 5xx server error - retry with backoff
                error_msg = f"HTTP {response.status_code}: server error"
                logger.warning("Webhook {} attempt {} got {}", webhook.id, attempt, response.status_code)

                if attempt >= settings.webhook_max_retries:
                    await WebhookService._log_delivery(
                        webhook.id, message.id, "failed", attempt, error_msg
                    )
                else:
                    await asyncio.sleep(2 ** (attempt - 1))

            except Exception as e:
                error_msg = str(e)
                logger.warning("Webhook {} attempt {} failed: {}", webhook.id, attempt, error_msg)

                if attempt >= settings.webhook_max_retries:
                    await WebhookService._log_delivery(
                        webhook.id, message.id, "failed", attempt, error_msg
                    )
                else:
                    # Exponential backoff: 1s, 2s, 4s
                    await asyncio.sleep(2 ** (attempt - 1))

    @staticmethod
    async def _log_delivery(
        webhook_id: int,
        message_id: int,
        status: str,
        attempts: int,
        error_message: str = None
    ) -> None:
        """Log webhook delivery result"""
        db = SessionLocal()
        try:
            delivery = WebhookDelivery(
                webhook_id=webhook_id,
                message_id=message_id,
                status=status,
                attempts=attempts,
                error_message=error_message
            )
            db.add(delivery)
            db.commit()
        finally:
            db.close()
