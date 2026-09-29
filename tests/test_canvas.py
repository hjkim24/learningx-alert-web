import unittest

from learningx_alert.canvas import CanvasClient, PaginationError
from tests.fakes import FakeOpener, FakeResponse


class CanvasClientTests(unittest.TestCase):
    def test_courses_follow_same_origin_pagination(self) -> None:
        opener = FakeOpener([
            FakeResponse(
                url="https://canvas.example.edu/api/v1/courses?per_page=100&enrollment_state=active",
                body=b'[{"id": 1, "name": "A"}]',
                headers={"Link": '<https://canvas.example.edu/api/v1/courses?page=2>; rel="next"'},
            ),
            FakeResponse(
                url="https://canvas.example.edu/api/v1/courses?page=2",
                body=b'[{"id": 2, "name": "B"}]',
            ),
        ])
        client = CanvasClient("https://canvas.example.edu", "sentinel-token", opener=opener, resolve_public=False)
        self.assertEqual([course.id for course in client.courses()], [1, 2])
        self.assertTrue(all(request.headers["Authorization"] == "Bearer sentinel-token" for request in opener.requests))

    def test_courses_request_and_parse_term(self) -> None:
        opener = FakeOpener([
            FakeResponse(
                url="https://canvas.example.edu/api/v1/courses",
                body=(
                    '[{"id": 1, "name": "A", "term": {"name": "2026년  2학기", "start_at": "2026-08-07T15:00:00Z", "end_at": null}},'
                    ' {"id": 2, "name": "B", "term": {"name": "2021년 비정규", "start_at": "bad"}},'
                    ' {"id": 3, "name": "C"}]'
                ).encode(),
            ),
        ])
        client = CanvasClient("https://canvas.example.edu", "t", opener=opener, resolve_public=False)

        courses = client.courses()

        self.assertIn("include%5B%5D=term", opener.requests[0].full_url)
        self.assertEqual(courses[0].term_name, "2026년 2학기")
        self.assertEqual(courses[0].term_start_at.isoformat(), "2026-08-07T15:00:00+00:00")
        self.assertEqual((courses[1].term_name, courses[1].term_start_at), ("2021년 비정규", None))
        self.assertEqual((courses[2].term_name, courses[2].term_start_at), ("", None))

    def test_rejects_off_origin_next_link_before_request(self) -> None:
        opener = FakeOpener([
            FakeResponse(
                url="https://canvas.example.edu/api/v1/courses?per_page=100&enrollment_state=active",
                body=b"[]",
                headers={"Link": '<https://evil.example/api?page=2>; rel="next"'},
            )
        ])
        client = CanvasClient("https://canvas.example.edu", "sentinel-token", opener=opener, resolve_public=False)
        with self.assertRaises(PaginationError):
            client.courses()
        self.assertEqual(len(opener.requests), 1)

    def test_rejects_same_host_on_changed_port_before_request(self) -> None:
        opener = FakeOpener([
            FakeResponse(
                url="https://canvas.example.edu/api/v1/courses?per_page=100&enrollment_state=active",
                body=b"[]",
                headers={"Link": '<https://canvas.example.edu:8443/api?page=2>; rel="next"'},
            ),
            FakeResponse(url="https://canvas.example.edu:8443/api?page=2", body=b"[]"),
        ])
        client = CanvasClient("https://canvas.example.edu", "sentinel-token", opener=opener, resolve_public=False)
        with self.assertRaises(PaginationError):
            client.courses()
        self.assertEqual(len(opener.requests), 1)

    def test_rejects_repeated_next_link(self) -> None:
        repeated = "https://canvas.example.edu/api/v1/courses?page=2"
        opener = FakeOpener([
            FakeResponse(
                url="https://canvas.example.edu/api/v1/courses?per_page=100&enrollment_state=active",
                body=b"[]",
                headers={"Link": f'<{repeated}>; rel="next"'},
            ),
            FakeResponse(url=repeated, body=b"[]", headers={"Link": f'<{repeated}>; rel="next"'}),
        ])
        client = CanvasClient("https://canvas.example.edu", "sentinel-token", opener=opener, resolve_public=False)
        with self.assertRaises(PaginationError):
            client.courses()
