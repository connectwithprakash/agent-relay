"""
Agent Relay - FastAPI Application
Clean architecture with services and repositories
"""
import asyncio
import hashlib
import logging
import os
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .database import init_db, SessionLocal
from .models import Relay, Message, Webhook
from .schemas import (
    CreateRelayRequest, CreateRelayResponse,
    RelayState, SendMessageRequest, SendMessageResponse,
    MessageHistory, MessageSchema,
    RegisterWebhookRequest, RegisterWebhookResponse,
    WebhookSchema
)
from .services import PrivacyService, RelayService, WebhookService
from .repositories import RelayRepository, MessageRepository, WebhookRepository
from .utils.url_validator import validate_webhook_url

logger = logging.getLogger(__name__)

# CORS configuration
_DEFAULT_CORS_ORIGINS = ["http://localhost:5173", "http://localhost:3000"]


def _get_cors_origins() -> list[str]:
    """Get CORS origins from environment or use safe defaults."""
    env_origins = os.environ.get("CORS_ORIGINS")
    if env_origins:
        return [o.strip() for o in env_origins.split(",") if o.strip()]
    return _DEFAULT_CORS_ORIGINS


# Initialize FastAPI app
app = FastAPI(
    title="Agent Relay",
    description="Turn-based agent-to-agent communication with WebSocket and webhooks",
    version="2.0.0"
)

# CORS middleware - disable credentials when using wildcard origins
cors_origins = _get_cors_origins()
allow_credentials = cors_origins != ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        # relay_id -> list of (agent_name, websocket)
        self.active_connections: Dict[str, List[tuple[str, WebSocket]]] = {}

    async def connect(self, relay_id: str, agent_name: str, websocket: WebSocket):
        await websocket.accept()
        if relay_id not in self.active_connections:
            self.active_connections[relay_id] = []
        self.active_connections[relay_id].append((agent_name, websocket))

    def disconnect(self, relay_id: str, agent_name: str, websocket: WebSocket):
        if relay_id in self.active_connections:
            self.active_connections[relay_id] = [
                (name, ws) for name, ws in self.active_connections[relay_id]
                if ws != websocket
            ]

    async def broadcast_message(self, relay_id: str, message: dict):
        """Broadcast message to all connected WebSockets for this relay"""
        if relay_id not in self.active_connections:
            return

        disconnected = []
        for agent_name, websocket in self.active_connections[relay_id]:
            try:
                await websocket.send_json(message)
            except Exception:
                disconnected.append((agent_name, websocket))

        # Clean up disconnected websockets
        for agent_name, websocket in disconnected:
            self.disconnect(relay_id, agent_name, websocket)

manager = ConnectionManager()

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    init_db()

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Helper function
def get_relay_or_404(db: Session, relay_id: str) -> Relay:
    """Get relay by ID or raise 404"""
    repo = RelayRepository(db)
    relay = repo.get_by_id(relay_id)
    if not relay:
        raise HTTPException(status_code=404, detail=f"Relay {relay_id} not found")
    return relay

# API Endpoints

@app.post("/relays", response_model=CreateRelayResponse)
async def create_relay(req: CreateRelayRequest, db: Session = Depends(get_db)):
    """Create a new relay"""
    relay = RelayService.create_relay(db, req)
    return CreateRelayResponse(
        relay_id=relay.id,
        agent_names=relay.agent_names,
        current_turn=relay.agent_names[0]
    )

@app.get("/relays/{relay_id}", response_model=RelayState)
async def get_relay_state(relay_id: str, owner_id: str = None, db: Session = Depends(get_db)):
    """Get current relay state"""
    relay = get_relay_or_404(db, relay_id)

    if not PrivacyService.check_access(relay, owner_id):
        raise HTTPException(status_code=403, detail="Access denied. This relay is private.")

    return RelayService.get_relay_state(db, relay)

@app.post("/relays/{relay_id}/messages", response_model=SendMessageResponse)
async def send_message(relay_id: str, req: SendMessageRequest, db: Session = Depends(get_db)):
    """Send a message (only if your turn)"""
    relay = get_relay_or_404(db, relay_id)

    # Validate agent and turn using service
    try:
        agent, agent_index = RelayService.validate_agent(relay, req.agent)
        RelayService.validate_turn(relay, agent_index)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Create message
    message_repo = MessageRepository(db)
    message = Message(
        relay_id=relay_id,
        agent_index=agent_index,
        agent_name=agent,
        content=req.content,
        data=req.data,
        type=req.type
    )
    message = message_repo.create(message)

    # Switch turn
    next_turn = RelayService.advance_turn(db, relay)
    message_count = message_repo.count_by_relay_id(relay_id)

    # Prepare broadcast payload
    message_dict = {
        "id": message.id,
        "agent": message.agent_name,
        "content": message.content,
        "data": message.data,
        "type": message.type,
        "created_at": message.created_at.isoformat(),
        "next_turn": next_turn
    }

    # Broadcast via WebSocket and trigger webhooks
    asyncio.create_task(manager.broadcast_message(relay_id, message_dict))
    asyncio.create_task(WebhookService.trigger_webhooks(db, relay, message, relay.current_turn))

    return SendMessageResponse(
        status="ok",
        message_id=message.id,
        next_turn=next_turn,
        message_count=message_count
    )

@app.get("/relays/{relay_id}/history", response_model=MessageHistory)
async def get_message_history(
    relay_id: str,
    limit: int = 50,
    offset: int = 0,
    owner_id: str = None,
    db: Session = Depends(get_db)
):
    """Get message history"""
    relay = get_relay_or_404(db, relay_id)

    if not PrivacyService.check_access(relay, owner_id):
        raise HTTPException(status_code=403, detail="Access denied. This relay is private.")

    # Cap limit to prevent excessive queries
    limit = min(limit, 100)

    message_repo = MessageRepository(db)
    messages = message_repo.get_by_relay_id(relay_id, limit, offset)
    total_count = message_repo.count_by_relay_id(relay_id)

    return MessageHistory(
        relay_id=relay_id,
        messages=[
            MessageSchema(
                id=msg.id,
                agent=msg.agent_name,
                content=msg.content,
                data=msg.data,
                type=msg.type,
                created_at=msg.created_at.isoformat()
            )
            for msg in messages
        ],
        total_count=total_count
    )

@app.post("/relays/{relay_id}/webhooks", response_model=RegisterWebhookResponse)
async def register_webhook(
    relay_id: str,
    req: RegisterWebhookRequest,
    db: Session = Depends(get_db)
):
    """Register a webhook for receiving real-time updates"""
    relay = get_relay_or_404(db, relay_id)

    # Validate webhook URL to prevent SSRF
    if not validate_webhook_url(req.url):
        raise HTTPException(
            status_code=400,
            detail="Invalid webhook URL. Must be http/https and not target private networks."
        )

    try:
        _, agent_index = RelayService.validate_agent(relay, req.agent)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    webhook_repo = WebhookRepository(db)
    webhook = Webhook(
        relay_id=relay_id,
        agent_index=agent_index,
        agent_name=req.agent,
        url=req.url
    )
    webhook = webhook_repo.create(webhook)

    return RegisterWebhookResponse(
        webhook_id=webhook.id,
        url=webhook.url,
        agent=webhook.agent_name
    )

@app.get("/relays/{relay_id}/webhooks", response_model=List[WebhookSchema])
async def list_webhooks(relay_id: str, db: Session = Depends(get_db)):
    """List all webhooks for a relay"""
    get_relay_or_404(db, relay_id)

    webhook_repo = WebhookRepository(db)
    webhooks = webhook_repo.get_by_relay_id(relay_id)

    return [
        WebhookSchema(
            id=wh.id,
            agent=wh.agent_name,
            url=wh.url,
            created_at=wh.created_at.isoformat()
        )
        for wh in webhooks
    ]

@app.websocket("/relays/{relay_id}/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    relay_id: str,
    agent: str,
    api_key: Optional[str] = Query(default=None),
):
    """WebSocket endpoint for real-time message updates"""
    db = SessionLocal()
    try:
        relay_repo = RelayRepository(db)
        relay = relay_repo.get_by_id(relay_id)
        if not relay:
            await websocket.close(code=4004, reason="Relay not found")
            return

        if agent not in relay.agent_names:
            await websocket.close(code=4003, reason="Unknown agent")
            return

        # Authenticate WebSocket connection if relay has an API key
        if hasattr(relay, "api_key_hash") and relay.api_key_hash is not None:
            if not api_key:
                await websocket.close(code=4001, reason="Authentication required")
                return
            provided_hash = hashlib.sha256(api_key.encode()).hexdigest()
            if provided_hash != relay.api_key_hash:
                await websocket.close(code=4001, reason="Invalid API key")
                return

        await manager.connect(relay_id, agent, websocket)

        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(relay_id, agent, websocket)
    finally:
        db.close()

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "version": "2.0.0"}

# Run with: uvicorn app.main:app --reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
