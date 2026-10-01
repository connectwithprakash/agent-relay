import { afterEach, describe, expect, it, vi } from 'vitest';
import { getHistory, getRelay, redeemInvitation, renewLease } from '../../utils/api';

describe('getRelay', () => {
  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it('uses the stored relay token when reading private relay state', async () => {
    localStorage.setItem('relay_token_relay-123', 'secret-token');
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ relay_id: 'relay-123' }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(getRelay('relay-123')).resolves.toEqual({ relay_id: 'relay-123' });

    const [url, options] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(`${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/relays/relay-123`);
    expect(options).toEqual({ headers: { Authorization: 'Bearer secret-token' } });
  });
});

describe('getHistory', () => {
  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it('uses the stored relay token when reading private message history', async () => {
    localStorage.setItem('relay_token_relay-123', 'secret-token');
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ messages: [] }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await getHistory('relay-123');

    const [, options] = fetchMock.mock.calls[0];
    expect(options.headers.Authorization).toBe('Bearer secret-token');
  });
});

describe('redeemInvitation', () => {
  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it('persists the participant token returned by the invitation exchange', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        relay_id: 'relay-123',
        agent_name: 'bob',
        token: 'participant-token',
        is_creator: true,
      }),
    }));

    await redeemInvitation('invite-secret');

    expect(localStorage.getItem('relay_token_relay-123')).toBe('participant-token');
    expect(localStorage.getItem('relay_controller_relay-123')).toBe('true');
  });
});

describe('renewLease', () => {
  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  const base = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

  it('posts the expected version and lease length with the relay token', async () => {
    localStorage.setItem('relay_token_relay-1', 'secret-token');
    const session = { session_id: 'session-1', version: 5, lease_expires_at: '2026-10-01T00:01:00' };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => session });
    vi.stubGlobal('fetch', fetchMock);

    await expect(renewLease('relay-1', 'session-1', { expectedVersion: 4, leaseSeconds: 60 })).resolves.toEqual(session);

    const [url, options] = fetchMock.mock.calls[0];
    expect(String(url)).toBe(`${base}/relays/relay-1/sessions/session-1/lease/renew`);
    expect(options.method).toBe('POST');
    expect(options.headers).toMatchObject({ Authorization: 'Bearer secret-token', 'Content-Type': 'application/json' });
    expect(JSON.parse(options.body)).toEqual({ lease_seconds: 60, expected_version: 4 });
  });

  it('rejects with the status and server detail on a conflict', async () => {
    localStorage.setItem('relay_token_relay-1', 'secret-token');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false, status: 409, statusText: 'Conflict', json: async () => ({ detail: 'Lease cannot be renewed; refresh and claim again if needed' }),
    }));

    await expect(renewLease('relay-1', 'session-1', { expectedVersion: 4, leaseSeconds: 60 }))
      .rejects.toMatchObject({ status: 409, message: 'Lease cannot be renewed; refresh and claim again if needed' });
  });

  it('rejects without a status on a network failure', async () => {
    localStorage.setItem('relay_token_relay-1', 'secret-token');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

    const error = await renewLease('relay-1', 'session-1', { expectedVersion: 4, leaseSeconds: 60 }).catch((e) => e);
    expect(error).toBeInstanceOf(Error);
    expect(error.status).toBeUndefined();
    expect(error.message).toMatch(/network/i);
  });

  it('refuses to call the server without a stored token', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    await expect(renewLease('relay-1', 'session-1', { expectedVersion: 4, leaseSeconds: 60 })).rejects.toThrow(/credential|token/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
