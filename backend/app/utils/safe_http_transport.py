"""HTTP transport that prevents DNS-rebinding SSRF at connect time."""

import socket
from typing import Iterable

import httpcore
import httpx
from anyio import to_thread
from httpcore._backends.anyio import AnyIOBackend
from httpcore._backends.base import SOCKET_OPTION, AsyncNetworkStream

from .url_validator import _is_private_ip


class PublicAddressBackend(AnyIOBackend):
    """Resolve once, reject non-global addresses, and connect to that exact IP."""

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> AsyncNetworkStream:
        try:
            addresses = await to_thread.run_sync(
                lambda: socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            )
        except socket.gaierror as exc:
            raise httpcore.ConnectError(f"Unable to resolve webhook host: {host}") from exc

        public_ips = []
        for _family, _socktype, _proto, _canonname, sockaddr in addresses:
            ip = str(sockaddr[0])
            if not _is_private_ip(ip) and ip not in public_ips:
                public_ips.append(ip)

        # Reject the entire hostname if DNS returned even one unsafe destination.
        if not public_ips or len(public_ips) != len({str(item[4][0]) for item in addresses}):
            raise httpcore.ConnectError("Webhook host resolves to a non-global address")

        # HTTP Core retains the original hostname for Host and TLS SNI/certificate
        # verification; only the TCP destination is replaced with a vetted IP.
        # Try every safe answer so dual-stack hosts retain normal DNS fallback.
        last_error: httpcore.ConnectError | None = None
        for ip in public_ips:
            try:
                return await super().connect_tcp(
                    ip,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except httpcore.ConnectError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error


class SafeAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    """HTTPX transport whose connection pool uses PublicAddressBackend."""

    def __init__(self, *, limits: httpx.Limits) -> None:
        super().__init__(limits=limits, trust_env=False)
        self._pool._network_backend = PublicAddressBackend()
