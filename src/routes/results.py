import json

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from src.db import get_db
from src.models import Question

router = APIRouter()


@router.get("/results/{quiz_id}")
async def show_results(request: Request, quiz_id: str):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM quizzes WHERE id = ?", (quiz_id,))
        quiz = await cursor.fetchone()
        if not quiz:
            return RedirectResponse(url="/")

        question_ids = json.loads(quiz["question_ids"])
        placeholders = ",".join("?" * len(question_ids))

        # Fetch questions
        cursor = await db.execute(
            f"SELECT * FROM questions WHERE id IN ({placeholders})", question_ids
        )
        rows = await cursor.fetchall()
        q_map = {row["id"]: Question.from_row(dict(row)) for row in rows}

        # Fetch results
        cursor = await db.execute(
            "SELECT * FROM quiz_results WHERE quiz_id = ?", (quiz_id,)
        )
        result_rows = await cursor.fetchall()
        r_map = {row["question_id"]: dict(row) for row in result_rows}

        # Build combined view
        items = []
        total_correct = 0
        total_answered = 0

        for qid in question_ids:
            q = q_map.get(qid)
            r = r_map.get(qid)
            if not q:
                continue

            total_answered += 1
            is_correct = r["is_correct"] if r else None
            if is_correct == 1:
                total_correct += 1

            items.append({
                "question": q,
                "user_answer": r["user_answer"] if r else "",
                "is_correct": is_correct,
                "score": r["score"] if r else None,
                "feedback": r["feedback"] if r else None,
            })
    finally:
        await db.close()

    pct = round(total_correct / total_answered * 100) if total_answered else 0
    tab_switches = quiz["tab_switches"] if "tab_switches" in quiz.keys() else 0

    return request.app.state.templates.TemplateResponse(
        "results.html",
        {
            "request": request,
            "quiz_id": quiz_id,
            "filter_type": quiz["filter_type"],
            "filter_value": quiz["filter_value"],
            "items": items,
            "total_correct": total_correct,
            "total_answered": total_answered,
            "pct": pct,
            "tab_switches": tab_switches or 0,
        },
    )
