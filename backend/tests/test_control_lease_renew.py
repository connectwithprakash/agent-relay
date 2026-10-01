"""Atomic lease renewal for the current lease holder."""
from datetime import timedelta

import pytest

from app.models import ControlEvent, ControlLease, HarnessSession, Worker
from app.routes.control import _as_utc, _now

from .test_control_stream import _auth, _ready_control_session, _receive_until, _ws_headers

FAR_CURSOR = 10**6


def _url(relay, session_id, tail):
    return f"/relays/{relay['relay_id']}/sessions/{session_id}/{tail}"


def _state(db_session, session_id):
    db_session.expire_all()
    session = db_session.get(HarnessSession, session_id)
    lease = db_session.get(ControlLease, session_id)
    events = db_session.query(ControlEvent).filter(ControlEvent.session_id == session_id).count()
    return (
        session.status,
        session.version,
        lease.controller_agent if lease else None,
        lease.expires_at if lease else None,
        events,
    )


def _renew(client, relay, session_id, version, seconds=60, token=None):
    return client.post(
        _url(relay, session_id, "lease/renew"),
        json={"lease_seconds": seconds, "expected_version": version},
        headers=_auth(token or relay["token"]),
    )


def _held(client, db_session):
    relay, worker_token, session_id = _ready_control_session(client)
    status, version, *_ = _state(db_session, session_id)
    assert status == "controlled"
    return relay, worker_token, session_id, version


def test_holder_renews_lease_atomically(client, db_session):
    relay, _worker_token, session_id, version = _held(client, db_session)
    before = _as_utc(_state(db_session, session_id)[3])

    response = _renew(client, relay, session_id, version, seconds=300)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "controlled"
    assert body["version"] == version + 1
    assert body["controller_agent"] is not None
    status, new_version, holder, expires_at, _events = _state(db_session, session_id)
    assert (status, new_version) == ("controlled", version + 1)
    assert _as_utc(expires_at) > before + timedelta(seconds=200)
    assert body["lease_expires_at"] is not None


def test_renew_response_has_same_shape_as_claim(client, db_session):
    relay, _worker_token, session_id, version = _held(client, db_session)

    renewed = _renew(client, relay, session_id, version).json()

    assert set(renewed) == {
        "session_id", "worker_id", "profile", "status", "version", "controller_agent", "lease_expires_at",
    }


def test_renew_stores_lease_renewed_event_with_holder_and_expiry(client, db_session):
    relay, _worker_token, session_id, version = _held(client, db_session)

    renewed = _renew(client, relay, session_id, version).json()

    events = client.get(_url(relay, session_id, "events"), headers=_auth(relay["token"])).json()["events"]
    renewals = [e for e in events if e["kind"] == "lease_renewed"]
    assert len(renewals) == 1
    assert renewals[0]["data"] == {
        "controller_agent": renewed["controller_agent"],
        "expires_at": renewed["lease_expires_at"],
    }


def test_renew_is_broadcast_to_connected_controllers(client, db_session):
    relay, _worker_token, session_id, version = _held(client, db_session)
    path = _url(relay, session_id, f"stream?cursor={FAR_CURSOR}")

    with client.websocket_connect(path, headers=_ws_headers(relay["token"])) as controller_ws:
        _receive_until(controller_ws, "connected")
        assert _renew(client, relay, session_id, version).status_code == 200
        pushed = _receive_until(controller_ws, "event", "lease_renewed")["event"]

    assert pushed["data"]["controller_agent"]


def test_renewed_lease_keeps_input_working_past_the_original_expiry(client, db_session):
    relay, _worker_token, session_id, version = _held(client, db_session)
    lease = db_session.get(ControlLease, session_id)
    lease.expires_at = _now() + timedelta(seconds=1)
    db_session.commit()

    assert _renew(client, relay, session_id, version, seconds=300).status_code == 200

    assert _as_utc(_state(db_session, session_id)[3]) > _now() + timedelta(seconds=200)
    posted = client.post(_url(relay, session_id, "input"), json={"input": "x"}, headers=_auth(relay["token"]))
    assert posted.status_code == 202


@pytest.mark.parametrize("delta", [-1, 1])
def test_stale_or_future_expected_version_is_409_and_changes_nothing(client, db_session, delta):
    relay, _worker_token, session_id, version = _held(client, db_session)
    before = _state(db_session, session_id)

    assert _renew(client, relay, session_id, version + delta).status_code == 409
    assert _state(db_session, session_id) == before


def test_expired_lease_cannot_be_renewed(client, db_session):
    relay, _worker_token, session_id, version = _held(client, db_session)
    lease = db_session.get(ControlLease, session_id)
    lease.expires_at = _now() - timedelta(seconds=1)
    db_session.commit()
    before = _state(db_session, session_id)

    assert _renew(client, relay, session_id, version).status_code == 409
    assert _state(db_session, session_id) == before


def test_non_holder_cannot_renew(client, db_session):
    relay, _worker_token, session_id, version = _held(client, db_session)
    lease = db_session.get(ControlLease, session_id)
    lease.controller_agent = "someone-else"
    db_session.commit()
    before = _state(db_session, session_id)

    assert _renew(client, relay, session_id, version).status_code == 409
    assert _state(db_session, session_id) == before


def test_released_lease_cannot_be_renewed(client, db_session):
    relay, _worker_token, session_id, version = _held(client, db_session)
    released = client.post(
        _url(relay, session_id, f"release?expected_version={version}"), headers=_auth(relay["token"])
    ).json()
    before = _state(db_session, session_id)

    assert _renew(client, relay, session_id, released["version"]).status_code == 409
    assert _state(db_session, session_id) == before


@pytest.mark.parametrize("status", ["ready", "detached", "failed", "starting"])
def test_session_must_be_controlled(client, db_session, status):
    relay, _worker_token, session_id, version = _held(client, db_session)
    db_session.get(HarnessSession, session_id).status = status
    db_session.commit()
    before = _state(db_session, session_id)

    assert _renew(client, relay, session_id, version).status_code == 409
    assert _state(db_session, session_id) == before


@pytest.mark.parametrize("worker_status", ["offline", "revoked"])
def test_worker_must_be_online_and_not_revoked(client, db_session, worker_status):
    relay, _worker_token, session_id, version = _held(client, db_session)
    worker = db_session.get(Worker, db_session.get(HarnessSession, session_id).worker_id)
    worker.status = worker_status
    if worker_status == "revoked":
        worker.revoked_at = _now()
    db_session.commit()
    before = _state(db_session, session_id)

    assert _renew(client, relay, session_id, version).status_code == 409
    assert _state(db_session, session_id) == before


def test_stale_worker_is_expired_before_renewal(client, db_session):
    relay, _worker_token, session_id, version = _held(client, db_session)
    worker = db_session.get(Worker, db_session.get(HarnessSession, session_id).worker_id)
    worker.last_seen = _now() - timedelta(hours=1)
    db_session.commit()

    assert _renew(client, relay, session_id, version).status_code == 409
    assert _state(db_session, session_id)[0] == "detached"


@pytest.mark.parametrize("seconds", [0, 9, 301, "x"])
def test_lease_seconds_bounds_are_validated(client, db_session, seconds):
    relay, _worker_token, session_id, version = _held(client, db_session)
    before = _state(db_session, session_id)

    assert _renew(client, relay, session_id, version, seconds=seconds).status_code == 422
    assert _state(db_session, session_id) == before


def test_only_a_relay_controller_may_renew(client, db_session):
    relay, worker_token, session_id, version = _held(client, db_session)
    before = _state(db_session, session_id)

    assert _renew(client, relay, session_id, version, token=worker_token).status_code == 403
    no_token = client.post(
        _url(relay, session_id, "lease/renew"), json={"lease_seconds": 60, "expected_version": version}
    )
    assert no_token.status_code == 401
    assert _state(db_session, session_id) == before


def test_other_relays_token_cannot_renew(client, db_session):
    relay_a, _wa, session_a, version_a = _held(client, db_session)
    relay_b, _wb, session_b, _vb = _held(client, db_session)
    before = _state(db_session, session_a)

    response = client.post(
        _url(relay_a, session_a, "lease/renew"),
        json={"lease_seconds": 60, "expected_version": version_a},
        headers=_auth(relay_b["token"]),
    )

    assert response.status_code == 403
    assert _state(db_session, session_a) == before


def test_session_id_from_another_relay_is_404(client, db_session):
    relay_a, _wa, _session_a, _va = _held(client, db_session)
    relay_b, _wb, session_b, version_b = _held(client, db_session)
    before = _state(db_session, session_b)

    assert _renew(client, relay_a, session_b, version_b).status_code == 404
    assert _state(db_session, session_b) == before


def test_renew_in_one_session_does_not_touch_or_notify_another(client, db_session):
    relay_a, _wa, session_a, version_a = _held(client, db_session)
    relay_b, _wb, session_b, _vb = _held(client, db_session)
    before_b = _state(db_session, session_b)

    with client.websocket_connect(
        _url(relay_b, session_b, f"stream?cursor={FAR_CURSOR}"), headers=_ws_headers(relay_b["token"])
    ) as controller_b:
        _receive_until(controller_b, "connected")
        assert _renew(client, relay_a, session_a, version_a).status_code == 200
        client.post(
            _url(relay_b, session_b, "events"),
            json={"kind": "output", "data": {"text": "marker"}},
            headers=_auth(_wb),
        )
        first = _receive_until(controller_b, "event")["event"]

    assert first["kind"] == "output"
    assert _state(db_session, session_b)[:4] == before_b[:4]


def test_concurrent_renewals_with_same_version_succeed_once(client, db_session):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    relay, _worker_token, session_id, version = _held(client, db_session)
    barrier = Barrier(2)

    def renew():
        barrier.wait()
        return _renew(client, relay, session_id, version).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(f.result() for f in [pool.submit(renew), pool.submit(renew)])

    assert codes == [200, 409]
    status, new_version, *_ = _state(db_session, session_id)
    assert (status, new_version) == ("controlled", version + 1)
    events = client.get(_url(relay, session_id, "events"), headers=_auth(relay["token"])).json()["events"]
    assert len([e for e in events if e["kind"] == "lease_renewed"]) == 1


def test_worker_cannot_post_lease_renewed_event(client, db_session):
    relay, worker_token, session_id, version = _held(client, db_session)

    response = client.post(
        _url(relay, session_id, "events"),
        json={"kind": "lease_renewed", "data": {}},
        headers=_auth(worker_token),
    )

    assert response.status_code == 422
