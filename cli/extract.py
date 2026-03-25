"""PDF text extraction and chunking for engineer quiz question generation."""

import hashlib
import json
import re
import string
import sys
from pathlib import Path

import fitz  # pymupdf
import typer

app = typer.Typer()

SAMPLE_PAGES = [0, 9, 49, 99, 199, 299, 499]  # 0-indexed
CHAPTER_PATTERN = re.compile(
    r"^(?:CHAPTER|Chapter)\s+(\d+)", re.MULTILINE
)
# Running headers in this textbook are ALL-CAPS topic names
HEADER_PATTERN = re.compile(
    r"^([A-Z][A-Z\s,&-]{10,})$", re.MULTILINE
)
SECTION_PATTERN = re.compile(
    r"^(\d+\.\d+(?:\.\d+)?)\s+[A-Z]", re.MULTILINE
)


def page_stats(text: str) -> dict:
    """Compute quality stats for a page of extracted text."""
    chars = len(text)
    words = len(text.split())
    printable = sum(1 for c in text if c in string.printable)
    pct_printable = (printable / chars * 100) if chars > 0 else 0
    has_chapter = bool(CHAPTER_PATTERN.search(text))
    has_section = bool(SECTION_PATTERN.search(text))
    return {
        "chars": chars,
        "words": words,
        "pct_printable": round(pct_printable, 1),
        "has_chapter_heading": has_chapter,
        "has_section_heading": has_section,
    }


@app.command()
def probe(
    pdf: Path = typer.Option(..., help="Path to the PDF file"),
    pages: str = typer.Option(
        "",
        help="Comma-separated 1-indexed page numbers to sample (default: 1,10,50,100,200,300,500)",
    ),
):
    """Extract sample pages and report text quality stats."""
    doc = fitz.open(str(pdf))
    total_pages = len(doc)
    typer.echo(f"PDF: {pdf.name}")
    typer.echo(f"Total pages: {total_pages}")
    typer.echo(f"Metadata: {doc.metadata}")
    typer.echo("=" * 80)

    if pages:
        sample_indices = [int(p) - 1 for p in pages.split(",")]
    else:
        sample_indices = [p for p in SAMPLE_PAGES if p < total_pages]

    # Overall stats
    empty_pages = 0
    low_density_pages = 0
    chapter_pages = []

    for idx in sample_indices:
        if idx >= total_pages:
            typer.echo(f"\n--- Page {idx + 1}: SKIPPED (beyond {total_pages} pages) ---")
            continue
        page = doc[idx]
        text = page.get_text("text")
        stats = page_stats(text)

        typer.echo(f"\n{'=' * 80}")
        typer.echo(f"PAGE {idx + 1} | words={stats['words']} chars={stats['chars']} printable={stats['pct_printable']}%")
        if stats["has_chapter_heading"]:
            typer.echo("  >> CHAPTER HEADING DETECTED")
        if stats["has_section_heading"]:
            typer.echo("  >> SECTION HEADING DETECTED")
        typer.echo("-" * 80)
        # Show first 2000 chars
        preview = text[:2000]
        typer.echo(preview)
        if len(text) > 2000:
            typer.echo(f"\n  ... ({len(text) - 2000} more chars)")

    # Quick scan of ALL pages for chapter headings and density
    typer.echo(f"\n{'=' * 80}")
    typer.echo("FULL SCAN: chapter headings and page density")
    typer.echo("-" * 80)

    for idx in range(total_pages):
        page = doc[idx]
        text = page.get_text("text")
        words = len(text.split())

        if words < 10:
            empty_pages += 1
        elif words < 50:
            low_density_pages += 1

        match = CHAPTER_PATTERN.search(text)
        if match:
            chapter_pages.append((idx + 1, match.group(0), words))
        else:
            # Try running header pattern (ALL-CAPS lines like "ASTRODYNAMICS")
            header_match = HEADER_PATTERN.search(text)
            if header_match:
                header = header_match.group(1).strip()
                # Filter out page numbers and short junk
                if len(header) > 12 and header != "FUNDAMENTALS OF SPACE SYSTEMS":
                    chapter_pages.append((idx + 1, header, words))

    typer.echo(f"Empty pages (<10 words): {empty_pages}")
    typer.echo(f"Low density pages (10-50 words): {low_density_pages}")
    typer.echo(f"Usable pages (>50 words): {total_pages - empty_pages - low_density_pages}")
    typer.echo(f"\nChapter/section headings found ({len(chapter_pages)}):")
    # Deduplicate consecutive same headings
    seen = set()
    for pg, heading, words in chapter_pages:
        if heading not in seen:
            typer.echo(f"  Page {pg}: {heading} ({words} words)")
            seen.add(heading)

    doc.close()


@app.command()
def extract(
    pdf: Path = typer.Option(..., help="Path to the PDF file"),
    output: Path = typer.Option("chunks.json", help="Output JSON file"),
    chunk_size: int = typer.Option(2000, help="Target chunk size in words"),
):
    """Extract full text from PDF and split into chunks."""
    doc = fitz.open(str(pdf))
    total_pages = len(doc)
    book_name = pdf.stem

    # Build page texts with chapter detection
    pages = []
    current_chapter = "Unknown"
    for idx in range(total_pages):
        page = doc[idx]
        text = page.get_text("text")
        match = CHAPTER_PATTERN.search(text)
        if match:
            current_chapter = match.group(0)
        else:
            header_match = HEADER_PATTERN.search(text)
            if header_match:
                header = header_match.group(1).strip()
                if len(header) > 12 and header != "FUNDAMENTALS OF SPACE SYSTEMS":
                    current_chapter = header
        pages.append({
            "page": idx + 1,
            "chapter": current_chapter,
            "text": text,
            "words": len(text.split()),
        })

    # Merge pages into chunks of ~chunk_size words
    chunks = []
    current_chunk_text = ""
    current_chunk_pages = []
    current_chunk_chapter = pages[0]["chapter"] if pages else "Unknown"

    for pg in pages:
        if pg["words"] < 10:
            continue  # skip empty pages

        # Start new chunk on chapter boundary or size limit
        words_so_far = len(current_chunk_text.split())
        new_chapter = pg["chapter"] != current_chunk_chapter

        if (words_so_far >= chunk_size or new_chapter) and current_chunk_text.strip():
            chunk_hash = hashlib.sha256(current_chunk_text.encode()).hexdigest()[:16]
            chunks.append({
                "book": book_name,
                "chapter": current_chunk_chapter,
                "pages": f"{current_chunk_pages[0]}-{current_chunk_pages[-1]}",
                "words": words_so_far,
                "hash": chunk_hash,
                "text": current_chunk_text.strip(),
            })
            current_chunk_text = ""
            current_chunk_pages = []
            current_chunk_chapter = pg["chapter"]

        current_chunk_text += pg["text"] + "\n"
        current_chunk_pages.append(pg["page"])

    # Don't forget the last chunk
    if current_chunk_text.strip():
        words_so_far = len(current_chunk_text.split())
        chunk_hash = hashlib.sha256(current_chunk_text.encode()).hexdigest()[:16]
        chunks.append({
            "book": book_name,
            "chapter": current_chunk_chapter,
            "pages": f"{current_chunk_pages[0]}-{current_chunk_pages[-1]}",
            "words": words_so_far,
            "hash": chunk_hash,
            "text": current_chunk_text.strip(),
        })

    doc.close()

    output.write_text(json.dumps(chunks, indent=2))
    typer.echo(f"Extracted {len(chunks)} chunks from {total_pages} pages -> {output}")
    for c in chunks[:5]:
        typer.echo(f"  {c['chapter']} | pages {c['pages']} | {c['words']} words")
    if len(chunks) > 5:
        typer.echo(f"  ... and {len(chunks) - 5} more")


if __name__ == "__main__":
    app()
