"""Managed local PTY sessions for worker-owned harness profiles."""
from __future__ import annotations

import fcntl
import os
import re
import select
import shutil
import subprocess
import sys
import struct
import termios
import time
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from websockets.sync.client import connect as connect_websocket


_FIXTURE_PROGRAM = """import sys
print('fixture ready', flush=True)
for line in sys.stdin:
    print('echo:' + line.rstrip('\\r\\n'), flush=True)
"""

MIN_COLS, MAX_COLS = 20, 500
MIN_ROWS, MAX_ROWS = 5, 200
MAX_APPROVAL_PROMPT_BYTES = 4096
_APPROVAL_BUFFER_CHARS = 8192

_ANSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_APPROVAL_PATTERN = re.compile(
    r"Do you want to [^\n?]*\?"
    r"[^\n]*\n(?:[^\n]*\n){0,8}?"
    r"[^\n]*\b1\.\s*Yes"
    r"[\s\S]{0,400}?\b\d\.\s*No[^\n]*"
)


def _clean_terminal_text(text: str) -> str:
    """Drop ANSI escape sequences and carriage returns so patterns match plain lines."""
    return _ANSI_PATTERN.sub("", text).replace("\r\n", "\n").replace("\r", "")


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

    @classmethod
    def start(cls, profile: str, workdir: str | None = None, executable: str | None = None) -> "ManagedPtySession":
        """Start one locally allowlisted session profile in a new PTY."""
        if profile == "fixture-shell":
            command = [sys.executable, "-u", "-c", _FIXTURE_PROGRAM]
        elif profile == "claude-code":
            claude = executable or shutil.which("claude")
            if not claude or not Path(claude).is_absolute() or not os.access(claude, os.X_OK):
                raise RuntimeError("Claude Code executable 'claude' is not installed")
            if not workdir or not Path(workdir).is_absolute() or not Path(workdir).is_dir():
                raise ValueError("Claude Code requires an existing absolute local workdir")
            command = [claude]
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
        finally:
            os.close(slave_fd)
        return cls(process=process, master_fd=master_fd, profile=profile)

    def write(self, data: str) -> None:
        """Write terminal input only while this worker-owned process is running."""
        if self.process.poll() is not None:
            raise RuntimeError("Managed PTY session is not running")
        os.write(self.master_fd, data.encode())

    def resize(self, cols: int, rows: int) -> None:
        """Apply a controller window size to the PTY within the control-stream bounds."""
        for value, low, high in ((cols, MIN_COLS, MAX_COLS), (rows, MIN_ROWS, MAX_ROWS)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"Terminal size must be integers within {low}..{high}")
        if self.process.poll() is not None:
            raise RuntimeError("Managed PTY session is not running")
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def read(self, timeout: float = 0.0) -> str:
        """Read currently available terminal output, waiting at most timeout seconds."""
        deadline = time.monotonic() + timeout
        chunks: list[bytes] = []
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            readable, _, _ = select.select([self.master_fd], [], [], remaining)
            if not readable:
                break
            try:
                chunk = os.read(self.master_fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            chunks.append(chunk)
            deadline = time.monotonic() + 0.02
        return b"".join(chunks).decode(errors="replace")

    def close(self) -> None:
        """Stop the owned process and release its PTY descriptor."""
        if self.master_fd >= 0:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = -1
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)


class WorkerDaemon:
    """Bridge authenticated control events to worker-owned managed PTYs."""

    def __init__(self, client, relay_id: str, name: str, profiles: list[str], profile_workdirs: dict[str, str] | None = None, profile_executables: dict[str, str] | None = None):
        self.client = client
        self.relay_id = relay_id
        self.name = name
        self.profiles = profiles
        self.profile_workdirs = profile_workdirs or {}
        self.profile_executables = profile_executables or {}
        self.worker_id: str | None = None
        self._sessions: dict[str, ManagedPtySession] = {}
        self._cursors: dict[str, int] = {}
        self._approval_detectors: dict[str, ApprovalDetector] = {}

    def _apply_resize(self, pty_session: ManagedPtySession, data: dict) -> None:
        """Apply a resize event; a malformed size is reported locally and skipped."""
        try:
            pty_session.resize(data.get("cols"), data.get("rows"))
        except ValueError as error:
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
                self.client.append_session_event(
                    self.relay_id,
                    session_id,
                    "session_failed",
                    {"reason": "worker_restarted"},
                )
                continue
            if session["status"] == "starting" and session_id not in self._sessions:
                self._sessions[session_id] = ManagedPtySession.start(
                    session["profile"],
                    self.profile_workdirs.get(session["profile"]),
                    self.profile_executables.get(session["profile"]),
                )
                self.client.mark_session_ready(self.relay_id, session_id)

            pty_session = self._sessions.get(session_id)
            if not pty_session:
                continue
            if pty_session.process.poll() is not None:
                self.client.append_session_event(
                    self.relay_id,
                    session_id,
                    "session_exited",
                    {"exit_code": pty_session.process.returncode},
                )
                pty_session.close()
                del self._sessions[session_id]
                self._approval_detectors.pop(session_id, None)
                continue
            events = self.client.get_session_events(
                self.relay_id, session_id, self._cursors.get(session_id, 0)
            )
            for event in events:
                self._cursors[session_id] = max(
                    self._cursors.get(session_id, 0), event["sequence"]
                )
                if event["kind"] == "input_requested":
                    pty_session.write(event["data"]["input"])
                elif event["kind"] == "resize_requested":
                    self._apply_resize(pty_session, event["data"])

            output = pty_session.read(timeout=0.05 if events else 0.0)
            if output:
                self.client.append_session_event(
                    self.relay_id, session_id, "output", {"text": output}
                )
                detector = self._approval_detectors.setdefault(session_id, ApprovalDetector())
                for prompt in detector.feed(output):
                    self.client.append_session_event(
                        self.relay_id, session_id, "approval_requested", {"prompt": prompt}
                    )

    def close(self) -> None:
        """Stop only the PTYs this daemon created and owns."""
        for session in self._sessions.values():
            session.close()
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
        with connection_factory(stream_url, subprotocols=[f"token-{token}"]) as websocket:
            while max_frames is None or processed < max_frames:
                try:
                    raw = websocket.recv(timeout=0.05)
                except TimeoutError:
                    raw = None
                if raw:
                    frame = json.loads(raw)
                    event = frame.get("event", {}) if frame.get("type") == "event" else {}
                    if event.get("kind") == "input_requested":
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
