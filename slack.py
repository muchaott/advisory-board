"""Read-only Slack access for the board via `sofi-mcp-cli slack`.

Reuses the user's existing SoFi MCP auth — no Slack token is stored in this
project. If Slack auth is missing/expired the helpers return None/"" and the
board simply omits Slack context (run `sofi-mcp-cli mcp reconnect slack` to
re-authorize).

Wired into agent context like the Google blocks: recent messages from the
channels listed in SLACK_CHANNELS are injected for the read-access agents.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

# The GUI app launches with a minimal PATH, so resolve the CLI absolutely.
CLI = shutil.which("sofi-mcp-cli") or os.path.expanduser("~/.local/bin/sofi-mcp-cli")

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_FAIL = ("token refresh failed", "unauthorized", "authentication failed",
         "401", "run: sofi-mcp-cli mcp reconnect")

_CTX = {"text": None, "ts": 0.0}     # recent_context() cache
_TTL = 300                            # seconds
_PER = 6000                           # char cap per channel
_LAST_GOOD: dict = {}                 # channel -> last successful text


def available() -> bool:
    return bool(CLI) and Path(CLI).exists()


def _run(args: list[str], timeout: int = 30) -> str | None:
    """Run `sofi-mcp-cli slack <args>`; return clean stdout, or None on failure."""
    if not available():
        return None
    try:
        p = subprocess.run([CLI, "slack", *args], capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None
    out = _ANSI.sub("", p.stdout or "").strip()
    blob = (out + " " + (p.stderr or "")).lower()
    if p.returncode != 0 or not out or any(s in blob for s in _FAIL):
        return None
    return out


def history(channel: str, limit: int = 20) -> str | None:
    """Recent messages from a channel (by name or ID)."""
    return _run(["sofi:conversations-history", "-c", channel, "-l", str(limit)])


def search(query: str, count: int = 20) -> str | None:
    """Search messages (supports from:, in:, after:, before:)."""
    return _run(["sofi:search-messages", "-q", query, "-c", str(count)])


def send(channel: str, text: str) -> bool:
    """Post a message to a channel/DM (by name or ID). True on success."""
    if not available() or not channel or not text:
        return False
    try:
        p = subprocess.run([CLI, "slack", "sofi:chat-post-message", "-c", channel, "-t", text],
                           capture_output=True, text=True, timeout=30)
    except Exception:
        return False
    blob = ((p.stdout or "") + " " + (p.stderr or "")).lower()
    return p.returncode == 0 and not any(s in blob for s in _FAIL)


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
    print("sofi-mcp-cli:", CLI, "(found)" if available() else "(MISSING)")
    print("channels:", _channels() or "(none set — set SLACK_CHANNELS in .env)")
    ctx = recent_context(force=True)
    print(f"context chars: {len(ctx)}")
    print(ctx[:1200] if ctx else "(no Slack context — set SLACK_CHANNELS and run "
          "`sofi-mcp-cli mcp reconnect slack`)")
