"""Tests for the connect-time webhook SSRF transport."""

import asyncio
import socket
from unittest.mock import AsyncMock, patch

import httpcore
import pytest
from httpcore._backends.anyio import AnyIOBackend

from app.utils.safe_http_transport import PublicAddressBackend


def _address(ip: str, port: int = 443):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    sockaddr = (ip, port, 0, 0) if family == socket.AF_INET6 else (ip, port)
    return (family, socket.SOCK_STREAM, 6, "", sockaddr)


def test_connect_uses_the_validated_public_ip():
    backend = PublicAddressBackend()
    stream = object()
    connect = AsyncMock(return_value=stream)

    with patch("socket.getaddrinfo", return_value=[_address("93.184.216.34")]), \
         patch.object(AnyIOBackend, "connect_tcp", connect):
        result = asyncio.run(backend.connect_tcp("example.com", 443))

    assert result is stream
    connect.assert_awaited_once_with(
        "93.184.216.34",
        443,
        timeout=None,
        local_address=None,
        socket_options=None,
    )


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.1", "::1", "fc00::1"])
def test_connect_rejects_non_global_dns_answers(ip):
    backend = PublicAddressBackend()

    with patch("socket.getaddrinfo", return_value=[_address(ip)]), \
         patch.object(AnyIOBackend, "connect_tcp", AsyncMock()) as connect:
        with pytest.raises(httpcore.ConnectError):
            asyncio.run(backend.connect_tcp("attacker.example", 443))

    connect.assert_not_awaited()


def test_connect_rejects_mixed_public_and_private_dns_answers():
    backend = PublicAddressBackend()

    with patch(
        "socket.getaddrinfo",
        return_value=[_address("93.184.216.34"), _address("127.0.0.1")],
    ), patch.object(AnyIOBackend, "connect_tcp", AsyncMock()) as connect:
        with pytest.raises(httpcore.ConnectError):
            asyncio.run(backend.connect_tcp("attacker.example", 443))

    connect.assert_not_awaited()
