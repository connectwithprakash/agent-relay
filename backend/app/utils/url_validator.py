"""
URL validation utilities to prevent SSRF attacks.

Validates webhook URLs to ensure they don't target internal/private networks.
"""
import ipaddress
import socket
from urllib.parse import urlparse

from ..config import settings


_BLOCKED_HOSTNAMES = {"localhost"}


def _is_private_ip(ip_str: str) -> bool:
    """Return whether an address is unsafe as an outbound webhook target."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    # is_global covers both address families and rejects loopback, private,
    # link-local, unspecified, multicast, reserved, and IPv4-mapped variants.
    return not addr.is_global


def validate_webhook_url(url: str) -> bool:
    """
    Validate a webhook URL to prevent SSRF attacks.

    Returns True if the URL is safe, False otherwise.
    In development mode (ENVIRONMENT=development), all URLs are allowed.
    """
    if settings.environment == "development":
        return True

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    # Only allow http and https schemes
    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    # Block known private hostnames
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        return False

    # Check if hostname is a raw IP address in a blocked range
    if _is_private_ip(hostname):
        return False

    # Resolve hostname and check resolved IPs
    try:
        resolved = socket.getaddrinfo(hostname, None)
        for _family, _type, _proto, _canonname, sockaddr in resolved:
            ip_str = sockaddr[0]
            if _is_private_ip(ip_str):
                return False
    except socket.gaierror:
        # Cannot resolve hostname - allow it (will fail at delivery time)
        pass

    return True
