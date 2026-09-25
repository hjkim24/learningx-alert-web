import unittest

from learningx_alert.models import CapabilityStatus
from learningx_alert.probe import probe_canvas


class StubCanvasClient:
    def assignments(self, course_id: int):
        return [{"id": 11, "name": "Report"}]

    def submission_state(self, course_id: int, assignment_id: int) -> str:
        raise RuntimeError("sentinel-token must not escape")


class CanvasProbeTests(unittest.TestCase):
    def test_submission_failure_does_not_erase_assignment_success(self) -> None:
        results = probe_canvas(StubCanvasClient(), [7])
        by_capability = {result.capability: result for result in results}
        self.assertEqual(by_capability["assignments"].status, CapabilityStatus.VERIFIED)
        self.assertEqual(by_capability["assignments"].count, 1)
        self.assertEqual(by_capability["submission_state"].status, CapabilityStatus.UNAVAILABLE)
        self.assertEqual(by_capability["submission_state"].reason, "submission_state_failed")
        self.assertNotIn("sentinel-token", repr(results))

    def test_empty_assignment_list_is_verified_not_unavailable(self) -> None:
        class EmptyClient(StubCanvasClient):
            def assignments(self, course_id: int):
                return []

        result = probe_canvas(EmptyClient(), [7])[0]
        self.assertEqual(result.status, CapabilityStatus.VERIFIED)
        self.assertEqual(result.count, 0)
