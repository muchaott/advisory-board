"""FastAPI backend for the Advisory Board GUI.

A thin API + SSE layer over the existing modules — no agent logic lives here.
Binds to 127.0.0.1 only (local app, never exposed).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import agents as A
import context as C
import morning as M
import orchestrator as O
import scheduler as SCH
import sync_gdoc as SY

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"

app = FastAPI(title="Advisory Board")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/agents")
def api_agents():
    return [
        {"key": a.key, "name": a.name, "goal": a.goal,
         "reads_docs": a.reads_docs, "writes_brag": a.writes_brag, "deep": a.deep}
        for a in A.roster()
    ]


def _sse(gen):
    def event_stream():
        for ev in gen:
            yield f"data: {json.dumps(ev)}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/ask")
async def api_ask(req: Request):
    body = await req.json()
    mode = body.get("mode", "single")
    keys = body.get("agents", [])
    message = (body.get("message") or "").strip()
    history = body.get("history") or []
    if not message or (mode != "board" and not keys):
        return JSONResponse({"error": "need a message and at least one agent"}, status_code=400)
    return _sse(O.run_stream(mode, keys, message, history=history))


@app.post("/api/brag")
async def api_brag(req: Request):
    body = await req.json()
    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "empty"}, status_code=400)
    section, entry = O.pm_log(text)
    return {"section": section, "entry": entry}


@app.get("/api/morning")
def api_morning():
    return {"questions": M.questions()}


@app.post("/api/morning/plan")
async def api_morning_plan(req: Request):
    body = await req.json()
    qa = [(a.get("q", ""), a.get("a", "")) for a in body.get("answers", []) if a.get("a")]
    if not qa:
        return JSONResponse({"error": "no answers"}, status_code=400)
    return {"plan": M.plan(qa)}


@app.post("/api/weekly")
def api_weekly():
    return {"review": SCH.run_weekly_review()}


@app.post("/api/sync")
def api_sync():
    return {"results": [{"file": f, "status": s} for f, s in SY.sync_all()]}


_LOGS = Path.home() / "Library" / "Logs"


def _activity() -> list[dict]:
    items: list[dict] = []

    # Weekly reviews (date from filename)
    rev = ROOT / "reviews"
    if rev.exists():
        for p in sorted(rev.glob("weekly-*.md")):
            m = re.search(r"(\d{4}-\d{2}-\d{2})", p.name)
            items.append({
                "kind": "weekly", "title": "Weekly review",
                "date": m.group(1) if m else "",
                "body": p.read_text(encoding="utf-8", errors="replace")[:8000],
            })

    # Brag entries (dated bullets, with section)
    for line in C.recent_brag_entries((datetime.now() - timedelta(days=365)).date()):
        mm = re.match(r"\[(.*?)\]\s*\((\d{4}-\d{2}-\d{2})\)\s*(.*)", line)
        if mm:
            items.append({"kind": "brag", "title": f"Brag · {mm.group(1)}",
                          "date": mm.group(2), "body": mm.group(3)})

    items.sort(key=lambda x: x.get("date", ""), reverse=True)
    return items


@app.get("/api/activity")
def api_activity():
    return _activity()


app.mount("/web", StaticFiles(directory=WEB), name="web")
