import unittest
from http.client import HTTPConnection
from urllib.request import Request
from unittest.mock import Mock
from unittest.mock import patch

from learningx_alert.network import (
    PinnedHTTPSConnection,
    PinnedHTTPSHandler,
    UnsafeUrlError,
    validate_https_url,
)


class UrlValidationTests(unittest.TestCase):
    @patch("learningx_alert.network.socket.getaddrinfo")
    def test_rejects_private_resolution(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [(2, 1, 6, "", ("10.0.0.8", 443))]
        with self.assertRaises(UnsafeUrlError):
            validate_https_url("https://canvas.example.edu/api", {"canvas.example.edu"})

    @patch("learningx_alert.network.socket.getaddrinfo")
    def test_accepts_allowlisted_public_https_host(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [(2, 1, 6, "", ("8.8.8.8", 443))]
        self.assertEqual(
            validate_https_url("https://canvas.example.edu/api", {"canvas.example.edu"}),
            "https://canvas.example.edu/api",
        )

    @patch("learningx_alert.network.socket.getaddrinfo")
    def test_rejects_address_that_rebinds_before_connection(self, getaddrinfo) -> None:
        getaddrinfo.side_effect = [
            [(2, 1, 6, "", ("8.8.8.8", 443))],
            [(2, 1, 6, "", ("10.0.0.8", 443))],
        ]
        url = "https://canvas.example.edu/api"
        validate_https_url(url, {"canvas.example.edu"})
        with self.assertRaises(UnsafeUrlError):
            PinnedHTTPSHandler().https_open(Request(url))

    def test_pinned_connection_uses_ip_but_keeps_hostname_for_tls(self) -> None:
        context = Mock()
        socket = Mock()
        connected_hosts: list[str] = []

        def connect(connection) -> None:
            connected_hosts.append(connection.host)
            connection.sock = socket

        connection = PinnedHTTPSConnection(
            "canvas.example.edu",
            pinned_address="8.8.8.8",
            context=context,
        )
        with patch.object(HTTPConnection, "connect", connect):
            connection.connect()

        self.assertEqual(connected_hosts, ["8.8.8.8"])
        context.wrap_socket.assert_called_once_with(socket, server_hostname="canvas.example.edu")
