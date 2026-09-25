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
