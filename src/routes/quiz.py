import asyncio
import json
from datetime import datetime, UTC
from uuid import uuid4

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from src.config import settings
from src.db import get_db
from src.models import GradeResult, Question
from src.openrouter import grade_open_answer

router = APIRouter(prefix="/quiz")


@router.get("/start")
async def start_quiz(
    request: Request,
    role: str = "",
    chapter: str = "",
    book: str = "",
):
    filter_type = "chapter" if chapter else "role"
    filter_value = chapter if chapter else role

    if not filter_value:
        return RedirectResponse(url="/", status_code=303)

    db = await get_db()
    try:
        if filter_type == "chapter":
            if book:
                cursor = await db.execute(
                    """SELECT * FROM questions
                       WHERE chapter = ? AND book = ? AND difficulty <= 2
                       ORDER BY RANDOM() LIMIT ?""",
                    (filter_value, book, settings.quiz_size),
                )
            else:
                cursor = await db.execute(
                    """SELECT * FROM questions
                       WHERE chapter = ? AND difficulty <= 2
                       ORDER BY RANDOM() LIMIT ?""",
                    (filter_value, settings.quiz_size),
                )
        else:
            if book:
                cursor = await db.execute(
                    """SELECT * FROM questions
                       WHERE EXISTS (SELECT 1 FROM json_each(roles) WHERE value = ?)
                       AND book = ? AND difficulty <= 2
                       ORDER BY RANDOM() LIMIT ?""",
                    (filter_value, book, settings.quiz_size),
                )
            else:
                cursor = await db.execute(
                    """SELECT * FROM questions
                       WHERE EXISTS (SELECT 1 FROM json_each(roles) WHERE value = ?)
                       AND difficulty <= 2
                       ORDER BY RANDOM() LIMIT ?""",
                    (filter_value, settings.quiz_size),
                )
        rows = await cursor.fetchall()

        if not rows:
            cursor = await db.execute(
                "SELECT DISTINCT chapter FROM questions WHERE chapter IS NOT NULL ORDER BY chapter"
            )
            chapters = [row["chapter"] for row in await cursor.fetchall()]
            return request.app.state.templates.TemplateResponse(
                "home.html",
                {
                    "request": request,
                    "roles": settings.roles,
                    "books": [],
                    "chapters": chapters,
                    "error": f"No questions available for {filter_type} '{filter_value}'. Try a different selection.",
                },
            )

        questions = [Question.from_row(dict(r)) for r in rows]
        quiz_id = str(uuid4())
        question_ids = json.dumps([q.id for q in questions])

        await db.execute(
            "INSERT INTO quizzes (id, filter_type, filter_value, book, question_ids) VALUES (?, ?, ?, ?, ?)",
            (quiz_id, filter_type, filter_value, book or None, question_ids),
        )
        await db.commit()
    finally:
        await db.close()

    return RedirectResponse(url=f"/quiz/{quiz_id}", status_code=303)


@router.get("/{quiz_id}")
async def show_quiz(request: Request, quiz_id: str):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM quizzes WHERE id = ?", (quiz_id,))
        quiz = await cursor.fetchone()
        if not quiz:
            return RedirectResponse(url="/")

        question_ids = json.loads(quiz["question_ids"])
        placeholders = ",".join("?" * len(question_ids))
        cursor = await db.execute(
            f"SELECT * FROM questions WHERE id IN ({placeholders})", question_ids
        )
        rows = await cursor.fetchall()
        questions = [Question.from_row(dict(r)) for r in rows]
        # Preserve the quiz order
        q_map = {q.id: q for q in questions}
        questions = [q_map[qid] for qid in question_ids if qid in q_map]
    finally:
        await db.close()

    return request.app.state.templates.TemplateResponse(
        "quiz.html",
        {
            "request": request,
            "quiz_id": quiz_id,
            "questions": questions,
            "filter_type": quiz["filter_type"],
            "filter_value": quiz["filter_value"],
        },
    )


@router.post("/{quiz_id}/submit")
async def submit_quiz(request: Request, quiz_id: str):
    form = await request.form()
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM quizzes WHERE id = ?", (quiz_id,))
        quiz = await cursor.fetchone()
        if not quiz:
            return RedirectResponse(url="/")

        question_ids = json.loads(quiz["question_ids"])
        placeholders = ",".join("?" * len(question_ids))
        cursor = await db.execute(
            f"SELECT * FROM questions WHERE id IN ({placeholders})", question_ids
        )
        rows = await cursor.fetchall()
        q_map = {row["id"]: Question.from_row(dict(row)) for row in rows}

        # Grade all answers
        grading_tasks = []
        answers = []

        for qid in question_ids:
            q = q_map.get(qid)
            if not q:
                continue
            user_answer = form.get(f"q_{qid}", "").strip()
            answers.append((qid, user_answer, q))

            if q.question_type == "open" and user_answer and settings.openrouter_api_key:
                grading_tasks.append(
                    grade_open_answer(q.question_text, q.correct_answer, user_answer)
                )
            else:
                grading_tasks.append(None)

        # Run LLM grading concurrently
        grading_results: list[GradeResult | None] = []
        real_tasks = [t for t in grading_tasks if t is not None]
        if real_tasks:
            completed = await asyncio.gather(*real_tasks, return_exceptions=True)
            completed_iter = iter(completed)

        for task in grading_tasks:
            if task is None:
                grading_results.append(None)
            else:
                result = next(completed_iter)
                if isinstance(result, Exception):
                    grading_results.append(GradeResult(score=0.0, feedback=f"Grading error: {result}"))
                else:
                    grading_results.append(result)

        # Store results
        now = datetime.now(UTC).isoformat()
        for (qid, user_answer, q), grade in zip(answers, grading_results):
            if q.question_type == "mc":
                is_correct = 1 if user_answer.upper() == q.correct_answer.upper() else 0
                await db.execute(
                    """INSERT INTO quiz_results (quiz_id, question_id, user_answer, is_correct, graded_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (quiz_id, qid, user_answer, is_correct, now),
                )
            else:
                score = grade.score if grade else None
                feedback = grade.feedback if grade else "No grading available (API key not configured)"
                is_correct = 1 if score and score >= 0.5 else (0 if score is not None else None)
                await db.execute(
                    """INSERT INTO quiz_results (quiz_id, question_id, user_answer, is_correct, score, feedback, graded_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (quiz_id, qid, user_answer, is_correct, score, feedback, now),
                )

        # Store tab-switch count from anti-cheat JS
        tab_switches = int(form.get("tab_switches", 0) or 0)
        await db.execute(
            "UPDATE quizzes SET tab_switches = ? WHERE id = ?",
            (tab_switches, quiz_id),
        )

        await db.commit()
    finally:
        await db.close()

    return RedirectResponse(url=f"/results/{quiz_id}", status_code=303)
