# Cross-Harness Control Audit

**Date:** 2026-08-28
**Scope:** Read-only audit of the current Agent Relay implementation before designing cross-harness control.
**Status:** Decision input; no production architecture decision or implementation yet.

## Executive conclusion

Cross-harness control can become a primary Agent Relay use case without replacing the existing turn-governed relay. The current codebase supplies reusable identity, pairing, idempotency, optimistic-concurrency, transactional-outbox, presence, SDK/CLI, and MCP foundations.

However, Agent Relay does not yet have a worker, harness-session, control-lease, task, ordered execution-event, artifact, approval, or durable cursor domain. A worker daemon and its initial managed-subprocess adapter are net-new.

**Recommended seam:** keep `Relay` as the authenticated coordination envelope; add a small task-control aggregate beneath it. Do not repurpose `Message` as a command bus or use the legacy agent registry as the authorization boundary.

## Verified reusable foundations

| Foundation | Evidence | Reuse for control plane |
|---|---|---|
| Participant identity | `backend/app/models.py` (`AgentToken`); `backend/app/auth.py`; `backend/app/routes/messages.py` | Derive controller and worker identities from bearer credentials. |
| Named pairing | `backend/app/models.py` (`PairingInvitation`); `backend/app/routes/relays.py` | Pair worker-side participants through creator-issued, expiring, single-use invitations. |
| Versioned state | `Relay.version` in `backend/app/models.py`; CAS in `backend/app/routes/messages.py` | Apply the same compare-and-swap pattern to task and control-session state. |
| Idempotent commands | Message uniqueness constraint and retry handling in `backend/app/models.py` and `backend/app/routes/messages.py` | Scope task creation and transition retries to authenticated actor and idempotency key. |
| Atomic commit pattern | Message append, turn update, relay CAS, and webhook outbox enqueue in `backend/app/routes/messages.py` | Commit task transition, event append, lease update, and outbox record as one transaction. |
| Durable delivery pattern | `WebhookOutbox` and `WebhookService` | Reuse lease, retry, and outbox patterns for post-commit control-event publication. |
| Presence | `AgentPresence`, relay heartbeat routes, and tests | Reuse participant liveness ideas; add worker/session-specific liveness separately. |
| Recovery boundary | `docs/reliability-boundaries.md`; HTTP history/listen; best-effort WebSocket/SSE | Treat persisted task/event reads as authoritative; live updates are acceleration only. |
| Agent integration | Python SDK, Click CLI, and stdio MCP server | Add task/worker/session operations through the established adapters after the native control model is stable. |

## Existing boundaries that must not be reused incorrectly

### Legacy registry

`AgentRegistration` provides namespace discovery and profile metadata, but it is not an authenticated worker directory. Its enrollment path is disabled by default behind `ALLOW_UNAUTHENTICATED_REGISTRY_ENROLLMENT`; read endpoints do not provide the private, capability-scoped authorization model required for harness control.

### Message transcript

`Message.data` can hold JSON, but a message has no task ownership, lease, terminal state, replayable execution-event contract, artifact identity, or bounded operation policy. Messages may notify about work; they must not become the authoritative execution state machine.

### Live streams

The WebSocket manager and SSE spectator path are process-local and best effort. They cannot be the recovery source for a restarted controller or worker.

## Missing control-plane domain

```text
Worker
  Authenticated machine-side process that advertises controlled capabilities.

HarnessSession
  A managed or adopted local runtime owned by one worker.

ControlTask
  Bounded requested work with controller, target session, state, version,
  idempotency, lease, timestamps, and terminal outcome.

ControlEvent
  Append-only, ordered task event used for audit and cursor replay.

TaskArtifact
  Durable evidence reference with producer, media type, integrity metadata,
  and optional validation status.

Approval
  A paused task state with an allowed responder and an audited outcome.
```

## Recommended first state machine

```text
requested
  -> queued
  -> claimed       (worker owns short-lived lease)
  -> running
  -> succeeded | failed | cancelled | rejected

claimed/running
  -> queued        (service expires lease or authorized release/reassignment)
  -> cancelled
```

Every accepted transition must atomically:

```text
authenticate actor
→ validate task version, ACL, state, and lease
→ append ControlEvent
→ update ControlTask state/version/lease
→ enqueue post-commit notification work
→ commit once
```

Terminal tasks remain immutable. An explicit retry creates a new attempt rather than silently reopening history.

## Baseline verification

An isolated temporary Python environment was used; the repository checkout was not modified. The only repository-local change remains the pre-existing untracked `docs/cross-harness-control-problem-brief.md`.

| Surface | Result |
|---|---|
| Backend | `253 passed` |
| SDK | `40 passed`, with one Click deprecation warning |
| MCP | `29 passed` when pinned to MCP 1.x |
| Frontend | `60 passed`; lint and production build passed |

### Packaging finding

`mcp-server/pyproject.toml` allows `mcp>=1.0.0`, but the implementation imports the MCP 1.x `FastMCP` API. A fresh environment selected MCP 2.x and failed at test collection because `mcp.server.fastmcp` is no longer available. Pinning `mcp<2` restored the suite. This is a pre-existing dependency compatibility finding, not part of the control-plane implementation.

## Required test additions for the control slice

- Two independent database sessions concurrently claim the same harness session; exactly one succeeds.
- A stale claim or stale transition returns conflict without appending an event.
- Repeating the same task submission key returns the original task and does not start duplicate work.
- Task state, event append, and outbox record roll back together.
- Controller cursor replay produces neither gaps nor duplicate durable events after reconnect.
- A worker restart produces an honest recoverable state, never a falsely succeeded task.
- Unauthorized discovery, claim, submission, event read, and approval are rejected.
- Migration tests cover a fresh database, an existing `create_all` database, upgrade, and rollback.
- Postgres integration tests validate leases and contention with separate connections.

## Architecture recommendation to review

1. Add `ControlTask`, `ControlEvent`, and `TaskArtifact` beneath `Relay` in the current backend.
2. Add a worker enrollment/heartbeat handshake bound to an existing authenticated relay participant; do not extend the unauthenticated legacy registry.
3. Start with a worker-owned **managed subprocess** adapter for one repository-scoped, read-only inspection operation.
4. Use HTTP reads and cursor-based task-event history as the recovery source of truth. Add WebSocket/SSE task updates only after transaction commit.
5. Defer tmux adoption and native harness adapters until the task/control contract is proved.
6. Expose the native model through SDK, CLI, and MCP after the backend contract and tests are stable.

## Decision needed before implementation

Approve or revise this first-slice boundary:

> Implement a local two-worker control-task vertical slice using authenticated worker enrollment, managed subprocess sessions, task leases, ordered events, cursor replay, and one allowlisted read-only repository-inspection operation. Defer tmux, interactive terminal control, work-machine access, and external multi-tenancy.
