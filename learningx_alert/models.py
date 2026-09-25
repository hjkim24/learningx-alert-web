from dataclasses import dataclass


@dataclass(frozen=True)
class CanvasProfile:
    id: int
    name: str


@dataclass(frozen=True)
class Course:
    id: int
    name: str
