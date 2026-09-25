from __future__ import annotations

import json
import re
from collections.abc import Sequence
from http.cookiejar import CookieJar
from typing import Any
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener

from .models import CanvasProfile, Course
from .network import UnsafeUrlError, validate_https_url


MAX_RESPONSE_BYTES = 5 * 1024 * 1024


class PaginationError(RuntimeError):
    pass


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


class CanvasClient:
    def __init__(self, base_url: str, token: str, *, opener=None, resolve_public: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        parsed = urlsplit(self.base_url)
        self.canvas_host = (parsed.hostname or "").lower()
        validate_https_url(self.base_url, {self.canvas_host}, resolve_public=resolve_public)
        self.token = token
        self.cookies = CookieJar()
        self.opener = opener or build_opener(HTTPCookieProcessor(self.cookies), NoRedirectHandler())
        self.resolve_public = resolve_public

    def _json(self, url: str) -> tuple[Any, dict[str, str], str]:
        validate_https_url(url, {self.canvas_host}, resolve_public=self.resolve_public)
        request = Request(url, headers={"Accept": "application/json", "Authorization": f"Bearer {self.token}"})
        with self.opener.open(request, timeout=30) as response:
            final_url = response.geturl()
            validate_https_url(final_url, {self.canvas_host}, resolve_public=self.resolve_public)
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError("response is too large")
            return json.loads(body), dict(response.headers.items()), final_url

    def get_all(self, path: str, params: Sequence[tuple[str, str]] = ()) -> list[dict[str, Any]]:
        url = f"{self.base_url}{path}?{urlencode([('per_page', '100'), *params])}"
        visited: set[str] = set()
        results: list[dict[str, Any]] = []
        while url:
            if url in visited:
                raise PaginationError("Canvas pagination repeated a URL")
            visited.add(url)
            try:
                page, headers, _ = self._json(url)
            except UnsafeUrlError as error:
                raise PaginationError("Canvas pagination left the configured origin") from error
            results.extend(page)
            match = re.search(r'<([^>]+)>;\s*rel="next"', headers.get("Link", ""))
            url = match.group(1) if match else ""
        return results

    def profile(self) -> CanvasProfile:
        payload, _, _ = self._json(f"{self.base_url}/api/v1/users/self/profile")
        return CanvasProfile(id=int(payload["id"]), name=str(payload.get("name") or ""))

    def courses(self) -> list[Course]:
        payload = self.get_all("/api/v1/courses", (("enrollment_state", "active"),))
        return [Course(id=int(entry["id"]), name=str(entry.get("name") or "")) for entry in payload]

    def assignments(self, course_id: int) -> list[dict[str, Any]]:
        return self.get_all(f"/api/v1/courses/{course_id}/assignments")

    def submission_state(self, course_id: int, assignment_id: int) -> str:
        payload, _, _ = self._json(
            f"{self.base_url}/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/self"
        )
        return str(payload.get("workflow_state") or "")
