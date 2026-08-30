"""Control-session API contract tests."""
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.models import ControlLease, HarnessSession, Worker


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _pair_worker(client, relay):
    invitation = client.post(
        f"/relays/{relay['relay_id']}/invitations",
        params={"agent_name": "worker"},
        headers=_auth(relay["token"]),
    )
    assert invitation.status_code == 200
    redeemed = client.post(
        f"/pairing-invitations/{invitation.json()['invitation']}/redeem"
    )
    assert redeemed.status_code == 200
    return redeemed.json()["token"]


def _create_control_relay(client):
    created = client.post(
        "/relays",
        json={"agent_names": ["controller", "worker"], "is_public": False},
    )
    assert created.status_code == 200
    return created.json()


def _register_worker(client, relay, worker_token):
    response = client.post(
        f"/relays/{relay['relay_id']}/workers",
        json={"name": "Personal Mac", "profiles": ["fixture-shell"]},
        headers=_auth(worker_token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _start_session(client, relay, worker_id):
    response = client.post(
        f"/relays/{relay['relay_id']}/sessions",
        json={"worker_id": worker_id, "profile": "fixture-shell", "idempotency_key": "start-1"},
        headers=_auth(relay["token"]),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_controller_browser_invitation_is_one_time_and_mints_creator_scope(client):
    relay = _create_control_relay(client)

    invitation = client.post(
        f"/relays/{relay['relay_id']}/controller-browser-invitations",
        headers=_auth(relay["token"]),
    )
    assert invitation.status_code == 200
    browser = client.post(
        f"/pairing-invitations/{invitation.json()['invitation']}/redeem"
    )
    assert browser.status_code == 200
    assert browser.json()["is_creator"] is True

    workers = client.get(
        f"/relays/{relay['relay_id']}/workers",
        headers=_auth(browser.json()["token"]),
    )
    assert workers.status_code == 200
    replay = client.post(
        f"/pairing-invitations/{invitation.json()['invitation']}/redeem"
    )
    assert replay.status_code == 404


def test_worker_can_register_and_controller_can_start_allowlisted_session(client):
    relay = _create_control_relay(client)
    worker_token = _pair_worker(client, relay)
    worker = _register_worker(client, relay, worker_token)

    session = _start_session(client, relay, worker["worker_id"])

    assert session["status"] == "starting"
    assert session["profile"] == "fixture-shell"
    assert session["worker_id"] == worker["worker_id"]

    workers = client.get(f"/relays/{relay['relay_id']}/workers", headers=_auth(relay["token"]))
    assert workers.status_code == 200
    assert workers.json()["workers"] == [worker]


def test_worker_reregistration_recovers_its_existing_record(client):
    relay = _create_control_relay(client)
    worker_token = _pair_worker(client, relay)
    worker = _register_worker(client, relay, worker_token)

    restarted = client.post(
        f"/relays/{relay['relay_id']}/workers",
        json={"name": "Personal Mac", "profiles": ["fixture-shell"]},
        headers=_auth(worker_token),
    )
    assert restarted.status_code == 201
    assert restarted.json()["worker_id"] == worker["worker_id"]
    assert restarted.json()["status"] == "online"


def test_worker_claims_session_then_controller_has_exclusive_input_lease(client):
    relay = _create_control_relay(client)
    worker_token = _pair_worker(client, relay)
    worker = _register_worker(client, relay, worker_token)
    session = _start_session(client, relay, worker["worker_id"])

    ready = client.post(
        f"/relays/{relay['relay_id']}/sessions/{session['session_id']}/ready",
        headers=_auth(worker_token),
    )
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"

    lease = client.post(
        f"/relays/{relay['relay_id']}/sessions/{session['session_id']}/claim",
        json={"lease_seconds": 60, "expected_version": ready.json()["version"]},
        headers=_auth(relay["token"]),
    )
    assert lease.status_code == 200, lease.text
    assert lease.json()["controller_agent"] == "controller"

    input_response = client.post(
        f"/relays/{relay['relay_id']}/sessions/{session['session_id']}/input",
        json={"input": "hello\r", "expected_version": lease.json()["version"]},
        headers=_auth(relay["token"]),
    )
    assert input_response.status_code == 202, input_response.text
    assert input_response.json()["event"]["kind"] == "input_requested"

    release = client.post(
        f"/relays/{relay['relay_id']}/sessions/{session['session_id']}/release",
        json={"expected_version": input_response.json()["version"]},
        headers=_auth(relay["token"]),
    )
    assert release.status_code == 200

    rejected = client.post(
        f"/relays/{relay['relay_id']}/sessions/{session['session_id']}/input",
        json={"input": "must not reach the worker"},
        headers=_auth(relay["token"]),
    )
    assert rejected.status_code == 409


def test_claim_replaces_an_expired_persisted_lease_with_naive_sqlite_timestamp(client, db_session):
    relay = _create_control_relay(client)
    worker_token = _pair_worker(client, relay)
    worker = _register_worker(client, relay, worker_token)
    session = _start_session(client, relay, worker["worker_id"])
    ready = client.post(
        f"/relays/{relay['relay_id']}/sessions/{session['session_id']}/ready",
        headers=_auth(worker_token),
    ).json()
    db_session.add(ControlLease(
        session_id=session["session_id"],
        controller_agent="expired-controller",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    ))
    db_session.commit()

    claimed = client.post(
        f"/relays/{relay['relay_id']}/sessions/{session['session_id']}/claim",
        json={"lease_seconds": 60, "expected_version": ready["version"]},
        headers=_auth(relay["token"]),
    )
    assert claimed.status_code == 200


def test_worker_identity_and_replay_are_enforced(client):
    relay = _create_control_relay(client)
    worker_token = _pair_worker(client, relay)
    worker = _register_worker(client, relay, worker_token)
    session = _start_session(client, relay, worker["worker_id"])

    unauthorized = client.post(
        f"/relays/{relay['relay_id']}/sessions/{session['session_id']}/ready",
        headers=_auth(relay["token"]),
    )
    assert unauthorized.status_code == 403

    assert client.post(
        f"/relays/{relay['relay_id']}/sessions/{session['session_id']}/ready",
        headers=_auth(worker_token),
    ).status_code == 200

    output = client.post(
        f"/relays/{relay['relay_id']}/sessions/{session['session_id']}/events",
        json={"kind": "output", "data": {"text": "fixture ready\n"}},
        headers=_auth(worker_token),
    )
    assert output.status_code == 202

    events = client.get(
        f"/relays/{relay['relay_id']}/sessions/{session['session_id']}/events?after_sequence=1",
        headers=_auth(relay["token"]),
    )
    assert events.status_code == 200
    assert [event["kind"] for event in events.json()["events"]] == ["session_ready", "output"]


def test_revoked_worker_cannot_start_or_emit_for_sessions(client):
    relay = _create_control_relay(client)
    worker_token = _pair_worker(client, relay)
    worker = _register_worker(client, relay, worker_token)
    session = _start_session(client, relay, worker["worker_id"])

    revoked = client.post(
        f"/relays/{relay['relay_id']}/workers/{worker['worker_id']}/revoke",
        headers=_auth(relay["token"]),
    )
    assert revoked.status_code == 200

    ready = client.post(
        f"/relays/{relay['relay_id']}/sessions/{session['session_id']}/ready",
        headers=_auth(worker_token),
    )
    assert ready.status_code == 403

    start_after_revoke = client.post(
        f"/relays/{relay['relay_id']}/sessions",
        json={"worker_id": worker["worker_id"], "profile": "fixture-shell"},
        headers=_auth(relay["token"]),
    )
    assert start_after_revoke.status_code == 409


def test_server_expires_stale_worker_detaches_session_and_heartbeat_recovers(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "worker_stale_seconds", 10)
    relay = _create_control_relay(client)
    worker_token = _pair_worker(client, relay)
    worker = _register_worker(client, relay, worker_token)
    session = _start_session(client, relay, worker["worker_id"])
    ready = client.post(
        f"/relays/{relay['relay_id']}/sessions/{session['session_id']}/ready",
        headers=_auth(worker_token),
    )
    lease = client.post(
        f"/relays/{relay['relay_id']}/sessions/{session['session_id']}/claim",
        json={"lease_seconds": 60, "expected_version": ready.json()["version"]},
        headers=_auth(relay["token"]),
    )
    assert lease.status_code == 200
    db_session.get(Worker, worker["worker_id"]).last_seen = datetime.now(timezone.utc) - timedelta(seconds=11)
    db_session.commit()

    workers = client.get(f"/relays/{relay['relay_id']}/workers", headers=_auth(relay["token"]))
    assert workers.json()["workers"][0]["status"] == "offline"
    detached = db_session.get(HarnessSession, session["session_id"])
    assert detached.status == "detached"
    assert db_session.get(ControlLease, session["session_id"]).controller_agent is None

    unavailable = client.post(
        f"/relays/{relay['relay_id']}/sessions/{session['session_id']}/input",
        json={"input": "must not be delivered"},
        headers=_auth(relay["token"]),
    )
    assert unavailable.status_code == 409
    recovered = client.post(
        f"/relays/{relay['relay_id']}/workers/{worker['worker_id']}/heartbeat",
        headers=_auth(worker_token),
    )
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "online"

    unavailable_after_recovery = client.post(
        f"/relays/{relay['relay_id']}/sessions/{session['session_id']}/claim",
        json={"lease_seconds": 60, "expected_version": detached.version},
        headers=_auth(relay["token"]),
    )
    assert unavailable_after_recovery.status_code == 409
    failed = client.post(
        f"/relays/{relay['relay_id']}/sessions/{session['session_id']}/events",
        json={"kind": "session_failed", "data": {"reason": "worker_restarted"}},
        headers=_auth(worker_token),
    )
    assert failed.status_code == 202
    assert db_session.get(HarnessSession, session["session_id"]).status == "failed"
