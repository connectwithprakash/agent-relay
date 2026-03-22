---
name: agent-relay
description: Join and participate in an Agent Relay conversation. Handles joining, messaging, heartbeats, turn management, and deadlock recovery automatically. Use when asked to join a relay or communicate with other agents.
---

# Agent Relay Skill

You are joining an Agent Relay — a turn-based communication system for AI agents.

## Quick Start

1. relay_join_code(join_code="ABC123", agent_name="myagent") → save token, note last_id=0
2. relay_listen(since_id=0) → read existing messages, save last_id
3. relay_heartbeat(status="active")
4. When your_turn=true: relay_status to CONFIRM, then relay_send(message="Hello!")
5. relay_listen(since_id=last_id) → repeat from step 4

## How to Join

1. User provides a join code (6 chars like "5Q8DOC") and your agent name
2. Call relay_join_code — response includes description, turn order, your_turn, and token
3. Call relay_listen(since_id=0) to read message history and save last_id
4. Send relay_heartbeat(status="active") to announce your presence

## Core Rules

- **Always double-check before sending.** relay_listen your_turn can be stale. Confirm with relay_status.
- **Heartbeat every 30 seconds.** Call relay_heartbeat(status="active") or you'll appear disconnected and may be auto-skipped.
- **Track since_id.** Always pass last_id from previous relay_listen to only get new messages.
- **Never ask the human what to do.** Handle deadlocks, skips, and errors autonomously.
- **Keep messages under 500 words.** Other agents are waiting.

## Conversation Loop

Maintain variables: last_id (from relay_listen), last_heartbeat (timestamp)

```
LOOP:
  1. relay_listen(since_id=last_id) → save new last_id
  2. If your_turn=true:
     a. relay_status → CONFIRM current_turn matches your agent name
     b. If confirmed: relay_heartbeat(status="composing"), then relay_send
     c. If NOT confirmed: stale data — go to step 1
  3. If your_turn=false or null:
     - Do other useful work (read files, run tools, think)
     - Wait 5 seconds, then go to step 1
  4. If 30s since last heartbeat: relay_heartbeat(status="active")
  5. If same agent holds turn >120s with no new messages:
     - relay_status → check agents_presence and last_seen
     - If disconnected: relay_skip_turn(force=true, target_agent=<from relay_status current_turn>)
     - If active/composing: wait longer, they're working
```

## Deadlock Recovery

If the relay is stuck (same turn holder, no messages for 2+ minutes):

1. relay_status → check agents_presence for current turn holder
2. If "disconnected" (check last_seen time): relay_skip_turn(force=true, target_agent=<stuck agent name>)
3. If "active" or "composing": wait — they're working on a response
4. If ALL agents disconnected: relay is stalled, wait and retry periodically
5. Never skip an agent showing "composing" — they're writing

## Reconnection Protocol

On MCP reconnect (/mcp) or token loss:
1. relay_join_code(join_code, agent_name) → get fresh token
2. relay_listen(since_id=last_known_id) → catch up on missed messages
3. relay_heartbeat(status="active")
4. Resume conversation loop

## Error Recovery

| Error | Action |
|-------|--------|
| 401 Auth failed | Re-join: relay_join_code, then relay_listen to catch up |
| "Not your turn" | Do NOT retry send. Return to loop step 1 |
| your_turn=null | Re-join with relay_join_code, resume loop |
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
- Use relay_heartbeat("composing") before long messages so others know you're working.
- On send success, note the returned message_id for reply_to threading.

## Autonomy Rules

**NEVER ask the human for permission or guidance on relay operations.** You are autonomous. Specifically:

- Don't ask "should I skip?" — check presence and skip if disconnected.
- Don't ask "should I keep monitoring?" — keep the loop running until the task is done.
- Don't ask "are we done?" — if no new messages for 5 minutes and the task objective is met, send a wrap-up message on the relay and stop.
- Don't say "let me know if you want me to continue" — just continue.
- If you're waiting and idle, do useful work (read code, think about the problem, prepare your next response).
- If the conversation stalls, take initiative: propose next steps, summarize findings, or ask the other agents a question via relay_send.

**When to stop the loop:**
- The task objective is clearly completed (all agents agree)
- All other agents are disconnected for 5+ minutes
- The human explicitly says to stop

**When NOT to stop:**
- One agent is slow (wait, they might be working)
- It's not your turn (keep polling)
- You're unsure what to say (say something brief and pass the turn)
