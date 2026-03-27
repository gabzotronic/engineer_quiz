import aiosqlite

from src.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book TEXT NOT NULL,
    chapter TEXT,
    chunk_hash TEXT,
    question_type TEXT NOT NULL CHECK(question_type IN ('mc', 'open', 'math')),
    difficulty INTEGER NOT NULL CHECK(difficulty BETWEEN 1 AND 3),
    roles TEXT NOT NULL DEFAULT '[]',
    question_text TEXT NOT NULL,
    options TEXT,
    correct_answer TEXT NOT NULL,
    explanation TEXT,
    diagram_images TEXT,
    math_metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS quizzes (
    id TEXT PRIMARY KEY,
    filter_type TEXT NOT NULL DEFAULT 'role',
    filter_value TEXT NOT NULL,
    book TEXT,
    question_ids TEXT NOT NULL,
    tab_switches INTEGER NOT NULL DEFAULT 0,
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
        # Migration: add tab_switches column to existing quizzes tables
        cursor = await db.execute("PRAGMA table_info(quizzes)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "tab_switches" not in columns:
            await db.execute(
                "ALTER TABLE quizzes ADD COLUMN tab_switches INTEGER NOT NULL DEFAULT 0"
            )

        # Migration: add diagram_images and math_metadata to questions
        cursor = await db.execute("PRAGMA table_info(questions)")
        q_columns = {row[1] for row in await cursor.fetchall()}
        if "diagram_images" not in q_columns:
            await db.execute(
                "ALTER TABLE questions ADD COLUMN diagram_images TEXT"
            )
        if "math_metadata" not in q_columns:
            await db.execute(
                "ALTER TABLE questions ADD COLUMN math_metadata TEXT"
            )

        # Migration: widen question_type CHECK to allow 'math'
        # SQLite can't ALTER CHECK constraints, so recreate table if needed
        try:
            await db.execute(
                "INSERT INTO questions (book, question_type, difficulty, question_text, correct_answer) "
                "VALUES ('__migration_test', 'math', 1, '__test', '__test')"
            )
            await db.execute(
                "DELETE FROM questions WHERE book = '__migration_test'"
            )
        except Exception:
            # Old CHECK constraint rejects 'math' — recreate table
            await db.execute("ALTER TABLE questions RENAME TO _questions_old")
            await db.executescript(SCHEMA.split("CREATE TABLE IF NOT EXISTS quizzes")[0])
            await db.execute(
                "INSERT INTO questions SELECT * FROM _questions_old"
            )
            await db.execute("DROP TABLE _questions_old")

        await db.commit()


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(settings.database_path)
    db.row_factory = aiosqlite.Row
    return db
