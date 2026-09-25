from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeUrlError(ValueError):
    pass


def validate_https_url(url: str, allowed_hosts: set[str], *, resolve_public: bool = True) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password or host not in allowed_hosts:
        raise UnsafeUrlError("destination is not allowed")
    if resolve_public:
        addresses = {entry[4][0] for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise UnsafeUrlError("destination address is not public")
    return url
