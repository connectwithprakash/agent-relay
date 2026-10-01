"""Managed local PTY sessions for worker-owned harness profiles."""
from __future__ import annotations

import fcntl
import os
import re
import select
import struct
import subprocess
import sys
import termios
import time
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import httpx
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as connect_websocket

from .exceptions import AgentRelayError
from .worker_common import _resolve_claude_launch, _validate_window_size
from .worker_tmux import DEFAULT_TMUX_SOCKET, TMUX_PROFILE, ManagedTmuxSession


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

_EXIT_DRAIN_SECONDS = 0.2
_ADOPTION_RETRY_START_SECONDS = 1.0
_ADOPTION_RETRY_MAX_SECONDS = 30.0
_RECONNECT_START_SECONDS = 1.0
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


@dataclass
class _PendingAdoption:
    """Retry state for one session_adopted report that the backend has not accepted."""

    next_attempt: float = 0.0
    delay: float = _ADOPTION_RETRY_START_SECONDS
    last_error: str | None = None


class WorkerDaemon:
    """Bridge authenticated control events to worker-owned managed PTYs."""

    def __init__(self, client, relay_id: str, name: str, profiles: list[str], profile_workdirs: dict[str, str] | None = None, profile_executables: dict[str, str] | None = None, state_dir: Path | str | None = None, tmux_path: str | None = None, tmux_socket: str = DEFAULT_TMUX_SOCKET, clock=time.monotonic):
        self.client = client
        self.relay_id = relay_id
        self.name = name
        self.profiles = profiles
        self.profile_workdirs = profile_workdirs or {}
        self.profile_executables = profile_executables or {}
        self.state_dir = state_dir
        self.tmux_path = tmux_path
        self.tmux_socket = tmux_socket
        self.clock = clock
        self.worker_id: str | None = None
        self._sessions: dict[str, ManagedPtySession | ManagedTmuxSession] = {}
        self._cursors: dict[str, int] = {}
        self._approval_detectors: dict[str, ApprovalDetector] = {}
        self._adoption_pending: dict[str, _PendingAdoption] = {}
        self._session_errors: dict[str, str] = {}
        self._ready_pending: set[str] = set()
        self._unsent_output: dict[str, str] = {}
        self._unsent_prompts: dict[str, list[str]] = {}

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
                self._adoption_pending[session_id] = _PendingAdoption()
        return adopted

    def _report_pending_adoption(self, session_id: str) -> None:
        """Tell the backend a detached session is back, retrying with backoff until accepted.

        A 409 means the session already moved on, so the report is dropped. Any other
        failure, including a transport error, is logged when it first appears or changes, and retried after a delay that
        doubles from one to thirty seconds so a permanent failure stays quiet and cheap.
        """
        pending = self._adoption_pending.get(session_id)
        if pending is None or self.clock() < pending.next_attempt:
            return
        try:
            self.client.append_session_event(self.relay_id, session_id, "session_adopted", {})
        except (AgentRelayError, httpx.HTTPError) as error:
            if getattr(error, "status_code", None) != 409:
                description = f"{type(error).__name__}: {error}" if isinstance(error, httpx.HTTPError) else str(error)
                if description != pending.last_error:
                    print(f"Could not report adoption of {session_id}, will retry: {description}", file=sys.stderr)
                    pending.last_error = description
                pending.next_attempt = self.clock() + pending.delay
                pending.delay = min(pending.delay * 2, _ADOPTION_RETRY_MAX_SECONDS)
                return
        del self._adoption_pending[session_id]

    def _relay_output(self, session_id: str, output: str) -> None:
        """Append terminal output as an event and report any permission prompts it completes.

        Output or prompts the backend did not accept are kept and sent first on the next call.
        """
        prompts = self._unsent_prompts.pop(session_id, [])
        output = self._unsent_output.pop(session_id, "") + output
        if output:
            try:
                self.client.append_session_event(self.relay_id, session_id, "output", {"text": output})
            except (AgentRelayError, httpx.HTTPError):
                self._unsent_output[session_id] = output
                self._unsent_prompts[session_id] = prompts
                raise
            detector = self._approval_detectors.setdefault(session_id, ApprovalDetector())
            prompts = prompts + detector.feed(output)
        for index, prompt in enumerate(prompts):
            try:
                self.client.append_session_event(
                    self.relay_id, session_id, "approval_requested", {"prompt": prompt}
                )
            except (AgentRelayError, httpx.HTTPError):
                self._unsent_prompts[session_id] = prompts[index:]
                raise

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
            try:
                self._process_session(session)
            except (AgentRelayError, httpx.HTTPError) as error:
                self._log_session_error(session_id, error)
            else:
                self._session_errors.pop(session_id, None)

    def _log_session_error(self, session_id: str, error: Exception) -> None:
        """Log a session's backend failure once per distinct error; the pass moves on."""
        description = f"{type(error).__name__}: {error}" if isinstance(error, httpx.HTTPError) else str(error)
        if self._session_errors.get(session_id) != description:
            print(f"Session {session_id} failed this pass, will retry: {description}", file=sys.stderr)
            self._session_errors[session_id] = description

    def _process_session(self, session: dict) -> None:
        """Start, adopt, or relay terminal I/O for one session."""
        session_id = session["session_id"]
        if session["status"] in {"detached", "ready", "controlled"} and session_id not in self._sessions:
            if self._reattach(session) is None:
                self.client.append_session_event(
                    self.relay_id,
                    session_id,
                    "session_failed",
                    {"reason": "worker_restarted"},
                )
                return
        if session["status"] == "starting" and session_id not in self._sessions:
            self._sessions[session_id] = self._start_session(session)
            self._ready_pending.add(session_id)
        if session_id in self._ready_pending:
            self.client.mark_session_ready(self.relay_id, session_id)
            self._ready_pending.discard(session_id)

        pty_session = self._sessions.get(session_id)
        if not pty_session:
            return
        self._report_pending_adoption(session_id)
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
            self._adoption_pending.pop(session_id, None)
            self._ready_pending.discard(session_id)
            return
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
        self._adoption_pending.clear()
        self._session_errors.clear()
        self._ready_pending.clear()
        self._unsent_output.clear()
        self._unsent_prompts.clear()

    def run_stream_with_reconnect(self, session_id: str, *, max_attempts: int = 5, sleep=time.sleep, **stream_options) -> None:
        """Run the live stream, reconnecting with doubling backoff up to max_attempts connections."""
        delay = _RECONNECT_START_SECONDS
        for attempt in range(1, max_attempts + 1):
            try:
                return self.stream_owned_session(session_id, **stream_options)
            except (ConnectionClosed, OSError) as error:
                session = self._sessions.get(session_id)
                if attempt == max_attempts or session is None or session.closed:
                    raise
                print(f"Stream for {session_id} dropped ({type(error).__name__}), reconnecting in {delay:g}s", file=sys.stderr)
                sleep(delay)
                delay = min(delay * 2, _ADOPTION_RETRY_MAX_SECONDS)

    def stream_owned_session(self, session_id: str, *, max_frames: int | None = None, connection_factory=connect_websocket) -> None:
        """Bridge one owned PTY over the authenticated per-session live stream.

        A dropped or refused connection raises (for example ConnectionClosedError) by
        design; this method never reconnects. worker-run uses the polling path, and a
        caller that wants a live stream owns reconnects, see run_stream_with_reconnect.
        """
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
