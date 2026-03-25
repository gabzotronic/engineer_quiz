"""Generate quiz questions from extracted PDF chunks using OpenRouter LLM."""

import asyncio
import hashlib
import json
import sys
from pathlib import Path

import httpx
import typer

app = typer.Typer()

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_ROLES = [
    "Software Engineer",
    "QA Engineer",
    "AOCS Engineer",
    "Project Manager",
    "Systems Engineer",
]

GENERATION_PROMPT = """You are creating quiz questions for satellite engineers studying "{book_title}", {chapter}.

Source text:
---
{chunk_text}
---

Generate exactly {n_questions} questions from this text.
- Create {n_mc} multiple-choice questions and {n_open} open-ended questions.
- Tag each question with the most relevant engineer roles from: {roles_list}
- Assign difficulty: 1 (recall/definition), 2 (application/analysis), 3 (synthesis/evaluation)
- For multiple-choice: provide exactly 4 options (A-D), mark the correct one letter, explain why
- For open-ended: provide a model answer (2-3 sentences) and explain key points

If the source text is too short, contains mostly figures/tables references, or is not suitable for questions, return an empty array [].

Respond ONLY with a JSON array (no markdown, no code fences):
[
  {{
    "question_type": "mc",
    "difficulty": 2,
    "roles": ["Systems Engineer", "AOCS Engineer"],
    "question_text": "...",
    "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
    "correct_answer": "B",
    "explanation": "..."
  }},
  {{
    "question_type": "open",
    "difficulty": 3,
    "roles": ["Project Manager"],
    "question_text": "...",
    "correct_answer": "Model answer...",
    "explanation": "Key points: ..."
  }}
]"""


FALLBACK_MODEL = "nvidia/nemotron-3-super-120b-a12b"


async def call_openrouter(
    api_key: str,
    model: str,
    messages: list[dict],
    json_mode: bool = False,
) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body: dict = {"model": model, "messages": messages}
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(OPENROUTER_URL, json=body, headers=headers)

        if resp.status_code in (429, 502, 503) and model != FALLBACK_MODEL:
            body["model"] = FALLBACK_MODEL
            resp = await client.post(OPENROUTER_URL, json=body, headers=headers)

        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def generate_for_chunk(
    chunk: dict,
    api_key: str,
    model: str,
    roles: list[str],
    n_questions: int = 5,
    semaphore: asyncio.Semaphore | None = None,
) -> list[dict]:
    n_mc = max(1, n_questions - 2)
    n_open = n_questions - n_mc

    prompt = GENERATION_PROMPT.format(
        book_title=chunk["book"],
        chapter=chunk.get("chapter", "Unknown section"),
        chunk_text=chunk["text"][:6000],  # cap to avoid token limits
        n_questions=n_questions,
        n_mc=n_mc,
        n_open=n_open,
        roles_list=", ".join(roles),
    )

    if semaphore:
        await semaphore.acquire()

    try:
        content = await call_openrouter(
            api_key=api_key,
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )

        # Strip markdown fences if present
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        questions = json.loads(content)
        if not isinstance(questions, list):
            return []

        # Add chunk metadata
        for q in questions:
            q["book"] = chunk["book"]
            q["chapter"] = chunk.get("chapter")
            q["chunk_hash"] = chunk.get("hash")

        return questions

    except (json.JSONDecodeError, httpx.HTTPError, KeyError) as e:
        typer.echo(f"  Error processing chunk {chunk.get('pages', '?')}: {e}", err=True)
        return []
    finally:
        if semaphore:
            semaphore.release()


async def run_generation(
    chunks_file: Path,
    api_key: str,
    model: str,
    db_path: str,
    roles: list[str],
    chunk_limit: int,
    concurrency: int,
    questions_per_chunk: int,
    dry_run: bool,
) -> None:
    import aiosqlite

    chunks = json.loads(chunks_file.read_text())
    if chunk_limit > 0:
        chunks = chunks[:chunk_limit]

    typer.echo(f"Processing {len(chunks)} chunks with model={model}, concurrency={concurrency}")

    if dry_run:
        for i, chunk in enumerate(chunks[:3]):
            typer.echo(f"\nChunk {i+1}: {chunk.get('chapter', '?')} pages={chunk.get('pages', '?')} words={chunk.get('words', '?')}")
            typer.echo(f"  First 200 chars: {chunk['text'][:200]}...")
        typer.echo("\n[DRY RUN] Would generate questions for the chunks above.")
        return

    # Check which chunk hashes already exist
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT DISTINCT chunk_hash FROM questions WHERE chunk_hash IS NOT NULL")
        existing_hashes = {row[0] for row in await cursor.fetchall()}

    new_chunks = [c for c in chunks if c.get("hash") not in existing_hashes]
    skipped = len(chunks) - len(new_chunks)
    if skipped:
        typer.echo(f"Skipping {skipped} already-processed chunks")

    if not new_chunks:
        typer.echo("No new chunks to process.")
        return

    semaphore = asyncio.Semaphore(concurrency)
    tasks = [
        generate_for_chunk(chunk, api_key, model, roles, questions_per_chunk, semaphore)
        for chunk in new_chunks
    ]

    all_questions = []
    for i, coro in enumerate(asyncio.as_completed(tasks)):
        questions = await coro
        all_questions.extend(questions)
        typer.echo(f"  [{i+1}/{len(new_chunks)}] Generated {len(questions)} questions")

    # Store in DB
    if all_questions:
        async with aiosqlite.connect(db_path) as db:
            for q in all_questions:
                await db.execute(
                    """INSERT INTO questions (book, chapter, chunk_hash, question_type, difficulty,
                       roles, question_text, options, correct_answer, explanation)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        q.get("book"),
                        q.get("chapter"),
                        q.get("chunk_hash"),
                        q.get("question_type", "mc"),
                        q.get("difficulty", 1),
                        json.dumps(q.get("roles", roles)),
                        q["question_text"],
                        json.dumps(q.get("options")) if q.get("options") else None,
                        q.get("correct_answer", ""),
                        q.get("explanation"),
                    ),
                )
            await db.commit()

    typer.echo(f"\nDone. Generated and stored {len(all_questions)} questions from {len(new_chunks)} chunks.")

    # Export full question bank to data/questions.json
    await export_questions_json(db_path)


async def export_questions_json(db_path: str) -> None:
    """Export all questions from DB to data/questions.json for version control."""
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(exist_ok=True)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT book, chapter, chunk_hash, question_type, difficulty, roles, "
            "question_text, options, correct_answer, explanation FROM questions ORDER BY id"
        )
        rows = await cursor.fetchall()

    questions = []
    for r in rows:
        q = dict(r)
        q["roles"] = json.loads(q["roles"])
        q["options"] = json.loads(q["options"]) if q["options"] else None
        questions.append(q)

    out = data_dir / "questions.json"
    out.write_text(json.dumps(questions, indent=2) + "\n")
    typer.echo(f"Exported {len(questions)} questions to {out}")


@app.command()
def generate(
    chunks_file: Path = typer.Option("chunks.json", help="Path to chunks JSON from extract step"),
    api_key: str = typer.Option(..., envvar="QUIZ_OPENROUTER_API_KEY", help="OpenRouter API key"),
    model: str = typer.Option("nvidia/nemotron-3-super-120b-a12b:free", envvar="QUIZ_DEFAULT_MODEL"),
    db_path: str = typer.Option("quiz.db", envvar="QUIZ_DATABASE_PATH"),
    chunk_limit: int = typer.Option(0, help="Limit to first N chunks (0=all)"),
    concurrency: int = typer.Option(3, help="Max concurrent API calls"),
    questions_per_chunk: int = typer.Option(5, help="Target questions per chunk"),
    dry_run: bool = typer.Option(False, help="Print prompts without calling API"),
) -> None:
    """Generate quiz questions from extracted text chunks via OpenRouter."""
    asyncio.run(run_generation(
        chunks_file=chunks_file,
        api_key=api_key,
        model=model,
        db_path=db_path,
        roles=DEFAULT_ROLES,
        chunk_limit=chunk_limit,
        concurrency=concurrency,
        questions_per_chunk=questions_per_chunk,
        dry_run=dry_run,
    ))


@app.command()
def export(
    db_path: str = typer.Option("quiz.db", envvar="QUIZ_DATABASE_PATH"),
) -> None:
    """Export all questions from DB to data/questions.json."""
    asyncio.run(export_questions_json(db_path))


if __name__ == "__main__":
    app()
