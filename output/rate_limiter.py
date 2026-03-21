import threading
import time


class RateLimiter:
    """Token bucket rate limiter with per-key tracking."""

    _PRUNE_THRESHOLD = 10_000

    def __init__(self, rate: float, burst: int) -> None:
        self._rate = rate
        self._burst = burst
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Return True if the request for *key* is allowed, False otherwise."""
        now = time.monotonic()
        with self._lock:
            self._maybe_prune(now)

            if key in self._buckets:
                tokens, last_time = self._buckets[key]
                elapsed = now - last_time
                tokens = min(self._burst, tokens + elapsed * self._rate)
            else:
                tokens = float(self._burst)

            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                return True

            self._buckets[key] = (tokens, now)
            return False

    def _maybe_prune(self, now: float) -> None:
        """Remove stale keys when the bucket map grows too large."""
        if len(self._buckets) <= self._PRUNE_THRESHOLD:
            return
        cutoff = now - (self._burst / self._rate) - 60
        self._buckets = {
            k: v for k, v in self._buckets.items() if v[1] > cutoff
        }
