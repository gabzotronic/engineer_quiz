import json

from fastapi import APIRouter, Request

from src.config import settings
from src.db import get_db

router = APIRouter()


@router.get("/")
async def home(request: Request):
    db = await get_db()
    try:
        # Get available books
        cursor = await db.execute("SELECT DISTINCT book FROM questions")
        books = [row["book"] for row in await cursor.fetchall()]
    finally:
        await db.close()

    return request.app.state.templates.TemplateResponse(
        "home.html",
        {"request": request, "roles": settings.roles, "books": books},
    )
