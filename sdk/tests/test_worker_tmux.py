"""tmux-backed session profile tests: re-attach, capture rotation, and state files."""

import json
import os
import shutil
import stat
import subprocess
import time
import uuid

import pytest

from agent_relay.worker import ManagedTmuxSession, WorkerDaemon

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is not installed")

ECHO_SCRIPT = """#!/bin/sh
echo ready
while IFS= read -r line; do echo "echo:$line"; done
"""


@pytest.fixture
def socket_name():
    name = f"arelay-test-{uuid.uuid4().hex[:8]}"
    yield name
    subprocess.run(["tmux", "-L", name, "kill-server"], capture_output=True)


@pytest.fixture
def state_dir(tmp_path):
    return tmp_path / "state"


def _script(tmp_path, body=ECHO_SCRIPT, name="agent.sh"):
    path = tmp_path / name
    path.write_text(body)
    path.chmod(0o755)
    return str(path)


def _start(tmp_path, socket_name, state_dir, session_id="s1", body=ECHO_SCRIPT, **kwargs):
    return ManagedTmuxSession.start(
        session_id,
        str(tmp_path),
        _script(tmp_path, body),
        socket=socket_name,
        state_dir=state_dir,
        **kwargs,
    )


def _read_until(session, needle, timeout=5.0):
    deadline = time.monotonic() + timeout
    collected = ""
    while needle not in collected and time.monotonic() < deadline:
        collected += session.read(timeout=0.1)
    return collected


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def test_write_and_read_round_trip(tmp_path, socket_name, state_dir):
    session = _start(tmp_path, socket_name, state_dir)
    try:
        assert "ready" in _read_until(session, "ready")
        session.write("hello tmux\n")
        assert "echo:hello tmux" in _read_until(session, "echo:hello tmux")
    finally:
        session.close()


def test_state_dir_and_files_are_private(tmp_path, socket_name, state_dir):
    session = _start(tmp_path, socket_name, state_dir)
    try:
        _read_until(session, "ready")
        session.save_cursor(4)
        assert _mode(state_dir) == 0o700
        files = [p for p in state_dir.iterdir()]
        assert files
        assert all(_mode(p) == 0o600 for p in files)
    finally:
        session.close()


def test_resize_sets_the_tmux_window_size(tmp_path, socket_name, state_dir):
    session = _start(tmp_path, socket_name, state_dir)
    try:
        session.resize(132, 43)
        assert session.display("#{window_width}x#{window_height}") == "132x43"
    finally:
        session.close()


@pytest.mark.parametrize("cols,rows", [(19, 24), (501, 24), (80, 4), (80, 201), (True, 24), ("80", 24)])
def test_resize_rejects_out_of_contract_dimensions(tmp_path, socket_name, state_dir, cols, rows):
    session = _start(tmp_path, socket_name, state_dir)
    try:
        before = session.display("#{window_width}x#{window_height}")
        with pytest.raises(ValueError):
            session.resize(cols, rows)
        assert session.display("#{window_width}x#{window_height}") == before
    finally:
        session.close()


def test_poll_reports_exit_code_when_command_exits(tmp_path, socket_name, state_dir):
    session = _start(tmp_path, socket_name, state_dir, body="#!/bin/sh\necho bye\nexit 3\n")
    try:
        deadline = time.monotonic() + 5.0
        while session.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert session.poll() == 3
        assert "bye" in _read_until(session, "bye")
    finally:
        session.close()


def test_invalid_session_ids_are_rejected(tmp_path, socket_name, state_dir):
    with pytest.raises(ValueError):
        _start(tmp_path, socket_name, state_dir, session_id="../escape")


def test_start_fails_closed_without_a_valid_executable_or_workdir(tmp_path, socket_name, state_dir, monkeypatch):
    real_which = shutil.which
    monkeypatch.setattr("agent_relay.worker.shutil.which", lambda name: None if name == "claude" else real_which(name))
    with pytest.raises(RuntimeError, match="not installed"):
        ManagedTmuxSession.start("s1", str(tmp_path), None, socket=socket_name, state_dir=state_dir)
    with pytest.raises(ValueError, match="workdir"):
        ManagedTmuxSession.start("s1", "relative", _script(tmp_path), socket=socket_name, state_dir=state_dir)


def test_detach_leaves_tmux_running_and_attach_resumes_without_replay(tmp_path, socket_name, state_dir):
    session = _start(tmp_path, socket_name, state_dir)
    _read_until(session, "ready")
    session.write("one\n")
    assert "echo:one" in _read_until(session, "echo:one")
    session.detach()

    # Output produced while no worker is attached is delivered exactly once on re-attach.
    subprocess.run(
        ["tmux", "-L", socket_name, "send-keys", "-t", "arelay-s1", "-l", "two\n"], check=True
    )
    resumed = ManagedTmuxSession.attach("s1", socket=socket_name, state_dir=state_dir)
    assert resumed is not None
    try:
        collected = _read_until(resumed, "echo:two")
        assert "echo:two" in collected
        assert "echo:one" not in collected
        assert "ready" not in collected
        resumed.write("three\n")
        assert "echo:three" in _read_until(resumed, "echo:three")
    finally:
        resumed.close()


def test_attach_returns_none_for_unknown_session(tmp_path, socket_name, state_dir):
    assert ManagedTmuxSession.attach("missing", socket=socket_name, state_dir=state_dir) is None


def test_close_kills_tmux_and_removes_state_files(tmp_path, socket_name, state_dir):
    session = _start(tmp_path, socket_name, state_dir)
    _read_until(session, "ready")
    session.save_cursor(2)
    session.close()

    assert ManagedTmuxSession.attach("s1", socket=socket_name, state_dir=state_dir) is None
    assert [p.name for p in state_dir.iterdir() if p.name.startswith("arelay-s1")] == []
    with pytest.raises(RuntimeError, match="not running"):
        session.write("late\n")


def test_capture_file_rotates_without_losing_or_duplicating_output(tmp_path, socket_name, state_dir):
    body = "#!/bin/sh\nfor i in $(seq 1 400); do echo \"line-$i-xxxxxxxxxxxxxxxxxxxx\"; done\nsleep 30\n"
    session = _start(tmp_path, socket_name, state_dir, body=body, capture_cap_bytes=2048)
    try:
        collected = _read_until(session, "line-400-", timeout=10.0)
        lines = [l.strip() for l in collected.splitlines() if l.strip().startswith("line-")]
        assert lines == [f"line-{i}-xxxxxxxxxxxxxxxxxxxx" for i in range(1, 401)]
        time.sleep(0.4)
        session.read(timeout=0.1)
        capture_files = [p for p in state_dir.iterdir() if p.name.endswith(".out")]
        assert len(capture_files) <= 2
    finally:
        session.close()


def test_cursor_is_persisted_atomically(tmp_path, socket_name, state_dir):
    session = _start(tmp_path, socket_name, state_dir)
    try:
        assert session.load_cursor() == 0
        session.save_cursor(7)
        session.save_cursor(9)
        assert session.load_cursor() == 9
        assert not [p for p in state_dir.iterdir() if p.name.endswith(".tmp")]
        session.detach()
        again = ManagedTmuxSession.attach("s1", socket=socket_name, state_dir=state_dir)
        assert again.load_cursor() == 9
        session = again
    finally:
        session.close()


def test_offset_file_is_valid_json(tmp_path, socket_name, state_dir):
    session = _start(tmp_path, socket_name, state_dir)
    try:
        _read_until(session, "ready")
        state = json.loads((state_dir / "arelay-s1.offset").read_text())
        assert state["offset"] > 0 and state["gen"] >= 0
    finally:
        session.close()


class _TmuxClient:
    base_url = "https://relay.example.test"
    _token = "worker-token"

    def __init__(self, status="starting", events=None):
        self.status = status
        self.events = events or []
        self.appended = []
        self.after_sequences = []
        self.ready = []

    def register_worker(self, relay_id, name, profiles):
        return {"worker_id": "worker-1"}

    def list_worker_sessions(self, relay_id, worker_id):
        return [{"session_id": "s1", "profile": "claude-code-tmux", "status": self.status}]

    def mark_session_ready(self, relay_id, session_id):
        self.ready.append(session_id)
        return {"status": "ready"}

    def get_session_events(self, relay_id, session_id, after_sequence=0):
        self.after_sequences.append(after_sequence)
        return [e for e in self.events if e["sequence"] > after_sequence]

    def append_session_event(self, relay_id, session_id, kind, data):
        self.appended.append((kind, data))
        return {"event": {"sequence": 99}}


def _daemon(client, tmp_path, socket_name, state_dir):
    return WorkerDaemon(
        client, "relay-1", "Mac", ["claude-code-tmux"],
        profile_workdirs={"claude-code-tmux": str(tmp_path)},
        profile_executables={"claude-code-tmux": _script(tmp_path)},
        state_dir=state_dir, tmux_socket=socket_name,
    )


def _pump(daemon, client, needle, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        daemon.run_once()
        text = "".join(d["text"] for k, d in client.appended if k == "output")
        if needle in text:
            return text
        time.sleep(0.03)
    raise AssertionError(f"{needle!r} not seen")


def test_daemon_reattaches_after_restart_and_never_replays_old_input(tmp_path, socket_name, state_dir):
    events = [{"sequence": 1, "kind": "input_requested", "data": {"input": "one\n"}}]
    client = _TmuxClient(events=events)
    first = _daemon(client, tmp_path, socket_name, state_dir)
    first.start()
    _pump(first, client, "echo:one")
    first.close()  # worker shutdown: detach, tmux keeps running

    assert subprocess.run(["tmux", "-L", socket_name, "has-session", "-t", "arelay-s1"]).returncode == 0

    client.status = "detached"
    client.events.append({"sequence": 2, "kind": "input_requested", "data": {"input": "two\n"}})
    client.appended.clear()
    client.after_sequences.clear()
    second = _daemon(client, tmp_path, socket_name, state_dir)
    second.start()
    try:
        text = _pump(second, client, "echo:two")
        assert "echo:one" not in text
        assert client.after_sequences[0] == 1
        assert not [k for k, _ in client.appended if k == "session_failed"]
    finally:
        second.close()
        ManagedTmuxSession.attach("s1", socket=socket_name, state_dir=state_dir).close()


def test_daemon_fails_detached_tmux_session_when_tmux_session_is_gone(tmp_path, socket_name, state_dir):
    client = _TmuxClient(status="detached")
    daemon = _daemon(client, tmp_path, socket_name, state_dir)
    daemon.start()
    try:
        daemon.run_once()
        assert client.appended == [("session_failed", {"reason": "worker_restarted"})]
    finally:
        daemon.close()


def test_daemon_reports_exit_and_cleans_up_when_the_command_ends(tmp_path, socket_name, state_dir):
    client = _TmuxClient()
    daemon = WorkerDaemon(
        client, "relay-1", "Mac", ["claude-code-tmux"],
        profile_workdirs={"claude-code-tmux": str(tmp_path)},
        profile_executables={"claude-code-tmux": _script(tmp_path, "#!/bin/sh\necho final words\nexit 5\n")},
        state_dir=state_dir, tmux_socket=socket_name,
    )
    daemon.start()
    try:
        deadline = time.monotonic() + 5.0
        while not [e for e in client.appended if e[0] == "session_exited"] and time.monotonic() < deadline:
            daemon.run_once()
            time.sleep(0.05)
        assert ("session_exited", {"exit_code": 5}) in client.appended
        kinds = [kind for kind, _ in client.appended]
        assert kinds[-1] == "session_exited"
        assert "final words" in "".join(d["text"] for k, d in client.appended if k == "output")
        assert ManagedTmuxSession.attach("s1", socket=socket_name, state_dir=state_dir) is None
        assert [p for p in state_dir.iterdir() if p.name.startswith("arelay-s1")] == []
    finally:
        daemon.close()


def test_stream_skips_input_at_or_below_the_persisted_cursor(tmp_path, socket_name, state_dir):
    client = _TmuxClient()
    daemon = _daemon(client, tmp_path, socket_name, state_dir)
    daemon.start()
    try:
        daemon.run_once()
        daemon._sessions["s1"].save_cursor(5)
        daemon._cursors["s1"] = 5

        class Stream:
            frames = [
                json.dumps({"type": "event", "event": {"sequence": 5, "kind": "input_requested", "data": {"input": "old\n"}}}),
                json.dumps({"type": "event", "event": {"sequence": 6, "kind": "input_requested", "data": {"input": "new\n"}}}),
            ]
            sent = []

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def recv(self, timeout):
                return self.frames.pop(0)

            def send(self, frame):
                self.sent.append(frame)

        stream = Stream()
        daemon.stream_owned_session("s1", max_frames=2, connection_factory=lambda url, subprotocols: stream)
        text = "".join(json.loads(f).get("text", "") for f in stream.sent)
        deadline = time.monotonic() + 3.0
        while "echo:new" not in text and time.monotonic() < deadline:
            text += daemon._sessions["s1"].read(timeout=0.1)
        assert "echo:new" in text
        assert "echo:old" not in text
        assert daemon._sessions["s1"].load_cursor() == 6
    finally:
        daemon.close()
        ManagedTmuxSession.attach("s1", socket=socket_name, state_dir=state_dir).close()


def test_executable_path_with_spaces_and_metacharacters_is_launched_literally(tmp_path, socket_name, state_dir):
    folder = tmp_path / "my tools; touch injected-marker; true"
    folder.mkdir()
    marker = tmp_path / "injected-marker"
    script = folder / "claude"
    script.write_text("#!/bin/sh\necho spaced-path-marker\nsleep 30\n")
    script.chmod(0o755)

    session = ManagedTmuxSession.start(
        "s1", str(tmp_path), str(script), socket=socket_name, state_dir=state_dir
    )
    try:
        assert "spaced-path-marker" in _read_until(session, "spaced-path-marker")
        assert not marker.exists()
    finally:
        session.close()


@pytest.mark.parametrize("session_id", ["abc\n", "abc\n\n", "", "a b", "a" * 65])
def test_session_ids_with_trailing_newline_or_bad_shape_are_rejected(tmp_path, socket_name, state_dir, session_id):
    with pytest.raises(ValueError):
        ManagedTmuxSession(session_id, tmux="/usr/bin/tmux", socket=socket_name, state_dir=state_dir, capture_cap_bytes=1024)


def _restart_with_status(tmp_path, socket_name, state_dir, status, append_error=None):
    """Start a tmux session, stop the worker, and run a fresh daemon that sees `status`."""
    client = _TmuxClient()
    first = _daemon(client, tmp_path, socket_name, state_dir)
    first.start()
    first.run_once()
    first.close()

    client.status = status
    client.appended.clear()
    if append_error is not None:
        original = client.append_session_event

        def failing(relay_id, session_id, kind, data):
            client.appended.append((kind, data))
            if kind == "session_adopted":
                raise append_error
            return original(relay_id, session_id, kind, data)

        client.append_session_event = failing
    second = _daemon(client, tmp_path, socket_name, state_dir)
    second.start()
    return client, second


def _adopted_events(client):
    return [entry for entry in client.appended if entry[0] == "session_adopted"]


def test_adopting_a_detached_session_reports_session_adopted_once(tmp_path, socket_name, state_dir):
    client, daemon = _restart_with_status(tmp_path, socket_name, state_dir, "detached")
    try:
        daemon.run_once()
        daemon.run_once()
        assert _adopted_events(client) == [("session_adopted", {})]
        assert not [kind for kind, _ in client.appended if kind == "session_failed"]
    finally:
        daemon.close()
        ManagedTmuxSession.attach("s1", socket=socket_name, state_dir=state_dir).close()


@pytest.mark.parametrize("status", ["ready", "controlled"])
def test_adopting_a_ready_or_controlled_session_stays_silent(tmp_path, socket_name, state_dir, status):
    client, daemon = _restart_with_status(tmp_path, socket_name, state_dir, status)
    try:
        daemon.run_once()
        assert _adopted_events(client) == []
    finally:
        daemon.close()
        ManagedTmuxSession.attach("s1", socket=socket_name, state_dir=state_dir).close()


def test_adoption_tolerates_a_409_from_the_backend(tmp_path, socket_name, state_dir):
    from agent_relay.exceptions import AgentRelayError

    client, daemon = _restart_with_status(
        tmp_path, socket_name, state_dir, "detached", append_error=AgentRelayError("conflict", status_code=409)
    )
    try:
        daemon.run_once()
        daemon.run_once()
        assert len(_adopted_events(client)) == 1
        assert "s1" in daemon._sessions
    finally:
        daemon.close()
        ManagedTmuxSession.attach("s1", socket=socket_name, state_dir=state_dir).close()


def test_other_adoption_errors_are_not_swallowed(tmp_path, socket_name, state_dir):
    from agent_relay.exceptions import AgentRelayError

    client, daemon = _restart_with_status(
        tmp_path, socket_name, state_dir, "detached", append_error=AgentRelayError("boom", status_code=500)
    )
    try:
        with pytest.raises(AgentRelayError):
            daemon.run_once()
    finally:
        daemon.close()
        ManagedTmuxSession.attach("s1", socket=socket_name, state_dir=state_dir).close()
