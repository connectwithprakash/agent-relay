"""Agent Relay CLI for creating, joining, and managing relays."""
import os
import signal
import time
from pathlib import Path
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Optional
from urllib.parse import parse_qs

import click
import httpx

from .client import AgentRelayClient
from .exceptions import AgentRelayError
from .config import save_config, load_config, DEFAULT_SERVER
from .worker import WorkerDaemon


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


def _write_worker_pid(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing_pid = int(path.read_text().strip())
            os.kill(existing_pid, 0)
        except (ValueError, ProcessLookupError):
            pass
        else:
            raise click.ClickException(f"Worker already running with PID {existing_pid}")
    path.write_text(f"{os.getpid()}\n")
    path.chmod(0o600)


def _enroll_worker(invitation: str, server: str, config_dir: Path) -> dict:
    """Redeem a local one-time worker invitation and persist its credential."""
    client = AgentRelayClient(server)
    try:
        result = client.redeem_invitation(invitation)
    finally:
        client.close()
    save_config(server, result["relay_id"], result["token"], result["agent_name"], path=str(config_dir))
    return result


def _worker_setup_page(worker_name: str, profiles: tuple[str, ...], workdir: Optional[Path], executable: Optional[Path], error: str = "") -> str:
    """Render the localhost-only Worker enrollment page without exposing secrets."""
    error_html = f"<p class=\"error\">{escape(error)}</p>" if error else ""
    details = "<br>".join(filter(None, [
        f"Worker name: {escape(worker_name)}",
        f"Allowed profiles: {escape(', '.join(profiles))}",
        f"Claude worktree: {escape(str(workdir))}" if workdir else None,
        f"Claude executable: {escape(str(executable))}" if executable else None,
    ]))
    return f"""<!doctype html><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>Agent Relay Worker setup</title>
<style>body{{font-family:system-ui;max-width:42rem;margin:3rem auto;padding:0 1rem;color:#172033}}input,button{{box-sizing:border-box;width:100%;padding:.8rem;margin:.4rem 0;font:inherit}}button{{background:#4f39f6;color:white;border:0;border-radius:.5rem;font-weight:700}}.card{{border:1px solid #dbe2ef;border-radius:1rem;padding:1.25rem}}.error{{color:#b42318}}</style>
<main><h1>Pair this computer</h1><p>This local Worker will only run the approved profile shown below.</p><div class=\"card\"><p>{details}</p></div>{error_html}
<form method=\"post\"><label>One-time work-computer code<input name=\"invitation\" required autocomplete=\"off\"></label><label>Relay server URL<input name=\"server\" required placeholder=\"https://relay.example\"></label><button>Pair and start Worker</button></form></main>"""


def _serve_worker_setup(worker_name: str, profiles: tuple[str, ...], workdir: Optional[Path], executable: Optional[Path], config_dir: Path, port: int) -> None:
    """Serve local enrollment until pairing succeeds, then let supervision restart Worker mode."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def _send(self, body: str, status: int = 200) -> None:
            encoded = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            self._send(_worker_setup_page(worker_name, profiles, workdir, executable))

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            form = parse_qs(self.rfile.read(length).decode())
            invitation = form.get("invitation", [""])[0].strip()
            server = form.get("server", [""])[0].strip()
            if not invitation or not server.startswith(("https://", "http://")):
                self._send(_worker_setup_page(worker_name, profiles, workdir, executable, "Enter a one-time code and an http(s) Relay URL."), 400)
                return
            try:
                _enroll_worker(invitation, server, config_dir)
            except Exception:
                self._send(_worker_setup_page(worker_name, profiles, workdir, executable, "Pairing failed. Check the code and Relay URL, then try again."), 400)
                return
            self._send("<!doctype html><title>Worker paired</title><h1>Worker paired</h1><p>The local Worker will restart and register automatically. You can return to the browser controller.</p>")
            Thread(target=self.server.shutdown, daemon=True).start()

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


@main.command("worker-run")
@click.option("--name", "worker_name", required=True, help="Local display name for this worker")
@click.option("--profile", "profiles", multiple=True, type=click.Choice(["fixture-shell", "claude-code"]), required=True)
@click.option("--claude-workdir", type=click.Path(path_type=Path), help="Fixed local directory for the claude-code profile")
@click.option("--claude-executable", type=click.Path(path_type=Path), help="Absolute local Claude Code executable path")
@click.option("--poll-seconds", default=0.2, show_default=True, type=click.FloatRange(min=0.05))
@click.option("--pid-file", default="~/.agent-relay/worker.pid", type=click.Path(path_type=Path), show_default=True)
@click.option("--config-dir", type=click.Path(path_type=Path), help="Directory containing .agent-relay.json")
@click.option("--setup-port", default=8765, type=click.IntRange(1024, 65535), show_default=True, help="Local setup page port when this Worker is unpaired")
def worker_run(worker_name, profiles, claude_workdir, claude_executable, poll_seconds, pid_file, config_dir, setup_port):
    """Run one locally configured, gracefully stoppable worker daemon."""
    if "claude-code" in profiles:
        if not claude_workdir or not claude_workdir.is_absolute() or not claude_workdir.is_dir():
            raise click.ClickException("claude-code requires an existing absolute --claude-workdir")
        if not claude_executable or not claude_executable.is_absolute() or not os.access(claude_executable, os.X_OK):
            raise click.ClickException("claude-code requires an executable absolute --claude-executable")
    config_dir = config_dir or Path.cwd()
    try:
        config = load_config(str(config_dir))
    except FileNotFoundError:
        click.echo(f"Worker setup required. Open http://127.0.0.1:{setup_port} on this Mac.")
        _serve_worker_setup(worker_name, profiles, claude_workdir, claude_executable, config_dir, setup_port)
        return
    except KeyError as error:
        raise click.ClickException(str(error)) from error

    pid_file = pid_file.expanduser()
    _write_worker_pid(pid_file)
    client = AgentRelayClient(config["server"], token=config["token"])
    daemon = WorkerDaemon(
        client, config["relay_id"], worker_name, list(profiles),
        profile_workdirs={"claude-code": str(claude_workdir)} if claude_workdir else {},
        profile_executables={"claude-code": str(claude_executable)} if claude_executable else {},
    )
    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def stop_worker(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_worker)
    try:
        worker_id = daemon.start()
        click.echo(f"Worker running: {worker_id}. Press Ctrl-C to stop.")
        while True:
            try:
                daemon.run_once()
            except (AgentRelayError, httpx.HTTPError) as error:
                click.echo(f"Worker transport error: {error}", err=True)
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        click.echo("Stopping worker.")
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        daemon.close()
        client.close()
        if pid_file.exists() and pid_file.read_text().strip() == str(os.getpid()):
            pid_file.unlink()


def _controller_client(config_dir: Path | None):
    try:
        config = load_config(str(config_dir) if config_dir else None)
    except (FileNotFoundError, KeyError) as error:
        raise click.ClickException(str(error)) from error
    return config, AgentRelayClient(config["server"], token=config["token"])


@main.command("browser-pairing-invitation")
@click.option("--expires-in-seconds", default=300, type=click.IntRange(60, 900), show_default=True)
@click.option("--config-dir", type=click.Path(path_type=Path), help="Directory containing .agent-relay.json")
def browser_pairing_invitation(expires_in_seconds, config_dir):
    """Create a one-time browser invitation with controller authority."""
    config, client = _controller_client(config_dir)
    try:
        invitation = client.create_controller_browser_invitation(
            config["relay_id"],
            expires_in_seconds,
        )
        click.echo(invitation["invitation"])
    finally:
        client.close()


@main.command("worker-list")
@click.option("--config-dir", type=click.Path(path_type=Path), help="Directory containing .agent-relay.json")
def worker_list(config_dir):
    """List server-owned worker availability without exposing credentials."""
    config, client = _controller_client(config_dir)
    try:
        for worker in client.list_workers(config["relay_id"]):
            profiles = ",".join(worker["profiles"])
            click.echo(f"{worker['worker_id']}  {worker['status']}  {worker['name']}  [{profiles}]")
    finally:
        client.close()


@main.command("session-list")
@click.option("--config-dir", type=click.Path(path_type=Path), help="Directory containing .agent-relay.json")
def session_list(config_dir):
    """List controller-visible managed sessions."""
    config, client = _controller_client(config_dir)
    try:
        for session in client.list_sessions(config["relay_id"]):
            click.echo(f"{session['session_id']}  {session['status']}  {session['profile']}  v{session['version']}")
    finally:
        client.close()


@main.command("session-start")
@click.argument("worker_id")
@click.argument("profile", type=click.Choice(["fixture-shell", "claude-code"]))
@click.option("--idempotency-key", help="Stable retry key for this session request")
@click.option("--config-dir", type=click.Path(path_type=Path), help="Directory containing .agent-relay.json")
def session_start(worker_id, profile, idempotency_key, config_dir):
    """Request one fixed allowlisted local profile from an online worker."""
    config, client = _controller_client(config_dir)
    try:
        session = client.start_session(config["relay_id"], worker_id, profile, idempotency_key)
        click.echo(f"Requested {session['session_id']} ({session['status']}, v{session['version']})")
    finally:
        client.close()


@main.command("session-claim")
@click.argument("session_id")
@click.option("--version", type=int, required=True, help="Version reported by session-list")
@click.option("--lease-seconds", default=60, type=click.IntRange(10, 300), show_default=True)
@click.option("--config-dir", type=click.Path(path_type=Path), help="Directory containing .agent-relay.json")
def session_claim(session_id, version, lease_seconds, config_dir):
    """Claim a bounded exclusive controller lease for a ready session."""
    config, client = _controller_client(config_dir)
    try:
        session = client.claim_session(config["relay_id"], session_id, version, lease_seconds)
        click.echo(f"Control claimed for {session['session_id']} until {session['lease_expires_at']}")
    finally:
        client.close()


@main.command("session-release")
@click.argument("session_id")
@click.option("--version", type=int, help="Version reported by session-list")
@click.option("--config-dir", type=click.Path(path_type=Path), help="Directory containing .agent-relay.json")
def session_release(session_id, version, config_dir):
    """Release the caller's controller lease."""
    config, client = _controller_client(config_dir)
    try:
        session = client.release_session(config["relay_id"], session_id, version)
        click.echo(f"Control released for {session['session_id']} ({session['status']}, v{session['version']})")
    finally:
        client.close()


@main.command("worker-revoke")
@click.argument("worker_id")
@click.option("--config-dir", type=click.Path(path_type=Path), help="Directory containing .agent-relay.json")
def worker_revoke(worker_id, config_dir):
    """Permanently revoke a worker from this relay."""
    config, client = _controller_client(config_dir)
    try:
        worker = client.revoke_worker(config["relay_id"], worker_id)
        click.echo(f"Revoked {worker['worker_id']} ({worker['name']})")
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
                result = client.wait_for_relay(
                    namespace,
                    agent_name,
                    timeout=timeout,
                    description=description or None,
                    capabilities=capabilities or None,
                )
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
                f" ({agent['status']}){desc_str}{caps_str}"
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
