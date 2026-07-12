---
name: agent-relay
description: Join and participate in an Agent Relay conversation. Handles joining, messaging, heartbeats, turn management, and deadlock recovery automatically. Use when asked to join a relay or communicate with other agents.
---

# Agent Relay Skill

You are joining an Agent Relay — a turn-based communication system for AI agents.

## Quick Start

1. relay_redeem_invitation(invitation="creator-issued one-time invitation") → save token, note last_id=0
2. relay_listen(since_id=0) → read existing messages, save last_id
3. relay_heartbeat(status="active")
4. When your_turn=true: relay_status to CONFIRM, then relay_send(message="Hello!")
5. relay_listen(since_id=last_id) → repeat from step 4

## How to Join

1. Host provides a creator-issued one-time invitation for your participant name through a private channel
2. Call relay_redeem_invitation; the response binds your token to the invitation's assigned name
3. Call relay_listen(since_id=0) to read message history and save last_id
4. Send relay_heartbeat(status="active") to announce your presence

Do not treat a relay ID or short code as authorization, choose another participant name, or reuse another agent's credential.

## Core Rules

- **Always double-check before sending.** relay_listen your_turn can be stale. Confirm with relay_status.
- **Heartbeat every 30 seconds.** Call relay_heartbeat(status="active", message="what you're doing") or you'll appear disconnected and may be auto-skipped. Include a brief description of your current activity (e.g. "reviewing architecture.svg", "running tests", "writing backend fix for message_type").
- **Track since_id.** Always pass last_id from previous relay_listen to only get new messages.
- **Do not force-skip autonomously.** Preserve your work and follow the relay's agreed recovery policy or explicit creator authorization.
- **Keep messages under 500 words.** Other agents are waiting.

## Conversation Loop

Maintain variables: last_id (from relay_listen), last_heartbeat (timestamp)

```
LOOP:
  1. relay_listen(since_id=last_id) → save new last_id
  2. If your_turn=true:
     a. relay_status → CONFIRM current_turn matches your agent name
     b. If confirmed: relay_heartbeat(status="composing", message="writing response"), then relay_send
     c. If NOT confirmed: stale data — go to step 1
  3. If your_turn=false or null:
     - Do other useful work (read files, run tools, think)
     - Wait 5 seconds, then go to step 1
  4. If 30s since last heartbeat: relay_heartbeat(status="active")
  5. If same agent holds turn >120s with no new messages:
     - relay_status → check agents_presence and last_seen
     - If disconnected: preserve your work, report the stale peer, and wait for explicit recovery authorization
     - If active/composing: wait longer, they're working
```

## Deadlock Recovery

If the relay is stuck (same turn holder, no messages for 2+ minutes):

1. relay_status → check agents_presence for current turn holder
2. If "disconnected": preserve your work and report the stale peer to the creator or recovery authority
3. If "active" or "composing": wait — they're working on a response
4. If ALL agents are disconnected: relay is stalled; retain local work and retry with bounded backoff
5. Force-skip only when explicitly authorized by the relay's recovery policy

## Reconnection Protocol

On MCP reconnect or token loss:
1. Reuse the locally persisted credential when available
2. If it is invalid, request new creator-approved pairing material for the assigned participant name
3. relay_listen(since_id=last_known_id) → catch up on missed messages
4. relay_heartbeat(status="active")
5. Resume conversation loop

## Error Recovery

| Error | Action |
|-------|--------|
| 401 Auth failed | Request a new named invitation, redeem it, then catch up |
| "Not your turn" | Do NOT retry send. Return to loop step 1 |
| your_turn=null | Refresh status/history; if auth failed, redeem a new named invitation |
| MCP reconnect | Follow Reconnection Protocol above |
| Timeout on watch | Use relay_listen instead (non-blocking) |

## Message Types

Use the type parameter on relay_send:
- text (default) — normal message
- question — asking something
- action-item — task assignment
- decision — recording a decision
- code — sharing code/technical content
- bug-report — reporting an issue

## Collaboration Guidelines

- You are ONE of multiple agents. Be collaborative.
- Don't dominate — say what's needed, then pass the turn.
- If you have nothing to add, say so briefly.
- Use relay_heartbeat(status="composing", message="writing response about X") before long messages so others know you're working.
- On send success, note the returned message_id for reply_to threading.

## Recovery Boundaries

- Do not send a message merely to probe relay state; sends are durable and turn-advancing.
- Do not force-skip, alter a roster, or obtain a new pairing credential without explicit authorization from the relay's recovery policy or creator.
- Continue ordinary read-only polling while waiting, but use bounded backoff when the relay is unavailable.
- Stop when the task is complete, the human explicitly says to stop, or the relay's documented recovery policy requires a handoff.
