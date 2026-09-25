from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from urllib.request import Request


@dataclass
class FakeResponse:
    url: str
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def geturl(self) -> str:
        return self.url

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]


class FakeOpener:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[Request] = []

    def open(self, request: Request, timeout: int = 30) -> FakeResponse:
        self.requests.append(request)
        return self.responses.pop(0)


class FakeCanvasForLti:
    base_url = "https://canvas.example.edu"
    canvas_host = "canvas.example.edu"

    def __init__(self, *, launch_url: str, html: str, cookie: str = "") -> None:
        self.launch_url = launch_url
        self.html = html.encode()
        self.cookie = cookie
        self.external_requests: list[SimpleNamespace] = []
        self.posted_forms: list[bytes] = []

    @classmethod
    def successful(cls):
        return cls(
            launch_url="https://learningx.example.edu/verify",
            html='<form action="/login"><input name="token" value="secret"></form>',
            cookie="learningx-session-token",
        )

    def json_path(self, path: str):
        if "/tabs" in path:
            return [{"label": "강의/출결", "id": "context_external_tool_42"}]
        return {"url": self.launch_url}

    def open_external(self, method: str, url: str, *, data=None, bearer=None, allowed_hosts=None):
        request = SimpleNamespace(method=method, url=url, data=data, bearer=bearer, headers={})
        self.external_requests.append(request)
        if data is not None:
            self.posted_forms.append(data)
        return (self.html if method == "GET" else b""), url

    def cookie_value(self, name: str) -> str:
        return self.cookie if name == "xn_api_token" else ""

    def external_json(self, url: str, *, bearer: str, allowed_hosts: set[str]):
        return []


class StubLearningXClient:
    def __init__(self, *, attendance_error: bool, modules: list[dict], attendance=None) -> None:
        self.attendance_error = attendance_error
        self.attendance_payload = attendance or []
        self.module_payload = modules

    def sessionless_launch(self, course_id: int) -> None:
        return None

    def attendance(self, course_id: int):
        if self.attendance_error:
            raise RuntimeError("attendance unavailable")
        return self.attendance_payload

    def modules(self, course_id: int):
        return self.module_payload
