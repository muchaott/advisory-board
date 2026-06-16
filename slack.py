"""Read + post Slack via the keychain MCP (same OAuth store as Google), reached
through gsuite.call. Returns None/"" / False gracefully when the Slack token is
missing or expired (it refreshes when Claude Code next uses the Slack MCP).

Wired into agent context like the Google blocks: recent messages from the
channels listed in SLACK_CHANNELS are injected for the read-access agents.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

import gsuite

_CTX = {"text": None, "ts": 0.0}     # recent_context() cache
_TTL = 300                            # seconds
_PER = 6000                           # char cap per channel
_LAST_GOOD: dict = {}                 # channel -> last successful text
_ID_CACHE: dict = {}                  # channel name -> id


def available() -> bool:
    return gsuite._creds("slack")[0] is not None


def _ok(r) -> bool:
    return isinstance(r, dict) and r.get("ok") is True


def send(channel: str, text: str) -> bool:
    """Post a message to a channel/DM (by name or ID). True on success."""
    if not channel or not text:
        return False
    return _ok(gsuite.call("slack", "chatPostMessage", {"channel": channel, "text": text}))


def search(query: str, count: int = 20) -> str | None:
    """Search messages (supports from:, in:, after:, before:)."""
    r = gsuite.call("slack", "searchMessages", {"query": query, "count": count})
    if not _ok(r):
        return None
    matches = ((r.get("messages") or {}).get("matches")) or []
    lines = [f"- {m.get('username') or m.get('user', '')}: {(m.get('text') or '').replace(chr(10), ' ')}"
             for m in matches]
    return "\n".join(lines) if lines else "(no matches)"


def _resolve_channel(name: str) -> str | None:
    """Resolve a channel name to its ID (cached). Bounded scan of conversationsList."""
    name = name.lstrip("#")
    if name in _ID_CACHE:
        return _ID_CACHE[name]
    cursor = None
    for _ in range(5):   # ~1000 channels max
        args = {"limit": 200, "types": "public_channel,private_channel", "exclude_archived": True}
        if cursor:
            args["cursor"] = cursor
        r = gsuite.call("slack", "conversationsList", args)
        if not _ok(r):
            return None
        for c in r.get("channels", []) or []:
            if c.get("name") == name:
                _ID_CACHE[name] = c["id"]
                return c["id"]
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return None


def history(channel: str, limit: int = 20) -> str | None:
    """Recent messages from a channel (by name or ID)."""
    cid = channel if channel[:1] in ("C", "G", "D") and channel.isupper() else _resolve_channel(channel)
    if not cid:
        return None
    r = gsuite.call("slack", "conversationsHistory", {"channel": cid, "limit": limit})
    if not _ok(r):
        return None
    msgs = r.get("messages", []) or []
    lines = [f"- {(m.get('text') or '').replace(chr(10), ' ')}" for m in msgs if m.get("text")]
    return "\n".join(lines) if lines else "(no recent messages)"


def _channels() -> list[str]:
    return [c.strip() for c in (os.getenv("SLACK_CHANNELS", "") or "").split(",") if c.strip()]


def recent_context(force: bool = False) -> str:
    """Recent messages from the configured channels, for agent context.

    Cached ~5 min; each channel falls back to its last-good copy on a transient
    failure. Returns '' when Slack isn't configured/authorized.
    """
    if not force and _CTX["text"] is not None and (time.time() - _CTX["ts"]) < _TTL:
        return _CTX["text"]
    limit = int(os.getenv("SLACK_HISTORY_LIMIT", "20") or 20)
    blocks = []
    for ch in _channels():
        # passive context uses channel IDs only (fast); name lookup is too slow in a
        # huge workspace — use the search_slack tool on demand for channels by name.
        if not (ch[:1] in ("C", "G", "D") and ch.isupper()):
            continue
        txt = history(ch, limit)
        if txt:
            _LAST_GOOD[ch] = txt
        else:
            txt = _LAST_GOOD.get(ch)
        if txt:
            if len(txt) > _PER:
                txt = txt[:_PER] + "\n… [truncated]"
            blocks.append(f"### #{ch.lstrip('#')}\n{txt}")
    text = ("MY SLACK (recent, read-only):\n\n" + "\n\n".join(blocks)) if blocks else ""
    _CTX["text"] = text
    _CTX["ts"] = time.time()
    return text


if __name__ == "__main__":
    print("slack token present:", available())
    print("channels:", _channels() or "(none set — set SLACK_CHANNELS in .env)")
    ctx = recent_context(force=True)
    print(f"context chars: {len(ctx)}")
    print(ctx[:800] if ctx else "(no Slack context)")
