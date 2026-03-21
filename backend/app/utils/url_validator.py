"""
URL validation utilities to prevent SSRF attacks.

Validates webhook URLs to ensure they don't target internal/private networks.
"""
import ipaddress
import os
import socket
from urllib.parse import urlparse


# Private IP ranges that should be blocked in production
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("10.0.0.0/8"),         # Private Class A
    ipaddress.ip_network("172.16.0.0/12"),      # Private Class B
    ipaddress.ip_network("192.168.0.0/16"),     # Private Class C
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local
    ipaddress.ip_network("0.0.0.0/8"),          # Current network
]

_BLOCKED_HOSTNAMES = {"localhost"}


def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address falls within a blocked private range."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(addr in network for network in _BLOCKED_NETWORKS)


def validate_webhook_url(url: str) -> bool:
    """
    Validate a webhook URL to prevent SSRF attacks.

    Returns True if the URL is safe, False otherwise.
    In development mode (ENVIRONMENT=development), all URLs are allowed.
    """
    if os.environ.get("ENVIRONMENT") == "development":
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
