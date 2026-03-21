import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { useRelayCreation } from '../../hooks/useRelayCreation';

// Mock the API module
vi.mock('../../utils/api', () => ({
  createRelay: vi.fn(),
}));

import { createRelay } from '../../utils/api';

describe('useRelayCreation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('initializes with two empty agent names', () => {
    const { result } = renderHook(() => useRelayCreation());
    expect(result.current.agentNames).toEqual(['', '']);
    expect(result.current.isPublic).toBe(false);
    expect(result.current.submitting).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.createdRelay).toBeNull();
  });

  it('adds an agent name slot', () => {
    const { result } = renderHook(() => useRelayCreation());
    act(() => {
      result.current.addAgent();
    });
    expect(result.current.agentNames).toHaveLength(3);
  });

  it('does not add more than 10 agents', () => {
    const { result } = renderHook(() => useRelayCreation());
    act(() => {
      for (let i = 0; i < 12; i++) {
        result.current.addAgent();
      }
    });
    expect(result.current.agentNames).toHaveLength(10);
  });

  it('removes an agent name slot', () => {
    const { result } = renderHook(() => useRelayCreation());
    act(() => {
      result.current.addAgent();
    });
    expect(result.current.agentNames).toHaveLength(3);

    act(() => {
      result.current.removeAgent(1);
    });
    expect(result.current.agentNames).toHaveLength(2);
  });

  it('does not remove below 2 agents', () => {
    const { result } = renderHook(() => useRelayCreation());
    act(() => {
      result.current.removeAgent(0);
    });
    expect(result.current.agentNames).toHaveLength(2);
  });

  it('updates an agent name', () => {
    const { result } = renderHook(() => useRelayCreation());
    act(() => {
      result.current.updateAgentName(0, 'builder');
    });
    expect(result.current.agentNames[0]).toBe('builder');
  });

  it('toggles public state', () => {
    const { result } = renderHook(() => useRelayCreation());
    act(() => {
      result.current.setIsPublic(true);
    });
    expect(result.current.isPublic).toBe(true);
  });

  it('validates empty agent names', async () => {
    const { result } = renderHook(() => useRelayCreation());
    let submitResult;
    await act(async () => {
      submitResult = await result.current.submit();
    });
    expect(submitResult).toBeNull();
    expect(result.current.error).toBe('All agent names are required');
  });

  it('validates duplicate agent names', async () => {
    const { result } = renderHook(() => useRelayCreation());
    act(() => {
      result.current.updateAgentName(0, 'same');
      result.current.updateAgentName(1, 'same');
    });

    let submitResult;
    await act(async () => {
      submitResult = await result.current.submit();
    });
    expect(submitResult).toBeNull();
    expect(result.current.error).toBe('Agent names must be unique');
  });

  it('submits successfully with valid data', async () => {
    const mockRelay = { relay_id: 'relay-123', agents: ['builder', 'reviewer'] };
    createRelay.mockResolvedValue(mockRelay);

    const { result } = renderHook(() => useRelayCreation());
    act(() => {
      result.current.updateAgentName(0, 'builder');
      result.current.updateAgentName(1, 'reviewer');
    });

    let submitResult;
    await act(async () => {
      submitResult = await result.current.submit();
    });

    expect(submitResult).toEqual(mockRelay);
    expect(result.current.createdRelay).toEqual(mockRelay);
    expect(createRelay).toHaveBeenCalledWith(['builder', 'reviewer'], null, false);
  });

  it('handles API errors on submit', async () => {
    createRelay.mockRejectedValue(new Error('Server error'));

    const { result } = renderHook(() => useRelayCreation());
    act(() => {
      result.current.updateAgentName(0, 'builder');
      result.current.updateAgentName(1, 'reviewer');
    });

    let submitResult;
    await act(async () => {
      submitResult = await result.current.submit();
    });

    expect(submitResult).toBeNull();
    expect(result.current.error).toBe('Server error');
  });

  it('resets form state', () => {
    const { result } = renderHook(() => useRelayCreation());
    act(() => {
      result.current.updateAgentName(0, 'builder');
      result.current.setIsPublic(true);
    });

    act(() => {
      result.current.reset();
    });

    expect(result.current.agentNames).toEqual(['', '']);
    expect(result.current.isPublic).toBe(false);
    expect(result.current.error).toBeNull();
  });
});
