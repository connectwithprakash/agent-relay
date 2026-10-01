"""Managed PTY adapter and worker-bridge tests."""

import time
import pytest

from agent_relay.worker import ManagedPtySession, WorkerDaemon


def test_fixture_profile_round_trips_terminal_input():
    session = ManagedPtySession.start("fixture-shell")
    try:
        assert "fixture ready" in session.read(timeout=1.0)

        session.write("hello from controller\n")
        output = session.read(timeout=1.0)
        assert "echo:hello from controller" in output
    finally:
        session.close()


def test_unknown_profile_is_rejected_without_starting_a_process():
    try:
        ManagedPtySession.start("not-allowlisted")
    except ValueError as error:
        assert "not allowed" in str(error)
    else:
        raise AssertionError("Unknown profile started a process")


def test_claude_profile_fails_closed_when_executable_is_missing(monkeypatch):
    monkeypatch.setattr("agent_relay.worker.shutil.which", lambda name: None)

    with pytest.raises(RuntimeError, match="not installed"):
        ManagedPtySession.start("claude-code", "/tmp")


def test_closed_session_rejects_input():
    session = ManagedPtySession.start("fixture-shell")
    session.close()

    try:
        session.write("must not be delivered\n")
    except RuntimeError as error:
        assert "not running" in str(error)
    else:
        raise AssertionError("Closed PTY accepted input")


class _FakeControlClient:
    def __init__(self):
        self.base_url = "https://relay.example.test"
        self._token = "worker-token"
        self.ready_sessions = []
        self.output_events = []

    def register_worker(self, relay_id, name, profiles):
        assert relay_id == "relay-1"
        assert profiles == ["fixture-shell"]
        return {"worker_id": "worker-1"}

    def list_worker_sessions(self, relay_id, worker_id):
        assert (relay_id, worker_id) == ("relay-1", "worker-1")
        return [{"session_id": "session-1", "profile": "fixture-shell", "status": "starting"}]

    def mark_session_ready(self, relay_id, session_id):
        self.ready_sessions.append((relay_id, session_id))
        return {"status": "ready"}

    def get_session_events(self, relay_id, session_id, after_sequence=0):
        assert (relay_id, session_id) == ("relay-1", "session-1")
        if after_sequence:
            return []
        return [{"sequence": 1, "kind": "input_requested", "data": {"input": "bridge test\n"}}]

    def append_session_event(self, relay_id, session_id, kind, data):
        self.output_events.append((relay_id, session_id, kind, data))
        return {"event": {"sequence": 2}}


def test_worker_daemon_bridges_authorized_input_to_owned_pty_output():
    client = _FakeControlClient()
    daemon = WorkerDaemon(client, "relay-1", "Personal Mac", ["fixture-shell"])
    try:
        daemon.start()
        deadline = time.monotonic() + 5.0
        collected = ""
        while "echo:bridge test" not in collected and time.monotonic() < deadline:
            daemon.run_once()
            collected = "".join(
                data["text"] for _, _, kind, data in client.output_events if kind == "output"
            )
            time.sleep(0.02)

        assert client.ready_sessions == [("relay-1", "session-1")]
        assert "echo:bridge test" in collected
    finally:
        daemon.close()

def test_worker_daemon_reports_detached_sessions_as_failed_after_restart():
    class DetachedClient(_FakeControlClient):
        def list_worker_sessions(self, relay_id, worker_id):
            return [{"session_id": "session-detached", "profile": "fixture-shell", "status": "detached"}]

    client = DetachedClient()
    daemon = WorkerDaemon(client, "relay-1", "Personal Mac", ["fixture-shell"])
    try:
        daemon.start()
        daemon.run_once()
        assert client.output_events == [
            ("relay-1", "session-detached", "session_failed", {"reason": "worker_restarted"})
        ]
    finally:
        daemon.close()


def test_worker_daemon_reports_unowned_ready_sessions_as_failed_after_restart():
    class ReadyClient(_FakeControlClient):
        def list_worker_sessions(self, relay_id, worker_id):
            return [{"session_id": "session-ready", "profile": "fixture-shell", "status": "ready"}]

    client = ReadyClient()
    daemon = WorkerDaemon(client, "relay-1", "Personal Mac", ["fixture-shell"])
    try:
        daemon.start()
        daemon.run_once()
        assert client.output_events == [
            ("relay-1", "session-ready", "session_failed", {"reason": "worker_restarted"})
        ]
    finally:
        daemon.close()


class _FakeStream:
    def __init__(self):
        self.frames = [
            '{"type":"connected"}',
            '{"type":"event","event":{"kind":"input_requested","data":{"input":"stream bridge\\n"}}}',
        ]
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def recv(self, timeout):
        return self.frames.pop(0)

    def send(self, frame):
        self.sent.append(frame)


def test_worker_stream_bridges_live_input_to_its_owned_pty():
    client = _FakeControlClient()
    daemon = WorkerDaemon(client, "relay-1", "Personal Mac", ["fixture-shell"])
    stream = _FakeStream()
    captured = {}

    def connect(url, subprotocols):
        captured["url"] = url
        captured["subprotocols"] = subprotocols
        return stream

    try:
        daemon.start()
        daemon.run_once()
        daemon.stream_owned_session("session-1", max_frames=2, connection_factory=connect)

        assert captured["url"] == "wss://relay.example.test/relays/relay-1/sessions/session-1/stream?cursor=0"
        assert captured["subprotocols"] == ["token-worker-token"]
        assert any("echo:stream bridge" in frame for frame in stream.sent)
    finally:
        daemon.close()
