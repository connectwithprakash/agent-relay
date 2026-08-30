"""Per-session WebSocket control stream tests."""


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _ws_headers(token):
    return {"sec-websocket-protocol": f"token-{token}"}


def _pair(client, relay, agent_name):
    invitation = client.post(
        f"/relays/{relay['relay_id']}/invitations",
        params={"agent_name": agent_name},
        headers=_auth(relay["token"]),
    )
    assert invitation.status_code == 200
    redeemed = client.post(f"/pairing-invitations/{invitation.json()['invitation']}/redeem")
    assert redeemed.status_code == 200
    return redeemed.json()["token"]


def _ready_control_session(client):
    relay = client.post(
        "/relays", json={"agent_names": ["controller", "worker"], "is_public": False}
    ).json()
    worker_token = _pair(client, relay, "worker")
    worker = client.post(
        f"/relays/{relay['relay_id']}/workers",
        json={"name": "Fixture worker", "profiles": ["fixture-shell"]},
        headers=_auth(worker_token),
    ).json()
    session = client.post(
        f"/relays/{relay['relay_id']}/sessions",
        json={"worker_id": worker["worker_id"], "profile": "fixture-shell"},
        headers=_auth(relay["token"]),
    ).json()
    ready = client.post(
        f"/relays/{relay['relay_id']}/sessions/{session['session_id']}/ready",
        headers=_auth(worker_token),
    ).json()
    claimed = client.post(
        f"/relays/{relay['relay_id']}/sessions/{session['session_id']}/claim",
        json={"lease_seconds": 60, "expected_version": ready["version"]},
        headers=_auth(relay["token"]),
    )
    assert claimed.status_code == 200
    return relay, worker_token, session["session_id"]


def _ready_session_without_lease(client):
    relay = client.post(
        "/relays", json={"agent_names": ["controller", "worker"], "is_public": False}
    ).json()
    worker_token = _pair(client, relay, "worker")
    worker = client.post(
        f"/relays/{relay['relay_id']}/workers",
        json={"name": "Fixture worker", "profiles": ["fixture-shell"]},
        headers=_auth(worker_token),
    ).json()
    session = client.post(
        f"/relays/{relay['relay_id']}/sessions",
        json={"worker_id": worker["worker_id"], "profile": "fixture-shell"},
        headers=_auth(relay["token"]),
    ).json()
    ready = client.post(
        f"/relays/{relay['relay_id']}/sessions/{session['session_id']}/ready",
        headers=_auth(worker_token),
    )
    assert ready.status_code == 200
    return relay, session["session_id"]


def _receive_until(ws, expected_type, expected_kind=None):
    for _ in range(10):
        frame = ws.receive_json()
        if frame["type"] == expected_type and (expected_kind is None or frame.get("event", {}).get("kind") == expected_kind):
            return frame
    raise AssertionError(f"did not receive {expected_type}/{expected_kind}")


def test_controller_input_reaches_only_its_session_worker_and_is_durable(client):
    relay, worker_token, session_id = _ready_control_session(client)
    path = f"/relays/{relay['relay_id']}/sessions/{session_id}/stream?cursor=0"

    with client.websocket_connect(path, headers=_ws_headers(relay["token"])) as controller_ws:
        with client.websocket_connect(path, headers=_ws_headers(worker_token)) as worker_ws:
            _receive_until(controller_ws, "connected")
            _receive_until(worker_ws, "connected")

            controller_ws.send_json({"type": "input", "input": "hello stream\r"})
            delivered = _receive_until(worker_ws, "event", "input_requested")
            assert delivered["event"]["data"]["input"] == "hello stream\r"

    events = client.get(
        f"/relays/{relay['relay_id']}/sessions/{session_id}/events",
        headers=_auth(relay["token"]),
    )
    assert events.status_code == 200
    assert any(event["kind"] == "input_requested" for event in events.json()["events"])


def test_worker_output_streams_to_controller_and_replays_from_cursor(client):
    relay, worker_token, session_id = _ready_control_session(client)
    path = f"/relays/{relay['relay_id']}/sessions/{session_id}/stream?cursor=0"

    with client.websocket_connect(path, headers=_ws_headers(relay["token"])) as controller_ws:
        with client.websocket_connect(path, headers=_ws_headers(worker_token)) as worker_ws:
            _receive_until(controller_ws, "connected")
            _receive_until(worker_ws, "connected")

            worker_ws.send_json({"type": "output", "text": "fixture output\r\n"})
            output = _receive_until(controller_ws, "event", "output")
            assert output["event"]["data"]["text"] == "fixture output\r\n"
            cursor = output["event"]["sequence"]

    with client.websocket_connect(
        f"/relays/{relay['relay_id']}/sessions/{session_id}/stream?cursor={cursor - 1}",
        headers=_ws_headers(relay["token"]),
    ) as reconnected:
        _receive_until(reconnected, "connected")
        replay = _receive_until(reconnected, "event", "output")
        assert replay["event"]["sequence"] == cursor


def test_creator_browser_token_can_open_a_session_started_by_another_creator(client):
    relay, _, session_id = _ready_control_session(client)
    invitation = client.post(
        f"/relays/{relay['relay_id']}/controller-browser-invitations",
        headers=_auth(relay["token"]),
    )
    assert invitation.status_code == 200
    browser = client.post(
        f"/pairing-invitations/{invitation.json()['invitation']}/redeem"
    )
    assert browser.status_code == 200

    with client.websocket_connect(
        f"/relays/{relay['relay_id']}/sessions/{session_id}/stream?cursor=0",
        headers=_ws_headers(browser.json()["token"]),
    ) as websocket:
        assert _receive_until(websocket, "connected")["actor"] == "controller"


def test_input_accepted_when_lease_is_claimed_after_stream_opened(client):
    """A stream opened before the lease must still deliver input claimed later.

    Regression: the stream's long-lived DB session identity-maps the lease row at
    connect; a claim made over HTTP afterwards was invisible to the stream, so
    every input frame was rejected with lease_required.
    """
    relay, worker_token, session_id = _ready_control_session(client)
    # Release the lease so the stream opens while no lease is held.
    released = client.post(
        f"/relays/{relay['relay_id']}/sessions/{session_id}/release",
        headers=_auth(relay["token"]),
    )
    assert released.status_code == 200
    path = f"/relays/{relay['relay_id']}/sessions/{session_id}/stream?cursor=0"

    with client.websocket_connect(path, headers=_ws_headers(relay["token"])) as controller_ws:
        with client.websocket_connect(path, headers=_ws_headers(worker_token)) as worker_ws:
            _receive_until(controller_ws, "connected")
            _receive_until(worker_ws, "connected")

            controller_ws.send_json({"type": "input", "input": "before lease\r"})
            assert _receive_until(controller_ws, "error")["code"] == "lease_required"

            claimed = client.post(
                f"/relays/{relay['relay_id']}/sessions/{session_id}/claim",
                json={"lease_seconds": 60, "expected_version": released.json()["version"]},
                headers=_auth(relay["token"]),
            )
            assert claimed.status_code == 200

            controller_ws.send_json({"type": "input", "input": "after lease\r"})
            delivered = _receive_until(worker_ws, "event", "input_requested")
            assert delivered["event"]["data"]["input"] == "after lease\r"

    events = client.get(
        f"/relays/{relay['relay_id']}/sessions/{session_id}/events",
        headers=_auth(relay["token"]),
    )
    kinds = [event["kind"] for event in events.json()["events"]]
    assert "input_requested" in kinds


def test_open_controller_stream_cannot_bypass_missing_control_lease(client):
    relay, session_id = _ready_session_without_lease(client)
    path = f"/relays/{relay['relay_id']}/sessions/{session_id}/stream?cursor=0"

    with client.websocket_connect(path, headers=_ws_headers(relay["token"])) as controller_ws:
        _receive_until(controller_ws, "connected")
        controller_ws.send_json({"type": "input", "input": "must not reach worker\r"})
        error = _receive_until(controller_ws, "error")
        assert error["code"] == "lease_required"

    events = client.get(
        f"/relays/{relay['relay_id']}/sessions/{session_id}/events",
        headers=_auth(relay["token"]),
    )
    assert not any(event["kind"] == "input_requested" for event in events.json()["events"])
