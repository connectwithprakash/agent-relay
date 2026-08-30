# Cross-Harness Control Problem Brief

## Leadership question

What is the smallest durable extension that lets one authenticated harness discover, invoke, observe, and recover work performed by another harness on a different approved machine, without turning Agent Relay into unrestricted remote shell access?

## Desired outcome

A source-backed decision on whether Agent Relay should add a worker and control-session domain, plus a narrow local proving slice that validates the riskiest parts of the model.

This project is personal Agent Relay work. It is not a claim about any employer's platform roadmap or architecture.

## Why this work

Agent Relay currently coordinates peers through turn-governed messages. That is useful for communication, but it cannot represent or control a live harness runtime. A controller cannot discover a specific running harness session, claim exclusive input ownership, submit a bounded task, observe durable progress, respond to a request for approval, or resume from a cursor after reconnecting.

## Existing assets to preserve

The first slice should build on existing relay guarantees rather than duplicate them.

- Named participant pairing uses creator-issued, single-use, expiring invitations; server-side credentials are stored as token hashes. See `backend/app/routes/relays.py` and `backend/app/models.py`.
- Message commands authenticate the participant from the bearer credential, use an idempotency key scoped to relay and participant, compare the client `expected_version`, append the message, advance the turn, and commit together. See `backend/app/routes/messages.py`.
- Relay versioning uses a database compare-and-swap to reject stale turn transitions. See `backend/app/services/relay_service.py`.
- Webhook outbox events commit in the same transaction as messages and turn changes; dispatch uses leases, retries, and at-least-once delivery. See `backend/app/services/webhook_service.py` and `docs/reliability-boundaries.md`.
- WebSocket delivery is intentionally best effort after the command commits. Consumers must reconcile authoritative state after reconnect. See `docs/reliability-boundaries.md`.
- The existing registry describes agents, not worker identity or runnable harness sessions. Its unauthenticated enrollment path is disabled by default and must not become the authorization boundary. See `backend/app/routes/registry.py`.

## Missing domain concepts

A control-plane design needs concepts that are absent from the current relay/message model:

```text
Worker          A registered, authenticated machine-side process.
Harness         A runtime type the worker can operate (for example a PTY-backed CLI).
Harness session A local managed or adopted runtime exposed by a worker.
Control session The leased, authenticated relationship granting a controller bounded control.
Task            A bounded unit of requested work with explicit terminal states.
Event           An ordered, replayable record of task or session progress.
Artifact        A result reference: report, patch, test result, file, or URL.
Approval        A paused state requiring a permitted actor to respond.
```

## First proving slice

Run two approved local worker processes against one local Agent Relay server. The controller must be able to:

1. discover an authenticated worker and one advertised harness capability;
2. create or select one managed local session;
3. claim a short-lived lease for that session;
4. submit one read-only, bounded repository-inspection task;
5. receive sequenced progress and one structured result artifact;
6. reconnect with an event cursor and replay everything after that cursor;
7. retry the same submission idempotently without starting the task twice;
8. observe lease expiry or explicit release when the controller disappears.

The initial worker may simulate a harness with a controlled subprocess. A PTY/tmux adapter is a follow-up integration, not a prerequisite for proving the control protocol.

## Explicit non-goals for the first slice

- unrestricted command execution or arbitrary filesystem access;
- public discovery of machines, device identifiers, or sessions;
- operating a work machine or exporting private source material;
- universal support for every coding harness;
- full terminal emulation or byte-for-byte terminal recording;
- a hosted multi-tenant service;
- treating Agent Relay messages as the authoritative execution event log.

## Decisions the proving slice must inform

1. Does control state belong in the current Agent Relay backend or in a separate worker service with a narrower relay integration?
2. Is a managed subprocess sufficient as the universal v1 adapter, with PTY/tmux and native adapters following later?
3. What resource hierarchy should authorization bind: participant -> worker -> project -> harness session -> operation?
4. How should the service implement single-controller ownership: row lock, version compare-and-swap, lease, or a combination?
5. Which events are durable and replayable, and which can remain best-effort live notifications?
6. What does a safe artifact reference contain, and when should content remain local to the worker?

## Success criteria

The slice is successful only when all of these are demonstrated against a running local server and two independently reconnectable clients:

- unauthorized discovery, claim, submission, or private-event reads are rejected;
- exactly one controller holds the session lease at a time;
- a stale claim or command is rejected without appending a task event;
- an idempotent retry returns the original task/submission result;
- task state and event append commit atomically;
- a restarted controller resumes using its cursor without duplicate or missing durable events;
- a worker restart leaves an honest terminal or recoverable state, never a falsely completed task;
- the result includes an observable artifact or execution result;
- the full test suite remains green and the new live flow is exercised independently.

## Initial risks

| Risk | First mitigation |
|---|---|
| Remote control silently becomes arbitrary shell access | Use an allowlisted worker operation with a repository-scoped, read-only first task. |
| A live stream is mistaken for durable state | Make a persisted event sequence and cursor the recovery source of truth. |
| Two controllers send conflicting input | Require a service-owned control lease and compare-and-swap/version checks. |
| A retry starts duplicate work | Scope an idempotency key to the control session and authenticated controller. |
| Existing registry becomes an authorization shortcut | Require authenticated worker enrollment and separate discovery from permission to act. |
| PTY details dominate the first implementation | Prove the task/control contract with a managed subprocess before adding terminal adapters. |

## Next action

Audit the current repository's package, migration, test, SDK, and MCP seams. Then write an implementation plan for the smallest local control-session vertical slice.
