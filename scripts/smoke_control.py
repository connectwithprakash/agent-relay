#!/usr/bin/env python3
"""End-to-end smoke test of the control stream with a real backend and worker.

Starts a local backend (uvicorn on a free port, temporary SQLite), a worker with the
fixture-shell profile, and drives a controller over the real WebSocket: claim a lease,
send input, check output, resize and check the PTY size, then check an approval round
trip. Exits non-zero on the first failure.

Run it with an interpreter that has the backend and SDK dependencies installed:

    backend/.venv/bin/python scripts/smoke_control.py
"""
import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk" / "src"))

from websockets.sync.client import connect  # noqa: E402

from agent_relay.client import AgentRelayClient  # noqa: E402
from agent_relay.worker import WorkerDaemon  # noqa: E402

STEP_TIMEOUT_SECONDS = 15.0
STARTUP_TIMEOUT_SECONDS = 30.0


class SmokeFailure(Exception):
    """A smoke check did not hold."""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_backend(workdir: Path, port: int) -> subprocess.Popen:
    env = {
        "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
        "DATABASE_URL": f"sqlite:///{workdir / 'smoke.db'}",
        "ENVIRONMENT": "development",
        "LOG_FORMAT": "text",
    }
    log = open(workdir / "backend.log", "wb")
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT / "backend", env=env, stdout=log, stderr=subprocess.STDOUT,
    )


def wait_for_backend(base_url: str, backend: subprocess.Popen) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    with AgentRelayClient(base_url) as probe:
        while time.monotonic() < deadline:
            if backend.poll() is not None:
                raise SmokeFailure("backend exited during startup")
            try:
                probe.health()
                return
            except Exception:
                time.sleep(0.2)
    raise SmokeFailure("backend did not become healthy")


def pair_worker(controller: AgentRelayClient, base_url: str, relay_id: str) -> str:
    invitation = controller.create_invitation(relay_id, "worker")
    with AgentRelayClient(base_url) as anonymous:
        return anonymous.redeem_invitation(invitation["invitation"])["token"]


def wait_until(description: str, predicate, timeout: float = STEP_TIMEOUT_SECONDS):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise SmokeFailure(f"timed out waiting for {description}")


class ControllerStream:
    """A controller WebSocket that keeps every event frame it has seen."""

    def __init__(self, url: str, token: str):
        self._socket = connect(url, subprotocols=[f"token-{token}"])
        self.events: list[dict] = []
        self.errors: list[dict] = []
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        try:
            for raw in self._socket:
                frame = json.loads(raw)
                with self._lock:
                    if frame.get("type") == "event":
                        self.events.append(frame["event"])
                    elif frame.get("type") == "error":
                        self.errors.append(frame)
        except Exception:
            return

    def send(self, frame: dict) -> None:
        self._socket.send(json.dumps(frame))

    def output_text(self) -> str:
        with self._lock:
            return "".join(e["data"].get("text", "") for e in self.events if e["kind"] == "output")

    def of_kind(self, kind: str) -> list[dict]:
        with self._lock:
            return [e for e in self.events if e["kind"] == kind]

    def close(self) -> None:
        self._socket.close()


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="agent-relay-smoke-"))
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    ws_base = f"ws://127.0.0.1:{port}"
    backend = start_backend(workdir, port)
    daemon = None
    stream = None
    try:
        wait_for_backend(base_url, backend)
        print(f"backend ready on {base_url}")
        controller = AgentRelayClient(base_url)
        relay = controller.create_relay(["controller", "worker"])
        relay_id, controller_token = relay.relay_id, relay.token
        worker_token = pair_worker(controller, base_url, relay_id)

        worker_client = AgentRelayClient(base_url, token=worker_token)
        daemon = WorkerDaemon(worker_client, relay_id, "Smoke worker", ["fixture-shell"])
        worker_id = daemon.start()
        session = controller.start_session(relay_id, worker_id, "fixture-shell", "smoke-1")
        session_id = session["session_id"]

        def session_ready():
            daemon.run_once()
            current = next(s for s in controller.list_sessions(relay_id) if s["session_id"] == session_id)
            return current if current["status"] == "ready" else None

        ready = wait_until("session to become ready", session_ready)
        controller.claim_session(relay_id, session_id, ready["version"], 60)
        print("lease claimed")

        worker_thread = threading.Thread(
            target=daemon.stream_owned_session, args=(session_id,), daemon=True
        )
        worker_thread.start()

        stream = ControllerStream(f"{ws_base}/relays/{relay_id}/sessions/{session_id}/stream", controller_token)

        wait_until("fixture banner", lambda: "fixture ready" in stream.output_text())

        stream.send({"type": "input", "input": "hello smoke\n"})
        wait_until("echoed input", lambda: "echo:hello smoke" in stream.output_text())
        print("input and output round trip ok")

        stream.send({"type": "resize", "cols": 101, "rows": 31})
        wait_until("resize event", lambda: stream.of_kind("resize_requested"))
        stream.send({"type": "input", "input": "size\n"})
        wait_until("PTY size report", lambda: "size:101x31" in stream.output_text())
        print("resize applied to the PTY (101x31)")

        stream.send({"type": "resize", "cols": 10, "rows": 31})
        wait_until("invalid_resize error", lambda: any(e.get("code") == "invalid_resize" for e in stream.errors))
        print("out-of-range resize rejected")

        stream.send({"type": "input", "input": "approval\n"})
        approvals = wait_until("approval event", lambda: stream.of_kind("approval_requested"))
        time.sleep(0.5)
        approvals = stream.of_kind("approval_requested")
        if len(approvals) != 1:
            raise SmokeFailure(f"expected exactly one approval event, saw {len(approvals)}")
        if not approvals[0]["data"]["prompt"].startswith("Do you want to proceed?"):
            raise SmokeFailure(f"unexpected approval prompt: {approvals[0]['data']['prompt']!r}")
        stream.send({"type": "input", "input": "1\n"})
        wait_until("answer reaching the PTY", lambda: "echo:1" in stream.output_text())
        print("approval round trip ok")

        print("SMOKE PASSED")
        return 0
    except SmokeFailure as failure:
        print(f"SMOKE FAILED: {failure}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"SMOKE FAILED: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    finally:
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        if daemon is not None:
            daemon.close()
        backend.terminate()
        try:
            backend.wait(timeout=5)
        except subprocess.TimeoutExpired:
            backend.kill()


if __name__ == "__main__":
    sys.exit(main())
