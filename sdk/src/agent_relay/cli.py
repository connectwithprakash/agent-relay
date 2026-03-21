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
