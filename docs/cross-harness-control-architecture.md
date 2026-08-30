# Cross-Harness Control: Complete Target Architecture

**Status:** Architecture proposal for review
**Scope:** Personal Agent Relay product direction; not an employer platform proposal.

## The product shift

```text
Today: Agent Relay is a walkie-talkie for agents.

Target: Agent Relay is the control plane through which one harness can
        discover, delegate to, supervise, interact with, and recover another
        approved harness across machines.
```

Messaging remains a core coordination primitive. It is no longer the only primary user experience.

## Mental model: a distributed agent operating system

```text
┌──────────────────────────── Controller plane ────────────────────────────┐
│ Hermes / Claude Code / Codex / UI                                        │
│                                                                           │
│  discover worker → start or attach session → assign task / interact      │
│  observe status → answer approval → inspect artifact → recover/replay    │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ SDK / CLI / MCP / Web UI
                                ▼
┌────────────────────────── Agent Relay control plane ────────────────────┐
│ Identity & pairing     Worker / session registry      Policy / ACL       │
│ Control sessions       Tasks / leases                 Approvals          │
│ Ordered events         Artifact catalog               Durable outbox     │
│ Reconnect cursors      Audit trail                    Live notification  │
└───────────────────────┬──────────────────────────────┬───────────────────┘
                        │ outbound authenticated stream │ durable reads
                        ▼                              ▼
┌──────────────────────────── Worker plane ───────────────────────────────┐
│ Worker daemon on each approved machine                                   │
│  - advertises capabilities and projects                                  │
│  - owns local policy and secrets                                         │
│  - creates, adopts, and supervises harness sessions                      │
│  - executes allowlisted operations                                       │
│  - emits events and artifact references                                  │
└───────────────────────┬─────────────────────────────────────────────────┘
                        ▼
┌────────────────────────── Runtime adapter plane ────────────────────────┐
│ Managed PTY        Adopted tmux         Native adapters                  │
│ Claude Code CLI    Existing sessions    Claude / Codex / Hermes APIs     │
│ Codex CLI          Compatibility mode   Structured turns/tools/approvals │
│ Generic subprocess                                                             │
└──────────────────────────────────────────────────────────────────────────┘
```

## The key separation

```text
Communication plane
  messages, threads, presence, notifications

Control plane
  discover, claim, invoke, observe, approve, interrupt, recover

Execution plane
  local worker policy, process lifecycle, PTY/tmux/native harness behavior
```

A terminal keystroke is an execution-adapter detail. A control request is a durable product command.

## Complete domain model

```text
Workspace / Relay
  └── Participant
       └── Worker
            └── Project capability
                 └── HarnessSession
                      ├── ControlSession (exclusive interactive lease)
                      └── Task / Run
                           ├── ControlEvent (ordered, replayable)
                           ├── ApprovalRequest
                           └── Artifact
```

### Domain responsibilities

| Domain object | Owns |
|---|---|
| Participant | authenticated actor identity and relay membership |
| Worker | one approved machine-side daemon and its liveness |
| Project capability | an approved local project/environment and permitted operations |
| HarnessSession | a managed, adopted, or native runtime instance |
| ControlSession | temporary exclusive interactive ownership and its lease |
| Task / Run | bounded work, lifecycle, retry identity, and terminal result |
| ControlEvent | durable ordered audit/replay history |
| ApprovalRequest | a paused action, authorized responder, and response record |
| Artifact | evidence reference, integrity metadata, producer, and access policy |

## Two interaction modes, one contract

```text
Task mode
  Controller: "Inspect this repository and return the architecture."
  Worker: runs bounded work and returns a structured artifact.

Interactive mode
  Controller: attaches to a session, sends input, observes output,
  interrupts, answers an approval, then releases control.
```

Both modes use the same identity, policy, event, artifact, and recovery system. Interactive mode adds an exclusive `ControlSession` lease and a streaming input/output adapter.

## Adapter model

| Adapter | Role in complete solution | Guarantees |
|---|---|---|
| Managed subprocess / PTY | universal managed path for CLI harnesses | worker owns process lifecycle, I/O, exit state, and restart handling |
| Adopted tmux | compatibility path for an already-running user session | lower guarantee; another human/process may also control the terminal |
| Native harness adapter | preferred path where a harness exposes a usable API | structured turns, tool calls, approvals, and state without terminal scraping |

The public interface is a `HarnessSession`, not a tmux wrapper:

```text
start / attach / status / observe / send_input / submit_task
approve / interrupt / stop / release / recover
```

## Reliability contract

Every mutation is one durable command:

```text
authenticate actor
→ authorize action on worker/project/session/task
→ validate expected version and active lease
→ append ordered event
→ update state / ownership / lease
→ add outbox notification work
→ commit once
```

| Concern | Required behavior |
|---|---|
| Duplicate submission | idempotency key returns the original accepted command/result |
| Competing control | exactly one active control lease per interactive session |
| Stale controller | rejected by version/lease comparison; cannot append an event |
| Worker crash | run becomes honestly recoverable, failed, or awaiting worker reconciliation—not falsely complete |
| Controller reconnect | reads task/session state and events after durable cursor |
| Live stream loss | no loss of authoritative history; stream is recovered from events or a fresh snapshot |
| Artifact integrity | artifact has producer, media type, reference/digest, and access policy |
| External notifications | delivered by outbox semantics after command commit |

## Pair-once experience

```text
First time
  Pair a worker with your personal Relay workspace through a QR/link/code
  and explicit confirmation on the machine being added.

After pairing
  Worker credentials live in the OS keychain or owner-only local store.
  The worker reconnects outbound whenever the machine is online.
  Your controller sees it in a familiar directory, like a remembered Wi-Fi network.

At use time
  Choose a worker → choose a project/session → request task or interactive control.
  A short-lived control lease, not the original pairing, grants input authority.
```

Pairing establishes durable **identity and trust**. It does not grant unrestricted execution. Session and operation policy still apply every time control is requested.

## Cross-network connectivity

```text
The normal product path works when controller and worker are on different
networks: home Wi-Fi, work Wi-Fi, travel, or cellular.

Controller and worker each make an authenticated outbound HTTPS/WebSocket
connection to a reachable Agent Relay service. Neither machine needs a stable
IP address, an inbound public port, port forwarding, or an SSH destination.
```

The Relay's worker directory is the discovery surface: a connected worker advertises
its current availability and locally allowed profiles; reconnecting workers recover
from durable session/event state. A private overlay such as Tailscale can be used
for development or self-hosted deployments, but it is not a normal-user prerequisite.

## Security model

```text
Pairing grants identity.
Identity grants membership.
Membership plus policy grants capability.
Capability plus lease grants one action.
```

The worker remains the final policy enforcement point. The control plane never assumes that possession of a relay identifier, a worker name, or a network path permits execution.

Initial policies must support:

- user-owned worker and project allowlists;
- operation-level permissions;
- read-only, write, destructive, and external-network distinctions;
- human approval for privileged operations;
- local secret containment;
- revocation of worker, participant, project, and control-session access;
- audit records without raw secret or terminal-transcript leakage.

## Integration surfaces

```text
SDK
  programmatic controller / worker client

CLI
  discover, workers, sessions, task submit, attach, logs, artifacts

MCP
  harness-facing tools for discovery, task control, observation, and approval

Web UI
  worker/session directory, live status, lease owner, task timeline,
  approval surface, artifact viewer, audit view
```

MCP and the UI are adapters over the native control model. They do not own task truth.

## Delivery sequence that preserves the complete design

```text
Phase 1 — control core
  Worker identity, task/run model, events, artifacts, policies, leases,
  replay, and a managed-subprocess adapter.

Phase 2 — interactive runtime control
  Full PTY stream/input semantics, attach/release, interrupt, approvals,
  backpressure, snapshots, and adoption of existing tmux sessions.

Phase 3 — harness-native adapters
  Claude Code, Codex, Hermes, and other adapters where structured APIs
  improve fidelity beyond terminal control.

Phase 4 — complete product surfaces
  SDK, CLI, MCP, UI, worker installation/pairing, capability directory,
  cross-device recovery, and administration/audit experience.

Phase 5 — hardening and interoperability
  Postgres concurrency verification, fault injection, upgrade/rollback,
  worker revocation, optional A2A facade, and self-hosted/hosted deployment.
```

The phases are not separate products. Each adds a complete layer required by the target system.

## Architecture decisions to make next

1. Is `Relay` the top-level workspace/control namespace, or should a new workspace model contain both relays and workers?
2. Does a worker maintain a long-lived outbound WebSocket, or does it combine HTTP command polling with a notification channel?
3. What exact control-event schema supports both task and interactive modes?
4. What artifacts are stored, referenced, or intentionally kept local?
5. How are tmux-adopted sessions reconciled with exclusive control leases?
6. Which native harness adapters are feasible and worth prioritizing after PTY support?
7. How will the public documentation reposition Agent Relay from turn-based messaging to cross-harness control?

## Recommendation

Adopt this complete architecture as the product target. The next implementation plan should start with the control core because the remaining layers depend on it, not because the remaining layers are out of scope.
