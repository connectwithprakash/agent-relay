"""
Dependencies for FastAPI dependency injection
"""
from .auth import get_api_key, require_relay_auth

__all__ = ["get_api_key", "require_relay_auth"]
