import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../components/TerminalViewport', () => ({
  default: () => <div aria-label="Live managed terminal" />,
}));

import LiveControlPage from '../../pages/LiveControlPage';

const session = {
  session_id: 'session-1',
  profile: 'claude-code',
  worker_status: 'online',
  controller_agent: 'browser-controller',
  lease_expires_at: '2099-01-01T00:00:00+00:00',
  version: 3,
};

describe('LiveControlPage lease errors', () => {
  const sockets = [];

  beforeEach(() => {
    class FakeWebSocket {
      static OPEN = 1;
      readyState = FakeWebSocket.OPEN;
      constructor(url, protocols) {
        this.url = url;
        this.protocols = protocols;
        sockets.push(this);
      }
      close = vi.fn();
      send = vi.fn();
    }
    vi.stubGlobal('WebSocket', FakeWebSocket);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ sessions: [{ ...session, controller_agent: null, lease_expires_at: null }] }),
    }));
    localStorage.setItem('relay_token_relay-1', 'browser-token');
    localStorage.setItem('relay_agent_relay-1', 'browser-controller');
  });

  afterEach(() => {
    localStorage.clear();
    sockets.length = 0;
    vi.unstubAllGlobals();
  });

  it('drops stale local lease state and disables terminal input after lease_required', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ sessions: [session] }),
    }));
    render(
      <MemoryRouter initialEntries={['/relay/relay-1/sessions/session-1/live']}>
        <Routes><Route path="/relay/:relayId/sessions/:sessionId/live" element={<LiveControlPage />} /></Routes>
      </MemoryRouter>,
    );

    await screen.findByRole('button', { name: 'Release control' });
    act(() => sockets[0].onmessage({
      data: JSON.stringify({ type: 'error', code: 'lease_required', message: 'An active control lease is required' }),
    }));

    await screen.findByRole('button', { name: 'Take control' });
    expect(screen.getByRole('alert')).toHaveTextContent('Control lease ended. Take control again to send input.');
    expect(screen.getByLabelText('Terminal input')).toBeDisabled();
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  });

  it('refreshes the session when the worker becomes unavailable so the badge and lease follow the server', async () => {
    const held = { ...session, status: 'controlled' };
    const detached = { ...session, status: 'detached', worker_status: 'offline', controller_agent: null, lease_expires_at: null, version: 4 };
    const responses = [held, detached];
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => ({
      ok: true,
      json: async () => ({ sessions: [responses.length > 1 ? responses.shift() : responses[0]] }),
    })));
    render(
      <MemoryRouter initialEntries={['/relay/relay-1/sessions/session-1/live']}>
        <Routes><Route path="/relay/:relayId/sessions/:sessionId/live" element={<LiveControlPage />} /></Routes>
      </MemoryRouter>,
    );
    await screen.findByRole('button', { name: 'Release control' });
    expect(screen.getByText('session controlled')).toBeInTheDocument();

    act(() => sockets[0].onmessage({
      data: JSON.stringify({ type: 'error', code: 'worker_unavailable', message: 'Worker is unavailable' }),
    }));

    expect(await screen.findByText('session detached')).toBeInTheDocument();
    expect(screen.getByText('worker offline')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Take control' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Release control' })).toBeNull();
  });

  it('does not offer to take control of a failed session', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ sessions: [{ ...session, status: 'failed', controller_agent: null, lease_expires_at: null }] }),
    }));
    render(
      <MemoryRouter initialEntries={['/relay/relay-1/sessions/session-1/live']}>
        <Routes><Route path="/relay/:relayId/sessions/:sessionId/live" element={<LiveControlPage />} /></Routes>
      </MemoryRouter>,
    );
    await screen.findByText('session failed');
    expect(screen.getByRole('button', { name: 'Take control' })).toBeDisabled();
  });

  describe('lease countdown', () => {
    const naiveUtc = (offsetMs) => new Date(Date.now() + offsetMs).toISOString().replace('Z', '');
    const mount = (overrides) => {
      const current = { ...session, ...overrides };
      vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => ({
        ok: true,
        json: async () => ({ sessions: [current] }),
      })));
      render(
        <MemoryRouter initialEntries={['/relay/relay-1/sessions/session-1/live']}>
          <Routes><Route path="/relay/:relayId/sessions/:sessionId/live" element={<LiveControlPage />} /></Routes>
        </MemoryRouter>,
      );
    };

    beforeEach(() => vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] }));
    afterEach(() => vi.useRealTimers());

    it('shows the remaining lease time and counts down', async () => {
      mount({ status: 'controlled', lease_expires_at: naiveUtc(90_000) });
      expect(await screen.findByText('Lease 1:30')).toBeInTheDocument();
      act(() => { vi.advanceTimersByTime(10_000); });
      expect(screen.getByText('Lease 1:20')).toBeInTheDocument();
    });

    it('drops control once when the lease runs out and does not loop', async () => {
      mount({ status: 'controlled', lease_expires_at: naiveUtc(3_000) });
      await screen.findByText('Lease 0:03');
      const callsBefore = fetch.mock.calls.length;

      await act(async () => { vi.advanceTimersByTime(3_000); });

      expect(await screen.findByRole('button', { name: 'Take control' })).toBeInTheDocument();
      expect(screen.queryByText(/^Lease /)).toBeNull();
      expect(fetch).toHaveBeenCalledTimes(callsBefore + 1);
      await act(async () => { vi.advanceTimersByTime(120_000); });
      expect(fetch).toHaveBeenCalledTimes(callsBefore + 1);
      expect(vi.getTimerCount()).toBe(0);
    });

    it('shows no countdown and runs no timer for a view-only tab', async () => {
      mount({ status: 'ready', controller_agent: 'someone-else', lease_expires_at: naiveUtc(90_000) });
      await screen.findByText('worker online');
      expect(screen.queryByText(/^Lease /)).toBeNull();
      expect(vi.getTimerCount()).toBe(0);
    });

    it.each(['failed', 'detached'])('shows no countdown for a %s session', async (status) => {
      mount({ status, lease_expires_at: naiveUtc(90_000) });
      await screen.findByText(`session ${status}`);
      expect(screen.queryByText(/^Lease /)).toBeNull();
      expect(vi.getTimerCount()).toBe(0);
    });

    it('stops the timer on unmount', async () => {
      mount({ status: 'controlled', lease_expires_at: naiveUtc(90_000) });
      await screen.findByText('Lease 1:30');
      cleanup();
      expect(vi.getTimerCount()).toBe(0);
    });
  });

  describe('naive UTC lease timestamps', () => {
    const naiveUtc = (offsetMs) => new Date(Date.now() + offsetMs).toISOString().replace('Z', '');
    const openLive = (leaseExpiresAt) => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ sessions: [{ ...session, lease_expires_at: leaseExpiresAt }] }),
      }));
      render(
        <MemoryRouter initialEntries={['/relay/relay-1/sessions/session-1/live']}>
          <Routes><Route path="/relay/:relayId/sessions/:sessionId/live" element={<LiveControlPage />} /></Routes>
        </MemoryRouter>,
      );
    };

    afterEach(() => vi.unstubAllEnvs());

    it.each(['Asia/Kolkata', 'America/Los_Angeles', 'UTC'])('treats an unexpired offset-less lease as held in %s', async (tz) => {
      vi.stubEnv('TZ', tz);
      openLive(naiveUtc(60_000));
      expect(await screen.findByRole('button', { name: 'Release control' })).toBeInTheDocument();
    });

    it.each(['Asia/Kolkata', 'America/Los_Angeles', 'UTC'])('treats an expired offset-less lease as ended in %s', async (tz) => {
      vi.stubEnv('TZ', tz);
      openLive(naiveUtc(-60_000));
      await screen.findByText('worker online');
      expect(screen.getByRole('button', { name: 'Take control' })).toBeEnabled();
      expect(screen.queryByRole('button', { name: 'Release control' })).toBeNull();
    });
  });
});
