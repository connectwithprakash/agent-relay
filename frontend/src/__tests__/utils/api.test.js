import { afterEach, describe, expect, it, vi } from 'vitest';
import { getHistory, getRelay, redeemInvitation } from '../../utils/api';

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
    expect(String(url)).toBe('http://localhost:8000/relays/relay-123');
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
      }),
    }));

    await redeemInvitation('invite-secret');

    expect(localStorage.getItem('relay_token_relay-123')).toBe('participant-token');
  });
});
