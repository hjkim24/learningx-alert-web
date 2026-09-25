from __future__ import annotations

from dataclasses import dataclass, field
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
