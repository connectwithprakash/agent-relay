"""
Relay service - Business logic for relay operations
"""
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session

from ..models import Relay, Message
from ..repositories import RelayRepository, MessageRepository
from ..schemas import CreateRelayRequest, RelayState, MessageSchema


class RelayService:
    """Service for relay business operations"""

    @staticmethod
    def generate_relay_id() -> str:
        """Generate unique relay ID"""
        return f"relay-{secrets.token_urlsafe(8)}"

    @staticmethod
    def create_relay(db: Session, request: CreateRelayRequest) -> Tuple[Relay, str]:
        """Create a new relay with an API key.

        Returns:
            Tuple of (relay, plaintext_api_key)
        """
        relay_id = RelayService.generate_relay_id()
        api_key = secrets.token_urlsafe(32)
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        relay = Relay(
            id=relay_id,
            agent_names=request.agent_names,
            agent_count=len(request.agent_names),
            current_turn=0,
            is_public=request.is_public,
            owner_id=request.owner_id,
            api_key_hash=api_key_hash,
            turn_timeout=getattr(request, 'turn_timeout', None),
            turn_started_at=datetime.now(timezone.utc),
        )

        repo = RelayRepository(db)
        relay = repo.create(relay)

        return relay, api_key

    @staticmethod
    def verify_api_key(relay: Relay, provided_key: str) -> bool:
        """Verify that a provided API key matches the relay's stored hash."""
        if relay.api_key_hash is None:
            return True
        key_hash = hashlib.sha256(provided_key.encode()).hexdigest()
        return key_hash == relay.api_key_hash
    
    @staticmethod
    def get_relay_state(db: Session, relay: Relay) -> RelayState:
        """Get current relay state with message info"""
        message_repo = MessageRepository(db)
        message_count = message_repo.count_by_relay_id(relay.id)
        last_message = message_repo.get_last_message(relay.id)
        
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
    
    @staticmethod
    def validate_agent(relay: Relay, agent: Optional[str]) -> Tuple[str, int]:
        """
        Validate agent exists and get agent info.
        
        Returns:
            Tuple of (agent_name, agent_index)
            
        Raises:
            ValueError if agent is unknown
        """
        if agent is None:
            agent = relay.agent_names[relay.current_turn]
        
        if agent not in relay.agent_names:
            raise ValueError(f"Unknown agent '{agent}'")
        
        return agent, relay.agent_names.index(agent)
    
    @staticmethod
    def validate_turn(relay: Relay, agent_index: int) -> None:
        """
        Validate it's the agent's turn.
        
        Raises:
            ValueError if not the agent's turn
        """
        if agent_index != relay.current_turn:
            raise ValueError(
                f"Not turn. Current turn: {relay.agent_names[relay.current_turn]}"
            )
    
    @staticmethod
    def advance_turn(db: Session, relay: Relay) -> str:
        """Advance to next agent's turn and return next agent name"""
        relay.current_turn = (relay.current_turn + 1) % relay.agent_count
        relay.turn_started_at = datetime.now(timezone.utc)
        db.commit()
        return relay.agent_names[relay.current_turn]
