"""Agent Relay CLI for creating, joining, and managing relays."""
import click

from .client import AgentRelayClient
from .config import save_config, load_config


@click.group()
def main():
    """Agent Relay - Turn-based communication for AI agents."""
    pass


@main.command()
@click.argument("agents", nargs=-1, required=True)
@click.option("--server", default="http://localhost:8000", help="Relay server URL")
@click.option("--public", is_flag=True, help="Make relay public")
def create(agents, server, public):
    """Create a new relay with the given agent names."""
    if len(agents) < 2:
        click.echo("Error: Need at least 2 agent names", err=True)
        raise SystemExit(1)

    client = AgentRelayClient(server)
    try:
        relay = client.create_relay(list(agents), is_public=public)

        config_path = save_config(server, relay.relay_id, relay.api_key, agents[0])

        click.echo(f"Relay created: {relay.relay_id}")
        click.echo(f"Config saved: {config_path}")
        click.echo(f"You are: {agents[0]}")
        click.echo("")
        click.echo("Share these join commands with other agents:")
        for agent in agents[1:]:
            click.echo(
                f"  agent-relay join {relay.relay_id} --agent {agent}"
                f" --key {relay.api_key} --server {server}"
            )
    finally:
        client.close()


@main.command()
@click.argument("relay_id")
@click.option("--agent", required=True, help="Your agent name")
@click.option("--key", required=True, help="API key")
@click.option("--server", default="http://localhost:8000", help="Relay server URL")
def join(relay_id, agent, key, server):
    """Join an existing relay."""
    config_path = save_config(server, relay_id, key, agent)
    click.echo(f"Joined relay: {relay_id} as {agent}")
    click.echo(f"Config saved: {config_path}")


@main.command()
@click.option("--name", default="default", help="Relay name in config")
def status(name):
    """Show current relay status."""
    try:
        config = load_config(relay_name=name)
    except (FileNotFoundError, KeyError) as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    client = AgentRelayClient(config["server"])
    try:
        state = client.get_relay(config["relay_id"])
        click.echo(f"Relay: {state.relay_id}")
        click.echo(f"Turn: {state.current_turn}")
        click.echo(f"Agents: {', '.join(state.agent_names)}")
        click.echo(f"Messages: {state.message_count}")
        click.echo(f"You are: {config['agent']}")
    finally:
        client.close()


@main.command()
@click.argument("message")
@click.option("--name", default="default", help="Relay name in config")
def send(message, name):
    """Send a message from your configured agent."""
    try:
        config = load_config(relay_name=name)
    except (FileNotFoundError, KeyError) as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    client = AgentRelayClient(config["server"], api_key=config["api_key"])
    try:
        result = client.send_message(config["relay_id"], message, agent=config["agent"])
        click.echo(f"Sent! Next turn: {result.next_turn}")
    finally:
        client.close()


@main.command()
@click.argument("namespace")
@click.argument("agent_name")
@click.option("--server", default="http://localhost:8000", help="Relay server URL")
@click.option("--wait/--no-wait", default=True, help="Wait for other agents to join")
@click.option("--timeout", default=300, help="Seconds to wait for relay creation")
def register(namespace, agent_name, server, wait, timeout):
    """Register in a namespace for cross-device discovery.

    Example: agent-relay register my-project alice --server http://myserver:8000
    On another device: agent-relay register my-project bob --server http://myserver:8000
    Both agents auto-discover each other and join the same relay!
    """
    client = AgentRelayClient(server)
    click.echo(f"Registering '{agent_name}' in namespace '{namespace}'...")

    try:
        if wait:
            click.echo("Waiting for other agents to join...")
            try:
                result = client.wait_for_relay(namespace, agent_name, timeout=timeout)
            except TimeoutError:
                click.echo("Timed out waiting for other agents.", err=True)
                raise SystemExit(1)
        else:
            result = client.register(namespace, agent_name)

        if result["status"] == "waiting":
            click.echo(f"Registered. Waiting for more agents in '{namespace}'.")
            click.echo(
                f"On another device run: agent-relay register {namespace}"
                f" <agent-name> --server {server}"
            )
        else:
            click.echo(f"Relay ready: {result['relay_id']}")
            click.echo(f"Agents: {', '.join(result['agents'])}")
            if result.get("api_key"):
                save_config(server, result["relay_id"], result["api_key"], agent_name)
                click.echo("Config saved to .agent-relay.json")
    finally:
        client.close()


@main.command()
@click.argument("namespace")
@click.option("--server", default="http://localhost:8000", help="Relay server URL")
def discover(namespace, server):
    """Discover agents in a namespace."""
    client = AgentRelayClient(server)
    try:
        result = client.discover(namespace)
        click.echo(f"Namespace: {namespace}")
        click.echo(f"Relay: {result.get('relay_id', 'none yet')}")
        for agent in result.get("agents", []):
            status_icon = "+" if agent["status"] == "ready" else "o"
            click.echo(
                f"  {status_icon} {agent['agent_name']}"
                f" ({agent['status']}) on {agent['device_id']}"
            )
    finally:
        client.close()
