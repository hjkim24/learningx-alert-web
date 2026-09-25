from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Callable, Mapping, Sequence

from .canvas import CanvasClient
from .learningx import LearningXClient
from .probe import probe_canvas, probe_learningx


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid arguments\n")


def build_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(prog="learningx-feasibility")
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


def render_courses(courses) -> str:
    return "\n".join(f"{course.id}\t{course.name}" for course in courses)


def render_results(results) -> str:
    return "\n".join(
        f"{result.course_id}\t{result.capability}\t{result.status}\t"
        f"{result.count if result.count is not None else '-'}\t{result.reason or '-'}"
        for result in results
    )


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
