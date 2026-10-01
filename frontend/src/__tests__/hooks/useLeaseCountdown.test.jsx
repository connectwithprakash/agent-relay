import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useLeaseCountdown } from '../../hooks/useLeaseCountdown';

describe('useLeaseCountdown', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] });
    vi.setSystemTime(new Date('2026-10-01T00:00:00Z'));
  });
  afterEach(() => vi.useRealTimers());

  const at = (seconds) => Date.parse('2026-10-01T00:00:00Z') + seconds * 1000;

  it('counts down whole seconds', () => {
    const { result } = renderHook(() => useLeaseCountdown(at(90), true, vi.fn()));
    expect(result.current).toBe(90);
    act(() => { vi.advanceTimersByTime(10_000); });
    expect(result.current).toBe(80);
  });

  it('calls onExpire once when the lease runs out and then stops ticking', () => {
    const onExpire = vi.fn();
    const { result } = renderHook(() => useLeaseCountdown(at(3), true, onExpire));
    act(() => { vi.advanceTimersByTime(3_000); });
    expect(result.current).toBe(0);
    expect(onExpire).toHaveBeenCalledTimes(1);
    act(() => { vi.advanceTimersByTime(30_000); });
    expect(onExpire).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('returns null and starts no timer when disabled or without an expiry', () => {
    const disabled = renderHook(() => useLeaseCountdown(at(90), false, vi.fn()));
    const missing = renderHook(() => useLeaseCountdown(Number.NaN, true, vi.fn()));
    expect(disabled.result.current).toBeNull();
    expect(missing.result.current).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('does not call onExpire for a disabled lease that is already past', () => {
    const onExpire = vi.fn();
    renderHook(() => useLeaseCountdown(at(-5), false, onExpire));
    expect(onExpire).not.toHaveBeenCalled();
  });

  it('clears its timer on unmount', () => {
    const { unmount } = renderHook(() => useLeaseCountdown(at(90), true, vi.fn()));
    expect(vi.getTimerCount()).toBe(1);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('restarts for a new expiry', () => {
    const onExpire = vi.fn();
    const { result, rerender } = renderHook(({ expiry }) => useLeaseCountdown(expiry, true, onExpire), { initialProps: { expiry: at(2) } });
    act(() => { vi.advanceTimersByTime(2_000); });
    expect(onExpire).toHaveBeenCalledTimes(1);
    rerender({ expiry: at(62) });
    expect(result.current).toBe(60);
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(onExpire).toHaveBeenCalledTimes(2);
  });
});
