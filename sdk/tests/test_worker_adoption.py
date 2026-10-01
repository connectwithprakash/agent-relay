"""session_adopted reporting: backoff, logging and isolation, using fake tmux sessions."""

import httpx
import pytest

from agent_relay.exceptions import AgentRelayError
from agent_relay.worker import ManagedTmuxSession, WorkerDaemon


class _FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class _FakeAdoptedSession:
    """Stands in for a live tmux session that a restarted worker has re-attached to."""

    closed = False

    def load_cursor(self):
        return 0

    def save_cursor(self, sequence):
        pass

    def poll(self):
        return None

    def read(self, timeout=0.0):
        return ""

    def detach(self):
        pass

    def close(self):
        pass


class _AdoptClient:
    base_url = "https://relay.example.test"
    _token = "worker-token"

    def __init__(self, session_ids=("s1",), status="detached"):
        self.sessions = [
            {"session_id": sid, "profile": "claude-code-tmux", "status": status} for sid in session_ids
        ]
        self.reports = []
        self.failures = {}

    def register_worker(self, relay_id, name, profiles):
        return {"worker_id": "worker-1"}

    def list_worker_sessions(self, relay_id, worker_id):
        return self.sessions

    def get_session_events(self, relay_id, session_id, after_sequence=0):
        return []

    def append_session_event(self, relay_id, session_id, kind, data):
        if kind != "session_adopted":
            return {}
        self.reports.append(session_id)
        attempt = self.reports.count(session_id)
        failure = self.failures.get(session_id)
        if callable(failure):
            failure = failure(attempt)
        if failure is not None:
            raise failure
        return {"event": {"sequence": 1}}


@pytest.fixture
def clock():
    return _FakeClock()


@pytest.fixture(autouse=True)
def fake_attach(monkeypatch):
    monkeypatch.setattr(
        ManagedTmuxSession, "attach", classmethod(lambda cls, session_id, **kwargs: _FakeAdoptedSession())
    )


def _daemon(client, clock):
    daemon = WorkerDaemon(client, "relay-1", "Mac", ["claude-code-tmux"], clock=clock)
    daemon.start()
    return daemon


def test_detached_session_is_reported_once(clock):
    client = _AdoptClient()
    daemon = _daemon(client, clock)
    for _ in range(3):
        daemon.run_once()
        clock.advance(60)
    assert client.reports == ["s1"]


def test_a_409_drops_the_report_silently(clock, capsys):
    client = _AdoptClient()
    client.failures["s1"] = AgentRelayError("conflict", status_code=409)
    daemon = _daemon(client, clock)
    for _ in range(3):
        daemon.run_once()
        clock.advance(60)
    assert client.reports == ["s1"]
    assert "s1" in daemon._sessions
    assert capsys.readouterr().err == ""


def test_failed_report_is_retried_after_the_backoff_until_it_succeeds(clock):
    client = _AdoptClient()
    client.failures["s1"] = lambda attempt: AgentRelayError("boom", status_code=500) if attempt == 1 else None
    daemon = _daemon(client, clock)
    daemon.run_once()
    assert client.reports == ["s1"]
    daemon.run_once()
    assert client.reports == ["s1"]  # still backing off
    clock.advance(1.0)
    daemon.run_once()
    assert client.reports == ["s1", "s1"]
    clock.advance(60)
    daemon.run_once()
    assert client.reports == ["s1", "s1"]  # accepted, so silent


def test_a_409_on_retry_clears_the_pending_report(clock):
    client = _AdoptClient()
    client.failures["s1"] = lambda attempt: (
        AgentRelayError("boom", status_code=500) if attempt == 1 else AgentRelayError("conflict", status_code=409)
    )
    daemon = _daemon(client, clock)
    for _ in range(4):
        daemon.run_once()
        clock.advance(1.0)
    assert client.reports == ["s1", "s1"]


def _attempt_gaps(daemon, client, clock, passes=400):
    times = []
    for _ in range(passes):
        before = len(client.reports)
        daemon.run_once()
        if len(client.reports) > before:
            times.append(clock.now)
        clock.advance(0.5)
    return [round(b - a, 1) for a, b in zip(times, times[1:])]


def test_permanently_failing_report_backs_off_from_1s_to_30s(clock):
    client = _AdoptClient()
    client.failures["s1"] = AgentRelayError("revoked", status_code=403)
    gaps = _attempt_gaps(_daemon(client, clock), client, clock)
    assert gaps[:5] == [1.0, 2.0, 4.0, 8.0, 16.0]
    assert set(gaps[5:]) == {30.0}


def test_repeated_identical_failures_are_logged_once_and_a_change_is_logged_again(clock, capsys):
    client = _AdoptClient()
    client.failures["s1"] = lambda attempt: (
        AgentRelayError("revoked", status_code=403) if attempt <= 3 else AgentRelayError("unavailable", status_code=503)
    )
    daemon = _daemon(client, clock)
    capsys.readouterr()
    for _ in range(4):
        daemon.run_once()
        clock.advance(31.0)
    logged = [line for line in capsys.readouterr().err.splitlines() if "adoption" in line]
    assert [("revoked" in line, "unavailable" in line) for line in logged] == [(True, False), (False, True)]


@pytest.mark.parametrize("error", [
    httpx.ConnectError("connection refused"),
    httpx.ReadTimeout(""),
])
def test_transport_errors_use_the_same_backoff_and_do_not_escape_run_once(clock, capsys, error):
    client = _AdoptClient()
    client.failures["s1"] = error
    daemon = _daemon(client, clock)
    capsys.readouterr()

    daemon.run_once()
    daemon.run_once()
    assert client.reports == ["s1"]  # backing off, nothing raised
    clock.advance(1.0)
    daemon.run_once()
    clock.advance(1.0)
    daemon.run_once()  # 1 s into a 2 s delay
    assert client.reports == ["s1", "s1"]

    logged = [line for line in capsys.readouterr().err.splitlines() if "adoption" in line]
    assert len(logged) == 1
    assert type(error).__name__ in logged[0]


def test_one_failing_session_does_not_stop_the_others_from_being_reported(clock):
    client = _AdoptClient(session_ids=("bad", "good"))
    client.failures["bad"] = httpx.ConnectError("connection refused")
    daemon = _daemon(client, clock)

    daemon.run_once()

    assert sorted(client.reports) == ["bad", "good"]
    assert set(daemon._adoption_pending) == {"bad"}


def test_close_clears_pending_adoption_reports(clock):
    client = _AdoptClient()
    client.failures["s1"] = AgentRelayError("boom", status_code=500)
    daemon = _daemon(client, clock)
    daemon.run_once()
    assert daemon._adoption_pending

    daemon.close()

    assert not daemon._adoption_pending
