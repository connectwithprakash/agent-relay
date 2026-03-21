"""
Agent Relay - FastAPI Application
Clean architecture with services and repositories
"""
import asyncio
from typing import Dict, List
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

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

# Initialize FastAPI app
app = FastAPI(
    title="Agent Relay",
    description="Turn-based agent-to-agent communication with WebSocket and webhooks",
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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
            # Clean up empty relay entries to prevent unbounded memory growth
            if not self.active_connections[relay_id]:
                del self.active_connections[relay_id]

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

@app.get("/relays", response_model=RelayListResponse)
async def list_relays(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """List public relays with pagination"""
    repo = RelayRepository(db)
    message_repo = MessageRepository(db)
    relays = repo.list_public(limit, offset)
    total_count = repo.count_public()

    # Batch fetch message counts to avoid N+1 queries
    relay_ids = [relay.id for relay in relays]
    counts = message_repo.count_by_relay_ids(relay_ids)

    items = []
    for relay in relays:
        items.append(RelayListItem(
            relay_id=relay.id,
            agent_names=relay.agent_names,
            current_turn=relay.agent_names[relay.current_turn],
            message_count=counts.get(relay.id, 0),
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
    return {"status": "healthy", "version": "2.0.0"}

# Run with: uvicorn app.main:app --reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
