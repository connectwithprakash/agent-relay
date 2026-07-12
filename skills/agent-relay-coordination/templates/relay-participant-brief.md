# Relay Participant Brief

Use this template when you host a relay and need another agent to join for a defined piece of work. Render it in the host agent's response or send it through an approved private channel. Do not commit the rendered brief when it contains a live invitation.

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
One-time invitation: <invitation secret delivered only through this private brief>

## Required sequence
1. Check the relay server health endpoint.
2. Redeem the invitation only as `<participant-name>`.
3. Persist the issued credential only through local Agent Relay configuration. Do not print, log, commit, or relay it.
4. Read authenticated relay state and relevant history before acting.
5. Send a heartbeat before long-running work.
6. Wait for your authenticated turn.
7. Send one concise handoff with a stable idempotency key and the relay version you observed, when supported.
8. Confirm that the message appears once in durable history and that the next turn is correct.

## Safety and recovery
- Do not create a second relay or alter the roster.
- Do not impersonate another participant or use their credential.
- On 401 or 403, stop and report the authorization problem.
- On 409, refresh state/history and retry only if you still own the turn.
- Do not force-skip a peer unless the host explicitly authorizes recovery under the relay policy.
- Treat WebSocket and webhook events as notifications; re-read durable state after a disconnect.

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