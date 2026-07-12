# Reliable Agent Relay Core Implementation Plan

> **For Hermes:** Execute this plan with the `subagent-driven-development` workflow: implement one task at a time, then perform specification and quality review before advancing.

**Goal:** Make Agent Relay safe and reliable enough for two authenticated agents on separate laptops to coordinate a bounded task through a durable relay.

**Architecture:** Preserve Agent Relay’s REST/MCP/SDK product shape, but make the backend’s database the sole authority for identity, message append, turn ownership, and idempotency. A command appends a message and advances the relay version in one transaction. Invitations mint a participant credential exactly once; credentials are stored only as hashes. The existing real-time and webhook surfaces remain non-authoritative until a later transactional-outbox release.

**Tech stack:** FastAPI, SQLAlchemy 2, Alembic, SQLite for local/integration tests, PostgreSQL-ready optimistic concurrency, pytest/httpx.

## Scope and non-goals

**This release includes**

- Atomic relay + creator credential creation.
- Cryptographically strong, expiring pairing invitations that mint a credential for a named pre-authorized participant.
- Hash-only persisted credentials, participant-bound authentication, and authenticated heartbeat/message/skip access.
- A relay `version` compare-and-swap update, atomic message append + turn advancement, and scoped DB-enforced idempotency.
- Correct, reproducible test environments and HTTP-level security/concurrency regression tests.
- SDK/CLI/MCP configuration fixes that preserve usable credentials safely with owner-only files.

**This release deliberately excludes**

- A2A facade (follow-up after the core contract stabilizes).
- NATS/JetStream and Temporal.
- Durable webhook outbox/workers (existing webhooks are demoted from a reliability claim until the next release).
- A general task state machine beyond typed messages and turn ownership.
- Frontend redesign.

## Model

```text
Agent credential (raw, client-only)
    -> SHA-256 hash stored in AgentToken
    -> authenticated participant identity
    -> command carries expected relay version + idempotency key
    -> DB transaction validates participant + current turn + version
    -> append Message + advance Relay.version/current_turn
    -> commit once
```

## Checklist

- [ ] 1. Repair the backend test/dependency contract and add HTTP integration harness.
- [ ] 2. Add schema/migration support for hashed tokens, invitation state, relay version, and scoped idempotency.
- [ ] 3. Make relay creation atomic and credentials hash-only; add create/send regression.
- [ ] 4. Replace implicit join-code identity with a participant-bound pairing flow and enforce route authorization.
- [ ] 5. Make message append/turn advance/idempotency atomic with optimistic concurrency.
- [ ] 6. Fix SDK, CLI, and MCP credential/session behavior and documentation.
- [ ] 7. Explicitly demote webhooks from the reliable contract; add a follow-up boundary/documentation.
- [ ] 8. Run backend, SDK, MCP, migration, and live HTTP verification; review; commit and push.

## Acceptance criteria

1. A created relay’s creator can immediately authenticate and send its first message.
2. A pairing invitation can mint one credential only for an approved participant; it cannot alter the roster or impersonate another agent.
3. Raw credentials never persist in the database or a default repo-local config file.
4. Heartbeat, skip, message, and private reads derive identity from authentication, not request parameters or `owner_id` query strings.
5. A stale expected version is rejected without appending a message; retry with the same scoped idempotency key returns the original response.
6. A message and turn/version state cannot be committed independently.
7. The full supported test suite is reproducible and green, and a live HTTP scenario verifies the complete two-agent flow.
