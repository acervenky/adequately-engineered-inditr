"""
Chunker and indexer for IndITR RAG knowledge base.

Strategy:
  - Split markdown by heading (## / ###) to preserve topic coherence
  - Hard-cap chunks at MAX_CHARS; slide with OVERLAP_CHARS for boundary coverage
  - Each chunk carries its source filename + heading path as metadata

Run via:
    python scripts/build_rag_index.py
"""
from __future__ import annotations
import re
import logging
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

MAX_CHARS    = 800   # ~200 tokens for bge-small (512-token limit)
OVERLAP_CHARS = 80   # overlap to avoid cutting mid-concept

# Resolve knowledge directory relative to this file
KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"


# ── Chunking ──────────────────────────────────────────────────────────────────

def _split_by_heading(text: str) -> list[tuple[str, str]]:
    """
    Split markdown into (heading_path, content) pairs.
    heading_path e.g. "Standard Deduction > New Regime"
    """
    sections: list[tuple[str, str]] = []
    current_heading = "Overview"
    current_lines: list[str] = []
    heading_stack: list[str] = []

    for line in text.splitlines():
        m = re.match(r'^(#{1,3})\s+(.+)', line)
        if m:
            # Flush previous section
            content = "\n".join(current_lines).strip()
            if content:
                sections.append((current_heading, content))
            current_lines = []

            level = len(m.group(1))
            title = m.group(2).strip()
            # Maintain breadcrumb
            heading_stack = heading_stack[:level - 1] + [title]
            current_heading = " > ".join(heading_stack)
        else:
            current_lines.append(line)

    # Flush final section
    content = "\n".join(current_lines).strip()
    if content:
        sections.append((current_heading, content))

    return sections


def _slide_chunk(text: str) -> Iterator[str]:
    """Hard-cap chunks at MAX_CHARS with OVERLAP_CHARS sliding window."""
    if len(text) <= MAX_CHARS:
        yield text.strip()
        return

    start = 0
    while start < len(text):
        end = start + MAX_CHARS
        chunk = text[start:end].strip()
        if chunk:
            yield chunk
        if end >= len(text):
            break
        start = end - OVERLAP_CHARS


def iter_chunks(md_text: str, source: str) -> Iterator[dict]:
    """
    Yield chunk dicts: {text, source, section}
    source = filename slug (e.g. "capital_gains")

    The section heading is prepended to each chunk so that searches for
    terms that appear only in headings (e.g. "Section 192", "ITR-1 eligibility")
    still hit the right chunks.
    """
    sections = _split_by_heading(md_text)
    for heading, content in sections:
        # Build the searchable text: heading context + body
        # Strip markdown bold/italic from heading for cleaner text
        clean_heading = re.sub(r'\*+', '', heading).strip()
        for chunk in _slide_chunk(content):
            if len(chunk) < 30:   # skip trivial fragments
                continue
            # Prefix heading so heading keywords are always in the chunk text
            full_text = f"{clean_heading}\n{chunk}" if clean_heading else chunk
            yield {
                "text":    full_text,
                "source":  source,
                "section": heading,
            }


# ── Indexing ──────────────────────────────────────────────────────────────────

def build_index() -> int:
    """
    Read all .md files from KNOWLEDGE_DIR, chunk, embed, and insert into zvec.
    Returns total chunk count inserted.
    """
    import zvec
    from inditr.rag.embedder import get_embedder
    from inditr.rag.store import create_collection

    if not KNOWLEDGE_DIR.exists():
        raise FileNotFoundError(f"Knowledge directory not found: {KNOWLEDGE_DIR}")

    md_files = sorted(KNOWLEDGE_DIR.glob("*.md"))
    if not md_files:
        raise FileNotFoundError(f"No .md files found in {KNOWLEDGE_DIR}")

    embedder = get_embedder()
    collection = create_collection(dimension=embedder.dimension)

    total = 0
    for md_path in md_files:
        source = md_path.stem
        text   = md_path.read_text(encoding="utf-8")
        chunks = list(iter_chunks(text, source))
        logger.info("  %s → %d chunks", source, len(chunks))

        docs = []
        for i, chunk in enumerate(chunks):
            vec = embedder.embed(chunk["text"])
            doc = zvec.Doc(
                id=f"{source}__{i:04d}",
                vectors={"embedding": vec},
                fields={
                    "text":    chunk["text"],
                    "source":  chunk["source"],
                    "section": chunk["section"],
                },
            )
            docs.append(doc)

        results = collection.insert(docs)
        ok = sum(1 for r in results if r.ok())
        logger.info("    inserted %d/%d chunks", ok, len(docs))
        total += ok

    logger.info("RAG index built: %d total chunks from %d documents", total, len(md_files))
    return total
