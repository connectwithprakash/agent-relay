"""
Tests for webhook delivery service
"""
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Relay, Message, Webhook, WebhookDelivery
from app.services.webhook_service import WebhookService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_session():
    """Provide an in-memory SQLite session for webhook delivery tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def relay(db_session):
    """Create a test relay."""
    r = Relay(
        id="relay-test",
        agent_names=["alice", "bob"],
        agent_count=2,
        current_turn=0,
        is_public=True,
    )
    db_session.add(r)
    db_session.commit()
    return r


@pytest.fixture()
def message(db_session, relay):
    """Create a test message."""
    msg = Message(
        relay_id=relay.id,
        agent_index=0,
        agent_name="alice",
        content="hello",
        type="text",
        created_at=datetime.utcnow(),
    )
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)
    return msg


@pytest.fixture()
def webhook(db_session, relay):
    """Create a test webhook targeting agent index 1 (bob)."""
    wh = Webhook(
        relay_id=relay.id,
        agent_index=1,
        agent_name="bob",
        url="https://example.com/hook",
    )
    db_session.add(wh)
    db_session.commit()
    db_session.refresh(wh)
    return wh


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTriggerWebhooks:
    def test_trigger_webhooks_creates_tasks(self, db_session, relay, message, webhook):
        """trigger_webhooks should create an asyncio task for each matching webhook."""
        def capture_task(coro):
            coro.close()
            return MagicMock()
        with patch("asyncio.create_task", side_effect=capture_task) as mock_create_task:
            asyncio.get_event_loop().run_until_complete(
                WebhookService.trigger_webhooks(db_session, relay, message, target_agent_index=1)
            )
            assert mock_create_task.call_count == 1

    def test_trigger_webhooks_no_match(self, db_session, relay, message, webhook):
        """No tasks should be created when no webhooks match the target agent index."""
        with patch("asyncio.create_task") as mock_create_task:
            asyncio.get_event_loop().run_until_complete(
                WebhookService.trigger_webhooks(db_session, relay, message, target_agent_index=0)
            )
            assert mock_create_task.call_count == 0


class TestDeliverWebhook:
    def test_deliver_webhook_success(self, db_session, webhook, message):
        """A successful POST should log delivery as 'success'."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("app.services.webhook_service._get_client", return_value=mock_client), \
             patch("app.services.webhook_service.SessionLocal", return_value=db_session), \
             patch.object(db_session, "close"):
            asyncio.get_event_loop().run_until_complete(
                WebhookService.deliver_webhook(webhook, message)
            )

        mock_client.post.assert_called_once()
        # Verify delivery was logged
        deliveries = db_session.query(WebhookDelivery).all()
        assert len(deliveries) == 1
        assert deliveries[0].status == "success"
        assert deliveries[0].attempts == 1

    def test_deliver_webhook_retry(self, db_session, webhook, message):
        """Failed attempts should be retried with exponential backoff."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=[
            Exception("Connection refused"),
            Exception("Connection refused"),
            Exception("Connection refused"),
        ])

        with patch("app.services.webhook_service._get_client", return_value=mock_client), \
             patch("app.services.webhook_service.settings") as mock_settings, \
             patch("app.services.webhook_service.SessionLocal", return_value=db_session), \
             patch.object(db_session, "close"), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            mock_settings.webhook_max_retries = 3
            asyncio.get_event_loop().run_until_complete(
                WebhookService.deliver_webhook(webhook, message)
            )

        assert mock_client.post.call_count == 3
        # Should log a failed delivery after all retries exhausted
        deliveries = db_session.query(WebhookDelivery).all()
        assert len(deliveries) == 1
        assert deliveries[0].status == "failed"
        assert deliveries[0].attempts == 3


class TestLogDelivery:
    def test_log_delivery_creates_record(self, db_session):
        """_log_delivery should create a WebhookDelivery record in the database."""
        with patch("app.services.webhook_service.SessionLocal", return_value=db_session), \
             patch.object(db_session, "close"):
            asyncio.get_event_loop().run_until_complete(
                WebhookService._log_delivery(
                    webhook_id=1,
                    message_id=1,
                    status="success",
                    attempts=1,
                    error_message=None,
                )
            )

        deliveries = db_session.query(WebhookDelivery).all()
        assert len(deliveries) == 1
        assert deliveries[0].webhook_id == 1
        assert deliveries[0].message_id == 1
        assert deliveries[0].status == "success"
        assert deliveries[0].attempts == 1
        assert deliveries[0].error_message is None

    def test_log_delivery_with_error(self, db_session):
        """_log_delivery should store error messages for failed deliveries."""
        with patch("app.services.webhook_service.SessionLocal", return_value=db_session), \
             patch.object(db_session, "close"):
            asyncio.get_event_loop().run_until_complete(
                WebhookService._log_delivery(
                    webhook_id=2,
                    message_id=3,
                    status="failed",
                    attempts=3,
                    error_message="Connection refused",
                )
            )

        deliveries = db_session.query(WebhookDelivery).all()
        assert len(deliveries) == 1
        assert deliveries[0].status == "failed"
        assert deliveries[0].error_message == "Connection refused"
