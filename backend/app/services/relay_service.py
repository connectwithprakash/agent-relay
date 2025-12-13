"""
Relay service - Business logic for relay operations
"""
import secrets
from typing import Optional, List
from sqlalchemy.orm import Session

from ..models import Relay, Message
from ..schemas import CreateRelayRequest, RelayState, MessageSchema


class RelayService:
    """Service for relay business operations"""
    
    @staticmethod
    def generate_relay_id() -> str:
        """Generate unique relay ID"""
        return f"relay-{secrets.token_urlsafe(8)}"
    
    @staticmethod
    def create_relay(db: Session, request: CreateRelayRequest) -> Relay:
        """Create a new relay"""
        relay_id = RelayService.generate_relay_id()
        
        relay = Relay(
            id=relay_id,
            agent_names=request.agent_names,
            agent_count=len(request.agent_names),
            current_turn=0,
            is_public=request.is_public,
            owner_id=request.owner_id
        )
        
        db.add(relay)
        db.commit()
        db.refresh(relay)
        
        return relay
    
    @staticmethod
    def get_relay_state(db: Session, relay: Relay) -> RelayState:
        """Get current relay state with message info"""
        message_count = db.query(Message).filter(Message.relay_id == relay.id).count()
        last_message = (
            db.query(Message)
            .filter(Message.relay_id == relay.id)
            .order_by(Message.created_at.desc())
            .first()
        )
        
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
    def validate_agent(relay: Relay, agent: Optional[str]) -> tuple[str, int]:
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
        db.commit()
        return relay.agent_names[relay.current_turn]
