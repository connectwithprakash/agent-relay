"""
Webhook registration and listing endpoints
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_agent
from ..database import get_db
from ..models import Relay, Webhook
from ..repositories import WebhookRepository
from ..schemas import (
    RegisterWebhookRequest, RegisterWebhookResponse,
    WebhookSchema,
)
from ..services import RelayService
from ..utils.url_validator import validate_webhook_url

router = APIRouter()


@router.post("/relays/{relay_id}/webhooks", response_model=RegisterWebhookResponse)
async def register_webhook(
    relay_id: str,
    req: RegisterWebhookRequest,
    agent_info: dict = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """Register a webhook for receiving real-time updates. Requires token for authenticated relays."""
    relay = agent_info["relay"]

    # Validate webhook URL to prevent SSRF
    if not validate_webhook_url(req.url):
        raise HTTPException(
            status_code=400,
            detail="Invalid webhook URL. Must be http/https and not target private networks."
        )

    authenticated_agent = agent_info["agent_name"]
    try:
        _, agent_index = RelayService.validate_agent(relay, req.agent)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if req.agent != authenticated_agent:
        raise HTTPException(
            status_code=403,
            detail="A participant may only register its own webhook",
        )


    webhook_repo = WebhookRepository(db)
    webhook = Webhook(
        relay_id=relay_id,
        agent_index=agent_index,
        agent_name=authenticated_agent,
        url=req.url
    )
    webhook = webhook_repo.create(webhook)

    return RegisterWebhookResponse(
        webhook_id=webhook.id,
        url=webhook.url,
        agent=webhook.agent_name
    )


@router.get("/relays/{relay_id}/webhooks", response_model=List[WebhookSchema])
async def list_webhooks(
    agent_info: dict = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """List all webhooks for a relay. Requires token for authenticated relays."""
    relay = agent_info["relay"]
    relay_id = relay.id

    webhook_repo = WebhookRepository(db)
    webhooks = [
        webhook
        for webhook in webhook_repo.get_by_relay_id(relay_id)
        if webhook.agent_name == agent_info["agent_name"]
    ]

    return [
        WebhookSchema(
            id=wh.id,
            agent=wh.agent_name,
            url=wh.url,
            created_at=wh.created_at.isoformat()
        )
        for wh in webhooks
    ]
