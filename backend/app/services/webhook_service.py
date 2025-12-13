"""
Webhook service - Webhook delivery and management
"""
import asyncio
from typing import List
import httpx

from sqlalchemy.orm import Session

from ..models import Relay, Message, Webhook, WebhookDelivery
from ..database import SessionLocal


class WebhookService:
    """Service for webhook operations"""
    
    MAX_RETRIES = 3
    TIMEOUT_SECONDS = 5.0
    
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
        
        for attempt in range(1, WebhookService.MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=WebhookService.TIMEOUT_SECONDS
                ) as client:
                    response = await client.post(webhook.url, json=payload)
                    
                    if response.status_code == 200:
                        await WebhookService._log_delivery(
                            webhook.id, message.id, "success", attempt
                        )
                        return
                        
            except Exception as e:
                error_msg = str(e)
                
                if attempt >= WebhookService.MAX_RETRIES:
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
