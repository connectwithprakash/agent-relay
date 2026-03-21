"""
Unit tests for repository layer
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Relay, Message, Webhook
from app.repositories.relay_repo import RelayRepository
from app.repositories.message_repo import MessageRepository
from app.repositories.webhook_repo import WebhookRepository


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


@pytest.fixture
def relay_repo(db):
    return RelayRepository(db)


@pytest.fixture
def message_repo(db):
    return MessageRepository(db)


@pytest.fixture
def webhook_repo(db):
    return WebhookRepository(db)


@pytest.fixture
def sample_relay(db, relay_repo):
    relay = Relay(
        id="test-relay-1",
        agent_names=["alice", "bob"],
        agent_count=2,
        current_turn=0,
        is_public=True,
        owner_id="owner-1",
    )
    return relay_repo.create(relay)


class TestRelayRepository:
    def test_create_and_get(self, relay_repo):
        relay = Relay(
            id="test-relay",
            agent_names=["a", "b"],
            agent_count=2,
            current_turn=0,
            is_public=True,
        )
        created = relay_repo.create(relay)
        assert created.id == "test-relay"

        fetched = relay_repo.get_by_id("test-relay")
        assert fetched is not None
        assert fetched.agent_names == ["a", "b"]

    def test_get_nonexistent(self, relay_repo):
        assert relay_repo.get_by_id("nonexistent") is None

    def test_update(self, relay_repo, sample_relay):
        sample_relay.current_turn = 1
        updated = relay_repo.update(sample_relay)
        assert updated.current_turn == 1

    def test_delete(self, relay_repo, sample_relay):
        relay_repo.delete(sample_relay)
        assert relay_repo.get_by_id("test-relay-1") is None

    def test_list_public(self, db, relay_repo):
        # Create public and private relays
        for i in range(3):
            relay_repo.create(Relay(
                id=f"public-{i}",
                agent_names=["a", "b"],
                agent_count=2,
                current_turn=0,
                is_public=True,
            ))
        relay_repo.create(Relay(
            id="private-1",
            agent_names=["a", "b"],
            agent_count=2,
            current_turn=0,
            is_public=False,
        ))

        public = relay_repo.list_public()
        assert len(public) == 3
        for r in public:
            assert r.is_public is True

    def test_list_public_pagination(self, relay_repo):
        for i in range(5):
            relay_repo.create(Relay(
                id=f"pub-{i}",
                agent_names=["a", "b"],
                agent_count=2,
                current_turn=0,
                is_public=True,
            ))

        page1 = relay_repo.list_public(limit=2, offset=0)
        assert len(page1) == 2

        page2 = relay_repo.list_public(limit=2, offset=2)
        assert len(page2) == 2

    def test_count_public(self, relay_repo):
        relay_repo.create(Relay(
            id="pub-1", agent_names=["a", "b"], agent_count=2,
            current_turn=0, is_public=True,
        ))
        relay_repo.create(Relay(
            id="priv-1", agent_names=["a", "b"], agent_count=2,
            current_turn=0, is_public=False,
        ))
        assert relay_repo.count_public() == 1


class TestMessageRepository:
    def test_create_and_count(self, message_repo, sample_relay):
        msg = Message(
            relay_id="test-relay-1",
            agent_index=0,
            agent_name="alice",
            content="Hello!",
            type="text",
        )
        created = message_repo.create(msg)
        assert created.id is not None
        assert created.content == "Hello!"

        count = message_repo.count_by_relay_id("test-relay-1")
        assert count == 1

    def test_get_by_relay_id(self, message_repo, sample_relay):
        for i in range(3):
            message_repo.create(Message(
                relay_id="test-relay-1",
                agent_index=i % 2,
                agent_name=["alice", "bob"][i % 2],
                content=f"Message {i}",
                type="text",
            ))

        messages = message_repo.get_by_relay_id("test-relay-1")
        assert len(messages) == 3

    def test_get_by_relay_id_pagination(self, message_repo, sample_relay):
        for i in range(5):
            message_repo.create(Message(
                relay_id="test-relay-1",
                agent_index=0,
                agent_name="alice",
                content=f"Message {i}",
                type="text",
            ))

        page = message_repo.get_by_relay_id("test-relay-1", limit=2, offset=0)
        assert len(page) == 2

    def test_get_last_message(self, message_repo, sample_relay):
        message_repo.create(Message(
            relay_id="test-relay-1",
            agent_index=0,
            agent_name="alice",
            content="First",
            type="text",
        ))
        message_repo.create(Message(
            relay_id="test-relay-1",
            agent_index=1,
            agent_name="bob",
            content="Second",
            type="text",
        ))

        last = message_repo.get_last_message("test-relay-1")
        assert last is not None
        assert last.content == "Second"

    def test_count_empty(self, message_repo):
        assert message_repo.count_by_relay_id("nonexistent") == 0


class TestWebhookRepository:
    def test_create_and_list(self, webhook_repo, sample_relay):
        wh = Webhook(
            relay_id="test-relay-1",
            agent_index=0,
            agent_name="alice",
            url="https://example.com/hook",
        )
        created = webhook_repo.create(wh)
        assert created.id is not None

        webhooks = webhook_repo.get_by_relay_id("test-relay-1")
        assert len(webhooks) == 1
        assert webhooks[0].url == "https://example.com/hook"

    def test_get_by_relay_and_agent(self, webhook_repo, sample_relay):
        webhook_repo.create(Webhook(
            relay_id="test-relay-1",
            agent_index=0,
            agent_name="alice",
            url="https://example.com/alice",
        ))
        webhook_repo.create(Webhook(
            relay_id="test-relay-1",
            agent_index=1,
            agent_name="bob",
            url="https://example.com/bob",
        ))

        alice_hooks = webhook_repo.get_by_relay_and_agent("test-relay-1", 0)
        assert len(alice_hooks) == 1
        assert alice_hooks[0].agent_name == "alice"

    def test_delete(self, webhook_repo, sample_relay):
        wh = webhook_repo.create(Webhook(
            relay_id="test-relay-1",
            agent_index=0,
            agent_name="alice",
            url="https://example.com/hook",
        ))
        webhook_repo.delete(wh)
        assert webhook_repo.get_by_relay_id("test-relay-1") == []
