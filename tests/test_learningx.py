import unittest

from learningx_alert.learningx import LearningXClient, LearningXSessionError
from learningx_alert.models import CapabilityStatus
from learningx_alert.probe import probe_learningx
from tests.fakes import FakeCanvasForLti, StubLearningXClient


class LearningXSafetyTests(unittest.TestCase):
    def test_rejects_form_action_outside_allowed_hosts_before_post(self) -> None:
        canvas = FakeCanvasForLti(
            launch_url="https://learningx.example.edu/verify",
            html='<form action="https://evil.example/steal"><input name="token" value="secret"></form>',
        )
        client = LearningXClient(canvas, {"learningx.example.edu"}, resolve_public=False)
        with self.assertRaises(LearningXSessionError):
            client.attendance(7)
        self.assertFalse(canvas.posted_forms)

    def test_attendance_session_failure_does_not_hide_module_results(self) -> None:
        client = StubLearningXClient(attendance_error=True, modules=[{"module_items": []}])
        results = probe_learningx(client, [7])
        by_capability = {result.capability: result for result in results}
        self.assertEqual(by_capability["sessionless_launch"].status, CapabilityStatus.VERIFIED)
        self.assertEqual(by_capability["attendance"].status, CapabilityStatus.UNAVAILABLE)
        self.assertEqual(by_capability["completion_state"].status, CapabilityStatus.UNAVAILABLE)
        self.assertEqual(by_capability["lectures"].status, CapabilityStatus.VERIFIED)
        self.assertEqual(by_capability["required_materials"].status, CapabilityStatus.VERIFIED)

    def test_missing_learningx_cookie_raises_safe_code(self) -> None:
        canvas = FakeCanvasForLti(
            launch_url="https://learningx.example.edu/verify",
            html='<form action="/login"><input name="token" value="secret"></form>',
        )
        client = LearningXClient(canvas, {"learningx.example.edu"}, resolve_public=False)
        with self.assertRaisesRegex(LearningXSessionError, "learningx_token_missing"):
            client.attendance(7)

    def test_explicit_completion_field_is_verified(self) -> None:
        client = StubLearningXClient(
            attendance_error=False,
            attendance=[{"completed": True}],
            modules=[{"module_items": []}],
        )
        results = probe_learningx(client, [7])
        completion = next(result for result in results if result.capability == "completion_state")
        self.assertEqual(completion.status, CapabilityStatus.VERIFIED)
        self.assertEqual(completion.count, 1)

    def test_canvas_bearer_is_never_sent_to_learningx_host(self) -> None:
        canvas = FakeCanvasForLti.successful()
        LearningXClient(canvas, {"learningx.example.edu"}, resolve_public=False).attendance(7)
        self.assertTrue(all(request.bearer is None for request in canvas.external_requests))
