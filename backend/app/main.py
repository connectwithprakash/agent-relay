"""
Enhanced Agent Relay - Main FastAPI Application
Features: WebSocket, Webhooks, Turn-based messaging
"""
import asyncio
import secrets
from datetime import datetime
from typing import Dict, List, Set
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import httpx

from .database import init_db, SessionLocal, get_db_session
from .models import Relay, Message, Webhook, WebhookDelivery
from .schemas import (
    CreateRelayRequest, CreateRelayResponse,
    RelayState, SendMessageRequest, SendMessageResponse,
    MessageHistory, MessageSchema,
    RegisterWebhookRequest, RegisterWebhookResponse,
    WebhookSchema
)

# Initialize FastAPI app
app = FastAPI(
    title="Agent Relay v2",
    description="Enhanced turn-based agent-to-agent communication with WebSocket and webhooks",
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

# Helper functions
def generate_relay_id() -> str:
    """Generate unique relay ID"""
    return f"relay-{secrets.token_urlsafe(8)}"

def get_relay_or_404(db: Session, relay_id: str) -> Relay:
    """Get relay by ID or raise 404"""
    relay = db.query(Relay).filter(Relay.id == relay_id).first()
    if not relay:
        raise HTTPException(status_code=404, detail=f"Relay {relay_id} not found")
    return relay

def check_relay_access(relay: Relay, owner_id: str = None) -> bool:
    """Check if access to relay is allowed"""
    # Public relays are accessible to everyone
    if relay.is_public:
        return True
    # Private relays require owner_id match
    if relay.owner_id and owner_id == relay.owner_id:
        return True
    # Private relays with no owner are accessible (backwards compat)
    if not relay.owner_id:
        return True
    return False

# API Endpoints

@app.post("/relays", response_model=CreateRelayResponse)
async def create_relay(req: CreateRelayRequest, db: Session = Depends(get_db)):
    """Create a new relay"""
    relay_id = generate_relay_id()

    relay = Relay(
        id=relay_id,
        agent_names=req.agent_names,
        agent_count=len(req.agent_names),
        current_turn=0,
        is_public=req.is_public,
        owner_id=req.owner_id
    )

    db.add(relay)
    db.commit()
    db.refresh(relay)

    return CreateRelayResponse(
        relay_id=relay_id,
        agent_names=req.agent_names,
        current_turn=req.agent_names[0]
    )

@app.get("/relays/{relay_id}", response_model=RelayState)
async def get_relay_state(relay_id: str, owner_id: str = None, db: Session = Depends(get_db)):
    """Get current relay state"""
    relay = get_relay_or_404(db, relay_id)

    # Check access for private relays
    if not check_relay_access(relay, owner_id):
        raise HTTPException(status_code=403, detail="Access denied. This relay is private.")

    # Get message count and last message
    message_count = db.query(Message).filter(Message.relay_id == relay_id).count()
    last_message = db.query(Message).filter(Message.relay_id == relay_id).order_by(Message.created_at.desc()).first()

    return RelayState(
        relay_id=relay.id,
        current_turn=relay.agent_names[relay.current_turn],
        agent_names=relay.agent_names,
        message_count=message_count,
        last_message=last_message.content if last_message else None,
        last_agent=last_message.agent_name if last_message else None,
        created_at=relay.created_at.isoformat(),
        is_public=relay.is_public,
        owner_id=relay.owner_id
    )

@app.post("/relays/{relay_id}/messages", response_model=SendMessageResponse)
async def send_message(relay_id: str, req: SendMessageRequest, db: Session = Depends(get_db)):
    """Send a message (only if your turn)"""
    relay = get_relay_or_404(db, relay_id)

    # Determine agent
    agent = req.agent or relay.agent_names[relay.current_turn]

    # Validate agent exists
    if agent not in relay.agent_names:
        raise HTTPException(status_code=400, detail=f"Unknown agent '{agent}'")

    agent_index = relay.agent_names.index(agent)

    # Validate turn
    if agent_index != relay.current_turn:
        raise HTTPException(
            status_code=400,
            detail=f"Not {agent}'s turn. Current turn: {relay.agent_names[relay.current_turn]}"
        )

    # Create message
    message = Message(
        relay_id=relay_id,
        agent_index=agent_index,
        agent_name=agent,
        content=req.content,
        data=req.data,
        type=req.type
    )
    db.add(message)

    # Switch turn
    relay.current_turn = (relay.current_turn + 1) % relay.agent_count
    db.commit()
    db.refresh(message)

    # Get message count
    message_count = db.query(Message).filter(Message.relay_id == relay_id).count()

    # Prepare message dict for broadcast
    message_dict = {
        "id": message.id,
        "agent": message.agent_name,
        "content": message.content,
        "data": message.data,
        "type": message.type,
        "created_at": message.created_at.isoformat(),
        "next_turn": relay.agent_names[relay.current_turn]
    }

    # Broadcast via WebSocket
    asyncio.create_task(manager.broadcast_message(relay_id, message_dict))

    # Trigger webhooks for OTHER agents
    next_agent_index = relay.current_turn
    asyncio.create_task(trigger_webhooks(db, relay, message, next_agent_index))

    return SendMessageResponse(
        status="ok",
        message_id=message.id,
        next_turn=relay.agent_names[relay.current_turn],
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

    # Check access for private relays
    if not check_relay_access(relay, owner_id):
        raise HTTPException(status_code=403, detail="Access denied. This relay is private.")

    # Get messages
    messages = (
        db.query(Message)
        .filter(Message.relay_id == relay_id)
        .order_by(Message.created_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    total_count = db.query(Message).filter(Message.relay_id == relay_id).count()

    message_schemas = [
        MessageSchema(
            id=msg.id,
            agent=msg.agent_name,
            content=msg.content,
            data=msg.data,
            type=msg.type,
            created_at=msg.created_at.isoformat()
        )
        for msg in messages
    ]

    return MessageHistory(
        relay_id=relay_id,
        messages=message_schemas,
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

    # Validate agent
    if req.agent not in relay.agent_names:
        raise HTTPException(status_code=400, detail=f"Unknown agent '{req.agent}'")

    agent_index = relay.agent_names.index(req.agent)

    # Create webhook
    webhook = Webhook(
        relay_id=relay_id,
        agent_index=agent_index,
        agent_name=req.agent,
        url=req.url
    )
    db.add(webhook)
    db.commit()
    db.refresh(webhook)

    return RegisterWebhookResponse(
        webhook_id=webhook.id,
        url=webhook.url,
        agent=webhook.agent_name
    )

@app.get("/relays/{relay_id}/webhooks", response_model=List[WebhookSchema])
async def list_webhooks(relay_id: str, db: Session = Depends(get_db)):
    """List all webhooks for a relay"""
    relay = get_relay_or_404(db, relay_id)

    webhooks = db.query(Webhook).filter(Webhook.relay_id == relay_id).all()

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
    # Get database session
    db = SessionLocal()
    try:
        # Validate relay exists
        relay = db.query(Relay).filter(Relay.id == relay_id).first()
        if not relay:
            await websocket.close(code=4004, reason="Relay not found")
            return

        # Validate agent
        if agent not in relay.agent_names:
            await websocket.close(code=4003, reason="Unknown agent")
            return

        # Connect
        await manager.connect(relay_id, agent, websocket)

        try:
            # Keep connection alive and handle incoming messages
            while True:
                # Wait for any message (usually keepalive)
                data = await websocket.receive_text()
                # Could handle commands here in future
        except WebSocketDisconnect:
            manager.disconnect(relay_id, agent, websocket)
    finally:
        db.close()

# Webhook delivery
async def trigger_webhooks(db: Session, relay: Relay, message: Message, target_agent_index: int):
    """Trigger webhooks for agents who should receive this message"""
    # Get webhooks for target agent
    webhooks = db.query(Webhook).filter(
        Webhook.relay_id == relay.id,
        Webhook.agent_index == target_agent_index
    ).all()

    # Deliver to each webhook
    for webhook in webhooks:
        asyncio.create_task(deliver_webhook(webhook, message))

async def deliver_webhook(webhook: Webhook, message: Message):
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

    # Try up to 3 times with exponential backoff
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(webhook.url, json=payload)

                if response.status_code == 200:
                    # Success - log it
                    db = SessionLocal()
                    try:
                        delivery = WebhookDelivery(
                            webhook_id=webhook.id,
                            message_id=message.id,
                            status="success",
                            attempts=attempt
                        )
                        db.add(delivery)
                        db.commit()
                    finally:
                        db.close()
                    return
        except Exception as e:
            error_msg = str(e)

            # If this was the last attempt, log failure
            if attempt >= 3:
                db = SessionLocal()
                try:
                    delivery = WebhookDelivery(
                        webhook_id=webhook.id,
                        message_id=message.id,
                        status="failed",
                        attempts=attempt,
                        error_message=error_msg
                    )
                    db.add(delivery)
                    db.commit()
                finally:
                    db.close()
            else:
                # Exponential backoff: 1s, 2s, 4s
                await asyncio.sleep(2 ** (attempt - 1))

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "version": "2.0.0"}

# Run with: uvicorn app.main:app --reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
