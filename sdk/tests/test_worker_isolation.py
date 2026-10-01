"""One failing session must not starve the others in run_once."""

import time

import httpx
import pytest

from agent_relay.worker import ManagedPtySession

from agent_relay.exceptions import AgentRelayError
from agent_relay.worker import WorkerDaemon


class _MultiClient:
    base_url = "https://relay.example.test"
    _token = "worker-token"

    def __init__(self, session_ids=("bad", "good")):
        self.sessions = [
            {"session_id": sid, "profile": "fixture-shell", "status": "starting"} for sid in session_ids
        ]
        self.events = {sid: [] for sid in session_ids}
        self.fail_events = {}
        self.fail_append = {}
        self.fail_ready = {}
        self.appended = []
        self.append_rule = None
        self.ready_calls = []
        self.event_calls = {sid: 0 for sid in session_ids}

    def register_worker(self, relay_id, name, profiles):
        return {"worker_id": "worker-1"}

    def list_worker_sessions(self, relay_id, worker_id):
        return self.sessions

    def mark_session_ready(self, relay_id, session_id):
        self.ready_calls.append(session_id)
        failure = self.fail_ready.get(session_id)
        if failure and len([c for c in self.ready_calls if c == session_id]) <= failure[0]:
            raise failure[1]
        return {"status": "ready"}

    def get_session_events(self, relay_id, session_id, after_sequence=0):
        self.event_calls[session_id] += 1
        failure = self.fail_events.get(session_id)
        if failure and self.event_calls[session_id] <= failure[0]:
            raise failure[1]
        return [e for e in self.events[session_id] if e["sequence"] > after_sequence]

    def append_session_event(self, relay_id, session_id, kind, data):
        if self.append_rule is not None:
            self.append_rule(session_id, kind, data)
        failure = self.fail_append.get((session_id, kind))
        if failure and failure[0] > 0:
            self.fail_append[(session_id, kind)] = (failure[0] - 1, failure[1])
            raise failure[1]
        self.appended.append((session_id, kind, data))
        return {"event": {"sequence": 1}}


def _input(sequence, text):
    return {"sequence": sequence, "kind": "input_requested", "data": {"input": text}}


def _output(client, session_id):
    return "".join(d["text"] for sid, kind, d in client.appended if sid == session_id and kind == "output")


def _pump(daemon, client, session_id, needle, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        daemon.run_once()
        if needle in _output(client, session_id):
            return
        time.sleep(0.03)
    raise AssertionError(f"{needle!r} not seen for {session_id}")


@pytest.fixture
def make_daemon():
    daemons = []

    def build(client, **options):
        daemon = WorkerDaemon(client, "relay-1", "Mac", ["fixture-shell"], **options)
        daemon.start()
        daemons.append(daemon)
        return daemon

    yield build
    for daemon in daemons:
        daemon.close()


CONNECT_ERROR = httpx.ConnectError("connection refused")


def test_a_failing_session_does_not_stop_the_next_one_in_the_same_pass(make_daemon):
    client = _MultiClient()
    client.events["good"] = [_input(1, "good-input\n")]
    client.fail_events["bad"] = (1000, CONNECT_ERROR)
    daemon = make_daemon(client)

    daemon.run_once()  # starts both, bad's event fetch fails

    assert daemon._cursors.get("good") == 1  # good's input was applied in the same pass
    assert daemon._cursors.get("bad", 0) == 0  # nothing advanced for bad
    _pump(daemon, client, "good", "echo:good-input")


def test_a_recovering_session_processes_its_events_in_order_without_loss_or_duplication(make_daemon):
    client = _MultiClient()
    client.events["bad"] = [_input(1, "one\n"), _input(2, "two\n")]
    client.fail_events["bad"] = (3, httpx.ReadTimeout(""))
    daemon = make_daemon(client)

    for _ in range(3):
        daemon.run_once()
        assert daemon._cursors.get("bad", 0) == 0
    _pump(daemon, client, "bad", "echo:two")

    text = _output(client, "bad")
    assert text.count("echo:one") == 1 and text.count("echo:two") == 1
    assert text.index("echo:one") < text.index("echo:two")
    assert daemon._cursors["bad"] == 2


def test_an_error_is_logged_once_per_session_until_it_changes_or_recovers(make_daemon, capsys):
    client = _MultiClient(session_ids=("bad",))
    clock = _FakeClock()
    daemon = make_daemon(client, clock=clock)
    client.fail_events["bad"] = (4, CONNECT_ERROR)
    capsys.readouterr()
    for _ in range(4):
        daemon.run_once()
    first = [l for l in capsys.readouterr().err.splitlines() if "bad" in l]
    assert len(first) == 1

    client.fail_events["bad"] = (1000, AgentRelayError("revoked", status_code=403))
    clock.advance(31)
    daemon.run_once()
    clock.advance(31)
    daemon.run_once()
    changed = [l for l in capsys.readouterr().err.splitlines() if "bad" in l]
    assert len(changed) == 1 and "revoked" in changed[0]

    client.fail_events["bad"] = (0, None)
    clock.advance(31)
    daemon.run_once()  # recovers
    client.fail_events["bad"] = (1000, AgentRelayError("revoked", status_code=403))
    client.event_calls["bad"] = 0
    capsys.readouterr()
    clock.advance(31)
    daemon.run_once()
    again = [l for l in capsys.readouterr().err.splitlines() if "bad" in l]
    assert len(again) == 1  # same error after a recovery is news again


def test_other_exception_types_still_propagate(make_daemon):
    client = _MultiClient(session_ids=("bad",))
    client.fail_events["bad"] = (1, KeyError("sequence"))
    daemon = make_daemon(client)

    with pytest.raises(KeyError):
        daemon.run_once()


def test_output_is_kept_and_resent_when_the_append_fails(make_daemon):
    client = _MultiClient(session_ids=("good",))
    client.events["good"] = [_input(1, "keep me\n")]
    client.fail_append[("good", "output")] = (2, CONNECT_ERROR)
    daemon = make_daemon(client)

    _pump(daemon, client, "good", "echo:keep me")

    text = _output(client, "good")
    assert text.count("echo:keep me") == 1
    assert text.count("fixture ready") == 1


def test_a_failed_mark_ready_is_retried_without_starting_a_second_process(make_daemon):
    client = _MultiClient(session_ids=("good",))
    client.fail_ready["good"] = (1, CONNECT_ERROR)
    daemon = make_daemon(client)

    daemon.run_once()
    first_process = daemon._sessions["good"]
    daemon.run_once()

    assert client.ready_calls == ["good", "good"]
    assert daemon._sessions["good"] is first_process
    daemon.run_once()
    assert client.ready_calls == ["good", "good"]


class _FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


PROMPT = "Do you want to proceed?\n  > 1. Yes\n    2. No\n"
EVENT_LIMIT_BYTES = 64 * 1024


def _scripted_reads(monkeypatch, chunks):
    queue = list(chunks)
    monkeypatch.setattr(ManagedPtySession, "read", lambda self, timeout=0.0: queue.pop(0) if queue else "")


def _backend_rule(client, fail_when=None):
    """Mimic the backend: reject oversize data with 422, and anything `fail_when` names."""

    def rule(session_id, kind, data):
        text = data.get("text") or data.get("prompt") or ""
        if len(text.encode()) > EVENT_LIMIT_BYTES:
            raise AgentRelayError("data too large", status_code=422)
        if fail_when is not None:
            fail_when(session_id, kind, data)

    client.append_rule = rule


def _outputs(client, session_id="good"):
    return [d["text"] for sid, kind, d in client.appended if sid == session_id and kind == "output"]


def test_oversize_output_is_split_into_small_events_and_later_output_still_flows(make_daemon, monkeypatch):
    client = _MultiClient(session_ids=("good",))
    _backend_rule(client)
    big = "".join(chr(0x4e00 + (i % 500)) for i in range(70000))  # 3-byte characters
    _scripted_reads(monkeypatch, ["", big, "small after\n"])
    daemon = make_daemon(client)

    for _ in range(3):
        daemon.run_once()

    events = _outputs(client)
    assert all(len(text.encode()) <= 16 * 1024 for text in events)
    assert "".join(events) == big + "small after\n"
    assert not daemon._unsent_output


def test_a_permanent_4xx_drops_the_chunk_without_retaining_it(make_daemon, monkeypatch, capsys):
    client = _MultiClient(session_ids=("good",))
    _backend_rule(client, fail_when=lambda sid, kind, data: (_ for _ in ()).throw(
        AgentRelayError("rejected", status_code=422)) if "POISON" in data.get("text", "") else None)
    _scripted_reads(monkeypatch, ["", "POISON\n", "POISON again\n", "fine\n"])
    daemon = make_daemon(client)
    capsys.readouterr()

    for _ in range(4):
        daemon.run_once()

    assert "fine" in "".join(_outputs(client))
    assert not daemon._unsent_output
    assert len([l for l in capsys.readouterr().err.splitlines() if "dropp" in l]) == 1


def test_retained_output_is_capped_during_a_long_outage_and_the_newest_text_survives(make_daemon, monkeypatch, capsys):
    client = _MultiClient(session_ids=("good",))
    outage = {"on": True}

    def rule(session_id, kind, data):
        if outage["on"]:
            raise httpx.ConnectError("down")

    client.append_rule = rule
    chunks = [f"{i:04d}" + "x" * 9996 for i in range(200)]
    _scripted_reads(monkeypatch, [""] + chunks + [""])
    daemon = make_daemon(client)
    capsys.readouterr()

    for _ in range(201):
        daemon.run_once()

    assert len(daemon._unsent_output["good"]) <= 256 * 1024
    assert daemon._unsent_output["good"].endswith(chunks[-1])
    assert len([l for l in capsys.readouterr().err.splitlines() if "dropp" in l]) == 1

    outage["on"] = False
    daemon.run_once()
    assert "".join(_outputs(client)).endswith(chunks[-1])


def test_retained_output_is_resent_first_and_in_order_after_recovery(make_daemon, monkeypatch):
    client = _MultiClient(session_ids=("good",))
    outage = {"on": True}

    def rule(session_id, kind, data):
        if outage["on"] and kind == "output":
            raise AgentRelayError("unavailable", status_code=503)

    client.append_rule = rule
    _scripted_reads(monkeypatch, ["", "A", "B", "C", "D"])
    daemon = make_daemon(client)

    for _ in range(4):
        daemon.run_once()
    outage["on"] = False
    daemon.run_once()

    assert "".join(_outputs(client)) == "ABCD"


@pytest.mark.parametrize("status", [None, 408, 429, 500, 503])
def test_retryable_errors_keep_the_output(make_daemon, monkeypatch, status):
    client = _MultiClient(session_ids=("good",))
    calls = []

    def rule(session_id, kind, data):
        calls.append(kind)
        if len(calls) == 1:
            raise AgentRelayError("transient", status_code=status)

    client.append_rule = rule
    _scripted_reads(monkeypatch, ["", "keep\n"])
    daemon = make_daemon(client)

    daemon.run_once()
    daemon.run_once()
    daemon.run_once()

    assert "keep" in "".join(_outputs(client))


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413, 422])
def test_other_4xx_errors_drop_the_output(make_daemon, monkeypatch, status):
    client = _MultiClient(session_ids=("good",))

    def rule(session_id, kind, data):
        if "lost" in data.get("text", ""):
            raise AgentRelayError("permanent", status_code=status)

    client.append_rule = rule
    _scripted_reads(monkeypatch, ["", "lost\n", "kept\n"])
    daemon = make_daemon(client)

    for _ in range(3):
        daemon.run_once()

    assert "".join(_outputs(client)) == "kept\n"
    assert not daemon._unsent_output


def test_a_rejected_approval_prompt_is_dropped_and_a_retryable_one_is_kept(make_daemon, monkeypatch):
    client = _MultiClient(session_ids=("good",))
    mode = {"error": AgentRelayError("rejected", status_code=422)}

    def rule(session_id, kind, data):
        if kind == "approval_requested" and mode["error"] is not None:
            raise mode["error"]

    client.append_rule = rule
    _scripted_reads(monkeypatch, ["", PROMPT, "next\n"])
    daemon = make_daemon(client)

    daemon.run_once()
    daemon.run_once()
    daemon.run_once()
    assert not daemon._unsent_prompts.get("good")
    assert "next" in "".join(_outputs(client))

    mode["error"] = httpx.ConnectError("down")
    _scripted_reads(monkeypatch, [PROMPT])
    daemon.run_once()
    assert len(daemon._unsent_prompts["good"]) == 1
    mode["error"] = None
    daemon.run_once()
    prompts = [d["prompt"] for sid, kind, d in client.appended if kind == "approval_requested"]
    assert len(prompts) == 1 and prompts[0].startswith("Do you want to proceed?")


def test_retained_prompts_are_capped(make_daemon, monkeypatch):
    client = _MultiClient(session_ids=("good",))

    def rule(session_id, kind, data):
        if kind == "approval_requested":
            raise httpx.ConnectError("down")

    client.append_rule = rule
    _scripted_reads(monkeypatch, [""] + [PROMPT] * 60)
    daemon = make_daemon(client)
    for _ in range(61):
        try:
            daemon.run_once()
        except httpx.ConnectError:
            pass
    assert len(daemon._unsent_prompts["good"]) <= 16


def test_a_session_with_a_permanent_4xx_every_pass_backs_off(make_daemon, capsys):
    client = _MultiClient(session_ids=("gone",))
    client.fail_events["gone"] = (10**6, AgentRelayError("session not found", status_code=404))
    clock = _FakeClock()
    daemon = make_daemon(client, clock=clock)
    capsys.readouterr()

    times = []
    for _ in range(400):
        before = client.event_calls["gone"]
        daemon.run_once()
        if client.event_calls["gone"] > before:
            times.append(clock.now)
        clock.advance(0.5)

    gaps = [round(b - a, 1) for a, b in zip(times, times[1:])]
    assert gaps[:5] == [1.0, 2.0, 4.0, 8.0, 16.0]
    assert set(gaps[5:]) == {30.0}
    assert len([l for l in capsys.readouterr().err.splitlines() if "gone" in l]) == 1
