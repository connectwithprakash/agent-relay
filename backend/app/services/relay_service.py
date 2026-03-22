"""
Relay service - Business logic for relay operations
"""
import random
import secrets
import string
from datetime import datetime, timezone
from typing import Optional, Tuple
from sqlalchemy.orm import Session

from ..models import AgentToken, Relay
from ..repositories import RelayRepository, MessageRepository, PresenceRepository
from ..schemas import AgentPresenceSchema, CreateRelayRequest, RelayState
from loguru import logger


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
    def generate_token() -> str:
        """Generate a secure agent token."""
        return secrets.token_urlsafe(32)

    @staticmethod
    def create_agent_token(
        db: Session,
        relay_id: str,
        agent_name: str,
        is_creator: bool = False,
    ) -> str:
        """Create and store an agent token. Returns the plaintext token."""
        token_str = RelayService.generate_token()
        agent_token = AgentToken(
            token=token_str,
            relay_id=relay_id,
            agent_name=agent_name,
            is_creator=is_creator,
        )
        db.add(agent_token)
        db.flush()
        return token_str

    @staticmethod
    def create_relay(db: Session, request: CreateRelayRequest) -> Tuple[Relay, str]:
        """Create a new relay with a creator token.

        Returns:
            Tuple of (relay, plaintext_token)
        """
        relay_id = RelayService.generate_relay_id()
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

        # Generate creator token
        creator_name = agent_names[0] if agent_names else "creator"
        token_str = RelayService.create_agent_token(
            db, relay_id, creator_name, is_creator=True
        )
        db.flush()

        return relay, token_str

    @staticmethod
    def _format_seconds_ago(seconds: float) -> str:
        """Format seconds into a human-readable 'ago' string."""
        if seconds < 60:
            return f"{int(seconds)}s ago"
        elif seconds < 3600:
            return f"{int(seconds / 60)}m ago"
        else:
            return f"{int(seconds / 3600)}h ago"

    @staticmethod
    def get_presence_for_relay(db: Session, relay: Relay) -> list[AgentPresenceSchema]:
        """Get presence info for all agents in a relay."""
        agent_names = relay.agent_names or []
        if not agent_names:
            return []

        presence_repo = PresenceRepository(db)
        presence_records = presence_repo.get_for_relay(relay.id)
        presence_map = {p.agent_name: p for p in presence_records}

        now = datetime.now(timezone.utc)
        result = []
        for agent in agent_names:
            record = presence_map.get(agent)
            if record:
                last_seen = record.last_seen
                if last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                seconds_ago = (now - last_seen).total_seconds()
                if seconds_ago > 120:
                    agent_status = "disconnected"
                elif seconds_ago > 60:
                    agent_status = "idle"
                else:
                    agent_status = record.status
                result.append(AgentPresenceSchema(
                    agent=agent,
                    status=agent_status,
                    last_seen=RelayService._format_seconds_ago(seconds_ago),
                    status_message=record.status_message if agent_status not in ("disconnected", "idle") else None,
                ))
            else:
                result.append(AgentPresenceSchema(
                    agent=agent,
                    status="unknown",
                    last_seen="never",
                ))
        return result

    @staticmethod
    def get_relay_state(db: Session, relay: Relay) -> RelayState:
        """Get current relay state with message info and presence"""
        message_repo = MessageRepository(db)
        message_count = message_repo.count_by_relay_id(relay.id)
        last_message = message_repo.get_last_message(relay.id)

        agent_names = relay.agent_names or []
        current_turn = (
            agent_names[relay.current_turn]
            if agent_names and 0 <= relay.current_turn < len(agent_names)
            else None
        )
        status = "open" if not agent_names else "active"

        # Auto-skip disconnected agent if they hold the current turn
        presence_list = RelayService.get_presence_for_relay(db, relay)
        if current_turn:
            current_presence = next(
                (p for p in presence_list if p.agent == current_turn), None
            )
            if current_presence and current_presence.status == "disconnected":
                current_turn = RelayService.advance_turn(db, relay)
                # Refresh presence after turn advance
                presence_list = RelayService.get_presence_for_relay(db, relay)

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
            agents_presence=presence_list,
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
                if agent_names and 0 <= relay.current_turn < len(agent_names)
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

        # Check for starving agents (exclude disconnected ones)
        max_skip = relay.max_skip_count or 3
        # Get presence to filter out disconnected agents
        disconnected = set()
        try:
            presence_list = RelayService.get_presence_for_relay(db, relay)
            disconnected = {p.agent for p in presence_list if p.status == "disconnected"}
        except Exception:
            logger.warning("Failed to fetch presence for starvation check in relay %s", relay.id)

        starving = [(a, cnt) for a, cnt in turns_waited.items()
                    if cnt >= max_skip and a != current_agent and a in agent_names and a not in disconnected]

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
