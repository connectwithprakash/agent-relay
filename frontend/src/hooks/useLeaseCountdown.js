import { useEffect, useReducer, useRef } from 'react';

const TICK_MS = 1000;

// Whole seconds until expiresAtMs, or null when there is nothing to count down.
// onExpire runs once per expiry value, after the countdown reaches zero.
export function useLeaseCountdown(expiresAtMs, enabled, onExpire) {
  const [, tick] = useReducer((count) => count + 1, 0);
  const onExpireRef = useRef(onExpire);
  useEffect(() => { onExpireRef.current = onExpire; });

  const active = enabled && Number.isFinite(expiresAtMs);
  // eslint-disable-next-line react-hooks/purity -- the countdown is a function of the wall clock
  const remaining = active ? Math.max(0, Math.ceil((expiresAtMs - Date.now()) / 1000)) : null;
  const expired = remaining === 0;

  useEffect(() => {
    if (!active || expired) return undefined;
    const timer = setInterval(tick, TICK_MS);
    return () => clearInterval(timer);
  }, [active, expired, expiresAtMs]);

  useEffect(() => {
    if (expired) onExpireRef.current?.();
  }, [expired, expiresAtMs]);

  return remaining;
}
