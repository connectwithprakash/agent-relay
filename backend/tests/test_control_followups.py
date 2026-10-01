"""Live input events, session adoption and input hardening."""
from datetime import timedelta

import pytest

from app.models import ControlEvent, ControlLease, HarnessSession, Worker

from .test_control_stream import (
    _auth,
    _event_kinds,
    _ready_control_session,
    _receive_until,
    _ws_headers,
)

FAR_CURSOR = 10**6


def _stream_path(relay, session_id, cursor=FAR_CURSOR):
    return f"/relays/{relay['relay_id']}/sessions/{session_id}/stream?cursor={cursor}"


def _events_url(relay, session_id):
    return f"/relays/{relay['relay_id']}/sessions/{session_id}/events"


def _frames_until_marker(ws, marker_text):
    """Collect event frames up to and including the worker output marker."""
    seen = []
    for _ in range(10):
        event = _receive_until(ws, "event")["event"]
        seen.append(event)
        if event["kind"] == "output" and event["data"] == {"text": marker_text}:
            return seen
    raise AssertionError("marker not received")


# Live input_requested to other controllers

def test_ws_input_is_pushed_to_other_controllers_and_not_echoed_to_sender(client):
    relay, worker_token, session_id = _ready_control_session(client)
    path = _stream_path(relay, session_id)

    with client.websocket_connect(path, headers=_ws_headers(relay["token"])) as sender_ws:
        with client.websocket_connect(path, headers=_ws_headers(relay["token"])) as other_ws:
            with client.websocket_connect(path, headers=_ws_headers(worker_token)) as worker_ws:
                for ws in (sender_ws, other_ws, worker_ws):
                    _receive_until(ws, "connected")

                sender_ws.send_json({"type": "input", "input": "1\r"})

                assert _receive_until(worker_ws, "event", "input_requested")["event"]["data"] == {"input": "1\r"}
                assert _receive_until(other_ws, "event", "input_requested")["event"]["data"] == {"input": "1\r"}

                worker_ws.send_json({"type": "output", "text": "marker"})
                seen_by_sender = _frames_until_marker(sender_ws, "marker")
                assert [e["kind"] for e in seen_by_sender] == ["output"]
                seen_by_other = _frames_until_marker(other_ws, "marker")
                assert [e["kind"] for e in seen_by_other] == ["output"]


def test_ws_input_is_delivered_to_each_other_controller_exactly_once(client):
    relay, worker_token, session_id = _ready_control_session(client)
    path = _stream_path(relay, session_id)

    with client.websocket_connect(path, headers=_ws_headers(relay["token"])) as sender_ws:
        with client.websocket_connect(path, headers=_ws_headers(relay["token"])) as other_ws:
            with client.websocket_connect(path, headers=_ws_headers(worker_token)) as worker_ws:
                for ws in (sender_ws, other_ws, worker_ws):
                    _receive_until(ws, "connected")
                sender_ws.send_json({"type": "input", "input": "once\r"})
                worker_ws.send_json({"type": "output", "text": "marker"})

                kinds = [e["kind"] for e in _frames_until_marker(other_ws, "marker")]
                assert kinds == ["input_requested", "output"]


def test_http_input_is_pushed_live_to_connected_controllers(client):
    relay, worker_token, session_id = _ready_control_session(client)
    path = _stream_path(relay, session_id)

    with client.websocket_connect(path, headers=_ws_headers(relay["token"])) as controller_ws:
        _receive_until(controller_ws, "connected")
        posted = client.post(
            f"/relays/{relay['relay_id']}/sessions/{session_id}/input",
            json={"input": "from http\r"},
            headers=_auth(relay["token"]),
        )
        assert posted.status_code == 202
        pushed = _receive_until(controller_ws, "event", "input_requested")
        assert pushed["event"]["data"] == {"input": "from http\r"}
        assert pushed["event"]["sequence"] == posted.json()["event"]["sequence"]


def test_input_event_does_not_reach_controllers_of_another_session(client):
    relay_a, worker_token_a, session_a = _ready_control_session(client)
    relay_b, worker_token_b, session_b = _ready_control_session(client)

    with client.websocket_connect(_stream_path(relay_b, session_b), headers=_ws_headers(relay_b["token"])) as controller_b:
        with client.websocket_connect(_stream_path(relay_b, session_b), headers=_ws_headers(worker_token_b)) as worker_b:
            for ws in (controller_b, worker_b):
                _receive_until(ws, "connected")
            with client.websocket_connect(_stream_path(relay_a, session_a), headers=_ws_headers(relay_a["token"])) as controller_a:
                _receive_until(controller_a, "connected")
                controller_a.send_json({"type": "input", "input": "for A\r"})
                client.post(
                    f"/relays/{relay_a['relay_id']}/sessions/{session_a}/input",
                    json={"input": "http for A\r"},
                    headers=_auth(relay_a["token"]),
                )
            worker_b.send_json({"type": "output", "text": "marker"})
            assert [e["kind"] for e in _frames_until_marker(controller_b, "marker")] == ["output"]


# session_adopted

def _detach(db_session, session_id):
    session = db_session.get(HarnessSession, session_id)
    session.status = "detached"
    lease = db_session.get(ControlLease, session_id)
    if lease:
        lease.controller_agent = None
        lease.expires_at = None
    db_session.commit()
    return session.version


def _adopt(client, relay, worker_token, session_id, data=None):
    return client.post(
        _events_url(relay, session_id),
        json={"kind": "session_adopted", "data": {} if data is None else data},
        headers=_auth(worker_token),
    )


def _session_state(db_session, session_id):
    db_session.expire_all()
    session = db_session.get(HarnessSession, session_id)
    return session.status, session.version


def test_adoption_moves_detached_session_to_ready_and_bumps_version(client, db_session):
    relay, worker_token, session_id = _ready_control_session(client)
    version = _detach(db_session, session_id)

    response = _adopt(client, relay, worker_token, session_id)

    assert response.status_code == 202
    assert _session_state(db_session, session_id) == ("ready", version + 1)
    assert response.json()["version"] == version + 1
    assert "session_adopted" in _event_kinds(client, relay, session_id)


def test_adoption_does_not_restore_a_lease(client, db_session):
    relay, worker_token, session_id = _ready_control_session(client)
    _detach(db_session, session_id)

    assert _adopt(client, relay, worker_token, session_id).status_code == 202

    db_session.expire_all()
    lease = db_session.get(ControlLease, session_id)
    assert lease is None or lease.controller_agent is None
    refused = client.post(
        f"/relays/{relay['relay_id']}/sessions/{session_id}/input",
        json={"input": "x"},
        headers=_auth(relay["token"]),
    )
    assert refused.status_code == 409


def test_adoption_is_broadcast_to_connected_controllers(client, db_session):
    relay, worker_token, session_id = _ready_control_session(client)
    _detach(db_session, session_id)

    with client.websocket_connect(_stream_path(relay, session_id), headers=_ws_headers(relay["token"])) as controller_ws:
        _receive_until(controller_ws, "connected")
        assert _adopt(client, relay, worker_token, session_id).status_code == 202
        pushed = _receive_until(controller_ws, "event", "session_adopted")
        assert pushed["event"]["data"] == {}


@pytest.mark.parametrize("status", ["starting", "ready", "controlled", "failed"])
def test_adoption_is_rejected_unless_session_is_detached(client, db_session, status):
    relay, worker_token, session_id = _ready_control_session(client)
    session = db_session.get(HarnessSession, session_id)
    session.status = status
    db_session.commit()
    version = session.version

    response = _adopt(client, relay, worker_token, session_id)

    assert response.status_code == 409
    assert _session_state(db_session, session_id) == (status, version)
    assert "session_adopted" not in _event_kinds(client, relay, session_id)


@pytest.mark.parametrize("worker_status", ["offline", "revoked"])
def test_adoption_requires_online_worker(client, db_session, worker_status):
    relay, worker_token, session_id = _ready_control_session(client)
    version = _detach(db_session, session_id)
    worker = db_session.get(Worker, db_session.get(HarnessSession, session_id).worker_id)
    worker.status = worker_status
    if worker_status == "revoked":
        from datetime import datetime, timezone
        worker.revoked_at = datetime.now(timezone.utc)
    db_session.commit()

    response = _adopt(client, relay, worker_token, session_id)

    assert response.status_code in (403, 409)
    assert _session_state(db_session, session_id) == ("detached", version)
    assert "session_adopted" not in _event_kinds(client, relay, session_id)


def test_adoption_rejects_stale_worker_whose_heartbeat_expired(client, db_session):
    relay, worker_token, session_id = _ready_control_session(client)
    version = _detach(db_session, session_id)
    worker = db_session.get(Worker, db_session.get(HarnessSession, session_id).worker_id)
    from app.routes.control import _now
    worker.last_seen = _now() - timedelta(hours=1)
    db_session.commit()

    assert _adopt(client, relay, worker_token, session_id).status_code == 409
    assert _session_state(db_session, session_id) == ("detached", version)


def test_adoption_by_non_owner_is_forbidden_and_changes_nothing(client, db_session):
    relay, worker_token, session_id = _ready_control_session(client)
    version = _detach(db_session, session_id)

    response = _adopt(client, relay, relay["token"], session_id)

    assert response.status_code == 403
    assert _session_state(db_session, session_id) == ("detached", version)


@pytest.mark.parametrize("data", [{"x": 1}, {"prompt": "p"}])
def test_adoption_requires_empty_data(client, db_session, data):
    relay, worker_token, session_id = _ready_control_session(client)
    version = _detach(db_session, session_id)

    assert _adopt(client, relay, worker_token, session_id, data).status_code == 422
    assert _session_state(db_session, session_id) == ("detached", version)


def test_second_adoption_is_rejected_after_the_first(client, db_session):
    relay, worker_token, session_id = _ready_control_session(client)
    version = _detach(db_session, session_id)

    assert _adopt(client, relay, worker_token, session_id).status_code == 202
    assert _adopt(client, relay, worker_token, session_id).status_code == 409
    assert _session_state(db_session, session_id) == ("ready", version + 1)


# Input hardening: lone surrogates

LONE_SURROGATE_JSON = '"\\ud800"'


def test_ws_input_with_lone_surrogate_is_rejected_and_stream_stays_open(client):
    relay, worker_token, session_id = _ready_control_session(client)

    with client.websocket_connect(_stream_path(relay, session_id), headers=_ws_headers(relay["token"])) as controller_ws:
        _receive_until(controller_ws, "connected")
        for _ in range(2):
            controller_ws.send_text('{"type":"input","input":' + LONE_SURROGATE_JSON + '}')
            assert _receive_until(controller_ws, "error")["code"] == "invalid_input"

    assert "input_requested" not in _event_kinds(client, relay, session_id)


def test_ws_output_with_lone_surrogate_is_rejected_and_stream_stays_open(client):
    relay, worker_token, session_id = _ready_control_session(client)

    with client.websocket_connect(_stream_path(relay, session_id), headers=_ws_headers(worker_token)) as worker_ws:
        _receive_until(worker_ws, "connected")
        for _ in range(2):
            worker_ws.send_text('{"type":"output","text":' + LONE_SURROGATE_JSON + '}')
            assert _receive_until(worker_ws, "error")["code"] == "invalid_output"

    assert "output" not in _event_kinds(client, relay, session_id)


def test_ws_approval_with_lone_surrogate_is_rejected_and_stream_stays_open(client):
    relay, worker_token, session_id = _ready_control_session(client)

    with client.websocket_connect(_stream_path(relay, session_id), headers=_ws_headers(worker_token)) as worker_ws:
        _receive_until(worker_ws, "connected")
        for _ in range(2):
            worker_ws.send_text('{"type":"approval","prompt":' + LONE_SURROGATE_JSON + '}')
            assert _receive_until(worker_ws, "error")["code"] == "invalid_approval"


def test_http_input_with_lone_surrogate_is_rejected_with_422(client):
    relay, worker_token, session_id = _ready_control_session(client)

    response = client.post(
        f"/relays/{relay['relay_id']}/sessions/{session_id}/input",
        content='{"input":' + LONE_SURROGATE_JSON + '}',
        headers={**_auth(relay["token"]), "content-type": "application/json"},
    )

    assert response.status_code == 422
    assert "input_requested" not in _event_kinds(client, relay, session_id)


@pytest.mark.parametrize("kind,data", [
    ("output", '{"text":' + LONE_SURROGATE_JSON + '}'),
    ("approval_requested", '{"prompt":' + LONE_SURROGATE_JSON + '}'),
])
def test_http_event_with_lone_surrogate_is_rejected_with_422(client, kind, data):
    relay, worker_token, session_id = _ready_control_session(client)

    response = client.post(
        _events_url(relay, session_id),
        content='{"kind":"' + kind + '","data":' + data + '}',
        headers={**_auth(worker_token), "content-type": "application/json"},
    )

    assert response.status_code == 422
    assert kind not in _event_kinds(client, relay, session_id)


@pytest.mark.parametrize("role", ["controller", "worker"])
@pytest.mark.parametrize("frame_type", ["[]", "{}", "null", "5", "true", "1.5"])
def test_frame_with_non_string_type_gets_invalid_frame_and_stream_stays_open(client, role, frame_type):
    relay, worker_token, session_id = _ready_control_session(client)
    token = relay["token"] if role == "controller" else worker_token

    with client.websocket_connect(_stream_path(relay, session_id), headers=_ws_headers(token)) as ws:
        _receive_until(ws, "connected")
        for _ in range(2):
            ws.send_text('{"type":' + frame_type + '}')
            assert _receive_until(ws, "error")["code"] == "invalid_frame"


def test_empty_output_text_is_still_accepted_and_stored(client):
    relay, worker_token, session_id = _ready_control_session(client)

    with client.websocket_connect(_stream_path(relay, session_id), headers=_ws_headers(relay["token"])) as controller_ws:
        with client.websocket_connect(_stream_path(relay, session_id), headers=_ws_headers(worker_token)) as worker_ws:
            for ws in (controller_ws, worker_ws):
                _receive_until(ws, "connected")
            worker_ws.send_json({"type": "output", "text": ""})
            assert _receive_until(controller_ws, "event", "output")["event"]["data"] == {"text": ""}

    events = client.get(_events_url(relay, session_id), headers=_auth(relay["token"])).json()["events"]
    assert any(e["kind"] == "output" and e["data"] == {"text": ""} for e in events)


def test_concurrent_adoptions_bump_the_version_once(client, db_session):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    relay, worker_token, session_id = _ready_control_session(client)
    version = _detach(db_session, session_id)
    barrier = Barrier(2)

    def adopt():
        barrier.wait()
        return _adopt(client, relay, worker_token, session_id).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(f.result() for f in [pool.submit(adopt), pool.submit(adopt)])

    assert codes == [202, 409]
    assert _session_state(db_session, session_id) == ("ready", version + 1)
    adopted = [k for k in _event_kinds(client, relay, session_id) if k == "session_adopted"]
    assert len(adopted) == 1
