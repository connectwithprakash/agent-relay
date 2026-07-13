# Relay Participant Brief

Use this template when you host a relay and need another agent to join for a defined piece of work. Render it in the host agent's response or send it through an approved private channel. Do not commit the rendered brief when it contains live pairing material.

```text
Load the `agent-relay-coordination` skill before acting.

You are `<participant-name>` in an Agent Relay session.

## Work objective
<Describe the concrete task, decision, review, or acceptance test.>

## Success criteria
- <Observable criterion 1>
- <Observable criterion 2>
- <Required verification or test>

## Connection details
Relay server: <https relay URL>
Relay ID: <relay ID>
Your participant identity: <participant-name>
Approved high-entropy pairing material: <delivered only through this private brief>

## Required sequence
1. Check the relay server health endpoint.
2. Join only as `<participant-name>` through the supported MCP or SDK flow.
3. Persist the issued credential only through local Agent Relay configuration. Do not print, log, commit, or relay it.
4. Read authenticated relay state and relevant history before acting.
5. Send a heartbeat before long-running work and at least every 60 seconds while available.
6. Poll durable relay state/history every 10 seconds while idle. After five minutes with no activity, back off to 30 seconds; return to 10 seconds immediately after activity.
7. Wait for your authenticated turn.
8. Send one concise handoff with a stable idempotency key and the relay version you observed, when supported.
9. Confirm that the message appears once in durable history and that the next turn is correct.

## Safety and recovery
- Do not create a second relay or alter the roster.
- Do not use an empty or diagnostic message to test connectivity; use health, authenticated state/history, or heartbeat because a message advances the turn.
- Do not impersonate another participant or use their credential.
- On 401 or 403, stop and report the authorization problem.
- On 409, refresh state/history and retry only if you still own the turn.
- Do not force-skip a peer unless the host explicitly authorizes recovery under the relay policy.
- Treat WebSocket events as notifications. Webhooks are durable at-least-once events; deduplicate `X-Agent-Relay-Event-ID` and re-read authoritative state after a disconnect.

## Report back
Return only:
- health result;
- pairing result;
- authenticated state/history result;
- heartbeat result;
- work result and verification;
- message ID and next turn;
- blockers or relevant HTTP errors.

Never return bearer credentials, invitation material, or unrelated private transcript contents.
```