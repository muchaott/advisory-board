"""Read-only access to the user's Google Workspace via the SoFi MCP gateway.

Reuses the OAuth access tokens Claude Code already keeps in the macOS keychain.
SAFETY: read-only — never refreshes or writes a token, so it can't break Claude's
MCP auth. Tokens expire ~daily (Claude refreshes them on use); if a token is
missing/expired a call returns None and callers fall back gracefully.

`call(server, tool, args)` reaches ANY of the six Google MCPs. Convenience
helpers cover the calendar (the piece wired into the board's context).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

SERVERS = {
    "calendar": "google-calendar", "docs": "google-docs", "drive": "google-drive",
    "sheets": "google-sheets", "slides": "google-slides", "gmail": "gmail",
}

_CACHE: dict = {}          # server -> (token, url)
_CTX_CACHE = {"text": None, "ts": 0.0}
_CTX_TTL = 300             # seconds

_FILES_CACHE = {"text": None, "ts": 0.0}   # important_files_context()
_FILES_TTL = 300                            # seconds
_FILES_PER = 14_000                         # char cap per file
_FILE_LAST_GOOD: dict = {}                  # id -> last successful markdown


def _creds(server: str):
    name = SERVERS.get(server, server)
    try:
        raw = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True, timeout=15).stdout
        for v in (json.loads(raw).get("mcpOAuth", {}) or {}).values():
            if v.get("serverName") == name and v.get("accessToken"):
                return v["accessToken"], v["serverUrl"]
    except Exception:
        pass
    return None, None


def call(server: str, tool: str, args: dict | None = None):
    """Call one tool on a Google MCP server. Returns parsed JSON/text, or None."""
    token, url = _creds(server)
    if not token:
        return None
    cookie = f"/tmp/adv_g_{os.getpid()}_{server}"
    hdr = cookie + ".h"

    def post(payload, sid=None):
        a = ["curl", "-sS", "-c", cookie, "-b", cookie, "-D", hdr, url,
             "-H", f"Authorization: Bearer {token}", "-H", "Content-Type: application/json",
             "-H", "Accept: application/json, text/event-stream"]
        if sid:
            a += ["-H", f"mcp-session-id: {sid}"]
        a += ["--data-binary", "@-", "--max-time", "30"]
        return subprocess.run(a, input=json.dumps(payload), capture_output=True, text=True).stdout

    def sse(body):
        chunks = [l[5:].strip() for l in body.splitlines() if l.startswith("data:")]
        return json.loads("".join(chunks)) if chunks else {}

    try:
        init = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                "clientInfo": {"name": "advisory", "version": "1"}}})
        if '"result"' not in init:
            return None
        sid = None
        for line in open(hdr).read().splitlines():
            if line.lower().startswith("mcp-session-id:"):
                sid = line.split(":", 1)[1].strip()
        post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
        env = sse(post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                        "params": {"name": tool, "arguments": args or {}}}, sid))
        text = env.get("result", {}).get("content", [{}])[0].get("text")
        if text is None:
            return None
        try:
            return json.loads(text)
        except Exception:
            return text
    except Exception:
        return None
    finally:
        for f in (cookie, hdr):
            try:
                os.remove(f)
            except OSError:
                pass


# ---- calendar ----------------------------------------------------------

def _rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def calendar_events(time_min: datetime, time_max: datetime) -> list[dict]:
    res = call("calendar", "listEvents", {
        "calendarId": "primary", "timeMin": _rfc3339(time_min), "timeMax": _rfc3339(time_max),
        "singleEvents": True, "orderBy": "startTime", "maxResults": 25,
    })
    if not isinstance(res, dict):
        return []
    return res.get("items", []) or []


def _fmt(ev: dict) -> str:
    start = ev.get("start", {})
    when = start.get("dateTime") or start.get("date") or ""
    if "T" in when:
        try:
            t = datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone()
            when = t.strftime("%a %H:%M")
        except Exception:
            pass
    else:
        when = (when or "") + " (all-day)"
    title = ev.get("summary", "(no title)")
    return f"{when} — {title}"


def calendar_today() -> list[str]:
    now = datetime.now().astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return [_fmt(e) for e in calendar_events(start, end)]


def calendar_upcoming(days: int = 7) -> list[str]:
    now = datetime.now().astimezone()
    end = (now + timedelta(days=days)).replace(hour=23, minute=59, second=59)
    return [_fmt(e) for e in calendar_events(now, end)]


def google_context(force: bool = False) -> str:
    """A compact calendar block for the agents' context (cached ~5 min)."""
    if not force and _CTX_CACHE["text"] is not None and (time.time() - _CTX_CACHE["ts"]) < _CTX_TTL:
        return _CTX_CACHE["text"]
    try:
        today = calendar_today()
        soon = calendar_upcoming(7)
    except Exception:
        today, soon = [], []
    if not today and not soon:
        text = ""  # token stale or nothing scheduled — stay silent
    else:
        parts = ["MY CALENDAR (Google):"]
        parts.append("Today:\n" + ("\n".join("  - " + t for t in today) if today else "  (nothing today)"))
        if soon:
            parts.append("Next 7 days:\n" + "\n".join("  - " + s for s in soon[:12]))
        text = "\n".join(parts)
    _CTX_CACHE["text"] = text
    _CTX_CACHE["ts"] = time.time()
    return text


# ---- important files (curated live context: Sheets + Docs) -------------

def _para(p: dict) -> str:
    return "".join(e.get("textRun", {}).get("content", "") for e in p.get("elements", [])).rstrip("\n")


def doc_markdown(doc_id: str) -> str | None:
    """Plain-markdown text of a Google Doc, or None if unavailable."""
    doc = call("docs", "getDocument", {"documentId": doc_id})
    if not isinstance(doc, dict) or "error" in doc:
        return None
    out = [f"# {doc.get('title', '(untitled)')}", ""]
    for el in doc.get("body", {}).get("content", []):
        if "paragraph" in el:
            out.append(_para(el["paragraph"]))
        elif "table" in el:
            for row in el["table"].get("tableRows", []):
                cells = []
                for c in row.get("tableCells", []):
                    txt = "".join(_para(ce["paragraph"]) + " "
                                  for ce in c.get("content", []) if "paragraph" in ce)
                    cells.append(txt.strip())
                out.append(" | ".join(cells))
    return "\n".join(out).strip()


def sheet_markdown(sid: str, max_rows: int = 60, max_cols: int = 30) -> str | None:
    """Render a Google Sheet's tabs as markdown pipe tables, or None."""
    meta = call("sheets", "getSpreadsheet", {"spreadsheetId": sid})
    if not isinstance(meta, dict) or "error" in meta:
        return None
    title = meta.get("properties", {}).get("title", "(untitled sheet)")
    tabs = [s.get("properties", {}).get("title") for s in meta.get("sheets", [])]
    out = [f"# {title}"]
    for tab in tabs:
        if not tab:
            continue
        v = call("sheets", "getValues", {"spreadsheetId": sid, "range": tab})
        rows = v.get("values", []) if isinstance(v, dict) else []
        out.append(f"\n## {tab}")
        if not rows:
            out.append("(empty)")
            continue
        for r in rows[:max_rows]:
            cells = [str(c) for c in r[:max_cols]]
            out.append(" | ".join(cells))
        if len(rows) > max_rows:
            out.append(f"… (+{len(rows) - max_rows} more rows)")
    return "\n".join(out).strip()


def _gfiles() -> list[tuple[str, str, str]]:
    """Parse GFILES env: 'type:id:label, type:id:label' -> [(type, id, label)]."""
    out = []
    for item in (os.getenv("GFILES", "") or "").split(","):
        item = item.strip()
        if not item:
            continue
        parts = item.split(":")
        if len(parts) < 2:
            continue
        ftype = parts[0].strip().lower()
        fid = parts[1].strip()
        label = (":".join(parts[2:]).strip() if len(parts) > 2 else fid)
        if ftype in ("sheet", "doc") and fid:
            out.append((ftype, fid, label))
    return out


def important_files_context(force: bool = False) -> str:
    """Curated Google files (Sheets/Docs) rendered for agent context.

    Cached ~5 min. Each file falls back to its last-good copy on a transient
    failure, so a stale token degrades gracefully instead of dropping content.
    """
    if (not force and _FILES_CACHE["text"] is not None
            and (time.time() - _FILES_CACHE["ts"]) < _FILES_TTL):
        return _FILES_CACHE["text"]
    blocks = []
    for ftype, fid, label in _gfiles():
        md = sheet_markdown(fid) if ftype == "sheet" else doc_markdown(fid)
        if md:
            _FILE_LAST_GOOD[fid] = md
        else:
            md = _FILE_LAST_GOOD.get(fid)  # keep last good copy if fetch failed
        if md:
            if len(md) > _FILES_PER:
                md = md[:_FILES_PER] + "\n… [truncated]"
            blocks.append(f"### {label}\n{md}")
    text = ("MY KEY GOOGLE FILES (live, read-only):\n\n" + "\n\n".join(blocks)) if blocks else ""
    _FILES_CACHE["text"] = text
    _FILES_CACHE["ts"] = time.time()
    return text


def status() -> dict:
    """Which Google services have a usable token right now."""
    return {k: (_creds(k)[0] is not None) for k in SERVERS}


if __name__ == "__main__":
    print("token status:", json.dumps(status()))
    print("today:", calendar_today())
