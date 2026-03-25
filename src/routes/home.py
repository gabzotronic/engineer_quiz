import json

from fastapi import APIRouter, Request

from src.config import settings
from src.db import get_db

router = APIRouter()


@router.get("/")
async def home(request: Request):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT DISTINCT book FROM questions")
        books = [row["book"] for row in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT DISTINCT chapter FROM questions WHERE chapter IS NOT NULL ORDER BY chapter"
        )
        chapters = [row["chapter"] for row in await cursor.fetchall()]
    finally:
        await db.close()

    return request.app.state.templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "roles": settings.roles,
            "books": books,
            "chapters": chapters,
        },
    )
