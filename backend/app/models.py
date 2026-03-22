"""
Database models for Agent Relay
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Index, Integer, String, Text, DateTime, ForeignKey, JSON, Boolean
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Relay(Base):
    """A relay manages turn-based communication between agents"""
    __tablename__ = "relays"

    id = Column(String, primary_key=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    current_turn = Column(Integer, default=0)  # Index of agent whose turn it is
    agent_count = Column(Integer, default=2)
    agent_names = Column(JSON)  # List of agent names
    is_public = Column(Boolean, default=False)  # Privacy control
    owner_id = Column(String, nullable=True)  # Owner identifier for access control
    join_code = Column(String(6), unique=True, nullable=True, index=True)  # Short human-readable join code
    turn_timeout = Column(Integer, nullable=True)  # Seconds per turn, None = no timeout
    turn_started_at = Column(DateTime, nullable=True)  # When the current turn began
    description = Column(Text, nullable=True)  # What this relay is for
    agent_instructions = Column(JSON, nullable=True)  # Per-agent instructions {"agent": "instruction"}
    max_agents = Column(Integer, default=10)  # Max agents allowed
    min_agents = Column(Integer, default=2)  # Min agents before turns start
    turns_waited = Column(JSON, nullable=True)  # Starvation tracking {"agent": count}
    max_skip_count = Column(Integer, default=3)  # Max skips before forced turn

    # Relationships
    messages = relationship("Message", back_populates="relay", cascade="all, delete-orphan")
    webhooks = relationship("Webhook", back_populates="relay", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Relay {self.id}>"


class Message(Base):
    """A message sent by an agent in a relay"""
    __tablename__ = "messages"
    __table_args__ = (
        Index('ix_messages_relay_created', 'relay_id', 'created_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    relay_id = Column(String, ForeignKey("relays.id"), nullable=False)
    agent_index = Column(Integer, nullable=False)  # 0 or 1 (or more for multi-agent)
    agent_name = Column(String, nullable=False)
    content = Column(Text, nullable=True)  # Plain text message
    data = Column(JSON, nullable=True)  # Structured data
    type = Column(String, default="text")  # 'text' or 'structured'
    reply_to = Column(Integer, ForeignKey("messages.id"), nullable=True)  # Thread reference
    message_type = Column(String, default="text")  # text, question, action-item, decision, bug-report, code
    idempotency_key = Column(String(255), nullable=True)  # Prevents duplicate messages
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    relay = relationship("Relay", back_populates="messages")
    parent = relationship("Message", remote_side=[id], backref="replies")

    def __repr__(self):
        return f"<Message {self.id} from {self.agent_name}>"


class Webhook(Base):
    """Webhook registration for receiving real-time updates"""
    __tablename__ = "webhooks"
    __table_args__ = (
        Index('ix_webhooks_relay_agent', 'relay_id', 'agent_index'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    relay_id = Column(String, ForeignKey("relays.id"), nullable=False)
    agent_index = Column(Integer, nullable=False)  # Which agent this webhook belongs to
    agent_name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    relay = relationship("Relay", back_populates="webhooks")
    deliveries = relationship("WebhookDelivery", back_populates="webhook", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Webhook {self.id} for {self.agent_name}>"


class WebhookDelivery(Base):
    """Log of webhook delivery attempts"""
    __tablename__ = "webhook_deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    webhook_id = Column(Integer, ForeignKey("webhooks.id"), nullable=False)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    status = Column(String, nullable=False)  # 'success' or 'failed'
    attempts = Column(Integer, default=1)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    webhook = relationship("Webhook", back_populates="deliveries")

    def __repr__(self):
        return f"<WebhookDelivery {self.id} status={self.status}>"


class AgentToken(Base):
    """Token-based authentication for agents in a relay"""
    __tablename__ = "agent_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token = Column(String, unique=True, nullable=False, index=True)
    relay_id = Column(String, ForeignKey("relays.id"), nullable=False)
    agent_name = Column(String, nullable=False)
    is_creator = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    relay = relationship("Relay")

    def __repr__(self):
        return f"<AgentToken {self.agent_name}@{self.relay_id}>"


class AgentRegistration(Base):
    """Cross-device agent registration for namespace-based discovery"""
    __tablename__ = "agent_registrations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    namespace = Column(String, nullable=False, index=True)
    agent_name = Column(String, nullable=False)
    device_id = Column(String, nullable=False)
    description = Column(String, nullable=True)  # What this agent does
    capabilities = Column(JSON, nullable=True)  # ["code_review", "security", "python"]
    metadata_ = Column("metadata", JSON, nullable=True)  # Arbitrary key-value pairs
    relay_id = Column(String, ForeignKey("relays.id"), nullable=True)
    status = Column(String, default="waiting")  # waiting, ready, offline
    last_heartbeat = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    relay = relationship("Relay")

    def __repr__(self):
        return f"<AgentRegistration {self.agent_name}@{self.namespace}>"
