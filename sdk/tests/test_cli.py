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
    mock_relay.api_key = "key-test-abc"
    mock_client.create_relay.return_value = mock_relay
    mock_save_config.return_value = "/tmp/.agent-relay.json"

    runner = CliRunner()
    result = runner.invoke(main, ["create", "alice", "bob", "--server", "http://test:8000"])

    assert result.exit_code == 0
    assert "relay-test-123" in result.output
    assert "alice" in result.output
    assert "bob" in result.output
    mock_client.create_relay.assert_called_once_with(["alice", "bob"], is_public=False)
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


@patch("agent_relay.cli.save_config")
def test_join_command(mock_save_config):
    """join command saves config for the joining agent."""
    mock_save_config.return_value = "/tmp/.agent-relay.json"

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["join", "relay-xyz", "--agent", "bob", "--key", "key-123", "--server", "http://test:8000"],
    )

    assert result.exit_code == 0
    assert "relay-xyz" in result.output
    assert "bob" in result.output
    mock_save_config.assert_called_once_with("http://test:8000", "relay-xyz", "key-123", "bob")


@patch("agent_relay.cli.AgentRelayClient")
@patch("agent_relay.cli.load_config")
def test_status_command(mock_load_config, mock_client_cls):
    """status command displays relay state."""
    mock_load_config.return_value = {
        "server": "http://test:8000",
        "relay_id": "relay-abc",
        "api_key": "key-abc",
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
    mock_client.close.assert_called_once()


@patch("agent_relay.cli.AgentRelayClient")
@patch("agent_relay.cli.load_config")
def test_send_command(mock_load_config, mock_client_cls):
    """send command sends a message and shows next turn."""
    mock_load_config.return_value = {
        "server": "http://test:8000",
        "relay_id": "relay-abc",
        "api_key": "key-abc",
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
