"""Managed local PTY sessions for worker-owned harness profiles."""
from __future__ import annotations

import codecs
import fcntl
import os
import re
import select
import shlex
import shutil
import struct
import subprocess
import sys
import termios
import time
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from websockets.sync.client import connect as connect_websocket

from .exceptions import AgentRelayError


_FIXTURE_PROGRAM = """import os, sys
print('fixture ready', flush=True)
for line in sys.stdin:
    text = line.rstrip('\\r\\n')
    if text == 'size':
        columns, rows = os.get_terminal_size(sys.stdout.fileno())
        print(f'size:{columns}x{rows}', flush=True)
    elif text == 'approval':
        print('Do you want to proceed?\\n  > 1. Yes\\n    2. No', flush=True)
    else:
        print('echo:' + text, flush=True)
"""

MIN_COLS, MAX_COLS = 20, 500
MIN_ROWS, MAX_ROWS = 5, 200
TMUX_PROFILE = "claude-code-tmux"
DEFAULT_TMUX_SOCKET = "agent-relay"
DEFAULT_CAPTURE_CAP_BYTES = 8 * 1024 * 1024
_SESSION_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
_SEND_KEYS_CHUNK_BYTES = 256
_READ_CHUNK_BYTES = 65536
_MAX_READ_BYTES = 1024 * 1024
_ROTATION_GRACE_SECONDS = 0.3
_EXIT_DRAIN_SECONDS = 0.2
MAX_APPROVAL_PROMPT_BYTES = 4096
_APPROVAL_BUFFER_CHARS = 8192

_CURSOR_COLUMN_PATTERN = re.compile(r"\x1b\[\d*[GC]")
_ANSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_APPROVAL_PATTERN = re.compile(
    r"Do\s+you\s+want\s+to\s[^\n?]*\?"
    r"[^\n]*\n(?:[^\n]*\n){0,8}?"
    r"[^\n]*\b1\.\s*Yes"
    r"[\s\S]{0,400}?\b\d\.\s*No[^\n]*\n"
)


def _clean_terminal_text(text: str) -> str:
    """Drop ANSI escapes and carriage returns so patterns match plain lines.

    Claude Code positions words with cursor-column moves instead of spaces, so those
    moves become a single space before the remaining escapes are removed.
    """
    return _ANSI_PATTERN.sub("", _CURSOR_COLUMN_PATTERN.sub(" ", text)).replace("\r\n", "\n").replace("\r", "")


def extract_approval_prompt(text: str) -> tuple[str, int] | None:
    """Find the first Claude Code permission prompt in text.

    Returns the prompt text (capped at the contract size) and the end offset of the
    match within the ANSI-stripped text, or None when no prompt is present.
    """
    cleaned = _clean_terminal_text(text)
    match = _APPROVAL_PATTERN.search(cleaned)
    if not match:
        return None
    prompt = match.group(0).strip().encode()[:MAX_APPROVAL_PROMPT_BYTES].decode(errors="ignore")
    return prompt, match.end()


class ApprovalDetector:
    """Report each permission prompt once, even when it arrives split across reads."""

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, chunk: str) -> list[str]:
        """Add terminal output and return prompts completed by it."""
        self._buffer += _clean_terminal_text(chunk)
        prompts: list[str] = []
        while (found := extract_approval_prompt(self._buffer)) is not None:
            prompt, end = found
            prompts.append(prompt)
            self._buffer = self._buffer[end:]
        self._buffer = self._buffer[-_APPROVAL_BUFFER_CHARS:]
        return prompts


def _validate_window_size(cols: object, rows: object) -> tuple[int, int]:
    """Enforce the control-stream resize bounds (integers only, booleans rejected)."""
    for value, low, high in ((cols, MIN_COLS, MAX_COLS), (rows, MIN_ROWS, MAX_ROWS)):
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"Terminal size must be integers within {low}..{high}")
    return cols, rows  # type: ignore[return-value]


def _resolve_claude_launch(workdir: str | None, executable: str | None) -> str:
    """Return the Claude Code executable after the shared fail-closed local checks."""
    claude = executable or shutil.which("claude")
    if not claude or not Path(claude).is_absolute() or not os.access(claude, os.X_OK):
        raise RuntimeError("Claude Code executable 'claude' is not installed")
    if not workdir or not Path(workdir).is_absolute() or not Path(workdir).is_dir():
        raise ValueError("Claude Code requires an existing absolute local workdir")
    return claude


@dataclass
class ManagedPtySession:
    """A terminal process started from an explicit local profile allowlist."""

    process: subprocess.Popen[bytes]
    master_fd: int
    profile: str
    slave_fd: int = -1

    @classmethod
    def start(cls, profile: str, workdir: str | None = None, executable: str | None = None) -> "ManagedPtySession":
        """Start one locally allowlisted session profile in a new PTY."""
        if profile == "fixture-shell":
            command = [sys.executable, "-u", "-c", _FIXTURE_PROGRAM]
        elif profile == "claude-code":
            command = [_resolve_claude_launch(workdir, executable)]
        else:
            raise ValueError(f"Session profile {profile!r} is not allowed")

        master_fd, slave_fd = os.openpty()

        def attach_controlling_terminal() -> None:
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

        try:
            process = subprocess.Popen(
                command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                cwd=workdir,
                preexec_fn=attach_controlling_terminal,
            )
        except BaseException:
            os.close(slave_fd)
            os.close(master_fd)
            raise
        # The slave end stays open here: on macOS the kernel discards unread output when
        # the last slave descriptor closes, so an exiting child would lose its final lines.
        return cls(process=process, master_fd=master_fd, profile=profile, slave_fd=slave_fd)

    def write(self, data: str) -> None:
        """Write terminal input only while this worker-owned process is running."""
        if self.process.poll() is not None:
            raise RuntimeError("Managed PTY session is not running")
        os.write(self.master_fd, data.encode())

    def resize(self, cols: int, rows: int) -> None:
        """Apply a controller window size to the PTY within the control-stream bounds."""
        _validate_window_size(cols, rows)
        if self.process.poll() is not None:
            raise RuntimeError("Managed PTY session is not running")
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    @property
    def closed(self) -> bool:
        """True once close() has released the PTY."""
        return self.master_fd < 0

    def read(self, timeout: float = 0.0) -> str:
        """Read currently available terminal output, waiting at most timeout seconds."""
        deadline = time.monotonic() + timeout
        chunks: list[bytes] = []
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                readable, _, _ = select.select([self.master_fd], [], [], remaining)
                if not readable:
                    break
                chunk = os.read(self.master_fd, 65536)
            except (ValueError, OSError):
                break  # closed underneath a concurrent reader
            if not chunk:
                break
            chunks.append(chunk)
            deadline = time.monotonic() + 0.02
        return b"".join(chunks).decode(errors="replace")

    def poll(self) -> int | None:
        """Return the exit code once the process has ended, else None."""
        return self.process.poll()

    def detach(self) -> None:
        """A PTY cannot outlive its worker, so detaching stops the process."""
        self.close()

    def close(self) -> None:
        """Stop the owned process and release its PTY descriptor."""
        if self.master_fd >= 0:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = -1
        if self.slave_fd >= 0:
            try:
                os.close(self.slave_fd)
            except OSError:
                pass
            self.slave_fd = -1
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)


def default_state_dir() -> Path:
    """Private per-user directory for tmux capture, offset and cursor files."""
    return Path.home() / ".agent-relay" / "worker"


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _write_private(path: Path, text: str, *, append: bool = False) -> None:
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if append else os.O_TRUNC)
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, text.encode())
    finally:
        os.close(fd)


def _replace_atomically(path: Path, text: str) -> None:
    """Write via a private temp file in the same directory, then rename over the target."""
    temp = path.with_name(path.name + ".tmp")
    _write_private(temp, text)
    os.replace(temp, path)


class ManagedTmuxSession:
    """A tmux-hosted Claude Code session that a restarted worker can re-attach to.

    Output is captured with pipe-pane into private generation files under the state
    directory; the worker reads them by persisted byte offset so a restart neither
    drops nor repeats bytes. Each capture file is rotated once the read offset passes
    the size cap, and a finished generation is deleted after it is fully drained.
    """

    profile = TMUX_PROFILE

    def __init__(self, session_id: str, *, tmux: str, socket: str, state_dir: Path, capture_cap_bytes: int):
        if not _SESSION_ID_PATTERN.fullmatch(session_id):
            raise ValueError("Session ID is not safe to use as a tmux session name")
        self.name = f"arelay-{session_id}"
        self._target = f"={self.name}:"
        self._tmux = tmux
        self._socket = socket
        self._state_dir = state_dir
        self._cap = capture_cap_bytes
        self._gen = 0
        self._offset = 0
        self._write_gen = 0
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._ended = False

    @staticmethod
    def _resolve_tmux(tmux_path: str | None) -> str:
        tmux = tmux_path or shutil.which("tmux")
        if not tmux or not Path(tmux).is_absolute() or not os.access(tmux, os.X_OK):
            raise RuntimeError("tmux executable is not installed")
        return tmux

    @classmethod
    def start(
        cls,
        session_id: str,
        workdir: str | None,
        executable: str | None,
        *,
        tmux_path: str | None = None,
        socket: str = DEFAULT_TMUX_SOCKET,
        state_dir: Path | str | None = None,
        capture_cap_bytes: int = DEFAULT_CAPTURE_CAP_BYTES,
    ) -> "ManagedTmuxSession":
        """Create a detached tmux session running the allowlisted Claude Code executable."""
        claude = _resolve_claude_launch(workdir, executable)
        directory = Path(state_dir) if state_dir else default_state_dir()
        session = cls(session_id, tmux=cls._resolve_tmux(tmux_path), socket=socket, state_dir=directory, capture_cap_bytes=capture_cap_bytes)
        _ensure_private_dir(directory)
        if session._exists():
            raise RuntimeError(f"tmux session {session.name} already exists")
        try:
            # tmux runs a single command argument through /bin/sh, so the path is quoted.
            # An idle placeholder holds the pane open while capture is attached, so the
            # real command's first bytes are never written before pipe-pane is listening.
            session._run("new-session", "-d", "-s", session.name, "-x", "120", "-y", "40", "-c", str(workdir), "cat")
            session._run("set-option", "-g", "window-size", "manual")
            session._run("set-option", "-g", "remain-on-exit", "on")
            session._run("set-option", "-g", "default-terminal", "screen-256color")
            session._start_pipe(0)
            session._save_offset()
            session._run("respawn-pane", "-k", "-t", session._target, "-c", str(workdir), "--", shlex.quote(claude))
        except RuntimeError:
            session.close()
            raise
        return session

    @classmethod
    def attach(
        cls,
        session_id: str,
        *,
        tmux_path: str | None = None,
        socket: str = DEFAULT_TMUX_SOCKET,
        state_dir: Path | str | None = None,
        capture_cap_bytes: int = DEFAULT_CAPTURE_CAP_BYTES,
    ) -> "ManagedTmuxSession | None":
        """Adopt a still-running tmux session after a worker restart, or return None."""
        directory = Path(state_dir) if state_dir else default_state_dir()
        session = cls(session_id, tmux=cls._resolve_tmux(tmux_path), socket=socket, state_dir=directory, capture_cap_bytes=capture_cap_bytes)
        if not session._exists():
            return None
        _ensure_private_dir(directory)
        try:
            saved = json.loads(session._path("offset").read_text())
            session._gen, session._offset = int(saved["gen"]), int(saved["offset"])
        except (OSError, ValueError, KeyError, TypeError):
            session._gen, session._offset = 0, 0
        generations = session._capture_generations()
        session._write_gen = max(generations) if generations else session._gen
        if session._run("display-message", "-p", "-t", session._target, "#{pane_pipe}", check=False).stdout.strip() != "1":
            session._start_pipe(session._write_gen)
        return session

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        env = {key: value for key, value in os.environ.items() if key != "TMUX"}
        result = subprocess.run(
            [self._tmux, "-f", "/dev/null", "-L", self._socket, *args],
            capture_output=True, text=True, env=env,
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"tmux {args[0]} failed: {result.stderr.strip()}")
        return result

    def _exists(self) -> bool:
        return self._run("has-session", "-t", f"={self.name}", check=False).returncode == 0

    def _path(self, suffix: str) -> Path:
        return self._state_dir / f"{self.name}.{suffix}"

    def _capture_path(self, generation: int) -> Path:
        return self._path(f"{generation}.out")

    def _capture_generations(self) -> list[int]:
        found = []
        for path in self._state_dir.glob(f"{self.name}.*.out"):
            middle = path.name[len(self.name) + 1:-len(".out")]
            if middle.isdigit():
                found.append(int(middle))
        return sorted(found)

    def _start_pipe(self, generation: int) -> None:
        path = self._capture_path(generation)
        _write_private(path, "", append=True)
        self._write_gen = generation
        self._run("pipe-pane", "-O", "-t", self._target, f"cat >> {shlex.quote(str(path))}")

    def _save_offset(self) -> None:
        _replace_atomically(self._path("offset"), json.dumps({"gen": self._gen, "offset": self._offset}))

    def display(self, template: str) -> str:
        """Expand a tmux format string against this session's pane."""
        return self._run("display-message", "-p", "-t", self._target, template).stdout.strip()

    @property
    def closed(self) -> bool:
        """True once the session was closed or detached by this worker."""
        return self._ended

    def poll(self) -> int | None:
        """Return the command's exit code once it has ended, else None."""
        if self._ended:
            return -1
        if not self._exists():
            return -1
        dead, status, signal_number = self.display("#{pane_dead}|#{pane_dead_status}|#{pane_dead_signal}").split("|")
        if dead != "1":
            return None
        if signal_number:
            return -int(signal_number)
        return int(status) if status else 0

    def write(self, data: str) -> None:
        """Send terminal input as exact bytes while the command is still running."""
        if self.poll() is not None:
            raise RuntimeError("Managed tmux session is not running")
        raw = data.encode()
        for start in range(0, len(raw), _SEND_KEYS_CHUNK_BYTES):
            chunk = raw[start:start + _SEND_KEYS_CHUNK_BYTES]
            self._run("send-keys", "-t", self._target, "-H", *[f"{byte:02x}" for byte in chunk])

    def resize(self, cols: int, rows: int) -> None:
        """Apply a controller window size to the tmux window within the contract bounds."""
        _validate_window_size(cols, rows)
        if self.poll() is not None:
            raise RuntimeError("Managed tmux session is not running")
        self._run("resize-window", "-t", self._target, "-x", str(cols), "-y", str(rows))

    def _age(self, path: Path) -> float:
        try:
            return time.time() - path.stat().st_mtime
        except FileNotFoundError:
            return float("inf")

    def _drain_once(self) -> bytes:
        path = self._capture_path(self._gen)
        try:
            with open(path, "rb") as handle:
                handle.seek(self._offset)
                data = handle.read(_READ_CHUNK_BYTES)
        except FileNotFoundError:
            data = b""
        if data:
            self._offset += len(data)
            return data
        if self._gen < self._write_gen:
            # Old generation: drop it only once its pipe has had time to finish flushing.
            if self._age(path) > _ROTATION_GRACE_SECONDS:
                path.unlink(missing_ok=True)
                self._gen += 1
                self._offset = 0
                self._save_offset()
            return b""
        if self._offset >= self._cap:
            self._start_pipe(self._write_gen + 1)
        return b""

    def read(self, timeout: float = 0.0) -> str:
        """Return captured output not yet delivered, waiting at most timeout seconds."""
        deadline = time.monotonic() + timeout
        chunks: list[bytes] = []
        total = 0
        while total < _MAX_READ_BYTES:
            data = self._drain_once()
            if data:
                chunks.append(data)
                total += len(data)
                deadline = time.monotonic() + 0.02
            elif time.monotonic() >= deadline:
                break
            else:
                time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
        if chunks:
            # Delivery is at-most-once: the offset is saved before the caller appends the
            # output event, so a crash in that window drops these bytes rather than repeating them.
            self._save_offset()
        return self._decoder.decode(b"".join(chunks))

    def save_cursor(self, sequence: int) -> None:
        """Persist the last control event sequence this worker has applied."""
        _replace_atomically(self._path("cursor"), str(int(sequence)))

    def load_cursor(self) -> int:
        """Return the persisted event cursor, or 0 when none was saved."""
        try:
            return int(self._path("cursor").read_text().strip())
        except (OSError, ValueError):
            return 0

    def detach(self) -> None:
        """Leave tmux running for a later re-attach; keep the state files."""
        if not self._ended:
            self._save_offset()
        self._ended = True

    def close(self) -> None:
        """End the tmux session and remove every state file belonging to it."""
        self._ended = True
        self._run("kill-session", "-t", f"={self.name}", check=False)
        for path in self._state_dir.glob(f"{self.name}.*"):
            path.unlink(missing_ok=True)


class WorkerDaemon:
    """Bridge authenticated control events to worker-owned managed PTYs."""

    def __init__(self, client, relay_id: str, name: str, profiles: list[str], profile_workdirs: dict[str, str] | None = None, profile_executables: dict[str, str] | None = None, state_dir: Path | str | None = None, tmux_path: str | None = None, tmux_socket: str = DEFAULT_TMUX_SOCKET):
        self.client = client
        self.relay_id = relay_id
        self.name = name
        self.profiles = profiles
        self.profile_workdirs = profile_workdirs or {}
        self.profile_executables = profile_executables or {}
        self.state_dir = state_dir
        self.tmux_path = tmux_path
        self.tmux_socket = tmux_socket
        self.worker_id: str | None = None
        self._sessions: dict[str, ManagedPtySession | ManagedTmuxSession] = {}
        self._cursors: dict[str, int] = {}
        self._approval_detectors: dict[str, ApprovalDetector] = {}

    def _tmux_options(self) -> dict:
        return {"tmux_path": self.tmux_path, "socket": self.tmux_socket, "state_dir": self.state_dir}

    def _start_session(self, session: dict) -> ManagedPtySession | ManagedTmuxSession:
        profile = session["profile"]
        workdir = self.profile_workdirs.get(profile)
        executable = self.profile_executables.get(profile)
        if profile == TMUX_PROFILE:
            return ManagedTmuxSession.start(session["session_id"], workdir, executable, **self._tmux_options())
        return ManagedPtySession.start(profile, workdir, executable)

    def _reattach(self, session: dict) -> ManagedTmuxSession | None:
        """Adopt a tmux session that outlived a worker restart, without emitting events."""
        if session["profile"] != TMUX_PROFILE:
            return None
        session_id = session["session_id"]
        try:
            adopted = ManagedTmuxSession.attach(session_id, **self._tmux_options())
        except RuntimeError as error:
            print(f"Cannot re-attach session {session_id}: {error}", file=sys.stderr)
            return None
        if adopted is not None:
            self._sessions[session_id] = adopted
            self._cursors[session_id] = adopted.load_cursor()
            if session["status"] == "detached":
                self._report_adoption(session_id)
        return adopted

    def _report_adoption(self, session_id: str) -> None:
        """Tell the backend a detached session is back; a 409 means it already moved on."""
        try:
            self.client.append_session_event(self.relay_id, session_id, "session_adopted", {})
        except AgentRelayError as error:
            if error.status_code != 409:
                raise

    def _relay_output(self, session_id: str, output: str) -> None:
        """Append terminal output as an event and report any permission prompts it completes."""
        if not output:
            return
        self.client.append_session_event(self.relay_id, session_id, "output", {"text": output})
        detector = self._approval_detectors.setdefault(session_id, ApprovalDetector())
        for prompt in detector.feed(output):
            self.client.append_session_event(
                self.relay_id, session_id, "approval_requested", {"prompt": prompt}
            )

    def _record_cursor(self, session_id: str, pty_session, sequence: int) -> None:
        """Advance the event cursor, persisting it first so a crash cannot replay input."""
        if sequence <= self._cursors.get(session_id, 0):
            return
        self._cursors[session_id] = sequence
        if isinstance(pty_session, ManagedTmuxSession):
            pty_session.save_cursor(sequence)

    def _apply_resize(self, pty_session: ManagedPtySession, data: dict) -> None:
        """Apply a resize event as best effort; a bad size or dead session is logged and skipped."""
        try:
            pty_session.resize(data.get("cols"), data.get("rows"))
        except (ValueError, RuntimeError, OSError) as error:
            print(f"Ignoring invalid resize request: {error}", file=sys.stderr)

    def start(self) -> str:
        """Register this daemon under its existing authenticated participant."""
        worker = self.client.register_worker(self.relay_id, self.name, self.profiles)
        worker_id = worker.get("worker_id")
        if not isinstance(worker_id, str):
            raise RuntimeError("Worker registration returned no worker ID")
        self.worker_id = worker_id
        return self.worker_id

    def run_once(self) -> None:
        """Claim requested profiles locally and relay authorized terminal I/O once."""
        if not self.worker_id:
            raise RuntimeError("Worker daemon has not been started")
        heartbeat = getattr(self.client, "heartbeat_worker", None)
        if heartbeat:
            heartbeat(self.relay_id, self.worker_id)
        for session in self.client.list_worker_sessions(self.relay_id, self.worker_id):
            session_id = session["session_id"]
            if session["status"] in {"detached", "ready", "controlled"} and session_id not in self._sessions:
                if self._reattach(session) is None:
                    self.client.append_session_event(
                        self.relay_id,
                        session_id,
                        "session_failed",
                        {"reason": "worker_restarted"},
                    )
                    continue
            if session["status"] == "starting" and session_id not in self._sessions:
                self._sessions[session_id] = self._start_session(session)
                self.client.mark_session_ready(self.relay_id, session_id)

            pty_session = self._sessions.get(session_id)
            if not pty_session:
                continue
            exit_code = pty_session.poll()
            if exit_code is not None:
                self._relay_output(session_id, pty_session.read(timeout=_EXIT_DRAIN_SECONDS))
                self.client.append_session_event(
                    self.relay_id,
                    session_id,
                    "session_exited",
                    {"exit_code": exit_code},
                )
                pty_session.close()
                del self._sessions[session_id]
                self._approval_detectors.pop(session_id, None)
                continue
            events = self.client.get_session_events(
                self.relay_id, session_id, self._cursors.get(session_id, 0)
            )
            for event in events:
                self._record_cursor(session_id, pty_session, event["sequence"])
                if event["kind"] == "input_requested":
                    pty_session.write(event["data"]["input"])
                elif event["kind"] == "resize_requested":
                    self._apply_resize(pty_session, event["data"])

            self._relay_output(session_id, pty_session.read(timeout=0.05 if events else 0.0))

    def close(self) -> None:
        """Stop owned PTYs; tmux sessions are detached and left running for re-attach."""
        for session in self._sessions.values():
            session.detach()
        self._sessions.clear()
        self._approval_detectors.clear()

    def stream_owned_session(self, session_id: str, *, max_frames: int | None = None, connection_factory=connect_websocket) -> None:
        """Bridge one owned PTY over the authenticated per-session live stream."""
        if not self.worker_id or session_id not in self._sessions:
            raise RuntimeError("Worker does not own this managed session")
        token = getattr(self.client, "_token", None)
        if not token:
            raise RuntimeError("Worker client has no stream credential")
        parsed = urlparse(self.client.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        stream_url = urlunparse((scheme, parsed.netloc, f"/relays/{self.relay_id}/sessions/{session_id}/stream", "", "cursor=0", ""))
        processed = 0
        pty_session = self._sessions[session_id]
        try:
            with connection_factory(stream_url, subprotocols=[f"token-{token}"]) as websocket:
                while (max_frames is None or processed < max_frames) and not pty_session.closed:
                    try:
                        raw = websocket.recv(timeout=0.05)
                    except TimeoutError:
                        raw = None
                    if raw:
                        frame = json.loads(raw)
                        event = frame.get("event", {}) if frame.get("type") == "event" else {}
                        sequence = event.get("sequence")
                        if isinstance(sequence, int) and not isinstance(sequence, bool):
                            already_applied = sequence <= self._cursors.get(session_id, 0)
                            self._record_cursor(session_id, pty_session, sequence)
                        else:
                            already_applied = False
                        if event.get("kind") == "input_requested":
                            if not already_applied:
                                pty_session.write(event["data"]["input"])
                        elif event.get("kind") == "resize_requested":
                            self._apply_resize(pty_session, event["data"])
                        processed += 1
                    output = pty_session.read(timeout=0.05 if raw else 0.0)
                    if output:
                        websocket.send(json.dumps({"type": "output", "text": output}))
                        detector = self._approval_detectors.setdefault(session_id, ApprovalDetector())
                        for prompt in detector.feed(output):
                            websocket.send(json.dumps({"type": "approval", "prompt": prompt}))
        finally:
            self._approval_detectors.pop(session_id, None)
