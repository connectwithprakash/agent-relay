import { renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useRelayList } from '../../hooks/useRelayList';

// Mock the API module
vi.mock('../../utils/api', () => ({
  listPublicRelays: vi.fn(),
}));

import { listPublicRelays } from '../../utils/api';

describe('useRelayList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches relays on mount and populates the relays list', async () => {
    const mockRelays = {
      relays: [
        { relay_id: 'relay-1', agent_names: ['a', 'b'], is_public: true },
        { relay_id: 'relay-2', agent_names: ['c', 'd'], is_public: true },
      ],
      total_count: 2,
    };
    listPublicRelays.mockResolvedValue(mockRelays);

    const { result } = renderHook(() => useRelayList());

    // Should start in loading state
    expect(result.current.loading).toBe(true);

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.relays).toHaveLength(2);
    expect(result.current.relays[0].relay_id).toBe('relay-1');
    expect(result.current.error).toBeNull();
    expect(listPublicRelays).toHaveBeenCalledWith(20, 0);
  });

  it('starts with loading state true', () => {
    listPublicRelays.mockReturnValue(new Promise(() => {})); // never resolves
    const { result } = renderHook(() => useRelayList());
    expect(result.current.loading).toBe(true);
    expect(result.current.relays).toEqual([]);
    expect(result.current.error).toBeNull();
  });

  it('sets error state when API call fails', async () => {
    listPublicRelays.mockRejectedValue(new Error('Network error'));

    const { result } = renderHook(() => useRelayList());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.error).toBe('Network error');
    expect(result.current.relays).toEqual([]);
  });

  it('handles array response format (fallback)', async () => {
    const mockRelays = [
      { relay_id: 'relay-1', agent_names: ['a', 'b'], is_public: true },
    ];
    listPublicRelays.mockResolvedValue(mockRelays);

    const { result } = renderHook(() => useRelayList());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.relays).toHaveLength(1);
  });

  it('passes custom limit to API call', async () => {
    listPublicRelays.mockResolvedValue({ relays: [], total_count: 0 });

    renderHook(() => useRelayList(5));

    await waitFor(() => {
      expect(listPublicRelays).toHaveBeenCalledWith(5, 0);
    });
  });

  it('provides a refresh function that re-fetches relays', async () => {
    listPublicRelays.mockResolvedValue({ relays: [], total_count: 0 });

    const { result } = renderHook(() => useRelayList());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    // Initial call
    expect(listPublicRelays).toHaveBeenCalledTimes(1);

    // Refresh
    listPublicRelays.mockResolvedValue({
      relays: [{ relay_id: 'relay-new', agent_names: ['x', 'y'], is_public: true }],
      total_count: 1,
    });

    result.current.refresh();

    await waitFor(() => {
      expect(listPublicRelays).toHaveBeenCalledTimes(2);
    });
  });
});
