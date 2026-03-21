"""
Pydantic schemas for request/response validation
"""
import json
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Maximum serialized size for structured data payloads (64 KB)
MAX_DATA_SIZE_BYTES = 65536


# Relay Schemas
class CreateRelayRequest(BaseModel):
    agent_names: Optional[list[str]] = Field(default=None, max_length=20)
    is_public: bool = False
    owner_id: Optional[str] = None
    description: Optional[str] = None
    agent_instructions: Optional[dict] = None
    turn_timeout: Optional[int] = Field(default=None, ge=1, description="Seconds per turn before auto-advance. None = no timeout.")
    max_agents: int = Field(default=10, ge=2, le=20)
    min_agents: int = Field(default=2, ge=2, le=20)
    max_skip_count: int = Field(default=3, ge=1, le=20)

    @field_validator('agent_names')
    @classmethod
    def no_duplicates(cls, v):
        if v is None:
            return v
        if len(v) != len(set(v)):
            raise ValueError('Agent names must be unique')
        if len(v) < 2:
            raise ValueError('Need at least 2 agent names')
        return v


class CreateRelayResponse(BaseModel):
    relay_id: str
    agent_names: list[str]
    current_turn: Optional[str] = None
    api_key: Optional[str] = None
    join_code: Optional[str] = None
    description: Optional[str] = None
    status: str = "active"


class RelayState(BaseModel):
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


# Message Schemas
class SendMessageRequest(BaseModel):
    content: Optional[str] = Field(default=None, max_length=65536)
    data: Optional[dict] = None
    type: Literal["text", "structured"] = "text"
    agent: Optional[str] = None  # Auto-detected if None

    @field_validator("data")
    @classmethod
    def validate_data_size(cls, v: Optional[dict]) -> Optional[dict]:
        if v is not None:
            serialized = json.dumps(v)
            if len(serialized.encode("utf-8")) > MAX_DATA_SIZE_BYTES:
                raise ValueError(
                    f"Serialized data exceeds maximum size of {MAX_DATA_SIZE_BYTES} bytes"
                )
        return v


class SendMessageResponse(BaseModel):
    status: str
    message_id: int
    next_turn: str
    message_count: int


class MessageSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent: str
    content: Optional[str] = None
    data: Optional[dict] = None
    type: str
    created_at: str


class MessageHistory(BaseModel):
    relay_id: str
    messages: list[MessageSchema]
    total_count: int


class RelayListItem(BaseModel):
    relay_id: str
    agent_names: list[str]
    current_turn: Optional[str] = None
    message_count: int
    is_public: bool
    created_at: str
    description: Optional[str] = None
    status: str = "active"


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
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent: str
    url: str
    created_at: str
