import io
import unittest
from contextlib import redirect_stderr

from learningx_alert import feasibility


class FeasibilityCliTests(unittest.TestCase):
    def test_read_token_rejects_blank_input(self) -> None:
        with self.assertRaisesRegex(ValueError, "Canvas token is required"):
            feasibility.read_token(lambda _: "   ")

    def test_parser_never_accepts_token_argument(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit):
            feasibility.build_parser().parse_args(["courses", "--token", "secret"])
        self.assertNotIn("secret", stderr.getvalue())

    def test_main_requires_operator_canvas_origin(self) -> None:
        with self.assertRaisesRegex(ValueError, "CANVAS_BASE_URL"):
            feasibility.main(["courses"], environ={}, prompt=lambda _: "token")
