"""Managed local PTY sessions for worker-owned harness profiles."""
from __future__ import annotations

import fcntl
import os
import select
import shutil
import subprocess
import sys
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

            output = pty_session.read(timeout=0.05 if events else 0.0)
            if output:
                self.client.append_session_event(
                    self.relay_id, session_id, "output", {"text": output}
                )

    def close(self) -> None:
        """Stop only the PTYs this daemon created and owns."""
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()

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
                    if frame.get("type") == "event" and frame.get("event", {}).get("kind") == "input_requested":
                        pty_session.write(frame["event"]["data"]["input"])
                    processed += 1
                output = pty_session.read(timeout=0.05 if raw else 0.0)
                if output:
                    websocket.send(json.dumps({"type": "output", "text": output}))
