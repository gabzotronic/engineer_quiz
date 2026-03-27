"""Playwright E2E smoke test for math questions and diagram display."""

import json
import os
import signal
import subprocess
import time
from pathlib import Path

import aiosqlite
import pytest

# Use a separate test database (absolute path for consistency)
PROJECT_DIR = Path(__file__).resolve().parent.parent
TEST_DB = str(PROJECT_DIR / "test_e2e.db")
TEST_PORT = 8765
BASE_URL = f"http://localhost:{TEST_PORT}"
STATIC_DIR = PROJECT_DIR / "src" / "static"
DIAGRAM_DIR = STATIC_DIR / "diagrams" / "test-book"

# Sample math questions for the fixture
FIXTURE_QUESTIONS = [
    {
        "book": "test-book",
        "chapter": None,
        "question_type": "math",
        "difficulty": 1,
        "roles": ["Math Student"],
        "question_text": "Calculate 2 + 3.",
        "options": None,
        "correct_answer": "5",
        "explanation": "Simple addition.",
        "diagram_images": None,
        "math_metadata": {
            "answer_type": "numeric",
            "expected_value": 5.0,
            "tolerance": 0.01,
        },
    },
    {
        "book": "test-book",
        "chapter": None,
        "question_type": "math",
        "difficulty": 1,
        "roles": ["Math Student"],
        "question_text": "Simplify x^2 + 2x + 1.",
        "options": None,
        "correct_answer": "(x+1)^2",
        "explanation": "Perfect square trinomial.",
        "diagram_images": None,
        "math_metadata": {
            "answer_type": "expression",
            "expected_expression": "(x+1)**2",
        },
    },
    {
        "book": "test-book",
        "chapter": None,
        "question_type": "math",
        "difficulty": 2,
        "roles": ["Math Student"],
        "question_text": "From the diagram, find the area of triangle ABC where AB = 5 cm and height = 8 cm.",
        "options": None,
        "correct_answer": "20",
        "explanation": "Area = 0.5 * base * height = 0.5 * 5 * 8 = 20",
        "diagram_images": ["test_diagram.png"],
        "math_metadata": {
            "answer_type": "numeric",
            "expected_value": 20.0,
            "tolerance": 0.1,
        },
    },
]


def _create_test_diagram():
    """Create a minimal test PNG for diagram display tests."""
    DIAGRAM_DIR.mkdir(parents=True, exist_ok=True)
    # Minimal valid 1x1 red PNG
    import struct
    import zlib

    def create_png(width=100, height=60):
        """Create a simple PNG with a colored rectangle."""

        def chunk(chunk_type, data):
            raw = chunk_type + data
            return (
                struct.pack(">I", len(data))
                + raw
                + struct.pack(">I", zlib.crc32(raw) & 0xFFFFFFFF)
            )

        # IHDR
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        # IDAT — simple blue rectangle
        raw_data = b""
        for y in range(height):
            raw_data += b"\x00"  # filter byte
            for x in range(width):
                raw_data += bytes([50, 100, 200])  # RGB blue-ish
        idat = zlib.compress(raw_data)

        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat)
            + chunk(b"IEND", b"")
        )

    (DIAGRAM_DIR / "test_diagram.png").write_bytes(create_png())


async def _seed_test_db():
    """Create and seed the test database."""
    from src.db import SCHEMA

    # Remove old test DB
    Path(TEST_DB).unlink(missing_ok=True)

    async with aiosqlite.connect(TEST_DB) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.executescript(SCHEMA)
        for q in FIXTURE_QUESTIONS:
            await db.execute(
                """INSERT INTO questions (book, chapter, question_type, difficulty,
                   roles, question_text, options, correct_answer, explanation,
                   diagram_images, math_metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    q["book"],
                    q["chapter"],
                    q["question_type"],
                    q["difficulty"],
                    json.dumps(q["roles"]),
                    q["question_text"],
                    json.dumps(q["options"]) if q["options"] else None,
                    q["correct_answer"],
                    q.get("explanation"),
                    json.dumps(q["diagram_images"]) if q.get("diagram_images") else None,
                    json.dumps(q["math_metadata"]) if q.get("math_metadata") else None,
                ),
            )
        await db.commit()


@pytest.fixture(scope="module")
def server():
    """Start uvicorn server with test DB, yield base URL, then clean up."""
    import asyncio

    asyncio.run(_seed_test_db())
    _create_test_diagram()

    env = os.environ.copy()
    env["QUIZ_DATABASE_PATH"] = TEST_DB
    env["QUIZ_QUIZ_SIZE"] = "3"  # all 3 fixture questions

    proc = subprocess.Popen(
        [
            "poetry",
            "run",
            "uvicorn",
            "src.app:app",
            "--port",
            str(TEST_PORT),
            "--log-level",
            "warning",
        ],
        env=env,
        cwd=str(PROJECT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to be ready
    for _ in range(30):
        try:
            import httpx

            resp = httpx.get(f"{BASE_URL}/", timeout=2)
            if resp.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        proc.kill()
        raise RuntimeError("Server did not start")

    yield BASE_URL

    os.kill(proc.pid, signal.SIGTERM)
    proc.wait(timeout=5)
    Path(TEST_DB).unlink(missing_ok=True)
    # Clean up test diagram
    (DIAGRAM_DIR / "test_diagram.png").unlink(missing_ok=True)
    try:
        DIAGRAM_DIR.rmdir()
    except OSError:
        pass


def test_math_quiz_full_flow(server):
    """Smoke test: start quiz, verify diagrams, submit answers, check results."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1. Home page loads
        page.goto(f"{server}/")
        assert page.title()
        assert "Knowledge Quiz" in page.content()

        # 2. Start quiz by role (Math Student is our fixture role)
        page.goto(f"{server}/quiz/start?role=Math+Student")
        page.wait_for_url("**/quiz/**")

        # 3. Verify we're on the quiz page
        assert "Quiz" in page.content()

        # 4. Verify diagram image renders (question 3 has a diagram)
        diagram_imgs = page.query_selector_all("img[src*='/static/diagrams/']")
        assert len(diagram_imgs) >= 1, "Expected at least one diagram image"
        for img in diagram_imgs:
            # Check image loaded (naturalWidth > 0)
            natural_width = img.evaluate("el => el.naturalWidth")
            assert natural_width > 0, f"Diagram image failed to load: {img.get_attribute('src')}"

        # 5. Verify math input fields exist (not textarea, but input[type=text])
        math_inputs = page.query_selector_all("input[type='text'][name^='q_']")
        assert len(math_inputs) >= 1, "Expected math input fields"

        # 6. Fill in answers
        # Find all input fields and textareas for answers
        all_inputs = page.query_selector_all(
            "input[type='text'][name^='q_'], textarea[name^='q_']"
        )
        answers = ["5", "(x+1)^2", "20"]
        for i, inp in enumerate(all_inputs):
            if i < len(answers):
                inp.fill(answers[i])

        # 7. Submit
        page.click("#submit-btn")
        page.wait_for_url("**/results/**", timeout=10000)

        # 8. Verify results page
        content = page.content()
        assert "Quiz Results" in content

        # Check that we got scores
        assert "Correct" in content or "Incorrect" in content

        # Verify diagram shows on results page too
        result_diagrams = page.query_selector_all("img[src*='/static/diagrams/']")
        assert len(result_diagrams) >= 1, "Diagram should appear on results page"

        # Check sympy feedback appears (score percentages)
        assert "Score:" in content or "100%" in content or "%" in content

        browser.close()


def test_math_grading_submits_and_grades(server):
    """Verify submitting math answers produces graded results."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(f"{server}/quiz/start?role=Math+Student")
        page.wait_for_url("**/quiz/**")

        # Fill all inputs with "5" — at least one numeric question should match
        inputs = page.query_selector_all(
            "input[type='text'][name^='q_'], textarea[name^='q_']"
        )
        for inp in inputs:
            inp.fill("5")

        page.click("#submit-btn")
        page.wait_for_url("**/results/**", timeout=10000)

        content = page.content()
        assert "Quiz Results" in content
        # Verify grading occurred — should have score percentages or correct/incorrect
        assert "%" in content, "Expected percentage score on results page"

        browser.close()


def test_math_grading_wrong_answer(server):
    """Verify wrong answers get marked incorrect."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(f"{server}/quiz/start?role=Math+Student")
        page.wait_for_url("**/quiz/**")

        # Fill all with wrong answers
        inputs = page.query_selector_all(
            "input[type='text'][name^='q_'], textarea[name^='q_']"
        )
        for inp in inputs:
            inp.fill("999")

        page.click("#submit-btn")
        page.wait_for_url("**/results/**", timeout=10000)

        content = page.content()
        assert "Incorrect" in content, "Expected at least one incorrect answer"

        browser.close()
