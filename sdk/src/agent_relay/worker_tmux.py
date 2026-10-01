"""tmux-backed Claude Code sessions that a restarted worker can re-attach to."""
from __future__ import annotations

import codecs
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from .worker_common import _resolve_claude_launch, _validate_window_size

TMUX_PROFILE = "claude-code-tmux"
DEFAULT_TMUX_SOCKET = "agent-relay"
DEFAULT_CAPTURE_CAP_BYTES = 8 * 1024 * 1024
_SESSION_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
_SEND_KEYS_CHUNK_BYTES = 256
_READ_CHUNK_BYTES = 65536
_MAX_READ_BYTES = 1024 * 1024
_ROTATION_GRACE_SECONDS = 0.3


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
