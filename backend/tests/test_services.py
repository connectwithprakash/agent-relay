"""
Unit tests for service layer
"""
import pytest
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import AgentToken, Base, Relay
from app.schemas import CreateRelayRequest
from app.services.relay_service import RelayService
from app.services.privacy_service import PrivacyService
from app.security import digest


# In-memory SQLite for service tests
engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


class TestRelayService:
    def test_create_relay(self, db):
        request = CreateRelayRequest(
            agent_names=["alice", "bob"],
            is_public=True,
            owner_id="owner-1",
        )
        relay, token = RelayService.create_relay(db, request)

        assert relay.id.startswith("relay-")
        assert relay.agent_names == ["alice", "bob"]
        assert relay.agent_count == 2
        assert relay.current_turn == 0
        assert relay.is_public is True
        assert relay.owner_id == "owner-1"
        assert len(token) > 20

        # Verify token is stored in the database
        agent_token = db.query(AgentToken).filter(AgentToken.token_hash == digest(token)).first()
        assert agent_token is not None
        assert agent_token.relay_id == relay.id
        assert agent_token.agent_name == "alice"
        assert agent_token.is_creator is True

    def test_validate_agent(self, db):
        request = CreateRelayRequest(agent_names=["alice", "bob"])
        relay, _ = RelayService.create_relay(db, request)

        agent, index = RelayService.validate_agent(relay, "alice")
        assert agent == "alice"
        assert index == 0

        agent, index = RelayService.validate_agent(relay, "bob")
        assert agent == "bob"
        assert index == 1

    def test_validate_agent_unknown(self, db):
        request = CreateRelayRequest(agent_names=["alice", "bob"])
        relay, _ = RelayService.create_relay(db, request)

        with pytest.raises(ValueError, match="Unknown agent"):
            RelayService.validate_agent(relay, "charlie")

    def test_validate_agent_auto(self, db):
        request = CreateRelayRequest(agent_names=["alice", "bob"])
        relay, _ = RelayService.create_relay(db, request)

        agent, index = RelayService.validate_agent(relay, None)
        assert agent == "alice"
        assert index == 0

    def test_validate_turn(self, db):
        request = CreateRelayRequest(agent_names=["alice", "bob"])
        relay, _ = RelayService.create_relay(db, request)

        # Alice (index 0) should be valid - current_turn is 0
        RelayService.validate_turn(relay, 0)

        # Bob (index 1) should fail
        with pytest.raises(ValueError, match="Not turn"):
            RelayService.validate_turn(relay, 1)

    def test_advance_turn(self, db):
        request = CreateRelayRequest(agent_names=["alice", "bob"])
        relay, _ = RelayService.create_relay(db, request)

        next_turn = RelayService.advance_turn(db, relay)
        assert next_turn == "bob"
        assert relay.current_turn == 1

        next_turn = RelayService.advance_turn(db, relay)
        assert next_turn == "alice"
        assert relay.current_turn == 0

    def test_advance_turn_three_agents(self, db):
        request = CreateRelayRequest(agent_names=["a", "b", "c"])
        relay, _ = RelayService.create_relay(db, request)

        assert RelayService.advance_turn(db, relay) == "b"
        assert RelayService.advance_turn(db, relay) == "c"
        assert RelayService.advance_turn(db, relay) == "a"

    def test_create_agent_token(self, db):
        """Creating agent tokens stores them and returns plaintext."""
        request = CreateRelayRequest(agent_names=["alice", "bob"])
        relay, _ = RelayService.create_relay(db, request)

        token_str = RelayService.create_agent_token(db, relay.id, "bob")
        db.commit()
        assert len(token_str) > 20

        agent_token = db.query(AgentToken).filter(AgentToken.token_hash == digest(token_str)).first()
        assert agent_token is not None
        assert agent_token.agent_name == "bob"
        assert agent_token.is_creator is False


class TestPrivacyService:
    def test_check_access_public(self):
        relay = MagicMock(is_public=True, owner_id="owner-1")
        assert PrivacyService.check_access(relay) is True
        assert PrivacyService.check_access(relay, "anyone") is True

    def test_check_access_private_with_owner(self):
        relay = MagicMock(is_public=False, owner_id="owner-1")
        assert PrivacyService.check_access(relay, "owner-1") is True
        assert PrivacyService.check_access(relay, "wrong-owner") is False

    def test_check_access_private_no_owner(self):
        relay = MagicMock(is_public=False, owner_id=None)
        # Legacy: private relay without owner is accessible
        assert PrivacyService.check_access(relay) is True

    def test_is_owner(self):
        relay = MagicMock(is_public=False, owner_id="owner-1")
        assert PrivacyService.is_owner(relay, "owner-1") is True
        assert PrivacyService.is_owner(relay, "other") is False

    def test_is_owner_no_owner(self):
        relay = MagicMock(is_public=True, owner_id=None)
        assert PrivacyService.is_owner(relay, "anyone") is False
