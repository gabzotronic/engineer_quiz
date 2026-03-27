from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class Question:
    id: int
    book: str
    chapter: str | None
    question_type: str  # "mc", "open", or "math"
    difficulty: int
    roles: list[str]
    question_text: str
    options: list[str] | None  # MC options
    correct_answer: str
    explanation: str | None
    diagram_images: list[str] | None = None
    math_metadata: dict | None = None

    @classmethod
    def from_row(cls, row: dict) -> Question:
        diagram_images = None
        raw_diagrams = row.get("diagram_images")
        if raw_diagrams:
            diagram_images = (
                json.loads(raw_diagrams)
                if isinstance(raw_diagrams, str)
                else raw_diagrams
            )

        math_metadata = None
        raw_math = row.get("math_metadata")
        if raw_math:
            math_metadata = (
                json.loads(raw_math) if isinstance(raw_math, str) else raw_math
            )

        return cls(
            id=row["id"],
            book=row["book"],
            chapter=row["chapter"],
            question_type=row["question_type"],
            difficulty=row["difficulty"],
            roles=json.loads(row["roles"]) if isinstance(row["roles"], str) else row["roles"],
            question_text=row["question_text"],
            options=json.loads(row["options"]) if row["options"] else None,
            correct_answer=row["correct_answer"],
            explanation=row["explanation"],
            diagram_images=diagram_images,
            math_metadata=math_metadata,
        )


@dataclass
class QuizResult:
    question_id: int
    user_answer: str
    is_correct: bool | None
    score: float | None
    feedback: str | None


@dataclass
class GradeResult:
    score: float
    feedback: str
