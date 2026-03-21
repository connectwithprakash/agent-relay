"""Agent Relay configuration discovery and persistence."""
import json
import os
from pathlib import Path
from typing import Optional

CONFIG_FILENAME = ".agent-relay.json"


def find_config(start_path: Optional[str] = None) -> Optional[Path]:
    """Walk upward from start_path (default: cwd) to find .agent-relay.json."""
    path = Path(start_path or os.getcwd()).resolve()
    while path != path.parent:
        config_file = path / CONFIG_FILENAME
        if config_file.exists():
            return config_file
        path = path.parent
    return None


def load_config(path: Optional[str] = None, relay_name: str = "default") -> dict:
    """Load config from .agent-relay.json.

    Returns dict with server, relay_id, api_key, agent.
    """
    config_path = find_config(path) if path is None else Path(path)
    if config_path is None or not config_path.exists():
        raise FileNotFoundError(f"No {CONFIG_FILENAME} found")

    with open(config_path) as f:
        data = json.load(f)

    relay = data.get("relays", {}).get(relay_name)
    if not relay:
        raise KeyError(f"Relay '{relay_name}' not found in config")

    return {
        "server": data.get("server", "http://localhost:8000"),
        "relay_id": relay["relay_id"],
        "api_key": relay.get("api_key"),
        "agent": relay.get("my_agent"),
    }


def save_config(
    server: str,
    relay_id: str,
    api_key: str,
    agent: str,
    relay_name: str = "default",
    path: Optional[str] = None,
) -> Path:
    """Save/update .agent-relay.json in the given path (default: cwd)."""
    config_path = Path(path or os.getcwd()) / CONFIG_FILENAME

    if config_path.exists():
        with open(config_path) as f:
            data = json.load(f)
    else:
        data = {"version": 1, "server": server, "relays": {}}

    data["server"] = server
    data["relays"][relay_name] = {
        "relay_id": relay_id,
        "api_key": api_key,
        "my_agent": agent,
    }

    with open(config_path, "w") as f:
        json.dump(data, f, indent=2)

    return config_path


def load_from_env() -> dict:
    """Load config from AGENT_RELAY_* environment variables."""
    server = os.environ.get("AGENT_RELAY_SERVER", "http://localhost:8000")
    relay_id = os.environ.get("AGENT_RELAY_ID")
    api_key = os.environ.get("AGENT_RELAY_KEY")
    agent = os.environ.get("AGENT_RELAY_AGENT")

    if not relay_id:
        raise EnvironmentError("AGENT_RELAY_ID environment variable not set")

    return {"server": server, "relay_id": relay_id, "api_key": api_key, "agent": agent}
