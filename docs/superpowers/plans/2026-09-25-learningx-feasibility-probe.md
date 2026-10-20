# LearningX Feasibility Probe Implementation Plan

> **과거 설계·구현 기록 (2026-10-20 분류):** 아래 상태·제약·체크리스트는 작성 당시의 기록이며 현재 실행할 작업 지시가 아니다. 현재 기능·지원 학교·한도는 [FEATURE_SPEC.md](../../../FEATURE_SPEC.md), 실제 계정 검증은 [FEASIBILITY.md](../../../FEASIBILITY.md), 작업 규칙·남은 일은 [HANDOFF](../../HANDOFF.md)를 따른다. 기존 도메인·SQLite·단일 학교·2계정 관문 등은 현재와 다를 수 있다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only command-line probe that proves which Canvas and LearningX data is available to two consenting student accounts without storing their tokens.

**Architecture:** A dependency-free Python package adapts the proven Canvas/LearningX request flow from `/Users/hjkim24/learningx-deadline-notifier` behind one strict HTTP boundary. The CLI prompts for a token with `getpass`, prints only safe summaries, and records no credentials; automated tests use fake openers and the two-account result is recorded manually in `FEASIBILITY.md`.

**Tech Stack:** Python 3.12 standard library, `urllib.request`, `http.cookiejar`, `argparse`, `getpass`, `dataclasses`, `unittest`

**Spec:** `docs/superpowers/specs/2026-09-25-learningx-alert-web-design.md`

## Global Constraints

- Support exactly one operator-configured Sungkyunkwan University Canvas origin during the pilot.
- Perform read-only requests; never submit assignments, alter attendance, or play lectures.
- Never accept the Canvas token as a command-line argument or write it to disk, logs, tracebacks, Git, or `FEASIBILITY.md`.
- Validate Canvas pagination links, sessionless-launch URLs, redirects, and LTI form actions before every request.
- Reject HTTP, userinfo-bearing URLs, non-allowlisted hosts, and loopback, private, link-local, reserved, multicast, or unspecified IP addresses.
- Send the Canvas bearer token only to the exact configured Canvas origin.
- Treat assignment, submission-state, attendance, module, and required-material checks independently; one failure must not hide other results.
- Record each capability as `verified`, `unavailable`, or `unverified`; never convert a failed lookup into an empty result.
- Use no Django, database, web UI, webhook, scheduler, or cloud deployment code before this feasibility gate is evaluated.
- Do not modify `/Users/hjkim24/learningx-deadline-notifier` or its secrets, workflow, and runtime state.

## Review Focus

- A Canvas `Link` header points off-origin or repeats a visited page: reject it before another request and report a safe pagination error.
- A sessionless-launch URL, redirect, or form action uses an unapproved or private destination: reject it without forwarding the Canvas bearer token or LTI form fields.
- A LearningX page has no usable form or no `xn_api_token` cookie: mark only that capability unavailable and continue the remaining probes.
- A submission-state request fails after assignment listing succeeds: report assignment listing as verified and submission state as unavailable, never as incomplete.
- A token-shaped sentinel appears in an exception or fake response: CLI output and raised public errors must not contain it.

---

### Task 1: Package and Safe CLI Entry

**Files:**
- Create: `pyproject.toml`
- Create: `learningx_alert/__init__.py`
- Create: `learningx_alert/feasibility.py`
- Create: `tests/__init__.py`
- Create: `tests/test_feasibility_cli.py`

**Interfaces:**
- Consumes: no project code.
- Produces: `build_parser() -> argparse.ArgumentParser`, `read_token(prompt: Callable[[str], str] = getpass.getpass) -> str`, and `main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing CLI tests**

```python
# tests/test_feasibility_cli.py
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
```

- [ ] **Step 2: Run the tests and verify the missing-module failure**

Run: `python3 -m unittest tests.test_feasibility_cli -v`

Expected: `ModuleNotFoundError: No module named 'learningx_alert'`.

- [ ] **Step 3: Add the package metadata and minimal CLI**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "learningx-alert-web"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []
```

```python
# learningx_alert/feasibility.py
from __future__ import annotations

import argparse
import getpass
import os
from collections.abc import Callable, Mapping, Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="learningx-feasibility")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("courses")
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("course_ids", metavar="COURSE_ID", type=int, nargs="+")
    return parser


def read_token(prompt: Callable[[str], str] = getpass.getpass) -> str:
    token = prompt("Canvas token: ").strip()
    if not token:
        raise ValueError("Canvas token is required")
    return token


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] = os.environ,
    prompt: Callable[[str], str] = getpass.getpass,
) -> int:
    args = build_parser().parse_args(argv)
    base_url = environ.get("CANVAS_BASE_URL", "").rstrip("/")
    if not base_url:
        raise ValueError("CANVAS_BASE_URL is required")
    read_token(prompt)
    print(f"{args.command}: probe not run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`learningx_alert/__init__.py` and `tests/__init__.py` remain empty.

- [ ] **Step 4: Run the CLI tests and verify they pass**

Run: `python3 -m unittest tests.test_feasibility_cli -v`

Expected: three tests pass and no entered token appears in output.

- [ ] **Step 5: Commit the safe CLI shell**

```bash
git add pyproject.toml learningx_alert/__init__.py learningx_alert/feasibility.py tests/__init__.py tests/test_feasibility_cli.py
git commit -m "feat: add safe feasibility CLI shell"
```

### Task 2: Strict HTTP Boundary and Canvas Discovery

**Files:**
- Create: `learningx_alert/network.py`
- Create: `learningx_alert/models.py`
- Create: `learningx_alert/canvas.py`
- Create: `tests/fakes.py`
- Create: `tests/test_network.py`
- Create: `tests/test_canvas.py`

**Interfaces:**
- Consumes: `CANVAS_BASE_URL` and the token returned by `read_token()`.
- Produces: `CanvasClient.profile() -> CanvasProfile`, `CanvasClient.courses() -> list[Course]`, and `CanvasClient.get_all(path: str, params: Sequence[tuple[str, str]] = ()) -> list[dict[str, Any]]`.

- [ ] **Step 1: Write failing URL and pagination tests**

```python
# tests/test_network.py
import unittest
from unittest.mock import patch

from learningx_alert.network import UnsafeUrlError, validate_https_url


class UrlValidationTests(unittest.TestCase):
    @patch("learningx_alert.network.socket.getaddrinfo")
    def test_rejects_private_resolution(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [(2, 1, 6, "", ("10.0.0.8", 443))]
        with self.assertRaises(UnsafeUrlError):
            validate_https_url("https://canvas.example.edu/api", {"canvas.example.edu"})

    @patch("learningx_alert.network.socket.getaddrinfo")
    def test_accepts_allowlisted_public_https_host(self, getaddrinfo) -> None:
        getaddrinfo.return_value = [(2, 1, 6, "", ("8.8.8.8", 443))]
        self.assertEqual(
            validate_https_url("https://canvas.example.edu/api", {"canvas.example.edu"}),
            "https://canvas.example.edu/api",
        )
```

```python
# tests/test_canvas.py
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
```

- [ ] **Step 2: Run the tests and verify undefined imports fail**

Run: `python3 -m unittest tests.test_network tests.test_canvas -v`

Expected: import failures for `learningx_alert.network` and `learningx_alert.canvas`.

- [ ] **Step 3: Implement URL validation, bounded responses, and Canvas pagination**

```python
# learningx_alert/models.py
from dataclasses import dataclass


@dataclass(frozen=True)
class CanvasProfile:
    id: int
    name: str


@dataclass(frozen=True)
class Course:
    id: int
    name: str
```

```python
# learningx_alert/network.py
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeUrlError(ValueError):
    pass


def validate_https_url(url: str, allowed_hosts: set[str], *, resolve_public: bool = True) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password or host not in allowed_hosts:
        raise UnsafeUrlError("destination is not allowed")
    if resolve_public:
        addresses = {entry[4][0] for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise UnsafeUrlError("destination address is not public")
    return url
```

```python
# learningx_alert/canvas.py
from __future__ import annotations

import json
import re
from collections.abc import Sequence
from http.cookiejar import CookieJar
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin, urlsplit
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
```

```python
# tests/fakes.py
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
```

- [ ] **Step 4: Run boundary and pagination tests**

Run: `python3 -m unittest tests.test_network tests.test_canvas -v`

Expected: all tests pass; off-origin and repeated pagination stop before a further request.

- [ ] **Step 5: Commit the Canvas discovery boundary**

```bash
git add learningx_alert/network.py learningx_alert/models.py learningx_alert/canvas.py tests/fakes.py tests/test_network.py tests/test_canvas.py
git commit -m "feat: add guarded Canvas discovery client"
```

### Task 3: Assignment and Submission-State Probe

**Files:**
- Modify: `learningx_alert/models.py`
- Modify: `learningx_alert/canvas.py`
- Create: `learningx_alert/probe.py`
- Create: `tests/test_canvas_probe.py`

**Interfaces:**
- Consumes: `CanvasClient.get_all()` and `CanvasClient._json()` from Task 2.
- Produces: `CapabilityStatus`, `CapabilityResult`, `CanvasClient.assignments(course_id: int)`, `CanvasClient.submission_state(course_id: int, assignment_id: int)`, and `probe_canvas(client: CanvasClient, course_ids: Sequence[int]) -> list[CapabilityResult]`.

- [ ] **Step 1: Write failing independent-capability tests**

```python
# tests/test_canvas_probe.py
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
```

- [ ] **Step 2: Run the focused probe tests and verify they fail**

Run: `python3 -m unittest tests.test_canvas_probe -v`

Expected: import failure for `learningx_alert.probe`.

- [ ] **Step 3: Implement safe capability results and independent checks**

```python
# additions to learningx_alert/models.py
from enum import StrEnum


class CapabilityStatus(StrEnum):
    VERIFIED = "verified"
    UNAVAILABLE = "unavailable"
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class CapabilityResult:
    course_id: int
    capability: str
    status: CapabilityStatus
    count: int | None = None
    reason: str = ""
```

```python
# additions to learningx_alert/canvas.py
    def assignments(self, course_id: int) -> list[dict[str, Any]]:
        return self.get_all(f"/api/v1/courses/{course_id}/assignments")

    def submission_state(self, course_id: int, assignment_id: int) -> str:
        payload, _, _ = self._json(
            f"{self.base_url}/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/self"
        )
        return str(payload.get("workflow_state") or "")
```

```python
# learningx_alert/probe.py
from __future__ import annotations

from collections.abc import Sequence

from .canvas import CanvasClient
from .models import CapabilityResult, CapabilityStatus


def probe_canvas(client: CanvasClient, course_ids: Sequence[int]) -> list[CapabilityResult]:
    results: list[CapabilityResult] = []
    for course_id in course_ids:
        try:
            assignments = client.assignments(course_id)
        except Exception:
            results.append(CapabilityResult(course_id, "assignments", CapabilityStatus.UNAVAILABLE, reason="assignments_failed"))
            results.append(CapabilityResult(course_id, "submission_state", CapabilityStatus.UNVERIFIED, reason="assignments_unavailable"))
            continue
        results.append(CapabilityResult(course_id, "assignments", CapabilityStatus.VERIFIED, count=len(assignments)))
        if not assignments:
            results.append(CapabilityResult(course_id, "submission_state", CapabilityStatus.VERIFIED, count=0))
            continue
        checked = 0
        try:
            for assignment in assignments:
                client.submission_state(course_id, int(assignment["id"]))
                checked += 1
        except Exception:
            results.append(CapabilityResult(course_id, "submission_state", CapabilityStatus.UNAVAILABLE, count=checked, reason="submission_state_failed"))
        else:
            results.append(CapabilityResult(course_id, "submission_state", CapabilityStatus.VERIFIED, count=checked))
    return results
```

Catch external failures at the capability boundary and replace them with fixed reason codes. Do not embed exception text in `CapabilityResult`.

- [ ] **Step 4: Run assignment and regression tests**

Run: `python3 -m unittest tests.test_canvas_probe tests.test_canvas -v`

Expected: all tests pass and the sentinel token is absent from result representations.

- [ ] **Step 5: Commit the Canvas capability probe**

```bash
git add learningx_alert/models.py learningx_alert/canvas.py learningx_alert/probe.py tests/test_canvas_probe.py
git commit -m "feat: probe assignments and submission state"
```

### Task 4: LearningX Session and Content Probe

**Files:**
- Create: `learningx_alert/learningx.py`
- Modify: `learningx_alert/probe.py`
- Create: `tests/test_learningx.py`
- Modify: `tests/fakes.py`

**Interfaces:**
- Consumes: the `CanvasClient` bearer-safe request boundary and `CapabilityResult` from earlier tasks.
- Produces: `LearningXClient(canvas: CanvasClient, allowed_hosts: set[str])`, `LearningXClient.sessionless_launch(course_id: int)`, `LearningXClient.attendance(course_id: int)`, `LearningXClient.modules(course_id: int)`, `flatten_module_items(modules)`, and `probe_learningx(client, course_ids) -> list[CapabilityResult]`.

- [ ] **Step 1: Write failing LTI safety and isolation tests**

```python
# tests/test_learningx.py
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
```

```python
# additions to tests/fakes.py
from types import SimpleNamespace


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
```

- [ ] **Step 2: Run the LearningX tests and verify they fail**

Run: `python3 -m unittest tests.test_learningx -v`

Expected: import failure for `learningx_alert.learningx`.

- [ ] **Step 3: Implement guarded sessionless launch and feature probes**

```python
# learningx_alert/learningx.py
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode, urljoin

from .canvas import CanvasClient
from .network import validate_https_url


FEATURE_LABELS = {
    "attendance": re.compile(r"강의[\s/·]*출결|출결현황|출석|attendance", re.I),
    "modules": re.compile(r"주차.*학습|모듈|강의콘텐츠|module", re.I),
}


class LearningXSessionError(RuntimeError):
    pass


class LtiFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.action = ""
        self.inputs: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if tag == "form" and not self.action:
            self.action = values.get("action") or ""
        if tag == "input" and values.get("name"):
            self.inputs.append((values["name"], values.get("value") or ""))


class LearningXClient:
    def __init__(self, canvas: CanvasClient, allowed_hosts: set[str], *, resolve_public: bool = True) -> None:
        self.canvas = canvas
        self.allowed_hosts = {host.lower() for host in allowed_hosts}
        self.resolve_public = resolve_public
        self.tokens: dict[tuple[int, str], str] = {}

    def _token(self, course_id: int, feature: str) -> str:
        key = (course_id, feature)
        if key in self.tokens:
            return self.tokens[key]
        tabs = self.canvas.json_path(f"/api/v1/courses/{course_id}/tabs?include[]=external")
        tab = next((entry for entry in tabs if FEATURE_LABELS[feature].search(entry.get("label", ""))), None)
        if not tab:
            raise LearningXSessionError("external_tool_missing")
        match = re.fullmatch(r"context_external_tool_(\d+)", str(tab.get("id") or ""))
        if not match:
            raise LearningXSessionError("external_tool_id_invalid")
        launch = self.canvas.json_path(
            f"/api/v1/courses/{course_id}/external_tools/sessionless_launch?id={match.group(1)}"
        )
        launch_url = validate_https_url(str(launch["url"]), self.allowed_hosts, resolve_public=self.resolve_public)
        html, page_url = self.canvas.open_external("GET", launch_url, allowed_hosts=self.allowed_hosts)
        parser = LtiFormParser()
        parser.feed(html.decode("utf-8", "replace"))
        if not parser.action or not parser.inputs:
            raise LearningXSessionError("lti_form_missing")
        action = validate_https_url(urljoin(page_url, parser.action), self.allowed_hosts, resolve_public=self.resolve_public)
        self.canvas.open_external(
            "POST", action, data=urlencode(parser.inputs).encode(), allowed_hosts=self.allowed_hosts
        )
        token = self.canvas.cookie_value("xn_api_token")
        if not token:
            raise LearningXSessionError("learningx_token_missing")
        self.tokens[key] = token
        return token

    def sessionless_launch(self, course_id: int) -> None:
        for feature in ("attendance", "modules"):
            try:
                self._token(course_id, feature)
            except Exception:
                continue
            return
        raise LearningXSessionError("sessionless_launch_failed")

    def attendance(self, course_id: int) -> list[dict[str, Any]]:
        token = self._token(course_id, "attendance")
        return self.canvas.external_json(
            f"{self.canvas.base_url}/learningx/api/v1/courses/{course_id}/allcomponents_db",
            bearer=token,
            allowed_hosts={self.canvas.canvas_host},
        )

    def modules(self, course_id: int) -> list[dict[str, Any]]:
        token = self._token(course_id, "modules")
        return self.canvas.external_json(
            f"{self.canvas.base_url}/learningx/api/v1/courses/{course_id}/modules",
            bearer=token,
            allowed_hosts={self.canvas.canvas_host},
        )


def flatten_module_items(modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for module in modules:
        for module_item in module.get("module_items") or module.get("items") or []:
            content = module_item.get("content_data") or module_item
            item_content = content.get("item_content_data") or {}
            items.append({
                "id": content.get("item_id") or module_item.get("module_item_id") or module_item.get("id"),
                "type": item_content.get("content_type") or module_item.get("content_type") or module_item.get("type") or "",
                "required": bool(module_item.get("required")),
                "completed": bool(module_item.get("completed")),
                "due_at": content.get("due_at") or module_item.get("due_at"),
            })
    return items
```

```python
# additions to CanvasClient in learningx_alert/canvas.py
    def json_path(self, path: str):
        payload, _, _ = self._json(f"{self.base_url}{path}")
        return payload

    def open_external(
        self,
        method: str,
        url: str,
        *,
        data: bytes | None = None,
        bearer: str | None = None,
        allowed_hosts: set[str],
    ) -> tuple[bytes, str]:
        current_url = url
        current_method = method
        current_data = data
        for _ in range(6):
            validate_https_url(current_url, allowed_hosts, resolve_public=self.resolve_public)
            headers = {"Accept": "application/json, text/html;q=0.9"}
            if bearer:
                headers["Authorization"] = f"Bearer {bearer}"
            if current_data is not None:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            request = Request(current_url, data=current_data, headers=headers, method=current_method)
            try:
                response = self.opener.open(request, timeout=30)
            except HTTPError as error:
                if error.code not in {301, 302, 303, 307, 308}:
                    raise
                location = error.headers.get("Location", "")
                if not location:
                    raise UnsafeUrlError("redirect has no destination") from error
                next_url = urljoin(current_url, location)
                validate_https_url(next_url, allowed_hosts, resolve_public=self.resolve_public)
                if bearer and urlsplit(next_url).netloc != urlsplit(current_url).netloc:
                    raise UnsafeUrlError("bearer redirect changed origin") from error
                if current_data is not None and error.code in {307, 308} and urlsplit(next_url).netloc != urlsplit(current_url).netloc:
                    raise UnsafeUrlError("form redirect changed origin") from error
                if error.code in {301, 302, 303}:
                    current_method, current_data = "GET", None
                current_url = next_url
                continue
            with response:
                final_url = response.geturl()
                validate_https_url(final_url, allowed_hosts, resolve_public=self.resolve_public)
                if urlsplit(final_url).netloc != urlsplit(current_url).netloc:
                    raise UnsafeUrlError("unexpected redirect")
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ValueError("response is too large")
                return body, final_url
        raise UnsafeUrlError("too many redirects")

    def external_json(self, url: str, *, bearer: str, allowed_hosts: set[str]):
        body, _ = self.open_external("GET", url, bearer=bearer, allowed_hosts=allowed_hosts)
        return json.loads(body)

    def cookie_value(self, name: str) -> str:
        return next((cookie.value for cookie in self.cookies if cookie.name == name), "")
```

`json_path()` is the only new helper that uses the Canvas bearer implicitly. Every `open_external()` call supplies its destination allowlist, and only `external_json()` supplies the LearningX bearer explicitly.

```python
# addition to learningx_alert/probe.py
from .learningx import flatten_module_items


MATERIAL_TYPES = {"pdf", "file", "document", "ppt", "pptx", "doc", "docx", "hwp", "xlsx", "xls"}


def probe_learningx(client, course_ids: Sequence[int]) -> list[CapabilityResult]:
    results: list[CapabilityResult] = []
    for course_id in course_ids:
        try:
            client.sessionless_launch(course_id)
        except Exception:
            results.append(CapabilityResult(course_id, "sessionless_launch", CapabilityStatus.UNAVAILABLE, reason="sessionless_launch_failed"))
        else:
            results.append(CapabilityResult(course_id, "sessionless_launch", CapabilityStatus.VERIFIED, count=1))
        try:
            attendance = client.attendance(course_id)
        except Exception:
            results.append(CapabilityResult(course_id, "attendance", CapabilityStatus.UNAVAILABLE, reason="attendance_failed"))
            results.append(CapabilityResult(course_id, "completion_state", CapabilityStatus.UNAVAILABLE, reason="attendance_failed"))
        else:
            results.append(CapabilityResult(course_id, "attendance", CapabilityStatus.VERIFIED, count=len(attendance)))
            completion_count = sum(1 for entry in attendance if "completed" in entry)
            completion_status = CapabilityStatus.VERIFIED if completion_count else CapabilityStatus.UNVERIFIED
            completion_reason = "" if completion_count else "no_completion_sample"
            results.append(CapabilityResult(course_id, "completion_state", completion_status, count=completion_count, reason=completion_reason))
        try:
            items = flatten_module_items(client.modules(course_id))
        except Exception:
            results.append(CapabilityResult(course_id, "lectures", CapabilityStatus.UNAVAILABLE, reason="modules_failed"))
            results.append(CapabilityResult(course_id, "required_materials", CapabilityStatus.UNAVAILABLE, reason="modules_failed"))
        else:
            materials = [item for item in items if str(item["type"]).lower() in MATERIAL_TYPES and item["required"]]
            results.append(CapabilityResult(course_id, "lectures", CapabilityStatus.VERIFIED, count=len(items)))
            results.append(CapabilityResult(course_id, "required_materials", CapabilityStatus.VERIFIED, count=len(materials)))
    return results
```

- [ ] **Step 4: Run the LearningX and regression tests**

Run: `python3 -m unittest tests.test_learningx tests.test_canvas_probe tests.test_canvas tests.test_network -v`

Expected: all tests pass; unsafe LTI actions are rejected before form POST and independent checks remain visible.

- [ ] **Step 5: Commit the LearningX probe**

```bash
git add learningx_alert/learningx.py learningx_alert/canvas.py learningx_alert/probe.py tests/fakes.py tests/test_learningx.py
git commit -m "feat: probe guarded LearningX capabilities"
```

### Task 5: Safe Reports and Operator Documentation

**Files:**
- Modify: `learningx_alert/feasibility.py`
- Create: `tests/test_report.py`
- Create: `README.md`
- Create: `FEASIBILITY.md`

**Interfaces:**
- Consumes: `CanvasClient`, `LearningXClient`, `probe_canvas()`, and `probe_learningx()`.
- Produces: `render_courses(courses: Sequence[Course]) -> str`, `render_results(results: Sequence[CapabilityResult]) -> str`, and working `courses` and `inspect` commands.

- [ ] **Step 1: Write failing output-redaction and status tests**

```python
# tests/test_report.py
import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from learningx_alert import feasibility
from learningx_alert.models import CapabilityResult, CapabilityStatus, Course
from learningx_alert.feasibility import render_courses, render_results


class ReportTests(unittest.TestCase):
    def test_course_output_contains_only_id_and_name(self) -> None:
        output = render_courses([Course(7, "Circuits")])
        self.assertEqual(output, "7\tCircuits")

    def test_results_use_fixed_status_and_reason_codes(self) -> None:
        output = render_results([
            CapabilityResult(7, "submission_state", CapabilityStatus.UNAVAILABLE, reason="submission_state_failed")
        ])
        self.assertEqual(output, "7\tsubmission_state\tunavailable\t-\tsubmission_state_failed")

    def test_token_shaped_text_is_not_rendered(self) -> None:
        output = render_results([
            CapabilityResult(7, "attendance", CapabilityStatus.UNAVAILABLE, reason="attendance_failed")
        ])
        self.assertNotIn("sentinel-token", output)

    @patch("learningx_alert.feasibility.main", side_effect=RuntimeError("sentinel-token"))
    def test_entrypoint_redacts_unexpected_errors(self, _main) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = feasibility.entrypoint([])
        self.assertEqual(code, 1)
        self.assertEqual(stderr.getvalue(), "검증 실패: probe_failed\n")
```

- [ ] **Step 2: Run the report tests and verify missing renderers fail**

Run: `python3 -m unittest tests.test_report -v`

Expected: import failure for `render_courses` and `render_results`.

- [ ] **Step 3: Wire commands and render only safe fields**

```python
# additions to learningx_alert/feasibility.py
def render_courses(courses) -> str:
    return "\n".join(f"{course.id}\t{course.name}" for course in courses)


def render_results(results) -> str:
    return "\n".join(
        f"{result.course_id}\t{result.capability}\t{result.status}\t"
        f"{result.count if result.count is not None else '-'}\t{result.reason or '-'}"
        for result in results
    )
```

```python
# replacement main flow in learningx_alert/feasibility.py
import sys

from .canvas import CanvasClient
from .learningx import LearningXClient
from .probe import probe_canvas, probe_learningx


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] = os.environ,
    prompt: Callable[[str], str] = getpass.getpass,
) -> int:
    args = build_parser().parse_args(argv)
    base_url = environ.get("CANVAS_BASE_URL", "").rstrip("/")
    if not base_url:
        raise ValueError("CANVAS_BASE_URL is required")
    token = read_token(prompt)
    canvas = CanvasClient(base_url, token)
    canvas.profile()
    print("Canvas connection: verified")
    courses = canvas.courses()
    if args.command == "courses":
        print(render_courses(courses))
        return 0

    requested = set(args.course_ids)
    owned = {course.id for course in courses}
    if not requested <= owned:
        raise ValueError("course_ids_not_owned")
    allowed_hosts = {
        host.strip().lower()
        for host in environ.get("LEARNINGX_ALLOWED_HOSTS", "").split(",")
        if host.strip()
    }
    if not allowed_hosts:
        raise ValueError("LEARNINGX_ALLOWED_HOSTS is required for inspect")
    learningx = LearningXClient(canvas, allowed_hosts)
    results = probe_canvas(canvas, args.course_ids) + probe_learningx(learningx, args.course_ids)
    print(render_results(results))
    return 0


def entrypoint(argv: Sequence[str] | None = None) -> int:
    try:
        return main(argv)
    except Exception:
        print("검증 실패: probe_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(entrypoint())
```

````markdown
# README.md
# LearningX Alert Web

The project is currently at the read-only two-account feasibility gate. It does not send notifications or store Canvas tokens.

## Run the probe

Set the operator-owned Canvas origin and, for LearningX inspection, the approved LearningX hostnames:

```bash
read -r -p 'Canvas base URL: ' CANVAS_BASE_URL
export CANVAS_BASE_URL
read -r -p 'Allowed LearningX hosts, comma-separated: ' LEARNINGX_ALLOWED_HOSTS
export LEARNINGX_ALLOWED_HOSTS
python3 -m learningx_alert.feasibility courses
read -r -p 'Course IDs to inspect, space-separated: ' LEARNINGX_COURSE_IDS
python3 -m learningx_alert.feasibility inspect $LEARNINGX_COURSE_IDS
```

The program prompts for the Canvas token without echoing it. Do not place the token in a command, `.env` file, screenshot, issue, or Git commit.

Run automated checks with:

```bash
python3 -m unittest discover -v
```
````

```markdown
# FEASIBILITY

## Safety conditions

- Scope: read-only Canvas and LearningX checks.
- Accounts: Account A and Account B, each used with voluntary consent.
- Credential handling: prompted in memory, not stored or copied into this file.
- Evidence: capability status and manually confirmed source-screen comparison only.

## Account A

| Check | Status | Evidence note |
| --- | --- | --- |
| Own course list is isolated | unverified | Awaiting approved live run |
| Assignment list | unverified | Awaiting approved live run |
| Own submission state | unverified | Awaiting approved live run |
| LearningX sessionless launch | unverified | Awaiting approved live run |
| Attendance and completion | unverified | Awaiting approved live run |
| Required materials | unverified | Awaiting approved live run |

## Account B

| Check | Status | Evidence note |
| --- | --- | --- |
| Own course list is isolated | unverified | Awaiting approved live run |
| Assignment list | unverified | Awaiting approved live run |
| Own submission state | unverified | Awaiting approved live run |
| LearningX sessionless launch | unverified | Awaiting approved live run |
| Attendance and completion | unverified | Awaiting approved live run |
| Required materials | unverified | Awaiting approved live run |

## Gate decision

Status: unverified. Public deployment and claims covering all LearningX lecture types remain blocked until both account sections contain verified or unavailable evidence.
```

- [ ] **Step 4: Run the complete automated suite and smoke help**

Run: `python3 -m unittest discover -v`

Expected: all tests pass.

Run: `python3 -m learningx_alert.feasibility --help`

Expected: help lists only `courses` and `inspect`; no token option exists.

- [ ] **Step 5: Scan tracked content and commit the operator workflow**

Run: `git grep -n -E 'CANVAS_ACCESS_TOKEN=|Bearer [A-Za-z0-9_-]{16,}|discord(app)?\.com/api/webhooks/[0-9]+/' -- . ':!docs/superpowers/plans/2026-09-25-learningx-feasibility-probe.md'`

Expected: no matches.

```bash
git add learningx_alert/feasibility.py tests/test_report.py README.md FEASIBILITY.md
git commit -m "docs: add two-account feasibility workflow"
```

### Task 6: Two-Account Read-Only Gate

**Files:**
- Modify: `FEASIBILITY.md`

**Interfaces:**
- Consumes: the completed probe and two voluntarily supplied Canvas tokens entered by their owners.
- Produces: a redacted gate decision that determines the scope of the Django implementation plan.

- [ ] **Step 1: Run Account A course discovery with explicit owner approval**

Run: `python3 -m learningx_alert.feasibility courses`

Expected: `Canvas connection: verified` followed only by Account A's active course IDs and names. Compare the list with Account A's LearningX screen without copying the token or raw API response.

- [ ] **Step 2: Run Account A capability inspection**

Run:

```bash
read -r -p 'Approved Account A course IDs, space-separated: ' LEARNINGX_COURSE_IDS
python3 -m learningx_alert.feasibility inspect $LEARNINGX_COURSE_IDS
```

Expected: one tab-separated `verified`, `unavailable`, or `unverified` row per course capability. Enter only IDs printed by Step 1; do not commit those IDs if the owner considers them sensitive.

- [ ] **Step 3: Repeat discovery and inspection for Account B**

Run the same two commands in a fresh process so no cookies or in-memory token state carry across accounts.

Expected: Account B sees only its own course list and receives independent capability results.

- [ ] **Step 4: Record redacted evidence and decide the gate**

Update each `FEASIBILITY.md` row to `verified` or `unavailable` and add a short evidence note such as `course count matched source UI` or `sessionless launch returned no usable form`. Do not paste names, tokens, URLs containing secrets, cookies, headers, or response bodies.

Set the gate decision to one of these exact outcomes:

- `pass`: both accounts verify assignments, own submission state, LearningX launch, attendance or completion, and required materials.
- `reduced-scope`: both accounts verify assignments and own submission state, but at least one LearningX-specific capability is unavailable.
- `blocked`: account isolation, assignment listing, or own submission state cannot be verified for both accounts.

- [ ] **Step 5: Review and commit the redacted gate result**

Run: `git diff --check`

Run: `git grep -n -E 'Bearer |access_token|xn_api_token|discord(app)?\.com/api/webhooks/' -- FEASIBILITY.md`

Expected: `git diff --check` succeeds and the secret-pattern scan has no matches.

```bash
git add FEASIBILITY.md
git commit -m "docs: record LearningX feasibility gate"
```

Stop after this commit. Use the recorded gate outcome to write the next implementation plan: full Django scope for `pass`, assignment-only scope for `reduced-scope`, or no public-service implementation for `blocked` without a separately approved investigation.
