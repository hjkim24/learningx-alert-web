from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class CanvasProfile:
    id: int
    name: str


@dataclass(frozen=True)
class Course:
    id: int
    name: str


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
