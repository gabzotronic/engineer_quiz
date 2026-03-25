from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class Question:
    id: int
    book: str
    chapter: str | None
    question_type: str  # "mc" or "open"
    difficulty: int
    roles: list[str]
    question_text: str
    options: list[str] | None  # MC options
    correct_answer: str
    explanation: str | None

    @classmethod
    def from_row(cls, row: dict) -> Question:
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
