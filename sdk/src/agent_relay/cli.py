"""Agent Relay CLI for creating, joining, and managing relays."""
import click

from .client import AgentRelayClient
from .config import save_config, load_config, DEFAULT_SERVER


@click.group()
def main():
    """Agent Relay - Turn-based communication for AI agents."""
    pass


@main.command()
@click.argument("agents", nargs=-1, required=True)
@click.option("--server", default=DEFAULT_SERVER, help="Relay server URL")
@click.option("--public", is_flag=True, help="Make relay public")
def create(agents, server, public):
    """Create a new relay with the given agent names."""
    if len(agents) < 2:
        click.echo("Error: Need at least 2 agent names", err=True)
        raise SystemExit(1)

    client = AgentRelayClient(server)
    try:
        relay = client.create_relay(list(agents), is_public=public)

        config_path = save_config(server, relay.relay_id, relay.token or "", agents[0])

        click.echo(f"Relay created: {relay.relay_id}")
        click.echo(f"Config saved: {config_path}")
        click.echo(f"You are: {agents[0]}")
        click.echo("")
        click.echo("Share each one-time invitation only with its named agent:")
        for agent in agents[1:]:
            invitation = client.create_invitation(relay.relay_id, agent)
            click.echo(
                f"  agent-relay join-invitation {invitation['invitation']}"
                f" --server {server}"
            )
    finally:
        client.close()


@main.command()
@click.argument("relay_id")
@click.option("--agent", required=True, help="Your agent name")
@click.option("--token", required=True, help="Auth token")
@click.option("--server", default=DEFAULT_SERVER, help="Relay server URL")
def join(relay_id, agent, token, server):
    """Join an existing relay."""
    config_path = save_config(server, relay_id, token, agent)
    click.echo(f"Joined relay: {relay_id} as {agent}")
    click.echo(f"Config saved: {config_path}")


@main.command("join-code")
@click.argument("code")
@click.argument("agent_name")
@click.option("--server", default=DEFAULT_SERVER, help="Relay server URL")
def join_code(code, agent_name, server):
    """Join using legacy relay-wide pairing material.

    Example: agent-relay join-code ABC123 alice
    """
    client = AgentRelayClient(server)
    try:
        result = client.join_by_code(code, agent_name)
        config_path = save_config(
            server, result["relay_id"], result["token"], agent_name
        )
        click.echo(f"Joined relay {result['relay_id']} as {agent_name}")
        click.echo(f"Join code: {result['join_code']}")
        click.echo(f"Agents: {', '.join(result['agent_names'])}")
        click.echo(f"Config saved: {config_path}")
    finally:
        client.close()


@main.command("join-invitation")
@click.argument("invitation")
@click.option("--server", default=DEFAULT_SERVER, help="Relay server URL")
def join_invitation(invitation, server):
    """Redeem a one-time, participant-bound invitation."""
    client = AgentRelayClient(server)
    try:
        result = client.redeem_invitation(invitation)
        config_path = save_config(
            server, result["relay_id"], result["token"], result["agent_name"]
        )
        click.echo(f"Joined relay {result['relay_id']} as {result['agent_name']}")
        click.echo(f"Config saved: {config_path}")
    finally:
        client.close()


@main.command()
@click.option("--name", default="default", help="Relay name in config")
def status(name):
    """Show current relay status."""
    try:
        config = load_config(relay_name=name)
    except (FileNotFoundError, KeyError) as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    client = AgentRelayClient(config["server"], token=config["token"])
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

    client = AgentRelayClient(config["server"], token=config["token"])
    try:
        result = client.send_message(config["relay_id"], message, agent=config["agent"])
        click.echo(f"Sent! Next turn: {result.next_turn}")
    finally:
        client.close()


@main.command("skip")
@click.option("--force", is_flag=True, help="Force skip even without timeout")
@click.option("--name", default="default", help="Relay name in config")
def skip_turn(force, name):
    """Skip the current agent's turn. Use --force for disconnected agents."""
    try:
        config = load_config(relay_name=name)
    except (FileNotFoundError, KeyError) as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    client = AgentRelayClient(config["server"], token=config["token"])
    try:
        result = client.skip_turn(config["relay_id"], force=force)
        click.echo(f"Skipped: {result.get('skipped_agent')}")
        click.echo(f"Next turn: {result.get('next_turn')}")
        if result.get("forced"):
            click.echo("(force skip)")
    finally:
        client.close()


@main.command()
@click.argument("namespace")
@click.argument("agent_name")
@click.option("--server", default=DEFAULT_SERVER, help="Relay server URL")
@click.option("--description", "-d", default="", help="What this agent does")
@click.option("--capabilities", "-c", default="", help="Comma-separated capabilities")
@click.option("--wait/--no-wait", default=True, help="Wait for other agents to join")
@click.option("--timeout", default=300, help="Seconds to wait for relay creation")
def register(namespace, agent_name, server, description, capabilities, wait, timeout):
    """Register agent with capabilities for discovery.

    Example: agent-relay register my-project alice -d "Code reviewer" -c "code_review,python"
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
            result = client.register(
                namespace,
                agent_name,
                description=description or None,
                capabilities=capabilities or None,
            )

        if result["status"] == "waiting":
            click.echo(f"Registered. Waiting for more agents in '{namespace}'.")
            click.echo(
                f"On another device run: agent-relay register {namespace}"
                f" <agent-name> --server {server}"
            )
        else:
            click.echo(f"Relay ready: {result['relay_id']}")
            click.echo(f"Agents: {', '.join(result['agents'])}")
            if result.get("token"):
                save_config(server, result["relay_id"], result["token"], agent_name)
                click.echo("Config saved to .agent-relay.json")
    finally:
        client.close()


@main.command()
@click.argument("namespace")
@click.option("--server", default=DEFAULT_SERVER, help="Relay server URL")
def discover(namespace, server):
    """Discover agents in a namespace."""
    client = AgentRelayClient(server)
    try:
        result = client.discover(namespace)
        click.echo(f"Namespace: {namespace}")
        click.echo(f"Relay: {result.get('relay_id', 'none yet')}")
        for agent in result.get("agents", []):
            status_icon = "+" if agent["status"] == "ready" else "o"
            caps = agent.get("capabilities") or []
            caps_str = f" [{', '.join(caps)}]" if caps else ""
            desc_str = f" - {agent['description']}" if agent.get("description") else ""
            click.echo(
                f"  {status_icon} {agent['agent_name']}"
                f" ({agent['status']}) on {agent['device_id']}"
                f"{desc_str}{caps_str}"
            )
    finally:
        client.close()


@main.command("search")
@click.option("--capability", "-c", default=None, help="Capability to search for")
@click.option("--namespace", "-n", default=None, help="Limit to namespace")
@click.option("--server", default=DEFAULT_SERVER, help="Relay server URL")
def search_agents(capability, namespace, server):
    """Search for agents by capability."""
    client = AgentRelayClient(server)
    try:
        result = client.search_agents(capability=capability, namespace=namespace)
        agents = result.get("agents", [])
        if not agents:
            click.echo("No agents found.")
            return
        click.echo(f"Found {len(agents)} agent(s):")
        for agent in agents:
            caps = agent.get("capabilities") or []
            caps_str = f" [{', '.join(caps)}]" if caps else ""
            desc_str = f" - {agent['description']}" if agent.get("description") else ""
            click.echo(
                f"  {agent['agent_name']}@{agent['namespace']}"
                f" ({agent['status']}){desc_str}{caps_str}"
            )
    finally:
        client.close()
