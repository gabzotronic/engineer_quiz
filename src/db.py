import aiosqlite

from src.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book TEXT NOT NULL,
    chapter TEXT,
    chunk_hash TEXT,
    question_type TEXT NOT NULL CHECK(question_type IN ('mc', 'open')),
    difficulty INTEGER NOT NULL CHECK(difficulty BETWEEN 1 AND 3),
    roles TEXT NOT NULL DEFAULT '[]',
    question_text TEXT NOT NULL,
    options TEXT,
    correct_answer TEXT NOT NULL,
    explanation TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS quizzes (
    id TEXT PRIMARY KEY,
    filter_type TEXT NOT NULL DEFAULT 'role',
    filter_value TEXT NOT NULL,
    book TEXT,
    question_ids TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS quiz_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id TEXT NOT NULL REFERENCES quizzes(id),
    question_id INTEGER NOT NULL REFERENCES questions(id),
    user_answer TEXT NOT NULL,
    is_correct INTEGER,
    score REAL,
    feedback TEXT,
    graded_at TEXT
);
"""


async def init_db() -> None:
    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.executescript(SCHEMA)
        await db.commit()


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(settings.database_path)
    db.row_factory = aiosqlite.Row
    return db
