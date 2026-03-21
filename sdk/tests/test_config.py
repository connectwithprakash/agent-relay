"""Tests for agent_relay.config module."""
import json
import os

import pytest

from agent_relay.config import (
    CONFIG_FILENAME,
    find_config,
    load_config,
    load_from_env,
    save_config,
)


def test_save_and_load_config(tmp_path):
    """save_config writes a valid JSON file that load_config can read back."""
    config_path = save_config(
        server="http://example.com:8000",
        relay_id="relay-123",
        api_key="key-abc",
        agent="alice",
        path=str(tmp_path),
    )
    assert config_path.exists()

    data = load_config(path=str(config_path), relay_name="default")
    assert data["server"] == "http://example.com:8000"
    assert data["relay_id"] == "relay-123"
    assert data["api_key"] == "key-abc"
    assert data["agent"] == "alice"


def test_save_config_updates_existing(tmp_path):
    """save_config merges into an existing config file without clobbering other relays."""
    save_config("http://s1", "r1", "k1", "a1", relay_name="first", path=str(tmp_path))
    save_config("http://s2", "r2", "k2", "a2", relay_name="second", path=str(tmp_path))

    with open(tmp_path / CONFIG_FILENAME) as f:
        raw = json.load(f)

    assert "first" in raw["relays"]
    assert "second" in raw["relays"]
    assert raw["relays"]["first"]["relay_id"] == "r1"
    assert raw["relays"]["second"]["relay_id"] == "r2"


def test_find_config_walks_upward(tmp_path):
    """find_config walks parent directories until it finds .agent-relay.json."""
    # Create config in the root of tmp_path
    save_config("http://localhost:8000", "relay-x", "key-x", "bob", path=str(tmp_path))

    # Create a nested directory structure
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)

    found = find_config(start_path=str(nested))
    assert found is not None
    assert found == tmp_path / CONFIG_FILENAME


def test_find_config_returns_none_when_missing(tmp_path):
    """find_config returns None when no config file exists in the hierarchy."""
    nested = tmp_path / "empty" / "tree"
    nested.mkdir(parents=True)
    assert find_config(start_path=str(nested)) is None


def test_load_from_env(monkeypatch):
    """load_from_env reads AGENT_RELAY_* environment variables."""
    monkeypatch.setenv("AGENT_RELAY_SERVER", "http://remote:9000")
    monkeypatch.setenv("AGENT_RELAY_ID", "relay-env")
    monkeypatch.setenv("AGENT_RELAY_KEY", "key-env")
    monkeypatch.setenv("AGENT_RELAY_AGENT", "eve")

    config = load_from_env()
    assert config["server"] == "http://remote:9000"
    assert config["relay_id"] == "relay-env"
    assert config["api_key"] == "key-env"
    assert config["agent"] == "eve"


def test_load_from_env_default_server(monkeypatch):
    """load_from_env uses default server when AGENT_RELAY_SERVER is not set."""
    monkeypatch.delenv("AGENT_RELAY_SERVER", raising=False)
    monkeypatch.setenv("AGENT_RELAY_ID", "relay-env")

    config = load_from_env()
    assert config["server"] == "http://localhost:8000"


def test_load_from_env_missing_relay_id(monkeypatch):
    """load_from_env raises when AGENT_RELAY_ID is not set."""
    monkeypatch.delenv("AGENT_RELAY_ID", raising=False)
    with pytest.raises(EnvironmentError, match="AGENT_RELAY_ID"):
        load_from_env()


def test_load_missing_config_raises():
    """load_config raises FileNotFoundError when pointed at a nonexistent path."""
    with pytest.raises(FileNotFoundError):
        load_config(path="/nonexistent/.agent-relay.json")


def test_load_config_missing_relay_name(tmp_path):
    """load_config raises KeyError when the requested relay name is not in the file."""
    save_config("http://localhost:8000", "r1", "k1", "a1", path=str(tmp_path))
    config_path = tmp_path / CONFIG_FILENAME

    with pytest.raises(KeyError, match="nonexistent"):
        load_config(path=str(config_path), relay_name="nonexistent")
