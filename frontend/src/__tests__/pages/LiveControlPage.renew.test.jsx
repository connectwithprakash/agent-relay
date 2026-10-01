import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../components/TerminalViewport', () => ({
  default: () => <div aria-label="Live managed terminal" />,
}));

import LiveControlPage from '../../pages/LiveControlPage';

const T0 = Date.parse('2026-10-01T00:00:00Z');
const naiveUtc = (ms) => new Date(ms).toISOString().replace('Z', '');
const held = (overrides = {}) => ({
  session_id: 'session-1',
  profile: 'claude-code',
  worker_status: 'online',
  status: 'controlled',
  controller_agent: 'browser-controller',
  lease_expires_at: naiveUtc(T0 + 60_000),
  version: 3,
  ...overrides,
});
const flush = () => act(async () => { await vi.advanceTimersByTimeAsync(0); });
const advance = (ms) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

describe('LiveControlPage lease renewal', () => {
  const sockets = [];
  let listed;
  let renewCalls;
  let renewHandler;
  let claimCalls;
  let claimResponse;

  const renewedResponse = (version) => () => ({
    ok: true,
    json: async () => held({ version, lease_expires_at: naiveUtc(Date.now() + 60_000) }),
  });

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(T0);
    class FakeWebSocket {
      static OPEN = 1;
      readyState = FakeWebSocket.OPEN;
      constructor(url, protocols) { this.url = url; this.protocols = protocols; sockets.push(this); }
      close = vi.fn();
      send = vi.fn();
    }
    vi.stubGlobal('WebSocket', FakeWebSocket);
    renewCalls = [];
    claimCalls = [];
    claimResponse = () => held({ version: 6, lease_expires_at: naiveUtc(Date.now() + 60_000) });
    renewHandler = renewedResponse(4);
    listed = held();
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url, options) => {
      if (String(url).endsWith('/lease/renew')) {
        renewCalls.push({ at: Date.now(), url: String(url), body: JSON.parse(options.body) });
        const outcome = renewHandler(renewCalls.length);
        if (outcome instanceof Error) throw outcome;
        return outcome;
      }
      if (String(url).endsWith('/release')) {
        return { ok: true, json: async () => held({ status: 'ready', controller_agent: null, lease_expires_at: null, version: 5 }) };
      }
      if (String(url).endsWith('/claim')) {
        claimCalls.push(JSON.parse(options.body));
        return { ok: true, json: async () => claimResponse() };
      }
      return { ok: true, json: async () => ({ sessions: [listed] }) };
    }));
    localStorage.setItem('relay_token_relay-1', 'browser-token');
    localStorage.setItem('relay_agent_relay-1', 'browser-controller');
  });

  afterEach(() => {
    cleanup();
    localStorage.clear();
    sockets.length = 0;
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  const open = async ({ connected = true } = {}) => {
    render(
      <MemoryRouter initialEntries={['/relay/relay-1/sessions/session-1/live']}>
        <Routes><Route path="/relay/:relayId/sessions/:sessionId/live" element={<LiveControlPage />} /></Routes>
      </MemoryRouter>,
    );
    await flush();
    if (connected) { act(() => sockets[0].onopen()); await flush(); }
  };

  it('renews at about half of the remaining lease with the current version', async () => {
    await open();
    await advance(29_000);
    expect(renewCalls).toHaveLength(0);

    await advance(1_500);

    expect(renewCalls).toHaveLength(1);
    expect(renewCalls[0].body).toEqual({ lease_seconds: 60, expected_version: 3 });
    expect(renewCalls[0].at - T0).toBeGreaterThanOrEqual(29_900);
    expect(renewCalls[0].at - T0).toBeLessThanOrEqual(31_000);
  });

  it('adopts the returned version, shows the extended lease and renews again with the new version', async () => {
    renewHandler = (n) => renewedResponse(3 + n)();
    await open();
    await advance(31_000);
    expect(screen.getByText(/^Lease 0:(5\d|60)$|^Lease 1:00$/)).toBeInTheDocument();

    await advance(30_000);

    expect(renewCalls.map((call) => call.body.expected_version)).toEqual([3, 4]);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByRole('button', { name: 'Release control' })).toBeInTheDocument();
  });

  it('keeps control well past one full lease period', async () => {
    renewHandler = (n) => renewedResponse(3 + n)();
    await open();
    for (let elapsed = 0; elapsed < 150_000; elapsed += 10_000) await advance(10_000);
    expect(renewCalls.length).toBeGreaterThanOrEqual(4);
    expect(renewCalls.map((call) => call.body.expected_version)).toEqual(renewCalls.map((_, index) => 3 + index));
    expect(screen.getByRole('button', { name: 'Release control' })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('stops after a 409, refetches once, and lets the lease run out without a retry loop', async () => {
    const error = Object.assign(new Error('Lease cannot be renewed'), { status: 409 });
    renewHandler = () => ({ ok: false, status: 409, statusText: 'Conflict', json: async () => ({ detail: error.message }) });
    await open();
    const listCallsBefore = fetch.mock.calls.filter(([url]) => !String(url).endsWith('/lease/renew')).length;

    await advance(31_000);
    await advance(120_000);

    expect(renewCalls).toHaveLength(1);
    const listCallsAfter = fetch.mock.calls.filter(([url]) => !String(url).endsWith('/lease/renew')).length;
    expect(listCallsAfter - listCallsBefore).toBeLessThanOrEqual(2);
    expect(screen.getByRole('button', { name: 'Take control' })).toBeInTheDocument();
  });

  it('stops after a network failure and its single retry without a loop', async () => {
    renewHandler = () => new TypeError('Failed to fetch');
    await open();

    await advance(31_000);
    await advance(120_000);

    expect(renewCalls).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Take control' })).toBeInTheDocument();
  });

  const serverError = () => ({ ok: false, status: 500, statusText: 'Server Error', json: async () => ({}) });

  it.each([
    ['a 500', () => serverError()],
    ['a network error', () => new TypeError('Failed to fetch')],
  ])('retries once at about 75 percent of the lease after %s and keeps control when the retry works', async (_name, failure) => {
    renewHandler = (n) => (n === 1 ? failure() : renewedResponse(4)());
    await open();

    await advance(31_000);
    expect(renewCalls).toHaveLength(1);
    await advance(16_000);

    expect(renewCalls).toHaveLength(2);
    expect(renewCalls[1].at - T0).toBeGreaterThanOrEqual(44_000);
    expect(renewCalls[1].at - T0).toBeLessThanOrEqual(46_500);
    expect(renewCalls[1].body.expected_version).toBe(3);
    await advance(20_000);
    expect(screen.getByRole('button', { name: 'Release control' })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('makes only two attempts when a 500 repeats, then lets the lease run out', async () => {
    renewHandler = () => serverError();
    await open();

    await advance(31_000);
    await advance(16_000);
    await advance(120_000);

    expect(renewCalls).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Take control' })).toBeInTheDocument();
  });

  it.each([
    [400, 'Bad Request'],
    [403, 'Forbidden'],
    [409, 'Conflict'],
  ])('does not retry after a %s', async (status, statusText) => {
    renewHandler = () => ({ ok: false, status, statusText, json: async () => ({ detail: 'refused' }) });
    await open();

    await advance(31_000);
    await advance(40_000);

    expect(renewCalls).toHaveLength(1);
  });

  it('drops the retry when the lease is no longer held', async () => {
    renewHandler = () => serverError();
    await open();
    await advance(31_000);
    expect(renewCalls).toHaveLength(1);

    listed = held({ status: 'ready', controller_agent: null, lease_expires_at: null, version: 4 });
    await act(async () => {
      sockets[0].onmessage({ data: JSON.stringify({ type: 'error', code: 'lease_required', message: 'An active control lease is required' }) });
    });
    await advance(40_000);

    expect(renewCalls).toHaveLength(1);
  });

  it('drops the retry on unmount', async () => {
    renewHandler = () => serverError();
    await open();
    await advance(31_000);
    cleanup();
    await advance(40_000);
    expect(renewCalls).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('does not renew from a view-only tab', async () => {
    listed = held({ controller_agent: 'someone-else', status: 'controlled' });
    await open();
    await advance(120_000);
    expect(renewCalls).toHaveLength(0);
  });

  it.each(['failed', 'detached'])('does not renew a %s session', async (status) => {
    listed = held({ status });
    await open();
    await advance(120_000);
    expect(renewCalls).toHaveLength(0);
  });

  it('does not renew while the stream is not connected', async () => {
    await open({ connected: false });
    await advance(45_000);
    expect(renewCalls).toHaveLength(0);
  });

  it('does not renew when the worker is not online', async () => {
    listed = held({ worker_status: 'offline' });
    await open();
    await advance(45_000);
    expect(renewCalls).toHaveLength(0);
  });

  it('stops renewing on unmount', async () => {
    await open();
    cleanup();
    await advance(120_000);
    expect(renewCalls).toHaveLength(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('refetches the session for a lease_renewed event of its own lease', async () => {
    await open();
    const before = fetch.mock.calls.length;
    await act(async () => {
      sockets[0].onmessage({ data: JSON.stringify({ type: 'event', event: { sequence: 9, kind: 'lease_renewed', data: { controller_agent: 'browser-controller', expires_at: naiveUtc(T0 + 90_000) } } }) });
    });
    await flush();
    expect(fetch.mock.calls.length).toBe(before + 1);
  });

  it('ignores a lease_renewed event for another controller', async () => {
    await open();
    const before = fetch.mock.calls.length;
    await act(async () => {
      sockets[0].onmessage({ data: JSON.stringify({ type: 'event', event: { sequence: 9, kind: 'lease_renewed', data: { controller_agent: 'someone-else', expires_at: naiveUtc(T0 + 90_000) } } }) });
    });
    await flush();
    expect(fetch.mock.calls.length).toBe(before);
  });

  it('renews the new lease after a claim that follows a failed renewal', async () => {
    const error = Object.assign(new Error('refused'), { status: 409 });
    renewHandler = (n) => (n === 1
      ? { ok: false, status: 409, statusText: 'Conflict', json: async () => ({ detail: error.message }) }
      : renewedResponse(7)());
    listed = held({ version: 3 });
    await open();
    await advance(31_000);
    expect(renewCalls).toHaveLength(1);
    await advance(40_000);
    listed = held({ version: 5, status: 'ready', controller_agent: null, lease_expires_at: null });
    expect(screen.getByRole('button', { name: 'Take control' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Take control' }));
    await flush();
    expect(claimCalls).toHaveLength(1);
    await advance(31_000);

    expect(renewCalls).toHaveLength(2);
    expect(renewCalls[1].body.expected_version).toBe(6);
  });

  it('does not renew the old session after the route switches to another session', async () => {
    function Switch() {
      const navigate = useNavigate();
      return <button onClick={() => navigate('/relay/relay-1/sessions/session-2/live')}>go to second</button>;
    }
    render(
      <MemoryRouter initialEntries={['/relay/relay-1/sessions/session-1/live']}>
        <Switch />
        <Routes><Route path="/relay/:relayId/sessions/:sessionId/live" element={<LiveControlPage />} /></Routes>
      </MemoryRouter>,
    );
    await flush();
    act(() => sockets[0].onopen());
    await flush();
    await advance(10_000);

    listed = held({ session_id: 'session-2', controller_agent: 'someone-else' });
    fireEvent.click(screen.getByText('go to second'));
    await flush();
    await advance(120_000);

    expect(renewCalls).toHaveLength(0);
  });

  it('keeps the renewed version when a stale session list arrives afterwards', async () => {
    renewHandler = (n) => renewedResponse(3 + n)();
    await open();
    await advance(31_000);
    expect(renewCalls).toHaveLength(1);

    listed = held({ version: 3 });
    await act(async () => {
      sockets[0].onmessage({ data: JSON.stringify({ type: 'event', event: { sequence: 9, kind: 'lease_renewed', data: { controller_agent: 'browser-controller' } } }) });
    });
    await flush();
    await advance(30_000);

    expect(renewCalls.map((call) => call.body.expected_version)).toEqual([3, 4]);
  });

  it('keeps the released state when a renew response arrives after the user released', async () => {
    let resolveRenew;
    const pending = new Promise((resolve) => { resolveRenew = resolve; });
    renewHandler = () => pending;
    await open();
    await advance(31_000);
    expect(renewCalls).toHaveLength(1);

    fireEvent.click(screen.getByRole('button', { name: 'Release control' }));
    await flush();
    expect(screen.getByRole('button', { name: 'Take control' })).toBeInTheDocument();

    await act(async () => { resolveRenew(renewedResponse(4)()); await pending; });
    await flush();

    expect(screen.getByText('session ready')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Take control' })).toBeInTheDocument();
    expect(screen.queryByText(/^Lease /)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Take control' }));
    await flush();
    expect(claimCalls[0].expected_version).toBe(5);
  });

  it('ignores a renew response older than the current session version', async () => {
    let resolveRenew;
    const pending = new Promise((resolve) => { resolveRenew = resolve; });
    renewHandler = () => pending;
    await open();
    await advance(31_000);

    listed = held({ version: 7, lease_expires_at: naiveUtc(Date.now() + 25_000) });
    await act(async () => {
      sockets[0].onmessage({ data: JSON.stringify({ type: 'event', event: { sequence: 9, kind: 'lease_renewed', data: { controller_agent: 'browser-controller' } } }) });
    });
    await flush();
    await act(async () => { resolveRenew(renewedResponse(4)()); await pending; });
    await flush();

    expect(screen.getByText(/^Lease 0:2\d$/)).toBeInTheDocument();
  });
});
