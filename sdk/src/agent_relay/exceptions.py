"""Exception classes for Agent Relay SDK."""
from typing import Optional


class AgentRelayError(Exception):
    """Base exception for Agent Relay SDK errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class NotYourTurnError(AgentRelayError):
    """Raised when an agent tries to send a message out of turn."""

    def __init__(self, message: str = "It is not your turn to send a message"):
        super().__init__(message, status_code=400)


class RelayNotFoundError(AgentRelayError):
    """Raised when a relay is not found."""

    def __init__(self, relay_id: str = ""):
        msg = f"Relay not found: {relay_id}" if relay_id else "Relay not found"
        super().__init__(msg, status_code=404)


class AuthenticationError(AgentRelayError):
    """Raised on authentication/authorization failures."""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, status_code=401)


class RateLimitError(AgentRelayError):
    """Raised when the API rate limit is exceeded."""

    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(message, status_code=429)
