"""Local file access for the board.

- load_docs(): concatenates the working docs (PRDs, notes, Brag Doc) for the
  agents that have reads_docs=True.
- append_brag(): the PM agent's write path -- adds a categorized entry under
  the right Brag Doc section.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime
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


_DATED = re.compile(r"^- \((\d{4}-\d{2}-\d{2})\)\s*(.*)$")


def recent_brag_entries(since: date) -> list[str]:
    """Brag Doc bullets dated on/after `since`, tagged with their section."""
    if not BRAG_PATH.exists():
        return []
    out, section = [], None
    for line in BRAG_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        m = _DATED.match(line.strip())
        if m:
            try:
                d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
            except ValueError:
                continue
            if d >= since:
                out.append(f"[{section}] ({m.group(1)}) {m.group(2)}".strip())
    return out


def recent_docs(since: date) -> list[str]:
    """Working-doc files (excluding the Brag Doc) modified on/after `since`."""
    res = []
    if not DOCS_DIR.exists():
        return res
    cutoff = datetime.combine(since, datetime.min.time()).timestamp()
    for p in sorted(DOCS_DIR.rglob("*")):
        if (p.is_file() and p.suffix.lower() in TEXT_EXT
                and p.name != "brag-doc.md" and p.stat().st_mtime >= cutoff):
            res.append(str(p.relative_to(DOCS_DIR)))
    return res


def recent_activity(since: date) -> str:
    """A compact 'what happened since `since`' block for the weekly summary."""
    brag = recent_brag_entries(since)
    docs = recent_docs(since)
    parts = []
    parts.append("Brag Doc entries logged in this window:\n"
                 + ("\n".join("  - " + b for b in brag) if brag else "  (none)"))
    parts.append("Working docs created/updated in this window:\n"
                 + ("\n".join("  - " + d for d in docs) if docs else "  (none)"))
    return "\n\n".join(parts)


def google_block() -> str:
    """Live Google context (calendar) for the agents; '' if unavailable."""
    try:
        import gsuite
        return gsuite.google_context()
    except Exception:
        return ""


def google_files_block() -> str:
    """Curated important Google files (Sheets/Docs) for the agents; '' if none."""
    try:
        import gsuite
        return gsuite.important_files_context()
    except Exception:
        return ""


def agent_context() -> str:
    """What read-access agents see: local docs + live calendar + key Google files."""
    blocks = [load_docs(), google_block(), google_files_block()]
    return "\n\n".join(b for b in blocks if b)


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
