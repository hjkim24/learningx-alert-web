import unittest
from unittest.mock import patch

from learningx_alert.network import UnsafeUrlError, validate_https_url


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
