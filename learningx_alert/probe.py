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
            results.append(
                CapabilityResult(
                    course_id,
                    "assignments",
                    CapabilityStatus.UNAVAILABLE,
                    reason="assignments_failed",
                )
            )
            results.append(
                CapabilityResult(
                    course_id,
                    "submission_state",
                    CapabilityStatus.UNVERIFIED,
                    reason="assignments_unavailable",
                )
            )
            continue

        results.append(
            CapabilityResult(
                course_id,
                "assignments",
                CapabilityStatus.VERIFIED,
                count=len(assignments),
            )
        )
        if not assignments:
            results.append(
                CapabilityResult(
                    course_id,
                    "submission_state",
                    CapabilityStatus.VERIFIED,
                    count=0,
                )
            )
            continue

        checked = 0
        try:
            for assignment in assignments:
                client.submission_state(course_id, int(assignment["id"]))
                checked += 1
        except Exception:
            results.append(
                CapabilityResult(
                    course_id,
                    "submission_state",
                    CapabilityStatus.UNAVAILABLE,
                    count=checked,
                    reason="submission_state_failed",
                )
            )
        else:
            results.append(
                CapabilityResult(
                    course_id,
                    "submission_state",
                    CapabilityStatus.VERIFIED,
                    count=checked,
                )
            )
    return results
