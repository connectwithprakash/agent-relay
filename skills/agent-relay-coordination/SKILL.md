---
name: agent-relay-coordination
description: Create, join, operate, and recover authenticated Agent Relay sessions for peer agents working across tools, sessions, or machines.
---

# Agent Relay Coordination

Use this skill when an agent needs to create or join an Agent Relay, coordinate a peer handoff, resume a relay session, use the Agent Relay MCP server or SDK, or recover from a relay failure.

## Outcome

Operate a relay as a durable coordination protocol, not as an informal chat channel:

```text
authenticated participant
→ observes relay version and current turn
→ sends one idempotent command when authorized
→ records a durable transcript and advances the turn
```

## Before starting

1. Identify the relay server URL. Prefer an explicitly configured HTTPS URL for cross-device work.
2. Check server health before creating or joining a session.
3. Never put raw credentials in a relay message, source file, terminal transcript intended for sharing, or commit.
4. Use the configured Agent Relay MCP server or SDK where available. Do not invent REST payload fields from memory.
5. Treat the server's durable relay state as authoritative after any restart, not local session memory.

## Start or join a session

### Participant identity

Every agent must use one stable participant name for a relay session. Prefer, in order:

1. an explicit name in the host's participant brief;
2. `AGENT_RELAY_AGENT` when the local environment provides it;
3. a locally derived candidate such as a sanitized `hostname -s` plus a role suffix.

A fallback name is only a proposed identity. Report it to the host and wait for a roster entry and approved pairing material for that exact name; never add yourself or choose a different name while joining. Persist the accepted participant name alongside the local credential so restarts resume as the same participant.

### Create a relay

Use the MCP `relay_create` tool, SDK, CLI, or documented API. Supply the complete intended participant roster at creation time.

- The creator receives a credential once. Store it only in the local Agent Relay config managed by the SDK/MCP server.
- For private work, keep the relay private and do not publish relay IDs, pairing material, or participant names in public artifacts.
- Pair named participants through creator-authorized invitations when supported. A relay ID or public discovery capability is not authorization.

### Join a relay

1. Obtain a creator-issued, one-time invitation for your exact participant name through a secure channel.
2. Redeem it with MCP `relay_redeem_invitation`, SDK `redeem_invitation`, or CLI `join-invitation`.
3. Persist the returned credential using the SDK/MCP config flow; those clients use atomic owner-only files.
4. Read state and history before sending any message.

Use relay-wide compatibility pairing material only for legacy deployments that do not expose invitations. It is not participant-bound and must not be the normal private-relay workflow.

## Normal coordination loop

1. Send a heartbeat before and during long work.
2. Read state and relevant transcript history.
3. Determine whether it is your turn from authenticated relay state.
4. Work locally while waiting; do not create empty messages.
5. Stay available while the relay is active: poll durable relay state/history every 10 seconds when idle and send a heartbeat at least every 60 seconds. After five minutes with no activity, back off polling to 30 seconds; reset to 10 seconds immediately when activity appears. Never rely only on WebSocket/webhook notifications after a disconnect or restart.
6. When it is your turn, send a concise handoff with:
   - result or decision;
   - relevant paths, commands, tests, or blockers;
   - a stable idempotency key for retry safety;
   - the relay version you observed, when the client exposes it.
6. Confirm the response shows the expected next turn before assuming handoff completed.

## Request outcomes and recovery

| Signal | Meaning | Correct action |
|---|---|---|
| `401` | Missing or invalid credential | Stop retrying. Reconfigure or obtain a new credential. |
| `403` | Authenticated but not authorized | Do not bypass it. Report the participant/roster mismatch. |
| `409` | Relay state changed or command is stale | Refresh state/history, reassess turn ownership, then retry only if still appropriate. |
| Existing idempotency result | A prior equivalent command was accepted | Use that result; do not send a duplicate message. |
| Invitation expired or redeemed | Pairing material is no longer valid | Ask the creator for a new invitation. |
| Peer absent | Presence is stale or disconnected | Preserve your work; apply any force-skip policy only with explicit authorization. |
| Server unavailable | Relay cannot accept commands | Keep local work durable and use bounded retry/backoff. |

## Safety rules

- A caller-supplied agent name is descriptive only; authenticated identity controls authorization.
- Never use a message send to diagnose. Sending a message is a durable, turn-advancing, peer-visible action, not a probe — there is no dry run. A "test" or "probe" send consumes your turn, appears in the peer's transcript, and cannot be recalled. Determine turn and version from a read-only source (e.g. the instructions/state endpoint or authenticated history) before ever posting; verify the message contract from documented schemas, not by trial send.
- Do not force-skip a peer merely to unblock yourself. Follow the relay's agreed recovery policy and creator permissions.
- WebSocket and webhook notifications are convenience signals. Re-read durable relay state after disconnects or restarts.
- Do not claim a notification was delivered unless the relay's documented delivery semantics guarantee it.
- Do not use short shared codes as durable authorization secrets.

## Invite another participant

When hosting a relay for another agent, create a named invitation with MCP `relay_create_invitation`, SDK `create_invitation`, or the CLI create flow. Render `templates/relay-participant-brief.md` with the concrete work objective, success criteria, HTTPS relay URL, relay ID, named participant identity, and that one-time invitation. Send it only through an approved private channel; never commit live pairing material.

## Completion handoff

Before ending a relay session:

1. Send the smallest useful durable handoff if it is your turn.
2. Include what changed, verification performed, remaining blockers, and the intended next actor.
3. Leave the relay state intact. Do not delete credentials, messages, or pairing records as cleanup.
4. If the work is human-visible, also record the result in its appropriate project artifact; a relay transcript is coordination evidence, not the sole project record.

## Verification checklist

Before claiming a relay workflow succeeded, verify:

- server health was reachable;
- the relay state identifies the expected participants and current turn;
- your credential can read the required private state;
- your message appears once in the durable history;
- the next turn changed as expected;
- no credential appeared in output or version control.
