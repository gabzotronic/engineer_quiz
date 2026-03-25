"""Seed the database from data/questions.json."""

import asyncio
import json
from pathlib import Path

import aiosqlite

from src.config import settings
from src.db import init_db

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


async def seed() -> None:
    questions_file = DATA_DIR / "questions.json"
    if not questions_file.exists():
        print(f"No questions file at {questions_file}")
        return

    questions = json.loads(questions_file.read_text())

    await init_db()
    async with aiosqlite.connect(settings.database_path) as db:
        for q in questions:
            await db.execute(
                """INSERT INTO questions (book, chapter, question_type, difficulty, roles,
                   question_text, options, correct_answer, explanation)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    q["book"],
                    q.get("chapter"),
                    q["question_type"],
                    q["difficulty"],
                    json.dumps(q["roles"]),
                    q["question_text"],
                    json.dumps(q["options"]) if q.get("options") else None,
                    q["correct_answer"],
                    q.get("explanation"),
                ),
            )
        await db.commit()
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM questions")
        row = await cursor.fetchone()
        print(f"Seeded database. Total questions: {row[0]}")


if __name__ == "__main__":
    asyncio.run(seed())
