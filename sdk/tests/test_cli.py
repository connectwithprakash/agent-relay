"""Tests for agent_relay.cli module."""
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from agent_relay.cli import main


@patch("agent_relay.cli.AgentRelayClient")
@patch("agent_relay.cli.save_config")
def test_create_command(mock_save_config, mock_client_cls):
    """create command creates a relay and saves config."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    mock_relay = MagicMock()
    mock_relay.relay_id = "relay-test-123"
    mock_relay.token = "tok-test-abc"
    mock_client.create_relay.return_value = mock_relay
    mock_client.create_invitation.return_value = {"invitation": "invite-bob"}
    mock_save_config.return_value = "/tmp/.agent-relay.json"

    runner = CliRunner()
    result = runner.invoke(main, ["create", "alice", "bob", "--server", "http://test:8000"])

    assert result.exit_code == 0
    assert "relay-test-123" in result.output
    assert "alice" in result.output
    assert "bob" in result.output
    mock_client.create_relay.assert_called_once_with(["alice", "bob"], is_public=False)
    mock_client.create_invitation.assert_called_once_with("relay-test-123", "bob")
    mock_save_config.assert_called_once()
    mock_client.close.assert_called_once()


@patch("agent_relay.cli.AgentRelayClient")
@patch("agent_relay.cli.save_config")
def test_create_command_needs_two_agents(mock_save_config, mock_client_cls):
    """create command errors when given fewer than 2 agents."""
    runner = CliRunner()
    result = runner.invoke(main, ["create", "alice"])
    assert result.exit_code != 0
    assert "Need at least 2 agent names" in result.output


@patch("agent_relay.cli.AgentRelayClient")
@patch("agent_relay.cli.save_config")
def test_join_invitation_command(mock_save_config, mock_client_cls):
    mock_client = mock_client_cls.return_value
    mock_client.redeem_invitation.return_value = {
        "relay_id": "relay-test-123",
        "agent_name": "bob",
        "token": "token-bob",
    }
    mock_save_config.return_value = "/tmp/.agent-relay.json"

    result = CliRunner().invoke(
        main, ["join-invitation", "invite-bob", "--server", "http://test:8000"]
    )

    assert result.exit_code == 0
    mock_save_config.assert_called_once_with(
        "http://test:8000", "relay-test-123", "token-bob", "bob"
    )


@patch("agent_relay.cli.save_config")
def test_join_command(mock_save_config):
    """join command saves config for the joining agent."""
    mock_save_config.return_value = "/tmp/.agent-relay.json"

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["join", "relay-xyz", "--agent", "bob", "--token", "tok-123", "--server", "http://test:8000"],
    )

    assert result.exit_code == 0
    assert "relay-xyz" in result.output
    assert "bob" in result.output
    mock_save_config.assert_called_once_with("http://test:8000", "relay-xyz", "tok-123", "bob")


@patch("agent_relay.cli.AgentRelayClient")
@patch("agent_relay.cli.load_config")
def test_status_command(mock_load_config, mock_client_cls):
    """status command displays relay state."""
    mock_load_config.return_value = {
        "server": "http://test:8000",
        "relay_id": "relay-abc",
        "token": "tok-abc",
        "agent": "alice",
    }

    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    mock_state = MagicMock()
    mock_state.relay_id = "relay-abc"
    mock_state.current_turn = "alice"
    mock_state.agent_names = ["alice", "bob"]
    mock_state.message_count = 5
    mock_client.get_relay.return_value = mock_state

    runner = CliRunner()
    result = runner.invoke(main, ["status"])

    assert result.exit_code == 0
    assert "relay-abc" in result.output
    assert "alice" in result.output
    assert "5" in result.output
    mock_client_cls.assert_called_once_with(
        "http://test:8000", token="tok-abc"
    )
    mock_client.close.assert_called_once()


@patch("agent_relay.cli.AgentRelayClient")
@patch("agent_relay.cli.load_config")
def test_send_command(mock_load_config, mock_client_cls):
    """send command sends a message and shows next turn."""
    mock_load_config.return_value = {
        "server": "http://test:8000",
        "relay_id": "relay-abc",
        "token": "tok-abc",
        "agent": "alice",
    }

    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    mock_result = MagicMock()
    mock_result.next_turn = "bob"
    mock_client.send_message.return_value = mock_result

    runner = CliRunner()
    result = runner.invoke(main, ["send", "Hello world"])

    assert result.exit_code == 0
    assert "bob" in result.output
    mock_client.send_message.assert_called_once_with("relay-abc", "Hello world", agent="alice")
    mock_client.close.assert_called_once()


def test_status_command_no_config():
    """status command errors gracefully when no config is found."""
    runner = CliRunner()
    # Run in an isolated temp dir where no .agent-relay.json exists
    with runner.isolated_filesystem():
        result = runner.invoke(main, ["status"])
        assert result.exit_code != 0


def test_worker_run_without_config_serves_local_setup(tmp_path):
    """An unpaired worker prints the localhost setup URL instead of failing."""
    with patch("agent_relay.cli._serve_worker_setup") as serve:
        result = CliRunner().invoke(
            main,
            ["worker-run", "--name", "Mac", "--profile", "fixture-shell",
             "--config-dir", str(tmp_path), "--setup-port", "18765"],
        )

    assert result.exit_code == 0
    assert "http://127.0.0.1:18765" in result.output
    assert serve.call_args.args[0] == "Mac"
    assert serve.call_args.args[4] == tmp_path
    assert serve.call_args.args[5] == 18765


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_worker_setup_server_pairs_and_shuts_down(tmp_path):
    """The setup page rejects bad input, then enrolls with a valid code and stops."""
    from threading import Thread

    import httpx

    from agent_relay.cli import _serve_worker_setup

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    with patch("agent_relay.cli._enroll_worker") as enroll:
        thread = Thread(
            target=_serve_worker_setup,
            args=("Mac", ("fixture-shell",), None, None, tmp_path, port),
            daemon=True,
        )
        thread.start()
        for _ in range(50):
            try:
                page = httpx.get(base, timeout=1)
                break
            except httpx.ConnectError:
                import time

                time.sleep(0.05)
        assert page.status_code == 200
        assert "Pair this computer" in page.text
        assert "fixture-shell" in page.text

        bad = httpx.post(base, data={"invitation": "", "server": "ftp://x"}, timeout=1)
        assert bad.status_code == 400
        enroll.assert_not_called()

        ok = httpx.post(base, data={"invitation": "inv-1", "server": "https://relay.example"}, timeout=1)
        assert ok.status_code == 200
        assert "Worker paired" in ok.text
        enroll.assert_called_once_with("inv-1", "https://relay.example", tmp_path)

        thread.join(timeout=3)
        assert not thread.is_alive()


def _fake_claude(tmp_path):
    executable = tmp_path / "claude"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    return executable


def test_worker_run_tmux_profile_requires_workdir_and_executable(tmp_path):
    result = CliRunner().invoke(
        main, ["worker-run", "--name", "Mac", "--profile", "claude-code-tmux", "--config-dir", str(tmp_path)]
    )

    assert result.exit_code != 0
    assert "claude-code-tmux requires" in result.output


def test_worker_run_tmux_profile_requires_tmux_binary(tmp_path):
    executable = _fake_claude(tmp_path)
    with patch("agent_relay.cli.shutil.which", return_value=None):
        result = CliRunner().invoke(
            main,
            ["worker-run", "--name", "Mac", "--profile", "claude-code-tmux",
             "--claude-workdir", str(tmp_path), "--claude-executable", str(executable),
             "--config-dir", str(tmp_path)],
        )

    assert result.exit_code != 0
    assert "tmux" in result.output


def test_worker_run_tmux_profile_is_accepted_with_local_prerequisites(tmp_path):
    executable = _fake_claude(tmp_path)
    with patch("agent_relay.cli.shutil.which", return_value="/usr/bin/tmux"), \
            patch("agent_relay.cli._serve_worker_setup") as serve:
        result = CliRunner().invoke(
            main,
            ["worker-run", "--name", "Mac", "--profile", "claude-code-tmux",
             "--claude-workdir", str(tmp_path), "--claude-executable", str(executable),
             "--config-dir", str(tmp_path), "--setup-port", "18766"],
        )

    assert result.exit_code == 0
    assert serve.call_args.args[1] == ("claude-code-tmux",)


def test_session_start_accepts_the_tmux_profile(tmp_path):
    with patch("agent_relay.cli._controller_client") as controller:
        client = controller.return_value[1]
        controller.return_value = ({"relay_id": "relay-1"}, client)
        client.start_session.return_value = {"session_id": "s1", "status": "starting", "profile": "claude-code-tmux", "version": 1}
        result = CliRunner().invoke(main, ["session-start", "worker-1", "claude-code-tmux"])

    assert result.exit_code == 0, result.output
    assert client.start_session.call_args.args[2] == "claude-code-tmux"
