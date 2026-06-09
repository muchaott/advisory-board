"""Local file access for the board.

- load_docs(): concatenates the working docs (PRDs, notes, Brag Doc) for the
  agents that have reads_docs=True.
- append_brag(): the PM agent's write path -- adds a categorized entry under
  the right Brag Doc section.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT / os.getenv("DOCS_DIR", "docs")
BRAG_PATH = DOCS_DIR / "brag-doc.md"

TEXT_EXT = {".md", ".markdown", ".txt", ".rst"}
MAX_CHARS = 60_000  # keep the injected context bounded


def load_docs() -> str:
    """Return a single string of all readable docs, truncated to MAX_CHARS."""
    if not DOCS_DIR.exists():
        return "(no docs folder found)"
    parts: list[str] = []
    for p in sorted(DOCS_DIR.rglob("*")):
        if p.is_file() and p.suffix.lower() in TEXT_EXT:
            try:
                body = p.read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                continue
            if body:
                rel = p.relative_to(DOCS_DIR)
                parts.append(f"--- FILE: {rel} ---\n{body}")
    if not parts:
        return "(docs folder is empty -- drop PRDs / notes / your Brag Doc into it)"
    blob = "\n\n".join(parts)
    if len(blob) > MAX_CHARS:
        blob = blob[:MAX_CHARS] + "\n\n[...truncated...]"
    return blob


SECTIONS = {
    "business impact": "## Business Impact",
    "ai leverage": "## AI Leverage",
    "cross-functional influence": "## Cross-functional Influence",
    "notes": "## Notes & Raw Log",
}


def _ensure_brag() -> str:
    if not BRAG_PATH.exists():
        BRAG_PATH.parent.mkdir(parents=True, exist_ok=True)
        BRAG_PATH.write_text(
            "# Brag Doc\n\n## Business Impact\n\n## AI Leverage\n\n"
            "## Cross-functional Influence\n\n## Notes & Raw Log\n",
            encoding="utf-8",
        )
    return BRAG_PATH.read_text(encoding="utf-8")


def append_brag(category: str, entry: str) -> str:
    """Insert a dated bullet under the matching Brag Doc section.

    category is fuzzy-matched to one of the four sections; unknown -> Notes.
    Returns the section heading it wrote under.
    """
    text = _ensure_brag()
    cat = (category or "").strip().lower()
    heading = next((h for k, h in SECTIONS.items() if k in cat or cat in k), SECTIONS["notes"])
    stamp = datetime.now().strftime("%Y-%m-%d")
    bullet = f"- ({stamp}) {entry.strip()}"

    lines = text.splitlines()
    out, inserted = [], False
    for i, line in enumerate(lines):
        out.append(line)
        if not inserted and line.strip() == heading:
            out.append(bullet)
            inserted = True
    if not inserted:  # heading missing -> append section
        out += ["", heading, bullet]
    BRAG_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    return heading
