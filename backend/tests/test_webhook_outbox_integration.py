"""Route-level transactional outbox integration tests."""
from unittest.mock import patch

from app.models import Message, Webhook, WebhookOutbox


def test_send_message_commits_message_and_outbox_together(
    client, db_session, sample_relay
):
    relay_id = sample_relay["relay_id"]
    webhook = Webhook(
        relay_id=relay_id,
        agent_index=1,
        agent_name="bob",
        url="https://example.com/hook",
    )
    db_session.add(webhook)
    db_session.commit()

    with patch("app.routes.messages.WebhookService.notify_dispatcher") as notify:
        response = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "durable event", "idempotency_key": "outbox-1"},
            headers={"Authorization": f"Bearer {sample_relay['token']}"},
        )

    assert response.status_code == 200
    message = db_session.query(Message).filter_by(content="durable event").one()
    event = db_session.query(WebhookOutbox).one()
    assert event.message_id == message.id
    assert event.webhook_id == webhook.id
    assert event.payload["content"] == "durable event"
    assert event.status == "pending"
    notify.assert_called_once_with()


def test_idempotent_replay_does_not_duplicate_outbox(client, db_session, sample_relay):
    relay_id = sample_relay["relay_id"]
    db_session.add(
        Webhook(
            relay_id=relay_id,
            agent_index=1,
            agent_name="bob",
            url="https://example.com/hook",
        )
    )
    db_session.commit()
    request = {
        "content": "once",
        "idempotency_key": "outbox-idempotent",
    }
    headers = {"Authorization": f"Bearer {sample_relay['token']}"}

    with patch("app.routes.messages.WebhookService.notify_dispatcher"):
        first = client.post(f"/relays/{relay_id}/messages", json=request, headers=headers)
        second = client.post(f"/relays/{relay_id}/messages", json=request, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["message_id"] == first.json()["message_id"]
    assert db_session.query(WebhookOutbox).count() == 1
