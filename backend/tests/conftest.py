"""
Shared test fixtures for Agent Relay backend tests.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.main import app, get_db


# Use a single in-memory database across the test session but isolate via
# transactions so each test gets a clean slate.
_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
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
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def relay_id(client):
    """Create a relay and return its ID."""
    resp = client.post("/relays", json={"agent_names": ["alice", "bob"]})
    assert resp.status_code == 200
    return resp.json()["relay_id"]
