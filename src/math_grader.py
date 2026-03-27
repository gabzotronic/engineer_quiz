"""Sympy-based grading for math questions."""

from __future__ import annotations

import re

from sympy import simplify, sympify
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from src.models import GradeResult

TRANSFORMS = standard_transformations + (implicit_multiplication_application,)


def _preprocess(raw: str, strip_units: bool = False) -> str:
    """Normalize user input for sympy parsing."""
    s = raw.strip()
    # Remove trailing units only for numeric answers (e.g. "42.5 m/s", "156.2 cm²")
    if strip_units:
        s = re.sub(r"\s+[a-zA-Z°²³]+[\s/a-zA-Z°²³]*$", "", s)
    # Replace common notations
    s = s.replace("^", "**")
    s = s.replace("×", "*").replace("÷", "/")
    # Handle percentage answers: "800%" -> "800"
    s = s.rstrip("%")
    return s.strip()


def grade_math_answer(user_answer: str, metadata: dict) -> GradeResult:
    """Grade a math answer using sympy.

    metadata keys:
        answer_type: "numeric" | "expression"
        expected_value: float (for numeric)
        expected_expression: str (sympy-parseable, for expression)
        tolerance: float (for numeric, default 0.01)
    """
    if not user_answer.strip():
        return GradeResult(score=0.0, feedback="No answer provided.")

    answer_type = metadata.get("answer_type", "numeric")
    if answer_type == "numeric":
        return _grade_numeric(user_answer, metadata)
    elif answer_type == "expression":
        return _grade_expression(user_answer, metadata)
    else:
        return GradeResult(score=0.0, feedback=f"Unknown answer type: {answer_type}")


def _grade_numeric(user_answer: str, metadata: dict) -> GradeResult:
    tolerance = metadata.get("tolerance", 0.01)
    expected = float(metadata["expected_value"])

    cleaned = _preprocess(user_answer, strip_units=True)
    try:
        user_val = float(sympify(cleaned))
    except Exception:
        return GradeResult(
            score=0.0,
            feedback=f"Could not parse '{user_answer}' as a number.",
        )

    if abs(user_val - expected) <= tolerance:
        return GradeResult(score=1.0, feedback="Correct!")
    # Partial credit for close answers (within 10x tolerance)
    elif abs(user_val - expected) <= tolerance * 10:
        return GradeResult(
            score=0.5,
            feedback=f"Close, but expected {expected}. You answered {user_val}.",
        )
    else:
        return GradeResult(
            score=0.0,
            feedback=f"Incorrect. Expected {expected}, got {user_val}.",
        )


def _grade_expression(user_answer: str, metadata: dict) -> GradeResult:
    expected_str = metadata["expected_expression"]

    try:
        expected_expr = parse_expr(expected_str, transformations=TRANSFORMS)
    except Exception:
        return GradeResult(
            score=0.0,
            feedback="Internal error: could not parse expected expression.",
        )

    cleaned = _preprocess(user_answer)
    try:
        user_expr = parse_expr(cleaned, transformations=TRANSFORMS)
    except Exception:
        return GradeResult(
            score=0.0,
            feedback=f"Could not parse '{user_answer}' as a math expression. "
            "Use ^ for powers, * for multiplication.",
        )

    try:
        diff = simplify(expected_expr - user_expr)
        if diff == 0:
            return GradeResult(score=1.0, feedback="Correct!")
        else:
            return GradeResult(
                score=0.0,
                feedback="Not equivalent to the expected answer.",
            )
    except Exception:
        # Fallback: numeric evaluation at random points
        try:
            from sympy import Symbol

            symbols = list(expected_expr.free_symbols | user_expr.free_symbols)
            if not symbols:
                # Both are constants — compare numerically
                e_val = float(expected_expr.evalf())
                u_val = float(user_expr.evalf())
                tolerance = metadata.get("tolerance", 0.01)
                if abs(e_val - u_val) <= tolerance:
                    return GradeResult(score=1.0, feedback="Correct!")
                return GradeResult(
                    score=0.0,
                    feedback=f"Incorrect. Expected {e_val}, got {u_val}.",
                )

            # Evaluate at several random points
            import random

            matches = 0
            trials = 10
            for _ in range(trials):
                subs = {s: random.uniform(0.5, 5.0) for s in symbols}
                e_val = float(expected_expr.subs(subs).evalf())
                u_val = float(user_expr.subs(subs).evalf())
                if abs(e_val - u_val) < 0.001:
                    matches += 1

            if matches == trials:
                return GradeResult(score=1.0, feedback="Correct!")
            elif matches >= trials * 0.8:
                return GradeResult(
                    score=0.5,
                    feedback="Partially correct — equivalent at most test points.",
                )
            return GradeResult(
                score=0.0, feedback="Not equivalent to the expected answer."
            )
        except Exception:
            return GradeResult(
                score=0.0,
                feedback="Could not verify equivalence. Check your expression.",
            )
