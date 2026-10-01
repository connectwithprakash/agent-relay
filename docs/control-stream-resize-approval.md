# Control stream: resize and approval frames

Shared contract for the resize and approval work. Backend, worker and frontend all build against this file. Change it first, then the code.

## Existing behavior (unchanged)

- Controller to worker: WebSocket frame `{"type": "input", "input": "<text>"}` becomes event `input_requested` with data `{"input": "<text>"}`. Requires an active control lease.
- Worker to controller: WebSocket frame `{"type": "output", "text": "<text>"}` becomes event `output` with data `{"text": "<text>"}`.
- Events carry a per-session `sequence` and are replayable with `cursor` / `after_sequence`.
- `EventRequest.kind` already allows `approval_requested`; it is stored but not yet pushed live on the HTTP events route.

## Resize

Controller to worker. Requires an active control lease, like input.

- Frame: `{"type": "resize", "cols": <int>, "rows": <int>}`
- Bounds: `cols` 20..500, `rows` 5..200, both integers. Anything else gets `{"type": "error", "code": "invalid_resize"}`.
- Stored and forwarded as event kind `resize_requested` with data `{"cols": N, "rows": N}`.
- The worker applies it to the PTY (`TIOCSWINSZ`) or tmux window and sends no reply. Resize is idempotent, so the latest event wins on replay.

## Approval

Worker to controller. Reuses the existing kind `approval_requested`; do not add `needs_approval`.

- Frame from worker: `{"type": "approval", "prompt": "<text>"}`, prompt up to 4096 bytes UTF-8.
- Stored and pushed live to controllers as event kind `approval_requested` with data `{"prompt": "<text>"}`.
- The HTTP events route must also push `approval_requested` to controllers (today it only pushes `output`).
- The controller answers by sending normal `input` (for example `1` plus Enter). No new response frame.
- Detection is the worker's job: match known Claude Code permission prompts in output, emit once per prompt, and do not alter the `output` stream.

## Ownership

| Part | Owner |
|---|---|
| Frame validation, event kinds, live push, migrations if any, backend tests | backend-engineer |
| PTY and tmux resize, prompt detection, worker tests | worker-engineer |
| xterm.js resize events, approval banner, frontend tests | frontend-engineer |
| Review of every branch | reviewer |

## Order

1. backend-engineer lands the frames and tests, then reports the branch.
2. worker-engineer and frontend-engineer build against this file in parallel; they can use fakes until the backend branch is merged.
3. reviewer approves each branch before merge.
