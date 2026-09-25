from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Callable, Mapping, Sequence


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
