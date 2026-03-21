"""
Relay service - Business logic for relay operations
"""
import hashlib
import random
import secrets
import string
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
    def generate_join_code() -> str:
        """Generate a 6-character human-readable join code (e.g. 'ABC123')."""
        chars = string.ascii_uppercase + string.digits
        return ''.join(random.choices(chars, k=6))

    @staticmethod
    def create_relay(db: Session, request: CreateRelayRequest) -> Tuple[Relay, str]:
        """Create a new relay with an API key.

        Returns:
            Tuple of (relay, plaintext_api_key)
        """
        relay_id = RelayService.generate_relay_id()
        api_key = secrets.token_urlsafe(32)
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        join_code = RelayService.generate_join_code()

        agent_names = request.agent_names or []
        is_open = len(agent_names) == 0

        relay = Relay(
            id=relay_id,
            agent_names=agent_names,
            agent_count=len(agent_names),
            current_turn=0,
            is_public=request.is_public,
            owner_id=request.owner_id,
            api_key_hash=api_key_hash,
            join_code=join_code,
            turn_timeout=request.turn_timeout,
            turn_started_at=datetime.now(timezone.utc) if not is_open else None,
            description=request.description,
            agent_instructions=request.agent_instructions,
            max_agents=request.max_agents,
            min_agents=request.min_agents,
            max_skip_count=request.max_skip_count,
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
        
        agent_names = relay.agent_names or []
        current_turn = (
            agent_names[relay.current_turn]
            if agent_names and relay.current_turn < len(agent_names)
            else None
        )
        status = "open" if not agent_names else "active"

        return RelayState(
            relay_id=relay.id,
            current_turn=current_turn,
            agent_names=agent_names,
            message_count=message_count,
            last_message=last_message.content if last_message else None,
            last_agent=last_message.agent_name if last_message else None,
            created_at=relay.created_at.isoformat(),
            is_public=relay.is_public,
            owner_id=relay.owner_id,
            description=relay.description,
            status=status,
            join_code=relay.join_code,
            max_agents=relay.max_agents,
            min_agents=relay.min_agents,
        )
    
    @staticmethod
    def validate_agent(relay: Relay, agent: Optional[str]) -> Tuple[str, int]:
        """
        Validate agent exists and get agent info.

        Returns:
            Tuple of (agent_name, agent_index)

        Raises:
            ValueError if agent is unknown or relay has no agents
        """
        agent_names = relay.agent_names or []
        if not agent_names:
            raise ValueError("Relay has no agents yet (open relay)")

        if agent is None:
            agent = agent_names[relay.current_turn]

        if agent not in agent_names:
            raise ValueError(f"Unknown agent '{agent}'")

        return agent, agent_names.index(agent)
    
    @staticmethod
    def validate_turn(relay: Relay, agent_index: int) -> None:
        """
        Validate it's the agent's turn.

        Raises:
            ValueError if not the agent's turn
        """
        agent_names = relay.agent_names or []
        if agent_index != relay.current_turn:
            current = (
                agent_names[relay.current_turn]
                if agent_names and relay.current_turn < len(agent_names)
                else "unknown"
            )
            raise ValueError(
                f"Not turn. Current turn: {current}"
            )
    
    @staticmethod
    def advance_turn(db: Session, relay: Relay, next_agent: str = None) -> str:
        """Advance turn with optional directed turn and starvation prevention.

        If next_agent specified and valid, they go next (unless an agent is starving).
        Otherwise falls back to round-robin.
        """
        agent_names = relay.agent_names or []
        if not agent_names:
            raise ValueError("Cannot advance turn: relay has no agents")

        # Update agent_count to match actual list (handles late joins)
        relay.agent_count = len(agent_names)

        # Starvation prevention: track wait counts
        turns_waited = dict(relay.turns_waited or {})
        current_agent = agent_names[relay.current_turn] if relay.current_turn < len(agent_names) else None

        if current_agent:
            turns_waited[current_agent] = 0
            for agent in agent_names:
                if agent != current_agent:
                    turns_waited[agent] = turns_waited.get(agent, 0) + 1

        # Check for starving agents
        max_skip = relay.max_skip_count or 3
        starving = [(a, cnt) for a, cnt in turns_waited.items()
                    if cnt >= max_skip and a != current_agent and a in agent_names]

        if starving:
            starving.sort(key=lambda x: -x[1])
            relay.current_turn = agent_names.index(starving[0][0])
        elif next_agent and next_agent in agent_names:
            relay.current_turn = agent_names.index(next_agent)
        else:
            relay.current_turn = (relay.current_turn + 1) % len(agent_names)

        relay.turns_waited = turns_waited
        relay.turn_started_at = datetime.now(timezone.utc)
        db.commit()
        return agent_names[relay.current_turn]
