# Live Control Stream Verification

## Scope

This verification covers managed fixture and Claude Code PTY profiles. It does not enable unrestricted shell execution.

## Local proof

Start the development Relay with a temporary database:

```bash
cd backend
DATABASE_URL=sqlite:////tmp/agent-relay-stream-live.db \
ENVIRONMENT=development \
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 18083
```

Run the worker stream proof from another terminal:

```bash
cd backend
PYTHONPATH=../sdk/src .venv/bin/python /tmp/run_worker_stream_live_proof.py
```

Observed result:

```text
verified real worker WebSocket -> PTY -> durable output
```

The proof exercises authenticated worker WebSocket connection, durable input replay, worker-owned PTY input, live output publication, and durable output persistence.

Repository checks:

```bash
cd backend && .venv/bin/pytest -q
cd sdk && PYTHONPATH=src ../backend/.venv/bin/pytest -q
cd frontend && npm test -- --run && npm run lint && npm run build
```

## Browser controller

The live route is:

```text
/relay/:relayId/sessions/:sessionId/live
```

The browser reads the already-paired relay credential from local storage and sends it through the WebSocket subprotocol. It does not place the credential in the URL. Without a stored credential, the route renders `Relay access required` and exposes no terminal input controls.

## Tailnet proof

The private-tailnet fixture proof passed with a controller on one Mac and a worker on the work Mac. It verified worker registration, session readiness, lease claim, PTY echo output, lease release, and rejected post-release input.

The managed Claude Code smoke test also passed over the tailnet: the worker started the locally allowlisted Claude executable in the fixed Agent Relay checkout, reached `ready`, and persisted startup output. No prompt, file edit, or permission action was sent.

The supervised `worker-run` proof passed: SIGINT removed the worker PID file and terminated only its owned Claude PTY. A separate pre-existing Claude session remained untouched.

## Not yet enabled

- Arbitrary remote shell commands.
- Binary terminal frames.
- Production WSS deployment.
