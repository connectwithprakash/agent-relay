"""
Test fixtures and configuration for Agent Relay tests
"""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models import Base
from app.main import app, get_db


# In-memory SQLite for testing - use StaticPool to share the same connection
# across threads (required for SQLite in-memory databases)
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_database():
    """Create tables before each test, drop after."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(setup_database):
    """Provide a transactional database session for tests."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    """FastAPI test client with overridden database dependency."""
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
