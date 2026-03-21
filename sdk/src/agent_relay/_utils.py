"""Shared utilities for sync and async clients."""

import httpx

from .exceptions import (
    AgentRelayError,
    AuthenticationError,
    NotYourTurnError,
    RateLimitError,
    RelayNotFoundError,
)


def raise_for_status(response: httpx.Response) -> None:
    """Convert HTTP error responses into typed SDK exceptions."""
    if response.is_success:
        return

    detail = ""
    try:
        body = response.json()
        detail = body.get("detail", "")
    except Exception:
        detail = response.text

    status = response.status_code
    if status == 400:
        if "turn" in detail.lower():
            raise NotYourTurnError(detail)
        raise AgentRelayError(detail, status_code=status)
    if status == 401 or status == 403:
        raise AuthenticationError(detail)
    if status == 404:
        raise RelayNotFoundError(detail)
    if status == 429:
        raise RateLimitError(detail)
    raise AgentRelayError(detail, status_code=status)
