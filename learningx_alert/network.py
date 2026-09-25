from __future__ import annotations

import ipaddress
import socket
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler


class UnsafeUrlError(ValueError):
    pass


def https_origin(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    try:
        port = parsed.port or 443
    except ValueError as error:
        raise UnsafeUrlError("destination port is invalid") from error
    return parsed.scheme, (parsed.hostname or "").lower(), port


def resolve_public_addresses(host: str, port: int) -> tuple[str, ...]:
    try:
        entries = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as error:
        raise UnsafeUrlError("destination address could not be resolved") from error
    addresses = tuple(
        dict.fromkeys(entry[4][0] for entry in entries)
    )
    try:
        public = addresses and all(ipaddress.ip_address(address).is_global for address in addresses)
    except ValueError as error:
        raise UnsafeUrlError("destination address is invalid") from error
    if not public:
        raise UnsafeUrlError("destination address is not public")
    return addresses


def validate_https_url(url: str, allowed_hosts: set[str], *, resolve_public: bool = True) -> str:
    parsed = urlsplit(url)
    scheme, host, port = https_origin(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or host not in allowed_hosts:
        raise UnsafeUrlError("destination is not allowed")
    if resolve_public:
        resolve_public_addresses(host, port)
    return url


class PinnedHTTPSConnection(HTTPSConnection):
    def __init__(self, host: str, *, pinned_address: str, **kwargs) -> None:
        super().__init__(host, **kwargs)
        self.pinned_address = pinned_address

    def connect(self) -> None:
        if self._tunnel_host:
            raise UnsafeUrlError("proxy tunnels are disabled")
        origin_host = self.host
        self.host = self.pinned_address
        try:
            HTTPConnection.connect(self)
        finally:
            self.host = origin_host
        self.sock = self._context.wrap_socket(self.sock, server_hostname=origin_host)


class PinnedHTTPSHandler(HTTPSHandler):
    def https_open(self, request):
        _, host, port = https_origin(request.full_url)
        address = resolve_public_addresses(host, port)[0]

        def connection_factory(request_host: str, **kwargs):
            return PinnedHTTPSConnection(request_host, pinned_address=address, **kwargs)

        return self.do_open(connection_factory, request, context=self._context)
