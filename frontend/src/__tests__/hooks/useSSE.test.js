import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useSSE } from '../../hooks/useSSE';

describe('useSSE', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('does not reconnect after a permanent authentication failure', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 401, body: null });
    const onError = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useSSE('/private-stream', { token: 'invalid', onError }));

    await waitFor(() => expect(result.current.connectionStatus).toBe('error'));
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledTimes(1);
  });
});
