#!/usr/bin/env python3
"""Temporary tailnet-only worker for the managed-PTY fixture proof."""
import argparse
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


_FIXTURE_PROGRAM = """import sys
print('fixture ready', flush=True)
for line in sys.stdin:
    print('echo:' + line.rstrip('\\r\\n'), flush=True)
"""


def request_json(server, method, path, token=None, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"{server.rstrip('/')}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read())
    except HTTPError as error:
        body = error.read().decode(errors="replace")
        raise RuntimeError(f"Relay request failed ({error.code}): {body}") from error


def start_fixture():
    master_fd, slave_fd = os.openpty()
    try:
        process = subprocess.Popen(
            [sys.executable, "-u", "-c", _FIXTURE_PROGRAM],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
        )
    finally:
        os.close(slave_fd)
    return process, master_fd


def read_output(master_fd, timeout):
    deadline = time.monotonic() + timeout
    chunks = []
    while True:
        remaining = max(0.0, deadline - time.monotonic())
        readable, _, _ = select.select([master_fd], [], [], remaining)
        if not readable:
            break
        try:
            chunk = os.read(master_fd, 65536)
        except OSError:
            break
        if not chunk:
            break
        chunks.append(chunk)
        deadline = time.monotonic() + 0.02
    return b"".join(chunks).decode(errors="replace")


def main():
    parser = argparse.ArgumentParser(description="Run the Agent Relay fixture worker over a private tailnet")
    parser.add_argument("--server", required=True, help="Private tailnet Relay URL")
    parser.add_argument("--invitation-file", required=True, type=Path)
    parser.add_argument("--name", default="Work laptop fixture worker")
    parser.add_argument("--poll-seconds", default=0.2, type=float)
    args = parser.parse_args()

    invitation_data = json.loads(args.invitation_file.read_text())
    invitation = invitation_data["invitation"]
    pairing = request_json(args.server, "POST", f"/pairing-invitations/{invitation}/redeem")
    args.invitation_file.unlink()

    relay_id = pairing["relay_id"]
    token = pairing["token"]
    worker = request_json(
        args.server,
        "POST",
        f"/relays/{relay_id}/workers",
        token,
        {"name": args.name, "profiles": ["fixture-shell"]},
    )
    worker_id = worker["worker_id"]
    print("Fixture worker registered. Press Ctrl-C to stop.", flush=True)

    sessions = {}
    cursors = {}
    try:
        while True:
            assigned = request_json(
                args.server,
                "GET",
                f"/relays/{relay_id}/sessions?worker_id={worker_id}",
                token,
            )["sessions"]
            for session in assigned:
                session_id = session["session_id"]
                if session["status"] == "starting" and session_id not in sessions:
                    sessions[session_id] = start_fixture()
                    request_json(args.server, "POST", f"/relays/{relay_id}/sessions/{session_id}/ready", token)

                owned = sessions.get(session_id)
                if not owned:
                    continue
                process, master_fd = owned
                events = request_json(
                    args.server,
                    "GET",
                    f"/relays/{relay_id}/sessions/{session_id}/events?after_sequence={cursors.get(session_id, 0)}",
                    token,
                )["events"]
                for event in events:
                    cursors[session_id] = max(cursors.get(session_id, 0), event["sequence"])
                    if event["kind"] == "input_requested":
                        os.write(master_fd, event["data"]["input"].encode())
                output = read_output(master_fd, args.poll_seconds if events else 0.0)
                if output:
                    request_json(
                        args.server,
                        "POST",
                        f"/relays/{relay_id}/sessions/{session_id}/events",
                        token,
                        {"kind": "output", "data": {"text": output}},
                    )
                if process.poll() is not None:
                    os.close(master_fd)
                    del sessions[session_id]
            time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        print("Stopping fixture worker.", flush=True)
    finally:
        for process, master_fd in sessions.values():
            os.close(master_fd)
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=2)


if __name__ == "__main__":
    main()
