# Live Managed-Session Stream Implementation Plan

> **For Hermes:** Implement one isolated control stream per managed harness session. Preserve durable events as recovery truth; treat WebSocket frames as best-effort acceleration.

**Goal:** Make a controller UI feel like a responsive remote terminal while preserving worker-local process ownership, exclusive input leases, authenticated authorization, durable replay, and reliable cleanup.

**Architecture:** Add a dedicated WebSocket endpoint for a single `HarnessSession`; do not extend the relay-wide message WebSocket. The controller and worker authenticate independently. The controller may send input only while its durable control lease is valid. The worker may publish only output/state for its owned session. Every accepted stream mutation is appended as a durable `ControlEvent` before best-effort fan-out. On reconnect, both peers load events after a cursor before trusting new frames.

**Tech stack:** FastAPI WebSocket, SQLAlchemy control tables, existing Python SDK `websockets` dependency, React 19/Vite, existing Tailwind design system, browser native WebSocket.

---

## Stream protocol

### Endpoint

```text
WS /relays/{relay_id}/sessions/{session_id}/stream?cursor=<last sequence>
```

Credentials travel through the existing `Sec-WebSocket-Protocol` token convention. The server derives actor identity from the token; clients do not choose a role or worker identity in a frame.

### Initial server frame

```json
{
  "type": "connected",
  "session_id": "session-...",
  "actor": "controller",
  "status": "controlled",
  "version": 4,
  "cursor": 12,
  "lease": {"held": true, "expires_at": "..."}
}
```

### Client-to-server frames

```json
{"type":"input","idempotency_key":"input-...","input":"hello\r"}
{"type":"resize","columns":120,"rows":36}
{"type":"heartbeat"}
```

Only `input` is in the first end-to-end fixture. Resize is protocol-reserved but not delivered to the fixture PTY until a real terminal emulator is selected.

### Worker-to-server frames

```json
{"type":"output","text":"echo:hello\r\n"}
{"type":"state","status":"exited","exit_code":0}
{"type":"approval_requested","summary":"..."}
```

### Server-to-peer frames

```json
{"type":"event","event":{"sequence":13,"kind":"output","data":{"text":"..."}}}
{"type":"lease","status":"released"}
{"type":"error","code":"lease_required","message":"..."}
```

Frame payloads are capped at 64 KB. Terminal bytes are UTF-8 text for this milestone; binary transfer and arbitrary file upload are out of scope.

---

## Impact map

- **Existing message WebSocket:** `backend/app/routes/websocket.py` and `backend/app/websocket_manager.py` remain relay-wide message transport. Do not alter their frame semantics or authentication behavior.
- **Control authorization:** `backend/app/routes/control.py` owns worker/session/lease/event truth. Extract shared authorization/event-append helpers before the stream route so HTTP and WebSocket paths enforce the same state transition rules.
- **Test database injection:** `backend/tests/conftest.py` currently patches the message WebSocket's `SessionLocal`; extend it for the new stream route.
- **Worker behavior:** `sdk/src/agent_relay/worker.py` currently polls durable events. Preserve polling as recovery fallback while adding a websocket stream client for low-latency input/output.
- **Frontend:** `frontend/src/pages/ControlDemoPage.jsx` remains a mock behavior demo. Add a separate live controller route/component; never point the mock page at incomplete production endpoints.
- **Responsive layout:** terminal output must live in a bounded, intentionally scrollable monospace region. At narrow widths, stack worker/status/lease controls above the terminal and prevent page-wide horizontal overflow.

---

## Tasks

### Task 1: Write failing per-session stream authorization tests

**Files:**
- Create: `backend/tests/test_control_stream.py`
- Modify: `backend/tests/conftest.py`

**Tests:**
1. Worker and controller connect to the same managed session with distinct authenticated tokens.
2. Controller input without a current control lease receives a terminal error/close and appends no event.
3. A controller with a valid lease sends one input frame; the worker receives one event frame and the durable event sequence advances once.
4. The worker sends output; controller receives the output event and a later HTTP cursor read returns the same event.
5. Another relay participant cannot attach to the session stream.
6. A worker paired to another session cannot emit output for this session.
7. Reconnecting from cursor returns only missing durable events.

**Verification:** Run `pytest -q tests/test_control_stream.py`; all stream authority and replay failures are observable before implementation.

### Task 2: Extract shared control-state helpers

**Files:**
- Create: `backend/app/services/control_service.py`
- Modify: `backend/app/routes/control.py`
- Test: `backend/tests/test_control_routes.py`

**Steps:**
1. Move session lookup, worker ownership check, active-lease check, event sequence allocation, and event serialization to the service layer.
2. Ensure the HTTP and WebSocket paths call the same helper for every input/output mutation.
3. Preserve existing HTTP status behavior and response shapes.
4. Add tests proving both paths reject stale/revoked identities without event creation.

**Verification:** Existing control-route tests remain green and the stream tests exercise the same event transition functions.

### Task 3: Add an isolated control stream manager and endpoint

**Files:**
- Create: `backend/app/control_stream_manager.py`
- Create: `backend/app/routes/control_stream.py`
- Modify: `backend/app/routes/__init__.py`
- Test: `backend/tests/test_control_stream.py`

**Steps:**
1. Maintain in-memory stream connections keyed by `(relay_id, session_id)` and authenticated actor identity.
2. Authenticate using the existing token hash and bind the resulting participant identity to the socket.
3. On connection, read/replay durable events after the supplied cursor and return a `connected` frame.
4. Persist an accepted input/output event before broadcasting it to the peer stream.
5. Bound frame size, validate exact frame types, and close malformed/unauthorized streams with explicit close codes.
6. On disconnect, remove only the matching socket; never mutate durable lease/session state merely because a live stream ended.

**Verification:** Stream tests prove no cross-relay/session broadcast, no unauthorized input, and replay after reconnect.

### Task 4: Add the worker WebSocket stream client with polling recovery

**Files:**
- Modify: `sdk/src/agent_relay/worker.py`
- Create: `sdk/tests/test_worker_stream.py`

**Steps:**
1. Add a worker stream loop using an authenticated WebSocket connection per owned active session.
2. On an input event, write only to the daemon-owned PTY, then emit output frames.
3. Retain the durable event cursor locally in memory for the fixture; a later production worker-state store may persist it securely.
4. On stream error/disconnect, reconnect with the cursor and use the existing HTTP event route as recovery fallback.
5. Keep the fixture profile as the sole permitted process profile.

**Verification:** An integration test starts a fixture PTY, receives a stream input, publishes output, forcibly reconnects, and verifies no duplicate terminal write.

### Task 5: Build the live controller UI

**Files:**
- Create: `frontend/src/pages/LiveControlPage.jsx`
- Create: `frontend/src/hooks/useControlStream.js`
- Create: `frontend/src/__tests__/pages/LiveControlPage.test.jsx`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/components/Layout.jsx`

**Desktop composition:**

```text
worker/session status + lease controls
terminal output viewport
single-line input composer
recovery/event details drawer
```

**Phone composition:**

```text
status and lease controls
terminal viewport, horizontally scrollable inside its own region
full-width input composer
compact recovery/events disclosure
```

**Steps:**
1. Configure the stream URL explicitly through a selected session; do not embed tokens in the URL.
2. Render connected/reconnecting/lease-required/revoked states visibly.
3. Append output with an opt-out auto-scroll behavior and preserve keyboard focus in the composer.
4. Disable composer input when no lease is active; provide an explicit acquire/release action.
5. On reconnect, request replay after the last displayed event cursor and deduplicate by sequence.
6. Add accessible live-region status changes but do not announce every terminal byte.

**Verification:** Component tests cover disconnected, lease-disabled, input send, output append, replay dedupe, and revoked states. Run the full frontend suite, lint, and production build.

### Task 6: Verify interactive behavior and responsive layout

**Files:**
- Modify: `docs/cross-harness-control-user-flows.md`
- Create: `docs/live-control-stream-verification.md`

**Steps:**
1. Run controller, Relay, and worker as separate local processes using the fixture profile.
2. Verify input/output streaming, lease release, reconnect/cursor recovery, worker restart state, and worker revocation.
3. Inspect the live controller at 320, 375, 390, 414, 768, 1024, and 1440px; assert no page-wide horizontal overflow.
4. Repeat the fixture-only test over the already-proven private tailnet before considering any real harness profile.
5. Record exact local-versus-tailnet test boundaries; do not claim a WSS production deployment until an HTTPS/WSS endpoint is actually tested.

**Verification:** Backend, SDK, and frontend suites pass; direct visual inspection passes; fixture tailnet run returns terminal output and cleanly releases/revokes access.

---

## Acceptance criteria

- [ ] A live controller stream cannot send input without a valid exclusive lease.
- [ ] The worker stream cannot emit for another worker/session.
- [ ] Every live input/output has exactly one durable event sequence.
- [ ] A reconnect from cursor replays missing output without duplicating terminal input.
- [ ] Stream loss never claims task/session completion.
- [ ] The controller UI makes worker, session, lease, and connection state clear.
- [ ] No token appears in a browser URL, terminal transcript, source file, or UI log.
- [ ] The live terminal layout has no page-wide horizontal overflow across the viewport matrix.
- [ ] The tailnet fixture proof passes before any Claude/Codex/Hermes profile is enabled.
