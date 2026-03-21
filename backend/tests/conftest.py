"""
Test fixtures and configuration for Agent Relay tests
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.main import app, get_db


# In-memory SQLite for testing - use StaticPool to share the same connection
# across threads (required for SQLite in-memory databases)
_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=_engine)
_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture()
def db_session():
    """Provide a transactional database session that rolls back after each test."""
    connection = _engine.connect()
    transaction = connection.begin()
    session = _TestingSessionLocal(bind=connection)

    # Nested transaction so that the session.commit() inside app code
    # doesn't actually commit the outer transaction.
    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(sess, trans):
        nonlocal nested
        if trans.nested and not trans._parent.nested:
            nested = connection.begin_nested()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db_session):
    """Create a test client that uses the transactional db session."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    # Disable rate limiting for tests
    app.state.limiter.enabled = False

    with TestClient(app) as c:
        yield c

    app.state.limiter.enabled = True
    app.dependency_overrides.clear()


@pytest.fixture
def sample_relay(client):
    """Create a sample relay and return the creation response."""
    response = client.post("/relays", json={
        "agent_names": ["alice", "bob"],
        "is_public": True,
        "owner_id": "test-owner",
    })
    assert response.status_code == 200, f"Failed to create relay: {response.text}"
    return response.json()


@pytest.fixture
def private_relay(client):
    """Create a private relay and return the creation response."""
    response = client.post("/relays", json={
        "agent_names": ["alice", "bob"],
        "is_public": False,
        "owner_id": "test-owner",
    })
    assert response.status_code == 200, f"Failed to create relay: {response.text}"
    return response.json()


@pytest.fixture
def sample_message(client, sample_relay):
    """Send a sample message and return the response along with relay info."""
    relay_id = sample_relay["relay_id"]
    api_key = sample_relay["api_key"]
    response = client.post(
        f"/relays/{relay_id}/messages",
        json={"content": "Hello from Alice", "agent": "alice"},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 200, f"Failed to send message: {response.text}"
    return {
        "relay": sample_relay,
        "message": response.json(),
    }


@pytest.fixture()
def relay_id(client):
    """Create a relay and return its ID."""
    resp = client.post("/relays", json={"agent_names": ["alice", "bob"]})
    assert resp.status_code == 200
    return resp.json()["relay_id"]
