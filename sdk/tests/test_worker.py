"""Managed PTY adapter and worker-bridge tests."""

import fcntl
import struct
import termios
import time
import pytest

from agent_relay.worker import ApprovalDetector, ManagedPtySession, WorkerDaemon, extract_approval_prompt


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
    def __init__(self, frames=None):
        self.frames = frames if frames is not None else [
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


PROMPT = (
    "Do you want to proceed?\n"
    "  > 1. Yes\n"
    "    2. Yes, and don't ask again for this command\n"
    "    3. No, and tell the agent what to do differently (esc)\n"
)


def _window_size(session):
    packed = fcntl.ioctl(session.master_fd, termios.TIOCGWINSZ, struct.pack("HHHH", 0, 0, 0, 0))
    rows, cols, _, _ = struct.unpack("HHHH", packed)
    return cols, rows


def test_resize_applies_window_size_to_the_pty():
    session = ManagedPtySession.start("fixture-shell")
    try:
        session.resize(132, 43)
        assert _window_size(session) == (132, 43)
    finally:
        session.close()


@pytest.mark.parametrize("cols,rows", [(19, 24), (501, 24), (80, 4), (80, 201), (True, 24), ("80", 24)])
def test_resize_rejects_out_of_contract_dimensions(cols, rows):
    session = ManagedPtySession.start("fixture-shell")
    try:
        before = _window_size(session)
        with pytest.raises(ValueError):
            session.resize(cols, rows)
        assert _window_size(session) == before
    finally:
        session.close()


def test_extract_approval_prompt_finds_permission_prompt():
    prompt, end = extract_approval_prompt("noise\n" + PROMPT)
    assert prompt.startswith("Do you want to proceed?")
    assert "1. Yes" in prompt and "3. No" in prompt
    assert end > 0


def test_extract_approval_prompt_ignores_ansi_and_ordinary_output():
    colored = "\x1b[1mDo you want to proceed?\x1b[0m\r\n\x1b[36m> 1. Yes\x1b[0m\r\n  2. No\r\n"
    prompt, _ = extract_approval_prompt(colored)
    assert "\x1b" not in prompt and "1. Yes" in prompt
    assert extract_approval_prompt("compiling...\nDo you want to proceed? maybe later\n") is None
    assert extract_approval_prompt("1. Yes\n2. No\n") is None


def test_extract_approval_prompt_caps_prompt_size():
    big = "Do you want to make this edit to " + "x" * 6000 + "?\n1. Yes\n2. No\n"
    prompt, _ = extract_approval_prompt(big)
    assert len(prompt.encode()) <= 4096


def test_detector_emits_once_per_prompt_across_chunks():
    detector = ApprovalDetector()
    emitted = []
    for chunk in [PROMPT[:20], PROMPT[20:60], PROMPT[60:], "still waiting\n", "more output\n"]:
        emitted.extend(detector.feed(chunk))
    assert len(emitted) == 1
    assert detector.feed(PROMPT) and len(detector.feed("x")) == 0


def _scripted_reads(monkeypatch, chunks):
    queue = list(chunks)
    monkeypatch.setattr(ManagedPtySession, "read", lambda self, timeout=0.0: queue.pop(0) if queue else "")


def test_run_once_applies_resize_requested_events_to_the_pty():
    class ResizeClient(_FakeControlClient):
        def get_session_events(self, relay_id, session_id, after_sequence=0):
            if after_sequence:
                return []
            return [{"sequence": 1, "kind": "resize_requested", "data": {"cols": 100, "rows": 30}}]

    daemon = WorkerDaemon(ResizeClient(), "relay-1", "Personal Mac", ["fixture-shell"])
    try:
        daemon.start()
        daemon.run_once()
        assert _window_size(daemon._sessions["session-1"]) == (100, 30)
    finally:
        daemon.close()


def test_run_once_reports_each_prompt_once_without_changing_output(monkeypatch):
    _scripted_reads(monkeypatch, ["working\n", PROMPT[:30], PROMPT[30:], "after\n"])
    client = _FakeControlClient()
    daemon = WorkerDaemon(client, "relay-1", "Personal Mac", ["fixture-shell"])
    try:
        daemon.start()
        for _ in range(5):
            daemon.run_once()
        outputs = [d["text"] for _, _, k, d in client.output_events if k == "output"]
        assert "".join(outputs) == "working\n" + PROMPT + "after\n"
        approvals = [d for _, _, k, d in client.output_events if k == "approval_requested"]
        assert len(approvals) == 1
        assert approvals[0]["prompt"].startswith("Do you want to proceed?")
    finally:
        daemon.close()


def test_stream_applies_resize_and_sends_one_approval_frame(monkeypatch):
    _scripted_reads(monkeypatch, ["", "", PROMPT, "tail\n"])
    client = _FakeControlClient()
    daemon = WorkerDaemon(client, "relay-1", "Personal Mac", ["fixture-shell"])
    stream = _FakeStream([
        '{"type":"connected"}',
        '{"type":"event","event":{"kind":"resize_requested","data":{"cols":90,"rows":40}}}',
        '{"type":"event","event":{"kind":"resize_requested","data":{"cols":10,"rows":40}}}',
    ])
    try:
        daemon.start()
        daemon.run_once()
        daemon.stream_owned_session("session-1", max_frames=3, connection_factory=lambda url, subprotocols: stream)
        assert _window_size(daemon._sessions["session-1"]) == (90, 40)
        import json
        frames = [json.loads(f) for f in stream.sent]
        approvals = [f for f in frames if f["type"] == "approval"]
        assert len(approvals) == 1 and approvals[0]["prompt"].startswith("Do you want to proceed?")
        assert "".join(f["text"] for f in frames if f["type"] == "output") == PROMPT + "tail\n"
    finally:
        daemon.close()
