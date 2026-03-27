"""Extract questions from exam papers using PyMuPDF + Claude subagent."""

import asyncio
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import aiosqlite
import fitz
import typer

app = typer.Typer()

STATIC_DIR = Path(__file__).resolve().parent.parent / "src" / "static"


def _extract_json_array(text: str) -> list[dict]:
    """Extract JSON array from text that may contain preamble/postamble."""
    # Try parsing directly first
    stripped = text.strip()
    if stripped.startswith("["):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    # Strip markdown fences
    if "```" in stripped:
        match = re.search(r"```(?:json)?\s*\n(.*?)```", stripped, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

    # Find the first [ and last ] — extract the array
    first_bracket = stripped.find("[")
    last_bracket = stripped.rfind("]")
    if first_bracket != -1 and last_bracket > first_bracket:
        try:
            return json.loads(stripped[first_bracket : last_bracket + 1])
        except json.JSONDecodeError:
            pass

    raise json.JSONDecodeError("No valid JSON array found in output", text, 0)


def slugify(name: str) -> str:
    """Convert a filename to a URL-safe slug."""
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[-\s]+", "-", s)
    return s.strip("-")


def extract_text_by_page(doc: fitz.Document) -> list[dict]:
    """Extract text from each page with page numbers."""
    pages = []
    for i in range(len(doc)):
        page = doc[i]
        text = page.get_text("text")
        pages.append({"page": i + 1, "text": text, "words": len(text.split())})
    return pages


def render_pages_as_png(doc: fitz.Document, output_dir: Path, dpi: int = 200) -> list[str]:
    """Render each page as PNG. Returns list of filenames."""
    output_dir.mkdir(parents=True, exist_ok=True)
    filenames = []
    for i in range(len(doc)):
        page = doc[i]
        pixmap = page.get_pixmap(dpi=dpi)
        filename = f"page_{i + 1}.png"
        pixmap.save(str(output_dir / filename))
        filenames.append(filename)
    return filenames


def split_sections(pages: list[dict]) -> dict:
    """Split pages into paper 1 questions, paper 2 questions, and marking scheme."""
    paper2_start = None
    marking_start = None

    for p in pages:
        text = p["text"]
        if "PAPER 2" in text and paper2_start is None:
            paper2_start = p["page"]
        if "Marking Scheme" in text and marking_start is None:
            marking_start = p["page"]

    sections = {
        "paper1_pages": [],
        "paper2_pages": [],
        "marking_pages": [],
    }

    for p in pages:
        pg = p["page"]
        if marking_start and pg >= marking_start:
            sections["marking_pages"].append(p)
        elif paper2_start and pg >= paper2_start:
            sections["paper2_pages"].append(p)
        else:
            sections["paper1_pages"].append(p)

    return sections


def build_subagent_prompt(
    sections: dict,
    diagram_filenames: list[str],
    book_slug: str,
) -> str:
    """Build the prompt for the Claude subagent."""

    # Concatenate all question pages with markers
    question_text = ""
    for section_name in ["paper1_pages", "paper2_pages"]:
        for p in sections[section_name]:
            if p["words"] > 5:  # skip near-empty pages
                question_text += f"\n--- PAGE {p['page']} ---\n{p['text']}\n"

    # Concatenate marking scheme
    marking_text = ""
    for p in sections["marking_pages"]:
        if p["words"] > 5:
            marking_text += f"\n--- MARKING SCHEME PAGE {p['page']} ---\n{p['text']}\n"

    # List diagram images available
    diagram_list = "\n".join(f"- {f}" for f in diagram_filenames)

    prompt = f"""You are extracting questions from a secondary school mathematics exam paper.

The exam has two papers. Below is the extracted text from all question pages, followed by the official marking scheme with correct answers.

Your task:
1. Identify every distinct question (and sub-question like 7a, 7b) in both papers
2. For each question, output structured JSON
3. Use the marking scheme to determine the correct answer — do NOT guess
4. Determine if the question needs a diagram from the exam paper
5. Classify each question's answer type for automated grading

EXAM TEXT:
{question_text}

MARKING SCHEME:
{marking_text}

AVAILABLE DIAGRAM IMAGES (one per page):
{diagram_list}

For each question, determine:
- question_type: "math" for computational/algebraic answers, "mc" for multiple choice (if any), "open" for construction/proof/explanation questions that can't be auto-graded
- difficulty: 1 (straightforward computation) or 2 (multi-step problem)
- diagram_images: array of page filenames that contain diagrams RELEVANT to this specific question. Only include a page if its diagram is actually needed to answer the question. Use the page numbers in the text to match — if a question appears on page 6 and references "the diagram", then "page_6.png" is likely relevant. Leave empty [] if no diagram needed.
- math_metadata: for "math" type questions only:
  - answer_type: "numeric" if the answer is a number, "expression" if it's an algebraic expression
  - expected_value: the numeric answer (for numeric type)
  - expected_expression: sympy-parseable expression string (for expression type). Use Python syntax: ** for power, * for multiply. Variables as single letters.
  - tolerance: acceptable numeric tolerance (default 0.01, use larger for rounded answers)

Output ONLY a JSON array (no markdown fences, no explanation):
[
  {{
    "question_type": "math",
    "difficulty": 1,
    "roles": ["Math Student"],
    "question_text": "The full question text as it appears in the exam",
    "correct_answer": "The answer from the marking scheme",
    "explanation": "Brief explanation of the solution method",
    "source_page": 6,
    "diagram_images": ["page_6.png"],
    "math_metadata": {{
      "answer_type": "numeric",
      "expected_value": 156.2,
      "expected_expression": null,
      "tolerance": 0.1
    }}
  }},
  {{
    "question_type": "math",
    "difficulty": 1,
    "roles": ["Math Student"],
    "question_text": "Simplify 2c^5 / (20c^2 d)",
    "correct_answer": "c^3 / (10d)",
    "explanation": "Divide coefficients and subtract exponents",
    "source_page": 4,
    "diagram_images": [],
    "math_metadata": {{
      "answer_type": "expression",
      "expected_value": null,
      "expected_expression": "c**3 / (10*d)",
      "tolerance": null
    }}
  }},
  {{
    "question_type": "open",
    "difficulty": 2,
    "roles": ["Math Student"],
    "question_text": "Construct the bisector of angle ABC",
    "correct_answer": "Correct construction with visible arcs",
    "explanation": "Geometric construction — cannot be auto-graded",
    "source_page": 6,
    "diagram_images": ["page_6.png"],
    "math_metadata": null
  }}
]

Important:
- Extract ALL questions from both Paper 1 and Paper 2
- For sub-questions (e.g., 9a, 9b, 9c), create separate entries
- source_page is the page number where the question appears in the PDF
- For expressions, ensure sympy compatibility: use ** not ^, explicit * for multiplication
- If a question involves reading a diagram/graph to get values, it NEEDS the diagram image
- Construction questions (compass/ruler) should be "open" type since they can't be auto-graded
- Proof/explanation questions should also be "open" type"""

    return prompt


def verify_diagram_relevance(
    questions: list[dict], pages: list[dict]
) -> list[dict]:
    """Verify that diagram associations are plausible based on page proximity."""
    warnings = []
    for i, q in enumerate(questions):
        if not q.get("diagram_images"):
            continue
        source_page = q.get("source_page", 0)
        for img in q["diagram_images"]:
            match = re.match(r"page_(\d+)\.png", img)
            if not match:
                warnings.append(
                    f"Q{i+1}: invalid diagram filename '{img}'"
                )
                continue
            diagram_page = int(match.group(1))
            distance = abs(diagram_page - source_page)
            if distance > 2:
                warnings.append(
                    f"Q{i+1} (page {source_page}): diagram '{img}' is {distance} pages away — suspicious"
                )
    return warnings


async def store_questions(
    questions: list[dict], book_name: str, db_path: str
) -> int:
    """Store extracted questions in the database."""
    async with aiosqlite.connect(db_path) as db:
        count = 0
        for q in questions:
            await db.execute(
                """INSERT INTO questions (book, chapter, question_type, difficulty,
                   roles, question_text, options, correct_answer, explanation,
                   diagram_images, math_metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    book_name,
                    q.get("chapter"),
                    q.get("question_type", "math"),
                    q.get("difficulty", 1),
                    json.dumps(q.get("roles", ["Math Student"])),
                    q["question_text"],
                    json.dumps(q["options"]) if q.get("options") else None,
                    q.get("correct_answer", ""),
                    q.get("explanation"),
                    json.dumps(q["diagram_images"]) if q.get("diagram_images") else None,
                    json.dumps(q["math_metadata"]) if q.get("math_metadata") else None,
                ),
            )
            count += 1
        await db.commit()
    return count


async def export_questions_json(db_path: str) -> None:
    """Export all questions from DB to data/questions.json."""
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(exist_ok=True)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT book, chapter, chunk_hash, question_type, difficulty, roles, "
            "question_text, options, correct_answer, explanation, "
            "diagram_images, math_metadata FROM questions ORDER BY id"
        )
        rows = await cursor.fetchall()

    questions = []
    for r in rows:
        q = dict(r)
        q["roles"] = json.loads(q["roles"])
        q["options"] = json.loads(q["options"]) if q["options"] else None
        q["diagram_images"] = json.loads(q["diagram_images"]) if q.get("diagram_images") else None
        q["math_metadata"] = json.loads(q["math_metadata"]) if q.get("math_metadata") else None
        questions.append(q)

    out = data_dir / "questions.json"
    out.write_text(json.dumps(questions, indent=2) + "\n")
    typer.echo(f"Exported {len(questions)} questions to {out}")


@app.command()
def extract(
    pdf: Path = typer.Option(..., help="Path to the exam PDF"),
    db_path: str = typer.Option("quiz.db", envvar="QUIZ_DATABASE_PATH"),
    dpi: int = typer.Option(200, help="DPI for page rendering"),
    dry_run: bool = typer.Option(False, help="Extract and build prompt without calling subagent"),
) -> None:
    """Extract questions from an exam paper using Claude subagent."""
    typer.echo(f"Opening {pdf.name}...")
    doc = fitz.open(str(pdf))
    book_slug = slugify(pdf.stem)
    book_name = pdf.stem

    # Step 1: Extract text
    typer.echo(f"Extracting text from {len(doc)} pages...")
    pages = extract_text_by_page(doc)

    # Step 2: Render pages as PNG
    diagram_dir = STATIC_DIR / "diagrams" / book_slug
    typer.echo(f"Rendering pages as PNG to {diagram_dir}...")
    filenames = render_pages_as_png(doc, diagram_dir, dpi=dpi)
    doc.close()

    # Step 3: Split into sections
    sections = split_sections(pages)
    typer.echo(
        f"Sections: Paper 1 = {len(sections['paper1_pages'])} pages, "
        f"Paper 2 = {len(sections['paper2_pages'])} pages, "
        f"Marking = {len(sections['marking_pages'])} pages"
    )

    # Step 4: Build prompt
    prompt = build_subagent_prompt(sections, filenames, book_slug)
    typer.echo(f"Prompt length: {len(prompt)} chars ({len(prompt.split())} words)")

    if dry_run:
        typer.echo("\n[DRY RUN] Prompt preview (first 2000 chars):")
        typer.echo(prompt[:2000])
        typer.echo(f"\n... ({len(prompt) - 2000} more chars)")
        return

    # Step 5: Invoke Claude subagent
    typer.echo("Invoking Claude subagent...")
    try:
        # Write prompt to temp file and reference it — avoids arg length limits
        # and stdin buffering issues with long prompts
        prompt_path = Path(tempfile.mktemp(suffix=".txt"))
        prompt_path.write_text(prompt)

        result = subprocess.run(
            [
                "claude",
                "-p",
                f"Read the file {prompt_path} and follow its instructions exactly. Output ONLY the JSON array.",
                "--allowedTools", "Read",
                "--output-format", "json",
            ],
            capture_output=True,
            text=True,
            timeout=900,
        )
        prompt_path.unlink(missing_ok=True)
    except FileNotFoundError:
        typer.echo("Error: 'claude' CLI not found. Install Claude Code first.", err=True)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        typer.echo("Error: Claude subagent timed out after 600s.", err=True)
        sys.exit(1)

    if result.returncode != 0:
        typer.echo(f"Subagent failed (exit {result.returncode}):", err=True)
        typer.echo(f"stderr: {result.stderr[:1000]}", err=True)
        typer.echo(f"stdout: {result.stdout[:1000]}", err=True)
        sys.exit(1)

    # Step 6: Parse output
    try:
        output = json.loads(result.stdout)
        # Handle --output-format json wrapper: the result field contains the actual content
        if isinstance(output, dict) and "result" in output:
            content = output["result"]
            if isinstance(content, list):
                questions = content
            elif isinstance(content, str):
                questions = _extract_json_array(content)
            else:
                typer.echo(f"Unexpected result type: {type(content)}", err=True)
                sys.exit(1)
        elif isinstance(output, list):
            questions = output
        else:
            typer.echo(f"Unexpected output format: {type(output)}", err=True)
            sys.exit(1)
    except json.JSONDecodeError as e:
        typer.echo(f"Failed to parse subagent output as JSON: {e}", err=True)
        typer.echo(f"Raw output (first 500 chars): {result.stdout[:500]}", err=True)
        sys.exit(1)

    typer.echo(f"Extracted {len(questions)} questions")

    # Step 7: Verify diagram relevance
    warnings = verify_diagram_relevance(questions, pages)
    if warnings:
        typer.echo(f"\nDiagram relevance warnings ({len(warnings)}):")
        for w in warnings:
            typer.echo(f"  ⚠ {w}")
        suspicious_pct = len(warnings) / max(1, sum(1 for q in questions if q.get("diagram_images")))
        if suspicious_pct > 0.3:
            typer.echo(
                f"\n⚠ {suspicious_pct:.0%} of diagram associations are suspicious. "
                "Review the output carefully.",
                err=True,
            )

    # Step 8: Store in DB
    from src.db import init_db

    asyncio.run(init_db())
    count = asyncio.run(store_questions(questions, book_name, db_path))
    typer.echo(f"Stored {count} questions in {db_path}")

    # Step 9: Export
    asyncio.run(export_questions_json(db_path))

    # Summary
    types = {}
    with_diagrams = 0
    for q in questions:
        qt = q.get("question_type", "unknown")
        types[qt] = types.get(qt, 0) + 1
        if q.get("diagram_images"):
            with_diagrams += 1

    typer.echo(f"\nSummary:")
    for qt, n in sorted(types.items()):
        typer.echo(f"  {qt}: {n}")
    typer.echo(f"  with diagrams: {with_diagrams}")


if __name__ == "__main__":
    app()
