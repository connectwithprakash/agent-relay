"""Pydantic models for Agent Relay API responses."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class RelayInfo(BaseModel):
    """Response from creating a new relay."""

    relay_id: str
    agent_names: list[str]
    current_turn: Optional[str] = None
    api_key: Optional[str] = None
    join_code: Optional[str] = None
    description: Optional[str] = None
    status: str = "active"


class RelayState(BaseModel):
    """Current state of a relay."""

    relay_id: str
    current_turn: Optional[str] = None
    agent_names: list[str]
    message_count: int
    last_message: Optional[str] = None
    last_agent: Optional[str] = None
    created_at: str
    is_public: bool = False
    owner_id: Optional[str] = None
    description: Optional[str] = None
    status: str = "active"
    join_code: Optional[str] = None
    max_agents: int = 10
    min_agents: int = 2


class MessageInfo(BaseModel):
    """A single message in a relay."""

    id: int
    agent: str
    content: Optional[str] = None
    data: Optional[dict] = None
    type: str
    created_at: str


class SendResult(BaseModel):
    """Response from sending a message."""

    status: str
    message_id: int
    next_turn: str
    message_count: int


class MessageHistory(BaseModel):
    """Paginated message history."""

    relay_id: str
    messages: list[MessageInfo]
    total_count: int
