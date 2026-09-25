import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from learningx_alert import feasibility
from learningx_alert.feasibility import render_courses, render_results
from learningx_alert.models import CapabilityResult, CapabilityStatus, Course


class ReportTests(unittest.TestCase):
    def test_course_output_contains_only_id_and_name(self) -> None:
        output = render_courses([Course(7, "Circuits")])
        self.assertEqual(output, "7\tCircuits")

    def test_results_use_fixed_status_and_reason_codes(self) -> None:
        output = render_results(
            [
                CapabilityResult(
                    7,
                    "submission_state",
                    CapabilityStatus.UNAVAILABLE,
                    reason="submission_state_failed",
                )
            ]
        )
        self.assertEqual(output, "7\tsubmission_state\tunavailable\t-\tsubmission_state_failed")

    def test_token_shaped_text_is_not_rendered(self) -> None:
        output = render_results(
            [
                CapabilityResult(
                    7,
                    "attendance",
                    CapabilityStatus.UNAVAILABLE,
                    reason="attendance_failed",
                )
            ]
        )
        self.assertNotIn("sentinel-token", output)

    @patch("learningx_alert.feasibility.main", side_effect=RuntimeError("sentinel-token"))
    def test_entrypoint_redacts_unexpected_errors(self, _main) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = feasibility.entrypoint([])
        self.assertEqual(code, 1)
        self.assertEqual(stderr.getvalue(), "검증 실패: probe_failed\n")
