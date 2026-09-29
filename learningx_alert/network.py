from __future__ import annotations

import ipaddress
import socket
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler

from opentelemetry import trace

_tracer = trace.get_tracer("learningx_alert.network")


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
        method = request.get_method()
        # One client span per outbound call. Host only, never the path or query:
        # webhook and push URLs carry their credential in the path.
        with _tracer.start_as_current_span(
            f"HTTPS {method} {host}",
            kind=trace.SpanKind.CLIENT,
            attributes={
                "server.address": host,
                "server.port": port,
                "http.request.method": method,
            },
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                address = resolve_public_addresses(host, port)[0]

                def connection_factory(request_host: str, **kwargs):
                    return PinnedHTTPSConnection(request_host, pinned_address=address, **kwargs)

                response = self.do_open(connection_factory, request, context=self._context)
            except Exception as error:
                # The class name only; messages can echo the URL.
                span.set_attribute("error.type", type(error).__name__)
                span.set_status(trace.StatusCode.ERROR)
                raise
            status = getattr(response, "status", None)
            if status is not None:
                span.set_attribute("http.response.status_code", status)
                if status >= 400:
                    span.set_attribute("error.type", str(status))
                    span.set_status(trace.StatusCode.ERROR)
            return response
