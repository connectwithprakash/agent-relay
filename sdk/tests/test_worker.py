"""Managed PTY adapter and worker-bridge tests."""

import fcntl
import json
import shlex
import struct
import sys
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


def test_detector_waits_for_the_last_option_line_to_finish():
    split = PROMPT.index("3. No, and tel") + len("3. No, and tel")
    detector = ApprovalDetector()

    assert detector.feed(PROMPT[:split]) == []
    emitted = detector.feed(PROMPT[split:])

    assert len(emitted) == 1
    assert emitted[0].endswith("(esc)")
    assert detector.feed("later output\n") == []


@pytest.mark.parametrize("cut", range(1, len(PROMPT)))
def test_detector_emits_one_complete_prompt_for_any_split_point(cut):
    detector = ApprovalDetector()
    emitted = detector.feed(PROMPT[:cut]) + detector.feed(PROMPT[cut:])

    assert len(emitted) == 1
    assert emitted[0].endswith("(esc)")


def test_prompt_cap_never_splits_a_multibyte_character():
    prompt_text = "Do you want to edit " + "\u00e9" * 3000 + "?\n1. Yes\n2. No\n"
    prompt, _ = extract_approval_prompt(prompt_text)

    assert len(prompt.encode()) <= 4096
    assert prompt.encode().decode() == prompt
    assert "\ufffd" not in prompt


def test_apply_resize_is_best_effort_for_an_exited_pty():
    session = ManagedPtySession.start("fixture-shell")
    session.close()
    daemon = WorkerDaemon(_FakeControlClient(), "relay-1", "Personal Mac", ["fixture-shell"])

    daemon._apply_resize(session, {"cols": 80, "rows": 24})


def test_stream_releases_its_approval_detector_when_it_ends(monkeypatch):
    _scripted_reads(monkeypatch, ["", PROMPT[:30]])
    daemon = WorkerDaemon(_FakeControlClient(), "relay-1", "Personal Mac", ["fixture-shell"])
    stream = _FakeStream(['{"type":"connected"}'])
    try:
        daemon.start()
        daemon.run_once()
        daemon.stream_owned_session("session-1", max_frames=1, connection_factory=lambda url, subprotocols: stream)
        assert "session-1" not in daemon._approval_detectors
    finally:
        daemon.close()


# Excerpt of raw bytes captured from a real Claude Code startup dialog through a PTY.
# Claude Code separates words with cursor-column escapes instead of spaces.
REAL_DIALOG_BYTES = (
    "\x1b[2GQuick\x1b[8Gsafety\x1b[15Gcheck:\x1b[22GIs\x1b[25Gthis\x1b[30Ga\x1b[32Gproject"
    "\x1b[40Gyou\x1b[44Gcreated\x1b[52Gor\x1b[55Gone\x1b[59Gyou\x1b[63Gtrust?\r\r\n"
)


def _cursor_positioned(text):
    """Re-render plain text the way Claude Code does: words placed by column escapes."""
    rendered = []
    for line in text.splitlines():
        column = 2
        out = ""
        for word in line.split(" "):
            out += f"\x1b[{column}G{word}"
            column += len(word) + 1
        rendered.append(out)
    return "\r\r\n".join(rendered) + "\r\r\n"


def test_cursor_column_escapes_become_word_separators():
    from agent_relay.worker import _clean_terminal_text

    cleaned = _clean_terminal_text(REAL_DIALOG_BYTES)

    assert "Quick safety check: Is this a project you created or one you trust?" in " ".join(cleaned.split())


def test_prompt_is_detected_when_words_are_placed_by_cursor_escapes():
    rendered = _cursor_positioned(PROMPT)
    detector = ApprovalDetector()
    cut = len(rendered) // 2

    emitted = detector.feed(rendered[:cut]) + detector.feed(rendered[cut:])

    assert len(emitted) == 1
    assert " ".join(emitted[0].split()).startswith("Do you want to proceed?")
    assert emitted[0].endswith("(esc)")


def test_stream_skips_replayed_input_the_polling_path_already_applied():
    client = _FakeControlClient()
    daemon = WorkerDaemon(client, "relay-1", "Personal Mac", ["fixture-shell"])
    stream = _FakeStream([
        '{"type":"event","event":{"sequence":1,"kind":"input_requested","data":{"input":"replayed\\n"}}}',
        '{"type":"event","event":{"sequence":2,"kind":"input_requested","data":{"input":"fresh\\n"}}}',
    ])
    try:
        daemon.start()
        daemon.run_once()  # applies sequence 1 ("bridge test") and records the cursor
        assert daemon._cursors["session-1"] == 1
        daemon.stream_owned_session("session-1", max_frames=2, connection_factory=lambda url, subprotocols: stream)

        seen = "".join(json.loads(frame).get("text", "") for frame in stream.sent)
        deadline = time.monotonic() + 3.0
        while "echo:fresh" not in seen and time.monotonic() < deadline:
            seen += daemon._sessions["session-1"].read(timeout=0.1)
        assert "echo:fresh" in seen
        assert "echo:replayed" not in seen
        assert daemon._cursors["session-1"] == 2
    finally:
        daemon.close()


def test_run_once_flushes_remaining_output_before_reporting_exit():
    class QuietClient(_FakeControlClient):
        def get_session_events(self, relay_id, session_id, after_sequence=0):
            return []

    client = QuietClient()
    daemon = WorkerDaemon(client, "relay-1", "Personal Mac", ["fixture-shell"])
    try:
        daemon.start()
        daemon.run_once()
        daemon._sessions["session-1"].write("last words\n\x04")  # echo the line, then end of input
        deadline = time.monotonic() + 5.0
        while "session_exited" not in [e[2] for e in client.output_events] and time.monotonic() < deadline:
            daemon.run_once()
            time.sleep(0.02)

        kinds = [kind for _, _, kind, _ in client.output_events]
        assert kinds[-1] == "session_exited"
        text = "".join(data["text"] for _, _, kind, data in client.output_events if kind == "output")
        assert "echo:last words" in text
    finally:
        daemon.close()


_BURST_PROGRAM = """import sys, time
sys.stdout.write('x' * 300000)
sys.stdout.flush()
time.sleep(0.1)
sys.stdout.write('y' * 200 + '\\nEND-OF-BURST\\n')
sys.stdout.flush()
"""


def _run_burst_session(tmp_path, read_delay=0.0):
    script = tmp_path / "claude"
    script.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} -u -c {shlex.quote(_BURST_PROGRAM)}\n")
    script.chmod(0o755)

    class BurstClient(_FakeControlClient):
        def register_worker(self, relay_id, name, profiles):
            return {"worker_id": "worker-1"}

        def list_worker_sessions(self, relay_id, worker_id):
            return [{"session_id": "session-1", "profile": "claude-code", "status": "starting"}]

        def get_session_events(self, relay_id, session_id, after_sequence=0):
            return []

    client = BurstClient()
    daemon = WorkerDaemon(
        client, "relay-1", "Personal Mac", ["claude-code"],
        profile_workdirs={"claude-code": str(tmp_path)},
        profile_executables={"claude-code": str(script)},
    )
    try:
        daemon.start()
        deadline = time.monotonic() + 20.0
        while "session_exited" not in [e[2] for e in client.output_events] and time.monotonic() < deadline:
            daemon.run_once()
            time.sleep(read_delay)
    finally:
        daemon.close()
    return client


def test_output_larger_than_the_pty_buffer_survives_an_immediate_exit(tmp_path):
    # The tail is written after the worker has gone quiet and the child exits before the next
    # poll, so only a worker that keeps the PTY slave open can still read it.
    client = _run_burst_session(tmp_path, read_delay=0.25)

    kinds = [e[2] for e in client.output_events]
    assert kinds[-1] == "session_exited"
    text = "".join(d["text"] for _, _, kind, d in client.output_events if kind == "output")
    assert text.count("x") == 300000
    assert text.count("y") == 200
    assert text.rstrip().endswith("END-OF-BURST")


def test_output_written_before_exit_is_kept_when_nobody_reads_until_after_the_child_ends(tmp_path):
    program = "import sys; sys.stdout.write('y' * 200 + '\\nEND-OF-OUTPUT\\n'); sys.stdout.flush()"
    script = tmp_path / "claude"
    script.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} -c {shlex.quote(program)}\n")
    script.chmod(0o755)
    session = ManagedPtySession.start("claude-code", str(tmp_path), str(script))
    try:
        time.sleep(0.5)  # the child writes and exits while nothing is reading
        collected = ""
        deadline = time.monotonic() + 5.0
        while "END-OF-OUTPUT" not in collected and time.monotonic() < deadline:
            collected += session.read(timeout=0.1)
        assert collected.count("y") == 200
        assert "END-OF-OUTPUT" in collected
    finally:
        session.close()


def _read_until_text(session, needle, timeout=5.0):
    deadline = time.monotonic() + timeout
    collected = ""
    while needle not in collected and time.monotonic() < deadline:
        collected += session.read(timeout=0.1)
    return collected


def test_fixture_shell_reports_its_terminal_size_after_a_resize():
    session = ManagedPtySession.start("fixture-shell")
    try:
        session.resize(100, 30)
        session.write("size\n")
        assert "size:100x30" in _read_until_text(session, "size:100x30")
    finally:
        session.close()


def test_fixture_shell_prints_a_detectable_permission_prompt_on_request():
    session = ManagedPtySession.start("fixture-shell")
    try:
        session.write("approval\n")
        output = _read_until_text(session, "2. No")
        detector = ApprovalDetector()
        prompts = detector.feed(output)
        assert len(prompts) >= 1
        assert prompts[-1].startswith("Do you want to proceed?")
    finally:
        session.close()


def test_read_on_a_closed_session_returns_nothing_instead_of_raising():
    session = ManagedPtySession.start("fixture-shell")
    session.close()

    assert session.read(timeout=0.05) == ""
    assert session.closed


def test_stream_ends_cleanly_when_its_session_is_closed_underneath_it():
    class IdleStream(_FakeStream):
        def recv(self, timeout):
            raise TimeoutError

    daemon = WorkerDaemon(_FakeControlClient(), "relay-1", "Personal Mac", ["fixture-shell"])
    try:
        daemon.start()
        daemon.run_once()
        daemon._sessions["session-1"].close()
        daemon.stream_owned_session("session-1", connection_factory=lambda url, subprotocols: IdleStream([]))
    finally:
        daemon.close()


def _reconnect_daemon():
    daemon = WorkerDaemon(_FakeControlClient(), "relay-1", "Personal Mac", ["fixture-shell"])
    daemon.start()
    daemon.run_once()
    return daemon


def _factory(outcomes):
    """Return a connection factory that raises or yields streams from a scripted list."""
    attempts = []

    def connect(url, subprotocols):
        attempts.append(url)
        outcome = outcomes[len(attempts) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    connect.attempts = attempts
    return connect


def test_run_stream_with_reconnect_retries_dropped_connections_with_backoff():
    from websockets.exceptions import ConnectionClosedError

    daemon = _reconnect_daemon()
    sleeps = []
    stream = _FakeStream(['{"type":"event","event":{"sequence":9,"kind":"input_requested","data":{"input":"after drop\\n"}}}'])
    factory = _factory([ConnectionClosedError(None, None), ConnectionRefusedError("down"), stream])
    try:
        daemon.run_stream_with_reconnect(
            "session-1", sleep=sleeps.append, connection_factory=factory, max_frames=1
        )
        assert len(factory.attempts) == 3
        assert sleeps == [1.0, 2.0]
    finally:
        daemon.close()


def test_run_stream_with_reconnect_gives_up_after_the_bounded_attempts():
    from websockets.exceptions import ConnectionClosedError

    daemon = _reconnect_daemon()
    sleeps = []
    factory = _factory([ConnectionClosedError(None, None)] * 3)
    try:
        with pytest.raises(ConnectionClosedError):
            daemon.run_stream_with_reconnect(
                "session-1", max_attempts=3, sleep=sleeps.append, connection_factory=factory
            )
        assert len(factory.attempts) == 3
        assert sleeps == [1.0, 2.0]
    finally:
        daemon.close()


def test_run_stream_with_reconnect_does_not_retry_programming_errors():
    daemon = _reconnect_daemon()
    factory = _factory([ValueError("bad frame")])
    try:
        with pytest.raises(ValueError):
            daemon.run_stream_with_reconnect("session-1", sleep=lambda s: None, connection_factory=factory)
        assert len(factory.attempts) == 1
    finally:
        daemon.close()


def test_run_stream_with_reconnect_stops_once_the_session_is_closed():
    from websockets.exceptions import ConnectionClosedError

    daemon = _reconnect_daemon()
    factory = _factory([ConnectionClosedError(None, None)] * 5)
    try:
        daemon._sessions["session-1"].close()
        with pytest.raises(ConnectionClosedError):
            daemon.run_stream_with_reconnect("session-1", sleep=lambda s: None, connection_factory=factory)
        assert len(factory.attempts) == 1
    finally:
        daemon.close()
