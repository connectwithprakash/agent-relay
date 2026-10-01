"""session_exited and session_failed are pushed live to the session's controllers."""
import pytest

from app.models import ControlLease, HarnessSession

from .test_control_stream import _auth, _ready_control_session, _receive_until, _ws_headers

FAR_CURSOR = 10**6


def _stream_path(relay, session_id, cursor=FAR_CURSOR):
    return f"/relays/{relay['relay_id']}/sessions/{session_id}/stream?cursor={cursor}"


def _events_url(relay, session_id):
    return f"/relays/{relay['relay_id']}/sessions/{session_id}/events"


def _post_exit(client, relay, worker_token, session_id, kind, data=None):
    return client.post(
        _events_url(relay, session_id),
        json={"kind": kind, "data": data or {"exit_code": 1}},
        headers=_auth(worker_token),
    )


@pytest.mark.parametrize("kind", ["session_exited", "session_failed"])
def test_exit_event_is_pushed_live_to_controller_and_matches_stored_event(client, kind):
    relay, worker_token, session_id = _ready_control_session(client)

    with client.websocket_connect(_stream_path(relay, session_id), headers=_ws_headers(relay["token"])) as controller_ws:
        _receive_until(controller_ws, "connected")
        posted = _post_exit(client, relay, worker_token, session_id, kind)
        assert posted.status_code == 202
        pushed = _receive_until(controller_ws, "event", kind)["event"]

    assert pushed == posted.json()["event"]
    assert pushed["data"] == {"exit_code": 1}
    stored = client.get(_events_url(relay, session_id), headers=_auth(relay["token"])).json()["events"]
    assert [e for e in stored if e["kind"] == kind] == [pushed]


@pytest.mark.parametrize("kind", ["session_exited", "session_failed"])
def test_exit_still_fails_session_bumps_version_and_releases_lease(client, db_session, kind):
    relay, worker_token, session_id = _ready_control_session(client)
    db_session.expire_all()
    version = db_session.get(HarnessSession, session_id).version

    response = _post_exit(client, relay, worker_token, session_id, kind)

    assert response.status_code == 202
    assert response.json()["version"] == version + 1
    db_session.expire_all()
    assert db_session.get(HarnessSession, session_id).status == "failed"
    lease = db_session.get(ControlLease, session_id)
    assert lease.controller_agent is None and lease.expires_at is None


@pytest.mark.parametrize("kind", ["session_exited", "session_failed"])
def test_exit_event_is_replayed_from_cursor_after_reconnect(client, kind):
    relay, worker_token, session_id = _ready_control_session(client)
    posted = _post_exit(client, relay, worker_token, session_id, kind).json()["event"]

    with client.websocket_connect(
        _stream_path(relay, session_id, posted["sequence"] - 1), headers=_ws_headers(relay["token"])
    ) as controller_ws:
        _receive_until(controller_ws, "connected")
        assert _receive_until(controller_ws, "event", kind)["event"] == posted


@pytest.mark.parametrize("kind", ["session_exited", "session_failed"])
def test_exit_event_does_not_reach_other_sessions_or_relays(client, kind):
    relay_a, worker_token_a, session_a = _ready_control_session(client)
    relay_b, worker_token_b, session_b = _ready_control_session(client)

    with client.websocket_connect(_stream_path(relay_b, session_b), headers=_ws_headers(relay_b["token"])) as controller_b:
        with client.websocket_connect(_stream_path(relay_b, session_b), headers=_ws_headers(worker_token_b)) as worker_b:
            for ws in (controller_b, worker_b):
                _receive_until(ws, "connected")
            assert _post_exit(client, relay_a, worker_token_a, session_a, kind).status_code == 202
            worker_b.send_json({"type": "output", "text": "marker"})
            seen = []
            for _ in range(10):
                event = _receive_until(controller_b, "event")["event"]
                seen.append(event["kind"])
                if event["kind"] == "output":
                    break
            assert seen == ["output"]
