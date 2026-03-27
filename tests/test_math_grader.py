"""Tests for the sympy-based math grader."""

import pytest

from src.math_grader import grade_math_answer


# --- Numeric grading ---


class TestNumericGrading:
    def _meta(self, expected, tolerance=0.01):
        return {
            "answer_type": "numeric",
            "expected_value": expected,
            "tolerance": tolerance,
        }

    def test_exact_match(self):
        result = grade_math_answer("42", self._meta(42.0))
        assert result.score == 1.0

    def test_within_tolerance(self):
        result = grade_math_answer("42.005", self._meta(42.0))
        assert result.score == 1.0

    def test_outside_tolerance(self):
        result = grade_math_answer("43", self._meta(42.0))
        assert result.score == 0.0

    def test_close_partial_credit(self):
        # Within 10x tolerance (0.1) but outside tolerance (0.01)
        result = grade_math_answer("42.05", self._meta(42.0))
        assert result.score == 0.5

    def test_fraction_input(self):
        result = grade_math_answer("3/4", self._meta(0.75))
        assert result.score == 1.0

    def test_negative_number(self):
        result = grade_math_answer("-1/2", self._meta(-0.5))
        assert result.score == 1.0

    def test_scientific_notation(self):
        result = grade_math_answer("1.5e3", self._meta(1500.0, tolerance=1.0))
        assert result.score == 1.0

    def test_percentage_stripped(self):
        result = grade_math_answer("800%", self._meta(800.0, tolerance=1.0))
        assert result.score == 1.0

    def test_with_units_stripped(self):
        result = grade_math_answer("156.2 cm", self._meta(156.2, tolerance=0.1))
        assert result.score == 1.0

    def test_empty_answer(self):
        result = grade_math_answer("", self._meta(42.0))
        assert result.score == 0.0

    def test_garbage_input(self):
        result = grade_math_answer("hello world", self._meta(42.0))
        assert result.score == 0.0
        assert "Could not parse" in result.feedback

    def test_large_tolerance(self):
        result = grade_math_answer("156.2", self._meta(156.0, tolerance=0.5))
        assert result.score == 1.0


# --- Expression grading ---


class TestExpressionGrading:
    def _meta(self, expr):
        return {"answer_type": "expression", "expected_expression": expr}

    def test_identical_expression(self):
        result = grade_math_answer("x**2 + 1", self._meta("x**2 + 1"))
        assert result.score == 1.0

    def test_algebraic_equivalence(self):
        result = grade_math_answer("(x+1)**2", self._meta("x**2 + 2*x + 1"))
        assert result.score == 1.0

    def test_caret_notation(self):
        result = grade_math_answer("(x+1)^2", self._meta("x**2 + 2*x + 1"))
        assert result.score == 1.0

    def test_simplified_fraction(self):
        result = grade_math_answer("c^3/(10*d)", self._meta("c**3 / (10*d)"))
        assert result.score == 1.0

    def test_trig_equivalence(self):
        result = grade_math_answer("sin(x)*cos(x)", self._meta("sin(2*x)/2"))
        assert result.score == 1.0

    def test_wrong_expression(self):
        result = grade_math_answer("x**2 + 1", self._meta("x**2 - 1"))
        assert result.score == 0.0

    def test_implicit_multiplication(self):
        result = grade_math_answer("2x", self._meta("2*x"))
        assert result.score == 1.0

    def test_garbage_expression(self):
        result = grade_math_answer("???", self._meta("x + 1"))
        assert result.score == 0.0
        assert "Could not parse" in result.feedback

    def test_constant_expression(self):
        result = grade_math_answer("6", self._meta("2*3"))
        assert result.score == 1.0
