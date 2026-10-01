# Live control UI verification

Date: 2026-10-01. Base: origin/main 8c4c209. Branch: `frontend-verify`.

This records a run of the control UI in a real browser against a real backend and worker, not mocked frames. Each result below says what was checked, the evidence, and whether it held.

## Setup

| Part | How it ran |
|---|---|
| Backend | `uvicorn app.main:app` from the main checkout's `backend/.venv`, free port, temporary SQLite database, minimal environment (same approach as `scripts/smoke_control.py`) |
| Worker | `agent-relay worker-run --profile fixture-shell` as a separate process, so it could be stopped and restarted. The test-only `fixture-shell` profile was the only profile used. No Claude process and no real agent was started. |
| Frontend | Vite dev server on port 5199 with `VITE_API_BASE_URL` pointing at the backend |
| Browser | The built-in Claude browser pane (`mcp__Claude_Browser__*`), real Chromium, not Playwright |
| Pairing | `agent-relay create controller`, `join-invitation` for the worker, `browser-pairing-invitation` redeemed on the Home page, session started from the Controller dashboard, lease claimed with the Take control button |

Evidence is DOM reads (`.xterm-rows` text, badge text, `[role=alert]` text), the backend events API read from inside the page, and screenshots taken during the run. Screenshots are not committed.

Two environment notes. `npm install` failed with E401 on the configured private registry, so dependencies were installed with `npm ci --registry https://registry.npmjs.org/`. The lease the UI requests lasts 60 seconds and the UI never renews it, so several steps had to be done quickly or re-claimed.

## Results

| Check | Result |
|---|---|
| (a) Typing reaches the worker and output returns | Passed |
| (b) Resizing the pane sends a resize and the fixture reports it | Passed |
| (c) Approval banner, dismiss, spinner output, answer | Passed |
| (d) Second tab sees input from the first and clears its banner | Passed, with a caveat on identity |
| (e) Worker stopped, then restarted, failed session not resurrected | Passed after two fixes |
| (f) Console errors | No uncaught errors; two benign 409s and one dev warning |

### (a) Typing

Clicked the xterm area and typed `hello browser` plus Enter. The terminal DOM then read `fixture ready`, `hello browser`, `echo:hello browser`. Output arrived in under a second (the worker polls). Passed.

### (b) Resize

Typed `size` at the initial pane size, set the viewport to 1100x800, typed `size` again. The backend events read from the page showed two `resize_requested` events, `{cols:122, rows:24}` then `{cols:132, rows:25}`, and two outputs `size:122x24` and `size:132x25`. The fixture reported exactly the sizes the browser sent. Passed.

### (c) Approval banner

Typed `approval`. An amber banner appeared with the text `Approval requested`, `Do you want to proceed?`, `> 1. Yes`, `2. No`, `Answer in the terminal below.` and a single Dismiss button.

- Dismiss removed the banner.
- On a pending approval, four spinner-style worker output events (`\r|`, `\r/`, `\r-`, `\r\`) were posted over HTTP as the worker. The terminal showed them and the banner stayed.
- Typing `1` plus Enter in the terminal cleared the banner and the terminal showed `echo:1`.

Passed. A first attempt at the second approval was invalid because the lease had expired and the alert I counted was the lease error, not the banner. The banner and the error both use `role="alert"`, which makes alert-role checks ambiguous.

### (d) Second tab

Opened a second tab on the same live URL. `approval` typed in tab 1 produced the banner in both tabs, tab 2 without reload. Answering `1` in tab 1 cleared the banner in tab 1 locally and in tab 2 on the pushed `input_requested` event. Both terminals showed the same output.

Caveat: both tabs share one `localStorage`, so they are the same controller identity on two sockets, not two distinct controllers. The server excludes only the sending socket, so this still exercises the push path, but distinct controller credentials were not tested.

### (e) Worker stopped and restarted

1. Stopped the worker with SIGTERM. The page changed nothing: badges stayed `session controlled` and `worker online`. After 100 seconds (past the 90 second staleness window) they still did. The server marks stale workers lazily and does not push that change, and the page does not poll, so the badge can show a dead worker as online until the next interaction.
2. Typed into the terminal. The stream answered `worker_unavailable`, the page showed `Worker is unavailable` and flipped the worker badge to `worker offline`, but the session badge still read `session controlled` with a Release control button, while the server already had the session `detached` with no controller and no lease. Bug 2 below.
3. After reload the page showed `session detached`, `worker offline`, Take control.
4. Restarted the worker (fixture profile, no tmux). Without any reload the badge changed from `session detached` to `session failed` through the live `session_failed` event, confirmed by a marker set on `window` surviving. This verifies the live push of session end events and the page's handling.
5. The restarted worker did not resurrect the session. After reload the page showed `session failed`. Clicking Take control returned `Session is not available for control` from the server and the status stayed failed. The button was enabled for a failed session, which is Bug 3 below.

Observation, not fixed: after the live `session_failed` the worker badge kept saying `worker offline` although the restarted worker was online, because the page does not refetch on that event. A reload corrects it.

### (f) Console

No uncaught errors or React warnings. Entries seen:

- Two `409 Conflict` resource errors. One is the claim retry path (stale version, then success). The other is the deliberate claim of a failed session.
- `WebSocket connection ... failed: WebSocket is closed before the connection is established` on every page load. This is React StrictMode in development mounting, unmounting and mounting the stream hook; the first socket is closed while connecting. It does not occur in a production build. Left as is.

## Bugs found and fixed on this branch

Each has a test written first, failing before the fix.

1. Lease timestamps parsed in local time (`6ec28d8`). The backend serializes naive UTC datetimes without an offset, for example `2026-10-01T07:03:46.074334`. `Date.parse` read that as local time, so in a timezone behind UTC an expired lease looked valid for hours and the page kept Release control after `lease_required`, and in a timezone ahead of UTC a fresh lease looked expired. Added `parseServerTimestamp` in `frontend/src/utils/time.js`; tests cover Asia/Kolkata, America/Los_Angeles and UTC and failed before the fix.
2. Session badge stale after `worker_unavailable` (`5e50fe8`). The page now refetches the session so the badge and lease follow the server.
3. Take control offered for a failed session (`4b362ad`). The button is now disabled when the session is failed.

## Not fixed, for follow-up

- The UI claims a 60 second lease and never renews it or shows a countdown, so control ends silently after a minute.
- Stale worker expiry is not pushed and the page does not poll, so a dead worker can show as online until the next interaction.
- The worker badge stays offline after a restarted worker comes back until the page refetches.
- Approval banner and error alert share `role="alert"`.
- Chat message and relay card timestamps (`MessageList.jsx`, `RelayCard.jsx`) use `new Date(timestamp)` on the same offset-less format and may show times shifted by the local offset. Not checked in a browser.
- Distinct controller credentials in (d) and a real tmux profile were not exercised.
