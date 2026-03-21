"""
Agent Relay - FastAPI Application
Clean architecture with services and repositories
"""
import asyncio
import hashlib
import logging
from contextlib import asynccontextmanager
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .config import settings
from .logging_config import setup_logging
from .middleware import RequestLoggingMiddleware
from .database import init_db, SessionLocal
from .models import Relay, Message, Webhook
from .schemas import (
    CreateRelayRequest, CreateRelayResponse,
    RelayState, SendMessageRequest, SendMessageResponse,
    MessageHistory, MessageSchema,
    RegisterWebhookRequest, RegisterWebhookResponse,
    WebhookSchema, RelayListResponse, RelayListItem,
)
from .services import PrivacyService, RelayService, WebhookService
from .repositories import RelayRepository, MessageRepository, WebhookRepository

logger = logging.getLogger("agent_relay.app")

# Rate limiter
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown"""
    setup_logging()
    if settings.environment == "development":
        init_db()
        logger.info("Database tables created (development mode)")
    logger.info("Agent Relay %s started (%s)", settings.app_version, settings.environment)
    yield
    logger.info("Agent Relay shutting down")

# Initialize FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="Turn-based agent-to-agent communication with WebSocket and webhooks",
    version=settings.app_version,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request logging middleware
app.add_middleware(RequestLoggingMiddleware)

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


# Auth helpers
async def get_api_key(
    authorization: str = Header(None),
    x_api_key: str = Header(None, alias="X-API-Key"),
) -> Optional[str]:
    """Extract API key from Authorization Bearer header or X-API-Key header."""
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return x_api_key


async def require_relay_auth(
    relay_id: str,
    api_key: Optional[str] = Depends(get_api_key),
    db: Session = Depends(get_db),
) -> Relay:
    """Verify API key for relay write operations."""
    repo = RelayRepository(db)
    relay = repo.get_by_id(relay_id)
    if not relay:
        raise HTTPException(status_code=404, detail=f"Relay {relay_id} not found")

    # Legacy relays without api_key_hash allow access without a key
    if relay.api_key_hash is None:
        return relay

    if api_key is None:
        raise HTTPException(status_code=401, detail="API key required")

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    if key_hash != relay.api_key_hash:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return relay


# API Endpoints

@app.post("/relays", response_model=CreateRelayResponse)
@limiter.limit("5/minute")
async def create_relay(request: Request, req: CreateRelayRequest, db: Session = Depends(get_db)):
    """Create a new relay"""
    relay, api_key = RelayService.create_relay(db, req)
    return CreateRelayResponse(
        relay_id=relay.id,
        agent_names=relay.agent_names,
        current_turn=relay.agent_names[0],
        api_key=api_key,
    )

@app.get("/relays", response_model=RelayListResponse)
@limiter.limit("30/minute")
async def list_relays(
    request: Request,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """List public relays with pagination"""
    repo = RelayRepository(db)
    message_repo = MessageRepository(db)
    relays = repo.list_public(limit, offset)
    total_count = repo.count_public()

    items = []
    for relay in relays:
        msg_count = message_repo.count_by_relay_id(relay.id)
        items.append(RelayListItem(
            relay_id=relay.id,
            agent_names=relay.agent_names,
            current_turn=relay.agent_names[relay.current_turn],
            message_count=msg_count,
            is_public=relay.is_public,
            created_at=relay.created_at.isoformat(),
        ))

    return RelayListResponse(relays=items, total_count=total_count)

@app.get("/relays/{relay_id}", response_model=RelayState)
async def get_relay_state(relay_id: str, owner_id: str = None, db: Session = Depends(get_db)):
    """Get current relay state"""
    relay = get_relay_or_404(db, relay_id)

    if not PrivacyService.check_access(relay, owner_id):
        raise HTTPException(status_code=403, detail="Access denied. This relay is private.")

    return RelayService.get_relay_state(db, relay)

@app.post("/relays/{relay_id}/messages", response_model=SendMessageResponse)
@limiter.limit("30/minute")
async def send_message(
    request: Request,
    req: SendMessageRequest,
    relay: Relay = Depends(require_relay_auth),
    db: Session = Depends(get_db),
):
    """Send a message (only if your turn). Requires API key for authenticated relays."""
    relay_id = relay.id

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
@limiter.limit("60/minute")
async def get_message_history(
    request: Request,
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
    relay: Relay = Depends(require_relay_auth),
    db: Session = Depends(get_db),
):
    """Register a webhook for receiving real-time updates. Requires API key for authenticated relays."""
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
async def websocket_endpoint(websocket: WebSocket, relay_id: str, agent: str):
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
    return {"status": "healthy", "version": settings.app_version}

# Run with: uvicorn app.main:app --reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
