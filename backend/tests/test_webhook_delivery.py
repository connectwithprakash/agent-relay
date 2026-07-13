"""Tests for the durable transactional webhook outbox."""
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import (
    Base,
    Message,
    Relay,
    Webhook,
    WebhookDelivery,
    WebhookOutbox,
)
from app.services.webhook_service import WebhookService


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    session = Session()
    session.info["factory"] = Session
    yield session
    session.close()


@pytest.fixture()
def event_data(db_session):
    relay = Relay(
        id="relay-test",
        agent_names=["alice", "bob"],
        agent_count=2,
        current_turn=1,
        is_public=True,
    )
    message = Message(
        relay_id=relay.id,
        agent_index=0,
        agent_name="alice",
        content="hello",
        type="text",
    )
    webhook = Webhook(
        relay_id=relay.id,
        agent_index=1,
        agent_name="bob",
        url="https://example.com/hook",
    )
    db_session.add_all([relay, message, webhook])
    db_session.flush()
    return relay, message, webhook


def _factory(db_session):
    return db_session.info["factory"]


def _claimed_event(db_session, event_data):
    relay, message, _ = event_data
    WebhookService.enqueue_webhooks(db_session, relay, message, 1)
    db_session.commit()
    with patch("app.services.webhook_service.SessionLocal", _factory(db_session)):
        return WebhookService._claim_batch()[0]


class TestTransactionalEnqueue:
    def test_enqueue_uses_callers_transaction(self, db_session, event_data):
        relay, message, _ = event_data
        assert WebhookService.enqueue_webhooks(db_session, relay, message, 1) == 1
        assert db_session.query(WebhookOutbox).count() == 1

        db_session.rollback()

        assert db_session.query(Message).count() == 0
        assert db_session.query(WebhookOutbox).count() == 0

    def test_enqueue_snapshots_target_and_payload(self, db_session, event_data):
        relay, message, webhook = event_data
        WebhookService.enqueue_webhooks(db_session, relay, message, 1)
        db_session.commit()

        event = db_session.query(WebhookOutbox).one()
        assert event.webhook_id == webhook.id
        assert event.target_url == webhook.url
        assert event.payload["message_id"] == message.id
        assert event.payload["content"] == "hello"
        assert event.status == "pending"

    def test_enqueue_only_targets_current_recipient(self, db_session, event_data):
        relay, message, _ = event_data
        assert WebhookService.enqueue_webhooks(db_session, relay, message, 0) == 0
        db_session.commit()
        assert db_session.query(WebhookOutbox).count() == 0


class TestClaiming:
    def test_claim_is_exclusive(self, db_session, event_data):
        _claimed_event(db_session, event_data)
        with patch("app.services.webhook_service.SessionLocal", _factory(db_session)):
            assert WebhookService._claim_batch() == []

    def test_stale_lease_is_reclaimed(self, db_session, event_data):
        event = _claimed_event(db_session, event_data)
        session = _factory(db_session)()
        row = session.get(WebhookOutbox, event["id"])
        row.locked_at = datetime.utcnow() - timedelta(minutes=5)
        session.commit()
        session.close()

        with patch("app.services.webhook_service.SessionLocal", _factory(db_session)):
            reclaimed = WebhookService._claim_batch()

        assert len(reclaimed) == 1
        assert reclaimed[0]["id"] == event["id"]
        assert reclaimed[0]["lock_token"] != event["lock_token"]

    def test_events_for_one_webhook_are_claimed_in_order(self, db_session, event_data):
        relay, first_message, _ = event_data
        WebhookService.enqueue_webhooks(db_session, relay, first_message, 1)
        second_message = Message(
            relay_id=relay.id,
            agent_index=0,
            agent_name="alice",
            content="second",
            type="text",
        )
        db_session.add(second_message)
        db_session.flush()
        WebhookService.enqueue_webhooks(db_session, relay, second_message, 1)
        db_session.commit()

        with patch("app.services.webhook_service.SessionLocal", _factory(db_session)):
            first_claim = WebhookService._claim_batch()
            second_claim = WebhookService._claim_batch()

        assert [event["message_id"] for event in first_claim] == [first_message.id]
        assert second_claim == []


class TestAttemptResults:
    def test_success_completes_outbox_and_logs_delivery(self, db_session, event_data):
        event = _claimed_event(db_session, event_data)
        with patch("app.services.webhook_service.SessionLocal", _factory(db_session)):
            WebhookService._complete_attempt(event, delivered=True, retryable=False)

        row = db_session.get(WebhookOutbox, event["id"])
        db_session.refresh(row)
        assert row.status == "delivered"
        assert row.attempts == 1
        assert row.delivered_at is not None
        assert db_session.query(WebhookDelivery).one().status == "success"

    def test_retry_uses_durable_backoff(self, db_session, event_data):
        event = _claimed_event(db_session, event_data)
        with patch("app.services.webhook_service.SessionLocal", _factory(db_session)), patch(
            "app.services.webhook_service.settings.webhook_outbox_retry_base_seconds", 2
        ):
            before = datetime.utcnow()
            WebhookService._complete_attempt(
                event, delivered=False, retryable=True, error_message="offline"
            )

        row = db_session.get(WebhookOutbox, event["id"])
        db_session.refresh(row)
        assert row.status == "pending"
        assert row.attempts == 1
        assert row.next_attempt_at >= before + timedelta(seconds=2)
        assert db_session.query(WebhookDelivery).one().status == "retrying"

    def test_non_retryable_response_goes_dead(self, db_session, event_data):
        event = _claimed_event(db_session, event_data)
        with patch("app.services.webhook_service.SessionLocal", _factory(db_session)):
            WebhookService._complete_attempt(
                event, delivered=False, retryable=False, error_message="HTTP 400"
            )

        row = db_session.get(WebhookOutbox, event["id"])
        db_session.refresh(row)
        assert row.status == "dead"
        assert db_session.query(WebhookDelivery).one().status == "failed"

    def test_retry_limit_dead_letters_event(self, db_session, event_data):
        event = _claimed_event(db_session, event_data)
        event["attempts"] = 3
        with patch("app.services.webhook_service.SessionLocal", _factory(db_session)), patch(
            "app.services.webhook_service.settings.webhook_max_retries", 3
        ):
            WebhookService._complete_attempt(
                event, delivered=False, retryable=True, error_message="still offline"
            )

        row = db_session.get(WebhookOutbox, event["id"])
        db_session.refresh(row)
        assert row.status == "dead"
        assert row.attempts == 3

    def test_deleted_webhook_does_not_block_outbox_completion(
        self, db_session, event_data
    ):
        event = _claimed_event(db_session, event_data)
        webhook = db_session.get(Webhook, event["webhook_id"])
        db_session.delete(webhook)
        db_session.commit()

        with patch("app.services.webhook_service.SessionLocal", _factory(db_session)):
            WebhookService._complete_attempt(event, delivered=True, retryable=False)

        row = db_session.get(WebhookOutbox, event["id"])
        db_session.refresh(row)
        assert row.status == "delivered"
        assert db_session.query(WebhookDelivery).count() == 0

    def test_stale_worker_cannot_complete_reclaimed_event(self, db_session, event_data):
        stale_event = _claimed_event(db_session, event_data)
        session = _factory(db_session)()
        row = session.get(WebhookOutbox, stale_event["id"])
        row.locked_at = datetime.utcnow() - timedelta(minutes=5)
        session.commit()
        session.close()
        with patch("app.services.webhook_service.SessionLocal", _factory(db_session)):
            current_event = WebhookService._claim_batch()[0]
            WebhookService._complete_attempt(
                stale_event, delivered=True, retryable=False
            )

        row = db_session.get(WebhookOutbox, current_event["id"])
        db_session.refresh(row)
        assert row.status == "processing"
        assert row.lock_token == current_event["lock_token"]
        assert db_session.query(WebhookDelivery).count() == 0


class TestHTTPDelivery:
    def test_delivery_sends_deduplication_headers(self, db_session, event_data):
        event = _claimed_event(db_session, event_data)
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post.return_value = response

        with patch("app.services.webhook_service._get_client", return_value=client), patch(
            "app.services.webhook_service.validate_webhook_url", return_value=True
        ), patch(
            "app.services.webhook_service.SessionLocal", _factory(db_session)
        ):
            asyncio.run(WebhookService._deliver_event(event))

        headers = client.post.await_args.kwargs["headers"]
        assert headers["X-Agent-Relay-Event-ID"] == str(event["id"])
        assert headers["X-Agent-Relay-Attempt"] == "1"
        row = db_session.get(WebhookOutbox, event["id"])
        db_session.refresh(row)
        assert row.status == "delivered"

    def test_ssrf_revalidation_dead_letters_without_connecting(
        self, db_session, event_data
    ):
        event = _claimed_event(db_session, event_data)
        client = AsyncMock(spec=httpx.AsyncClient)
        with patch("app.services.webhook_service._get_client", return_value=client), patch(
            "app.services.webhook_service.validate_webhook_url", return_value=False
        ), patch(
            "app.services.webhook_service.SessionLocal", _factory(db_session)
        ):
            asyncio.run(WebhookService._deliver_event(event))

        client.post.assert_not_awaited()
        row = db_session.get(WebhookOutbox, event["id"])
        db_session.refresh(row)
        assert row.status == "dead"
        assert "public address" in row.last_error