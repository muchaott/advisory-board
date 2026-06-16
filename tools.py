"""Tools the board agents can call mid-conversation (Anthropic tool-use).

Read + create/append Google Docs and create Google Sheets. Each tool fails
*gracefully* — if the needed MCP access is missing/expired it returns an
`auth_needed` result so the agent asks the user to authorize, and the UI shows
an actionable prompt.
"""
from __future__ import annotations

import re

import gsuite
import slack

# How to (re)authorize each MCP the tools depend on.
AUTH_HOWTO = {
    "google-docs": "Google Docs access — its token has likely expired. Reconnect Google "
                   "in Claude Code (/mcp → google-docs) or refresh it, then ask me again.",
    "google-sheets": "Google Sheets access — its token has likely expired. Reconnect Google "
                     "in Claude Code (/mcp → google-sheets), then retry.",
    "google-calendar": "Google Calendar access — its token has likely expired. Reconnect Google "
                       "in Claude Code (/mcp → google-calendar), then retry.",
    "slack": "Slack access — its token has likely expired. Reconnect Slack in Claude Code (/mcp → slack), then retry.",
    "gmail": "Gmail access — its token has likely expired. Reconnect Google in Claude Code (/mcp → gmail), then retry.",
    "google-drive": "Google Drive access — its token has likely expired. Reconnect Google in Claude Code (/mcp → google-drive), then retry.",
}

_READ_CAP = 12_000   # cap text returned to the model from a read


def extract_id(s: str) -> str:
    """Pull a Google file ID out of a URL, or accept a bare ID."""
    s = (s or "").strip()
    m = re.search(r"/d/([a-zA-Z0-9_-]{10,})", s)
    if m:
        return m.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]{20,}", s):
        return s
    return s  # let the API reject it


TOOLS = [
    {
        "name": "search_drive",
        "description": "Search the user's Google Drive for files by name. Returns matching files with links. "
                       "Use to find a doc/sheet the user mentions by name, then read it with "
                       "read_google_doc / read_google_sheet.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Words from the file name"}},
            "required": ["query"],
        },
    },
    {
        "name": "read_google_doc",
        "description": (
            "Read the full text of a Google Doc by its URL or ID. Use this whenever the user "
            "pastes a Google Doc link or asks you to read, open, review, or summarize a Google Doc. "
            "You CAN access Google Docs this way — don't claim you can't."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"url_or_id": {"type": "string", "description": "Google Doc URL or document ID"}},
            "required": ["url_or_id"],
        },
    },
    {
        "name": "read_google_sheet",
        "description": (
            "Read a Google Sheet's tabs and rows by URL or ID (rendered as text tables). Use when "
            "the user pastes a Sheets link or asks you to read/analyze a spreadsheet."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"url_or_id": {"type": "string", "description": "Google Sheet URL or spreadsheet ID"}},
            "required": ["url_or_id"],
        },
    },
    {
        "name": "create_google_doc",
        "description": (
            "Create a Google Doc with a title and body and return its URL. Use whenever the user asks "
            "you to write, draft, create, or save a doc / post / brief to Google Docs. Put the COMPLETE "
            "content in `content` (markdown ok). After it succeeds, share the link."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Document title"},
                "content": {"type": "string", "description": "Full document body (markdown ok)"},
            },
            "required": ["title", "content"],
        },
    },
    {
        "name": "append_to_google_doc",
        "description": "Append text to the end of an existing Google Doc (by URL or ID). Use when the user "
                       "asks you to add to / update a doc they reference.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url_or_id": {"type": "string", "description": "Google Doc URL or document ID"},
                "content": {"type": "string", "description": "Text to append (markdown ok)"},
            },
            "required": ["url_or_id", "content"],
        },
    },
    {
        "name": "create_google_sheet",
        "description": "Create a Google Sheet with a title and optional rows, and return its URL. Use when the "
                       "user asks for a spreadsheet/tracker. `rows` is a 2-D array (first row = headers).",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Spreadsheet title"},
                "rows": {"type": "array", "description": "Optional 2-D array of cell values",
                         "items": {"type": "array", "items": {"type": "string"}}},
            },
            "required": ["title"],
        },
    },
    {
        "name": "create_calendar_event",
        "description": "Create a Google Calendar event on the user's primary calendar. Use when the user asks "
                       "to schedule/block/add something. start/end are RFC3339 datetimes "
                       "(e.g. 2026-06-13T14:00:00-07:00).",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Event title"},
                "start": {"type": "string", "description": "Start, RFC3339 (include timezone offset)"},
                "end": {"type": "string", "description": "End, RFC3339 (include timezone offset)"},
                "description": {"type": "string"},
                "location": {"type": "string"},
                "attendees": {"type": "array", "items": {"type": "string"}, "description": "Attendee emails"},
            },
            "required": ["summary", "start", "end"],
        },
    },
    {
        "name": "search_slack",
        "description": "Search the user's Slack for messages. Supports modifiers: in:channel, from:@user, "
                       "after:YYYY-MM-DD, before:YYYY-MM-DD. Use to read/find Slack discussion on demand.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query (e.g. 'AI tips in:rdx-ai-tips')"}},
            "required": ["query"],
        },
    },
    {
        "name": "send_email",
        "description": "Send an email as the user via Gmail. ONLY use when the user explicitly asks to "
                       "send an email — confirm the recipient, subject, and body first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string"},
                "body": {"type": "string", "description": "Plain-text email body"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "send_slack_message",
        "description": "Post a message to a Slack channel or DM (by name or ID). ONLY use when the user "
                       "explicitly asks to send/post to Slack — confirm the channel and wording first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel name or ID (e.g. rdx-ai-tips)"},
                "text": {"type": "string", "description": "Message text"},
            },
            "required": ["channel", "text"],
        },
    },
]


def _auth(service: str) -> dict:
    return {"ok": False, "auth_needed": True, "service": service,
            "error": "I need " + AUTH_HOWTO.get(service, service + " access.")}


def run_tool(name: str, inp: dict) -> dict:
    """Execute a tool call. Returns a JSON-able result dict."""
    inp = inp or {}
    if name == "search_drive":
        files = gsuite.search_drive(inp.get("query", ""))
        if files is None:
            return _auth("google-drive")
        return {"ok": True, "files": files}

    if name == "read_google_doc":
        text = gsuite.doc_markdown(extract_id(inp.get("url_or_id", "")))
        if text is None:
            return _auth("google-docs")
        return {"ok": True, "text": text[:_READ_CAP]}

    if name == "read_google_sheet":
        text = gsuite.sheet_markdown(extract_id(inp.get("url_or_id", "")))
        if text is None:
            return _auth("google-sheets")
        return {"ok": True, "text": text[:_READ_CAP]}

    if name == "create_google_doc":
        url = gsuite.create_doc(inp.get("title") or "Untitled", inp.get("content") or "")
        return {"ok": True, "url": url} if url else _auth("google-docs")

    if name == "append_to_google_doc":
        url = gsuite.append_doc(extract_id(inp.get("url_or_id", "")), inp.get("content") or "")
        return {"ok": True, "url": url} if url else _auth("google-docs")

    if name == "create_google_sheet":
        url = gsuite.create_sheet(inp.get("title") or "Untitled", inp.get("rows") or None)
        return {"ok": True, "url": url} if url else _auth("google-sheets")

    if name == "create_calendar_event":
        url = gsuite.create_event(
            inp.get("summary") or "(no title)", inp.get("start") or "", inp.get("end") or "",
            description=inp.get("description") or "", location=inp.get("location") or "",
            attendees=inp.get("attendees") or None)
        return {"ok": True, "url": url} if url else _auth("google-calendar")

    if name == "send_email":
        ok = gsuite.send_email(inp.get("to") or "", inp.get("subject") or "", inp.get("body") or "")
        return {"ok": True, "to": inp.get("to")} if ok else _auth("gmail")

    if name == "search_slack":
        text = slack.search(inp.get("query", ""))
        return {"ok": True, "text": text} if text is not None else _auth("slack")

    if name == "send_slack_message":
        ok = slack.send(inp.get("channel") or "", inp.get("text") or "")
        return {"ok": True, "channel": inp.get("channel")} if ok else _auth("slack")

    return {"ok": False, "error": f"unknown tool: {name}"}
