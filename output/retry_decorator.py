import functools
import logging
import random
import time
from typing import Any, Callable, Tuple, Type, TypeVar

F = TypeVar("F", bound=Callable[..., Any])
logger = logging.getLogger(__name__)


def retry(
    max_retries: int = 3,
    delay: float = 1.0,
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
    jitter: bool = True,
) -> Callable[[F], F]:
    """Decorator that retries a function with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts.
        delay: Base delay in seconds between retries.
        exceptions: Tuple of exception types to catch and retry on.
        jitter: If True, add random jitter to backoff to avoid thundering herd.

    Returns:
        A decorator that wraps the target function with retry logic.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: BaseException | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exception = exc
                    if attempt < max_retries:
                        wait_time = delay * (2 ** attempt)
                        if jitter:
                            wait_time *= random.uniform(0.5, 1.5)
                        logger.warning(
                            "Retry %d/%d for %s in %.2fs: %s",
                            attempt + 1,
                            max_retries,
                            func.__name__,
                            wait_time,
                            exc,
                        )
                        time.sleep(wait_time)
            raise last_exception  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s - %(message)s")
    call_count = 0

    @retry(max_retries=3, delay=0.1, exceptions=(ConnectionError,))
    def unreliable_fetch() -> str:
        global call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError(f"Attempt {call_count} failed")
        return f"Success on attempt {call_count}"

    result = unreliable_fetch()
    print(result)
