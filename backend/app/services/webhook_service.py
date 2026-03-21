"""
Webhook service - Webhook delivery and management
"""
import asyncio
import logging
from typing import List, Optional
import httpx

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Relay, Message, Webhook, WebhookDelivery
from ..database import SessionLocal

logger = logging.getLogger("agent_relay.webhooks")

# Shared httpx client with connection pooling to avoid per-request client overhead
_http_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    """Get or lazily create a shared httpx.AsyncClient with connection pooling."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=settings.webhook_timeout_seconds,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
        )
    return _http_client


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
            asyncio.create_task(
                WebhookService.deliver_webhook(webhook, message)
            )

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
                response = await client.post(webhook.url, json=payload)

                if response.status_code == 200:
                    await WebhookService._log_delivery(
                        webhook.id, message.id, "success", attempt
                    )
                    logger.info("Webhook %d delivered (attempt %d)", webhook.id, attempt)
                    return

            except Exception as e:
                error_msg = str(e)
                logger.warning("Webhook %d attempt %d failed: %s", webhook.id, attempt, error_msg)

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
