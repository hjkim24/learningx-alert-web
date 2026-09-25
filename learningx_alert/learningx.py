from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode, urljoin

from .canvas import CanvasClient
from .network import UnsafeUrlError, validate_https_url


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
        try:
            launch_url = validate_https_url(
                str(launch["url"]),
                self.allowed_hosts,
                resolve_public=self.resolve_public,
            )
            html, page_url = self.canvas.open_external(
                "GET",
                launch_url,
                allowed_hosts=self.allowed_hosts,
            )
            parser = LtiFormParser()
            parser.feed(html.decode("utf-8", "replace"))
            if not parser.action or not parser.inputs:
                raise LearningXSessionError("lti_form_missing")
            action = validate_https_url(
                urljoin(page_url, parser.action),
                self.allowed_hosts,
                resolve_public=self.resolve_public,
            )
            self.canvas.open_external(
                "POST",
                action,
                data=urlencode(parser.inputs).encode(),
                allowed_hosts=self.allowed_hosts,
            )
        except UnsafeUrlError as error:
            raise LearningXSessionError("unsafe_lti_url") from error
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
            items.append(
                {
                    "id": content.get("item_id") or module_item.get("module_item_id") or module_item.get("id"),
                    "type": item_content.get("content_type")
                    or module_item.get("content_type")
                    or module_item.get("type")
                    or "",
                    "required": bool(module_item.get("required")),
                    "completed": bool(module_item.get("completed")),
                    "due_at": content.get("due_at") or module_item.get("due_at"),
                }
            )
    return items
