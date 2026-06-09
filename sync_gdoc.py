#!/usr/bin/env python3
"""Read-only sync of Google Docs into ./docs so the agents can read them.

SAFETY: this only *reads* the google-docs OAuth access token from the macOS
keychain (the one Claude Code already maintains). It never refreshes, rotates,
or writes that token, so it can't break Claude's MCP auth. If the token is
missing/expired, the sync fails gracefully and the previously synced copy is
left in place.

Config (.env):
  GDOC_SYNC = "<docId>:<filename.md>, <docId2>:<filename2.md>"
  GDOC_1ON1_ID = <docId>     # convenience -> docs/1on1-nathan.md

Usage:
  python sync_gdoc.py            # sync everything configured
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
DOCS_DIR = ROOT / os.getenv("DOCS_DIR", "docs")
GDOCS_URL = "https://ztaip-se0r42l7-4xp4r634bq-uc.a.run.app/mcp"


def _token() -> str | None:
    try:
        raw = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True, timeout=15,
        ).stdout
        oauth = json.loads(raw).get("mcpOAuth", {})
        for v in oauth.values():
            if v.get("serverName") == "google-docs" and v.get("accessToken"):
                return v["accessToken"]
    except Exception:
        return None
    return None


def _sse_json(body: str) -> dict:
    chunks = [l[5:].strip() for l in body.splitlines() if l.startswith("data:")]
    return json.loads("".join(chunks)) if chunks else {}


def _fetch_doc(doc_id: str, token: str) -> dict | None:
    """Call getDocument via the MCP using curl (handles corp TLS)."""
    cookie = f"/tmp/adv_sync_cookies_{os.getpid()}"
    hdr = f"/tmp/adv_sync_hdr_{os.getpid()}"

    def call(payload, sid=None):
        args = ["curl", "-sS", "-c", cookie, "-b", cookie, "-D", hdr, GDOCS_URL,
                "-H", f"Authorization: Bearer {token}",
                "-H", "Content-Type: application/json",
                "-H", "Accept: application/json, text/event-stream"]
        if sid:
            args += ["-H", f"mcp-session-id: {sid}"]
        args += ["--data-binary", "@-", "--max-time", "45"]
        p = subprocess.run(args, input=json.dumps(payload), capture_output=True, text=True)
        return p.stdout

    init = call({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                            "clientInfo": {"name": "sync", "version": "1"}}})
    if "result" not in init:
        return None
    sid = None
    try:
        for line in Path(hdr).read_text().splitlines():
            if line.lower().startswith("mcp-session-id:"):
                sid = line.split(":", 1)[1].strip()
    except Exception:
        pass
    call({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    resp = call({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "getDocument", "arguments": {"documentId": doc_id}}}, sid)
    env = _sse_json(resp)
    try:
        return json.loads(env["result"]["content"][0]["text"])
    except Exception:
        return None
    finally:
        for f in (cookie, hdr):
            try:
                os.remove(f)
            except OSError:
                pass


def _doc_to_md(doc: dict) -> str:
    out = [f"# {doc.get('title','(untitled)')}", ""]

    def para(p):
        return "".join(e.get("textRun", {}).get("content", "") for e in p.get("elements", [])).rstrip("\n")

    for el in doc.get("body", {}).get("content", []):
        if "paragraph" in el:
            out.append(para(el["paragraph"]))
        elif "table" in el:
            for row in el["table"].get("tableRows", []):
                cells = []
                for c in row.get("tableCells", []):
                    txt = ""
                    for ce in c.get("content", []):
                        if "paragraph" in ce:
                            txt += para(ce["paragraph"]) + " "
                    cells.append(txt.strip())
                out.append(" | ".join(cells))
    return "\n".join(out).strip() + "\n"


def _targets() -> list[tuple[str, str]]:
    pairs = []
    raw = os.getenv("GDOC_SYNC", "").strip()
    if raw:
        for item in raw.split(","):
            if ":" in item:
                doc_id, fname = item.split(":", 1)
                pairs.append((doc_id.strip(), fname.strip()))
    one = os.getenv("GDOC_1ON1_ID", "").strip()
    if one and not any(d == one for d, _ in pairs):
        pairs.append((one, "1on1-nathan.md"))
    return pairs


def sync_all() -> list[tuple[str, str]]:
    """Sync every configured doc. Returns [(filename, status)]."""
    targets = _targets()
    if not targets:
        return [("(none)", "skipped (set GDOC_1ON1_ID or GDOC_SYNC)")]
    token = _token()
    if not token:
        return [(f, "skipped (no Google token; using last synced copy)") for _, f in targets]

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for doc_id, fname in targets:
        doc = _fetch_doc(doc_id, token)
        if not doc:
            results.append((fname, "err (fetch failed; kept last copy)"))
            continue
        (DOCS_DIR / fname).write_text(_doc_to_md(doc), encoding="utf-8")
        results.append((fname, f"ok ({doc.get('title','')})"))
    return results


if __name__ == "__main__":
    for fname, status in sync_all():
        print(f"[sync] {fname}: {status}")
    sys.exit(0)
