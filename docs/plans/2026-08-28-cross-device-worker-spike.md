# Cross-Device Managed Harness Session Spike Plan

> **For Hermes:** Implement the worker-control core incrementally, with a real two-machine managed-terminal proof before adopting existing sessions.

**Goal:** Prove that a controller can pair and discover a trusted worker on another user-owned machine, start a named managed harness session, send terminal input, observe terminal output, recover after disconnection, and release exclusive input control without SSH or inbound worker ports.

**Architecture:** Reuse Agent Relay's named, single-use participant invitation and token hashing for initial identity only. Add a distinct worker-control domain for worker capabilities, managed harness sessions, ordered events, and exclusive control leases; a worker on the second machine makes authenticated outbound calls to the relay. The initial adapter creates a new, named managed PTY session for an explicitly approved harness command. It does not adopt an arbitrary existing terminal or tmux session. tmux adoption and native harness adapters are later compatibility/fidelity layers.

**Tech stack:** FastAPI, SQLAlchemy, Alembic, existing Python SDK/CLI, durable HTTP commands/events for identity and lease transitions, an outbound authenticated WebSocket for low-latency terminal input/output, and the existing React behavior prototype.

**Network requirement:** The completed product must work across different networks. Controller and worker both connect outward to a reachable HTTPS/WSS Relay service; a fixed IP address, inbound worker listener, SSH route, port forwarding, or shared Wi-Fi are never prerequisites. Tailscale is acceptable only as a private development/self-hosted transport.

---

## Product and safety contract

### First real workflow

```text
Controller laptop
  → discovers an already-paired worker
  → selects an available named harness session
  → requests temporary exclusive input control
  → sends a prompt / terminal input
  → sees sequenced output and session state
  → disconnects, reconnects, and releases control
```

### Explicit non-goals for this spike

- no adoption of an existing tmux or terminal session;
- no arbitrary command or arbitrary path execution after session start;
- no access to a work repository, work credentials, or local secret files;
- no public inbound port on the worker laptop;
- no use of the legacy unauthenticated registry as an authorization boundary;
- no deployment of unreviewed control code to a shared/production relay.

### Local policy

The worker starts only a controller-approved, named harness command from an allowlist, initially a dedicated Claude Code/Codex/Hermes session or a harmless terminal fixture. The worker records the command identity, working directory, PID/PTY ownership, and capability level. After session start, the active lease holder may send terminal bytes to that owned PTY; no other controller may do so. The worker never adopts a process merely because its PID or tmux name was supplied remotely.

### User actions required later

1. Choose a **user-owned personal machine** as the worker—not an employer-managed device—and have its terminal available during the live proof.
2. Choose a named harness command to demonstrate on that machine. Start with a harmless fixture shell or an approved personal Claude Code/Codex session; a Git repository is optional session context, not a prerequisite.
3. Confirm which relay reachability mode to use:
   - an existing HTTPS development/staging Relay endpoint, preferred; or
   - a temporary same-LAN development server for a one-session proof.
4. On the worker, paste one one-time pairing command only after reviewing it locally. Do not paste relay tokens, API keys, or credential-file contents into chat.

No SSH credentials, port forwarding, copied `.env` files, work credentials, or permanent remote-access permissions are needed.

---

## Impact map

- **Authentication:** `backend/app/auth.py` authenticates relay participants. Worker identity must be bound to the authenticated participant token; request bodies must never choose the worker identity.
- **Pairing:** `backend/app/routes/relays.py` already mints/redeems one-time named invitations. Reuse it for initial participant pairing; do not make invitations task credentials.
- **Data model:** `backend/app/models.py` and the Alembic head must gain separate worker/task/event/artifact tables. The message and turn model stays unchanged.
- **Delivery:** existing WebSocket broadcast is best effort and message-shaped. The spike uses durable reads/events as truth; live UI notifications may remain a later adapter.
- **SDK/CLI:** `sdk/src/agent_relay/cli.py` is the right home for controller and worker commands. The worker must persist its token in a user-only configuration location, not `.agent-relay.json` in a repository.
- **Frontend:** `frontend/src/pages/ControlDemoPage.jsx` remains mock-only until the backend contract is proven. It must not be wired to a half-complete control API.
- **Migrations:** this repository has Alembic migrations through revision `013`; add an upgrade/downgrade-tested revision rather than relying on development `Base.metadata.create_all`.

---

## Build sequence

### Task 1: Write the authoritative spike contract and test matrix

**Objective:** Freeze the exact narrow operation, actors, authorization boundaries, and pass/fail criteria before schema work.

**Files:**
- Create: `docs/cross-device-worker-spike-contract.md`
- Test: manual two-machine runbook embedded in the same file

**Steps:**
1. Define controller participant, worker participant, worker record, harness session, control lease, event, and session snapshot.
2. State the allowed session-start commands and exact rejected attach/start requests.
3. Define session states: `starting`, `ready`, `controlled`, `detached`, `exited`, `failed`, `revoked`.
4. Define failure checks: duplicate start, unpaired worker, competing controller, stale lease, worker restart, controller reconnect, and revoked worker.
5. Require a local-only test database and a separate non-production live proof.

**Verification:** The contract answers who authenticates, who authorizes, which state is durable, and what proves completion.

### Task 2: Add worker-control persistence through an Alembic migration

**Objective:** Make worker/session/lease/event state independent of turn-based messages.

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/014_add_worker_control_core.py`
- Test: `backend/tests/test_migrations.py`

**Steps:**
1. Add `Worker`, `WorkerCapability`, `HarnessSession`, `ControlLease`, and `ControlEvent` models with foreign keys to the relay and authenticated participant names.
2. Add database uniqueness for worker identity per relay, session-start idempotency per authenticated controller, and event sequence per session.
3. Add session version and exclusive control-lease expiry fields; never use in-memory locks as correctness.
4. Write migration upgrade and downgrade behavior.
5. Test migration from revision `013` and a fresh database.

**Verification:** Migration upgrade succeeds, downgrade restores the pre-spike schema, duplicate `(relay, controller, idempotency_key)` session creation cannot create two sessions, and event sequence collisions fail.

### Task 3: Add worker/session/lease/event schemas, repository, and service layer

**Objective:** Put typed durable command transitions behind a small control service.

**Files:**
- Modify: `backend/app/schemas.py`
- Create: `backend/app/repositories/control_repo.py`
- Create: `backend/app/services/control_service.py`
- Test: `backend/tests/test_control_service.py`

**Steps:**
1. Define request/response models with constrained session profiles and idempotency keys.
2. Implement one transaction for each mutation: authenticate, authorize, compare expected version/lease, append event, update state, commit.
3. Implement worker registration, managed-session start, exclusive lease acquisition/release, input append, output append, exit, failure, and revocation checks.
4. Reject unknown operations and invalid state transitions with explicit errors.
5. Write tests for idempotency, stale version, unauthorized worker claim, and terminal-state immutability.

**Verification:** Same-key retry returns the original session; stale and unauthorized commands append no event; session state and event history agree after every test.

### Task 4: Add authenticated controller and worker routes

**Objective:** Expose a narrow session-control contract without mixing it into message routes.

**Files:**
- Create: `backend/app/routes/control.py`
- Modify: `backend/app/routes/__init__.py`
- Test: `backend/tests/test_control_routes.py`

**Routes:**
```text
POST /relays/{relay_id}/workers
GET  /relays/{relay_id}/workers
POST /relays/{relay_id}/sessions
GET  /relays/{relay_id}/sessions/{session_id}
GET  /relays/{relay_id}/sessions/{session_id}/events?after_sequence=
POST /relays/{relay_id}/sessions/{session_id}/claim
POST /relays/{relay_id}/sessions/{session_id}/input
POST /relays/{relay_id}/sessions/{session_id}/events
POST /relays/{relay_id}/sessions/{session_id}/release
POST /relays/{relay_id}/workers/{worker_id}/revoke
```

**Verification:** API tests prove that request-body `worker_id`, session ID, or participant names cannot override the authenticated actor, and that only one valid lease can append input.

### Task 5: Add the managed PTY worker adapter

**Objective:** Start one known, named terminal/harness process on the worker and expose its input/output through durable control events.

**Files:**
- Create: `sdk/src/agent_relay/worker.py`
- Modify: `sdk/src/agent_relay/cli.py`
- Create: `sdk/tests/test_worker.py`

**Steps:**
1. Add `agent-relay worker pair` to redeem an invitation and save credentials under a user-only configuration directory with restrictive permissions.
2. Add `agent-relay worker run` to register capabilities and receive session-start work over its outbound connection.
3. Add a worker-local named session profile allowlist, initially a deterministic terminal fixture and one user-approved harness command. Do not accept a remote command string.
4. Start the selected profile in a managed PTY; persist only metadata necessary to reconcile the owned process after restart.
5. Deliver input only after the Relay validates an active control lease. Emit output chunks and state changes with monotonic event sequences and bounded chunk sizes.
6. On release or lease expiry, stop accepting remote input while leaving the local session running unless an explicit stop policy applies.

**Verification:** Unit tests prove that an unrecognized profile, missing lease, stale lease, second controller, and process not owned by the worker are rejected. A fixture PTY echoes input and its output is replayable from a cursor.

### Task 6: Add controller CLI commands and a same-machine PTY proof

**Objective:** Make the whole control path runnable without the React app.

**Files:**
- Modify: `sdk/src/agent_relay/cli.py`
- Create: `sdk/tests/test_control_cli.py`
- Create: `scripts/run_local_managed_session_spike.py`

**Steps:**
1. Add `agent-relay workers`, `agent-relay session start`, `agent-relay session attach`, `agent-relay session input`, `agent-relay session release`, and `agent-relay worker revoke` commands.
2. Run a worker and controller as separate processes against a temporary relay and an echo/REPL fixture—not a Git repository.
3. Send input, read output, release the lease, and verify that subsequent input is rejected.
4. Simulate controller disconnect by restarting attach from its latest durable sequence cursor.
5. Simulate worker restart and prove that the session becomes honestly `recovering`, `exited`, or reattached—never silently successful.

**Verification:** The end-to-end test proves one controller has input authority, observers can read when authorized, output replay does not duplicate input, and revocation blocks new sessions and leases.

### Task 7: Run the controlled two-machine managed-session proof

**Objective:** Validate seamless remote terminal/harness control using two user-owned machines.

**Steps:**
1. Create a new private spike relay with controller and worker participant identities.
2. Generate a short-lived, single-use invitation and transfer it through the user’s authenticated channel; never log the secret in source, shell history, or chat.
3. On the worker machine, locally select and start one named fixture or personal harness profile.
4. From the controller machine, discover the worker, request a control lease, attach, send a harmless input, observe output, and release control.
5. Disconnect the controller and reconnect from the durable event cursor.
6. Revoke the worker and confirm that no new control lease or input is accepted.

**Verification:** Capture sanitized session/event identifiers and exact test outcomes. Do not record tokens, terminal contents containing secrets, or personal absolute paths.

### Task 8: Add interactive harness fidelity deliberately

**Objective:** After managed PTY control works, add Claude Code/Codex/Hermes session profiles and then optional tmux adoption.

**Order:**
1. A named managed Claude Code/Codex PTY session in a user-approved personal workspace.
2. A native adapter where the harness exposes reliable structured state, approvals, and output.
3. Adopted tmux sessions only as an explicitly lower-guarantee compatibility mode.

---

## Two-machine acceptance checklist

- [ ] A worker paired with a single-use, named invitation reconnects with its stored credential.
- [ ] The controller discovers only workers it is authorized to view.
- [ ] The worker starts only locally allowlisted named session profiles.
- [ ] A controller can send input only while it holds a valid exclusive lease.
- [ ] Output and state events are ordered, durable, and replayable from a cursor.
- [ ] Controller reconnection does not grant input authority implicitly.
- [ ] Worker restart never fabricates session state.
- [ ] Releasing a lease leaves the harness session alive but removes remote input authority.
- [ ] Revocation blocks new session starts, leases, and input.
- [ ] No external machine can initiate an inbound connection to the worker.

## Stop conditions

Stop the live proof immediately if the worker would touch an employer-managed device, a work repository, a credential file, terminal content containing secrets, or an endpoint lacking authenticated transport. Return to the local managed-session test until that boundary is resolved.
