# Worker Service Runbook

## Safety boundaries

The worker accepts only the fixed `claude-code` profile, the fixed local workdir, and the fixed local executable in the prepared plist. Relay requests select a profile only; they never supply a command, executable, or path. The credential remains in the owner-only `/Users/bodhi/agent-relay-service/.agent-relay.json`; do not put it in a plist, log, shell history, or ticket.

Workers report `online`, `offline`, or `revoked`. The server marks an online worker offline when its persisted `last_seen` exceeds `worker_stale_seconds` (90 seconds by default), releases any lease, and detaches sessions. A successful heartbeat or re-registration recovers that worker to `online`; detached sessions are not resurrected, so request a new session after recovery. A revoked worker cannot recover.

## One-shot local run

```bash
PYTHONPATH=/Users/bodhi/Developer/agent-relay/sdk/src \
/Users/bodhi/Developer/agent-relay/backend/.venv/bin/python -c \
  'from agent_relay.cli import main; main()' worker-run \
  --name "Work Mac Claude service" \
  --profile claude-code \
  --claude-workdir /Users/bodhi/Developer/agent-relay \
  --claude-executable /Users/bodhi/.local/bin/claude \
  --config-dir /Users/bodhi/agent-relay-service
```

The command writes `~/.agent-relay/worker.pid` with mode `0600`. Stop only its owned PTYs with:

```bash
kill -INT "$(cat ~/.agent-relay/worker.pid)"
```

## Prepared LaunchAgent (not loaded)

`scripts/com.prakash.agent-relay-worker.plist` is a deliberately inactive template: `RunAtLoad` and `KeepAlive` are false. It uses the collision-free label `com.prakash.agent-relay-worker`, fixed local paths, and no credential values.

Before manually installing it, verify the explicit paths and owner-only credential directory:

```bash
plutil -lint scripts/com.prakash.agent-relay-worker.plist
stat -f '%Sp %N' /Users/bodhi/agent-relay-service/.agent-relay.json
```

If an operator deliberately chooses to install it later, copy it to `~/Library/LaunchAgents/` and use `launchctl bootstrap gui/$(id -u)` with that copied path. This task does **not** install, bootstrap, load, or enable the service.

## Controller lifecycle commands

All commands use the configured relay credential and do not print it:

```bash
agent-relay worker-list --config-dir /Users/bodhi/agent-relay-service
agent-relay session-list --config-dir /Users/bodhi/agent-relay-service
agent-relay session-start WORKER_ID claude-code --idempotency-key local-start-1 --config-dir /Users/bodhi/agent-relay-service
agent-relay session-claim SESSION_ID --version VERSION --config-dir /Users/bodhi/agent-relay-service
agent-relay session-release SESSION_ID --version VERSION --config-dir /Users/bodhi/agent-relay-service
agent-relay worker-revoke WORKER_ID --config-dir /Users/bodhi/agent-relay-service
```

Use `worker-list` before requesting a session. Only `online` workers may start or accept input. Revocation is permanent for that worker record.
