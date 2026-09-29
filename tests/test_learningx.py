import unittest

from learningx_alert.learningx import LearningXClient, LearningXSessionError, select_feature_tab
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
        self.assertEqual(by_capability["required_materials"].status, CapabilityStatus.UNVERIFIED)

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

    def test_null_and_malformed_completion_fields_are_unverified(self) -> None:
        client = StubLearningXClient(
            attendance_error=False,
            attendance=[{"completed": None}, {"completed": {}}, {"completed": "maybe"}],
            modules=[{"module_items": []}],
        )
        results = probe_learningx(client, [7])
        completion = next(result for result in results if result.capability == "completion_state")
        self.assertEqual(completion.status, CapabilityStatus.UNVERIFIED)
        self.assertEqual(completion.count, 0)
        self.assertEqual(completion.reason, "no_completion_sample")

    def test_required_material_needs_positive_sample(self) -> None:
        empty_client = StubLearningXClient(attendance_error=False, modules=[{"module_items": []}])
        empty_result = next(
            result
            for result in probe_learningx(empty_client, [7])
            if result.capability == "required_materials"
        )
        self.assertEqual(empty_result.status, CapabilityStatus.UNVERIFIED)
        self.assertEqual(empty_result.reason, "no_required_material_sample")

        positive_client = StubLearningXClient(
            attendance_error=False,
            modules=[
                {
                    "module_items": [
                        {
                            "required": True,
                            "content_data": {"item_content_data": {"content_type": "pdf"}},
                        }
                    ]
                }
            ],
        )
        positive_result = next(
            result
            for result in probe_learningx(positive_client, [7])
            if result.capability == "required_materials"
        )
        self.assertEqual(positive_result.status, CapabilityStatus.VERIFIED)
        self.assertEqual(positive_result.count, 1)

    def test_posts_only_inputs_from_selected_lti_form(self) -> None:
        canvas = FakeCanvasForLti(
            launch_url="https://learningx.example.edu/verify",
            html=(
                '<form action="/login"><input name="good" value="one"></form>'
                '<form action="/other"><input name="bad" value="two"></form>'
            ),
            cookie="learningx-session-token",
        )
        LearningXClient(canvas, {"learningx.example.edu"}, resolve_public=False).attendance(7)
        self.assertEqual(canvas.posted_forms, [b"good=one"])

    def test_canvas_bearer_is_never_sent_to_learningx_host(self) -> None:
        canvas = FakeCanvasForLti.successful()
        LearningXClient(canvas, {"learningx.example.edu"}, resolve_public=False).attendance(7)
        self.assertTrue(all(request.bearer is None for request in canvas.external_requests))


class FeatureTabSelectionTests(unittest.TestCase):
    """Labels observed on real SKKU Canvas courses (2021 English/Korean, 2026 Korean)."""

    def labels(self, *labels):
        return [{"id": f"context_external_tool_{index}", "label": label} for index, label in enumerate(labels)]

    def test_english_legacy_course_finds_lecture_contents_and_learn_status(self) -> None:
        tabs = self.labels(
            "Lecture Resources", "Open Board", "Q&A Board", "(Old) Lecture Contents",
            "ClassMix", "Zoom", "Learn Status", "GradeScope",
        )
        self.assertEqual(select_feature_tab(tabs, "modules")["label"], "(Old) Lecture Contents")
        self.assertEqual(select_feature_tab(tabs, "attendance")["label"], "Learn Status")

    def test_korean_courses_old_and_new(self) -> None:
        old = self.labels("수업자료실", "(구) 강의콘텐츠", "출결/학습 현황", "GradeScope")
        new = self.labels("게시판", "강의콘텐츠", "출결현황", "학습 활동 분석", "GradeScope")
        self.assertEqual(select_feature_tab(old, "modules")["label"], "(구) 강의콘텐츠")
        self.assertEqual(select_feature_tab(old, "attendance")["label"], "출결/학습 현황")
        self.assertEqual(select_feature_tab(new, "modules")["label"], "강의콘텐츠")
        self.assertEqual(select_feature_tab(new, "attendance")["label"], "출결현황")

    def test_current_tool_is_preferred_over_legacy(self) -> None:
        tabs = self.labels("(구) 강의콘텐츠", "강의콘텐츠")
        self.assertEqual(select_feature_tab(tabs, "modules")["label"], "강의콘텐츠")

    def test_unrelated_tabs_do_not_match(self) -> None:
        tabs = self.labels("게시판", "학습 활동 분석", "GradeScope", "Zoom")
        self.assertIsNone(select_feature_tab(tabs, "modules"))
