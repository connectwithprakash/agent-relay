"""One failing session must not starve the others in run_once."""

import time

import httpx
import pytest

from agent_relay.exceptions import AgentRelayError
from agent_relay.worker import WorkerDaemon


class _MultiClient:
    base_url = "https://relay.example.test"
    _token = "worker-token"

    def __init__(self, session_ids=("bad", "good")):
        self.sessions = [
            {"session_id": sid, "profile": "fixture-shell", "status": "starting"} for sid in session_ids
        ]
        self.events = {sid: [] for sid in session_ids}
        self.fail_events = {}
        self.fail_append = {}
        self.fail_ready = {}
        self.appended = []
        self.ready_calls = []
        self.event_calls = {sid: 0 for sid in session_ids}

    def register_worker(self, relay_id, name, profiles):
        return {"worker_id": "worker-1"}

    def list_worker_sessions(self, relay_id, worker_id):
        return self.sessions

    def mark_session_ready(self, relay_id, session_id):
        self.ready_calls.append(session_id)
        failure = self.fail_ready.get(session_id)
        if failure and len([c for c in self.ready_calls if c == session_id]) <= failure[0]:
            raise failure[1]
        return {"status": "ready"}

    def get_session_events(self, relay_id, session_id, after_sequence=0):
        self.event_calls[session_id] += 1
        failure = self.fail_events.get(session_id)
        if failure and self.event_calls[session_id] <= failure[0]:
            raise failure[1]
        return [e for e in self.events[session_id] if e["sequence"] > after_sequence]

    def append_session_event(self, relay_id, session_id, kind, data):
        failure = self.fail_append.get((session_id, kind))
        if failure and failure[0] > 0:
            self.fail_append[(session_id, kind)] = (failure[0] - 1, failure[1])
            raise failure[1]
        self.appended.append((session_id, kind, data))
        return {"event": {"sequence": 1}}


def _input(sequence, text):
    return {"sequence": sequence, "kind": "input_requested", "data": {"input": text}}


def _output(client, session_id):
    return "".join(d["text"] for sid, kind, d in client.appended if sid == session_id and kind == "output")


def _pump(daemon, client, session_id, needle, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        daemon.run_once()
        if needle in _output(client, session_id):
            return
        time.sleep(0.03)
    raise AssertionError(f"{needle!r} not seen for {session_id}")


@pytest.fixture
def make_daemon():
    daemons = []

    def build(client):
        daemon = WorkerDaemon(client, "relay-1", "Mac", ["fixture-shell"])
        daemon.start()
        daemons.append(daemon)
        return daemon

    yield build
    for daemon in daemons:
        daemon.close()


CONNECT_ERROR = httpx.ConnectError("connection refused")


def test_a_failing_session_does_not_stop_the_next_one_in_the_same_pass(make_daemon):
    client = _MultiClient()
    client.events["good"] = [_input(1, "good-input\n")]
    client.fail_events["bad"] = (1000, CONNECT_ERROR)
    daemon = make_daemon(client)

    daemon.run_once()  # starts both, bad's event fetch fails

    assert daemon._cursors.get("good") == 1  # good's input was applied in the same pass
    assert daemon._cursors.get("bad", 0) == 0  # nothing advanced for bad
    _pump(daemon, client, "good", "echo:good-input")


def test_a_recovering_session_processes_its_events_in_order_without_loss_or_duplication(make_daemon):
    client = _MultiClient()
    client.events["bad"] = [_input(1, "one\n"), _input(2, "two\n")]
    client.fail_events["bad"] = (3, httpx.ReadTimeout(""))
    daemon = make_daemon(client)

    for _ in range(3):
        daemon.run_once()
        assert daemon._cursors.get("bad", 0) == 0
    _pump(daemon, client, "bad", "echo:two")

    text = _output(client, "bad")
    assert text.count("echo:one") == 1 and text.count("echo:two") == 1
    assert text.index("echo:one") < text.index("echo:two")
    assert daemon._cursors["bad"] == 2


def test_an_error_is_logged_once_per_session_until_it_changes_or_recovers(make_daemon, capsys):
    client = _MultiClient(session_ids=("bad",))
    daemon = make_daemon(client)
    client.fail_events["bad"] = (4, CONNECT_ERROR)
    capsys.readouterr()
    for _ in range(4):
        daemon.run_once()
    first = [l for l in capsys.readouterr().err.splitlines() if "bad" in l]
    assert len(first) == 1

    client.fail_events["bad"] = (1000, AgentRelayError("revoked", status_code=403))
    daemon.run_once()
    daemon.run_once()
    changed = [l for l in capsys.readouterr().err.splitlines() if "bad" in l]
    assert len(changed) == 1 and "revoked" in changed[0]

    client.fail_events["bad"] = (0, None)
    daemon.run_once()  # recovers
    client.fail_events["bad"] = (1000, AgentRelayError("revoked", status_code=403))
    client.event_calls["bad"] = 0
    capsys.readouterr()
    daemon.run_once()
    again = [l for l in capsys.readouterr().err.splitlines() if "bad" in l]
    assert len(again) == 1  # same error after a recovery is news again


def test_other_exception_types_still_propagate(make_daemon):
    client = _MultiClient(session_ids=("bad",))
    client.fail_events["bad"] = (1, KeyError("sequence"))
    daemon = make_daemon(client)

    with pytest.raises(KeyError):
        daemon.run_once()


def test_output_is_kept_and_resent_when_the_append_fails(make_daemon):
    client = _MultiClient(session_ids=("good",))
    client.events["good"] = [_input(1, "keep me\n")]
    client.fail_append[("good", "output")] = (2, CONNECT_ERROR)
    daemon = make_daemon(client)

    _pump(daemon, client, "good", "echo:keep me")

    text = _output(client, "good")
    assert text.count("echo:keep me") == 1
    assert text.count("fixture ready") == 1


def test_a_failed_mark_ready_is_retried_without_starting_a_second_process(make_daemon):
    client = _MultiClient(session_ids=("good",))
    client.fail_ready["good"] = (1, CONNECT_ERROR)
    daemon = make_daemon(client)

    daemon.run_once()
    first_process = daemon._sessions["good"]
    daemon.run_once()

    assert client.ready_calls == ["good", "good"]
    assert daemon._sessions["good"] is first_process
    daemon.run_once()
    assert client.ready_calls == ["good", "good"]
