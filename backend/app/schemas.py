"""
Pydantic schemas for request/response validation
"""
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field


# Relay Schemas
class CreateRelayRequest(BaseModel):
    agent_names: list[str] = Field(default=["agent_0", "agent_1"], min_length=2, max_length=10)
    is_public: bool = False
    owner_id: Optional[str] = None


class CreateRelayResponse(BaseModel):
    relay_id: str
    agent_names: list[str]
    current_turn: str
    api_key: Optional[str] = None


class RelayState(BaseModel):
    relay_id: str
    current_turn: str
    agent_names: list[str]
    message_count: int
    last_message: Optional[str] = None
    last_agent: Optional[str] = None
    created_at: str
    is_public: bool = False
    owner_id: Optional[str] = None


# Message Schemas
class SendMessageRequest(BaseModel):
    content: Optional[str] = None
    data: Optional[dict] = None
    type: Literal["text", "structured"] = "text"
    agent: Optional[str] = None  # Auto-detected if None


class SendMessageResponse(BaseModel):
    status: str
    message_id: int
    next_turn: str
    message_count: int


class MessageSchema(BaseModel):
    id: int
    agent: str
    content: Optional[str] = None
    data: Optional[dict] = None
    type: str
    created_at: str

    class Config:
        from_attributes = True


class MessageHistory(BaseModel):
    relay_id: str
    messages: list[MessageSchema]
    total_count: int


class RelayListItem(BaseModel):
    relay_id: str
    agent_names: list[str]
    current_turn: str
    message_count: int
    is_public: bool
    created_at: str


class RelayListResponse(BaseModel):
    relays: list[RelayListItem]
    total_count: int


# Webhook Schemas
class RegisterWebhookRequest(BaseModel):
    url: str = Field(..., min_length=1)
    agent: str = Field(..., min_length=1)


class RegisterWebhookResponse(BaseModel):
    webhook_id: int
    url: str
    agent: str


class WebhookSchema(BaseModel):
    id: int
    agent: str
    url: str
    created_at: str

    class Config:
        from_attributes = True
