from __future__ import annotations

from collections.abc import Sequence

from .canvas import CanvasClient
from .learningx import flatten_module_items
from .models import CapabilityResult, CapabilityStatus


MATERIAL_TYPES = {"pdf", "file", "document", "ppt", "pptx", "doc", "docx", "hwp", "xlsx", "xls"}
COMPLETION_STRINGS = {"true", "false", "complete", "completed", "incomplete", "not_completed"}


def has_usable_completion(value) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, int):
        return value in {0, 1}
    if isinstance(value, str):
        return value.strip().lower() in COMPLETION_STRINGS
    return False


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


def probe_learningx(client, course_ids: Sequence[int]) -> list[CapabilityResult]:
    results: list[CapabilityResult] = []
    for course_id in course_ids:
        try:
            client.sessionless_launch(course_id)
        except Exception:
            results.append(
                CapabilityResult(
                    course_id,
                    "sessionless_launch",
                    CapabilityStatus.UNAVAILABLE,
                    reason="sessionless_launch_failed",
                )
            )
        else:
            results.append(
                CapabilityResult(
                    course_id,
                    "sessionless_launch",
                    CapabilityStatus.VERIFIED,
                    count=1,
                )
            )

        try:
            attendance = client.attendance(course_id)
        except Exception:
            results.append(
                CapabilityResult(
                    course_id,
                    "attendance",
                    CapabilityStatus.UNAVAILABLE,
                    reason="attendance_failed",
                )
            )
            results.append(
                CapabilityResult(
                    course_id,
                    "completion_state",
                    CapabilityStatus.UNAVAILABLE,
                    reason="attendance_failed",
                )
            )
        else:
            results.append(
                CapabilityResult(
                    course_id,
                    "attendance",
                    CapabilityStatus.VERIFIED,
                    count=len(attendance),
                )
            )
            completion_count = sum(
                1 for entry in attendance if has_usable_completion(entry.get("completed"))
            )
            completion_status = CapabilityStatus.VERIFIED if completion_count else CapabilityStatus.UNVERIFIED
            completion_reason = "" if completion_count else "no_completion_sample"
            results.append(
                CapabilityResult(
                    course_id,
                    "completion_state",
                    completion_status,
                    count=completion_count,
                    reason=completion_reason,
                )
            )

        try:
            items = flatten_module_items(client.modules(course_id))
        except Exception:
            results.append(
                CapabilityResult(
                    course_id,
                    "lectures",
                    CapabilityStatus.UNAVAILABLE,
                    reason="modules_failed",
                )
            )
            results.append(
                CapabilityResult(
                    course_id,
                    "required_materials",
                    CapabilityStatus.UNAVAILABLE,
                    reason="modules_failed",
                )
            )
        else:
            materials = [
                item
                for item in items
                if str(item["type"]).lower() in MATERIAL_TYPES and item["required"]
            ]
            material_status = CapabilityStatus.VERIFIED if materials else CapabilityStatus.UNVERIFIED
            material_reason = "" if materials else "no_required_material_sample"
            results.append(
                CapabilityResult(
                    course_id,
                    "lectures",
                    CapabilityStatus.VERIFIED,
                    count=len(items),
                )
            )
            results.append(
                CapabilityResult(
                    course_id,
                    "required_materials",
                    material_status,
                    count=len(materials),
                    reason=material_reason,
                )
            )
    return results
