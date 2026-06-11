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
import gsuite as G
import morning as M
import orchestrator as O
import scheduler as SCH
import sync_gdoc as SY

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
STATE_DIR = ROOT / "data"
CONV_PATH = STATE_DIR / "conversations.json"
ORDER_PATH = STATE_DIR / "agent-order.json"

app = FastAPI(title="Advisory Board")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/mini")
def mini():
    return FileResponse(WEB / "mini.html")


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
    images = body.get("images") or []
    if (not message and not images) or (mode != "board" and not keys):
        return JSONResponse({"error": "need a message and at least one agent"}, status_code=400)
    if not message:
        message = "(see attached image)"
    return _sse(O.run_stream(mode, keys, message, history=history, images=images))


@app.post("/api/brag")
async def api_brag(req: Request):
    body = await req.json()
    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "empty"}, status_code=400)
    section, entry = O.pm_log(text)
    return {"section": section, "entry": entry}


@app.get("/api/brag/suggest")
def api_brag_suggest():
    import json as _json
    import re
    from datetime import datetime, timedelta
    import llm
    pm = A.resolve("pm")
    recent = C.recent_activity((datetime.now() - timedelta(days=5)).date())
    docs = C.agent_context()
    prompt = (
        "Scan my recent activity, calendar, and docs below. Propose up to 3 concrete, "
        "noteworthy Brag Doc bullets (growth in craft, impact, or influence) for things I likely did recently but may not have "
        "logged yet. Each <=24 words, lead with impact, grounded in the actual context — do NOT "
        "invent. If nothing clear, return fewer or an empty array. Respond ONLY as a JSON array "
        f"of strings.\n\nRECENT ACTIVITY:\n{recent}\n\nCONTEXT:\n{docs}"
    )
    raw = llm.complete(pm.system(docs), [{"role": "user", "content": prompt}], max_tokens=300, temperature=0.4)
    out = []
    m = re.search(r"\[.*\]", raw, re.S)
    if m:
        try:
            out = [str(x).strip() for x in _json.loads(m.group(0)) if str(x).strip()][:3]
        except Exception:
            pass
    return {"suggestions": out}


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


_SUG = {"ts": 0.0, "items": []}


@app.get("/api/suggestions")
def api_suggestions():
    import time
    import re
    import json as _json
    from datetime import datetime, timedelta
    import llm
    if _SUG["items"] and time.time() - _SUG["ts"] < 1800:
        return {"suggestions": _SUG["items"]}
    pm = A.resolve("pm")
    docs = C.agent_context()
    recent = C.recent_activity((datetime.now() - timedelta(days=3)).date())
    prompt = (
        "Based on my calendar today and my recent project progress, suggest 3 short, "
        "actionable things I could ask you or do right now to make today count. Each <=7 "
        "words, imperative, specific to my actual context (name the project/meeting). "
        "Respond ONLY as a JSON array of 3 strings.\n\nRECENT:\n" + recent
    )
    try:
        raw = llm.complete(pm.system(docs), [{"role": "user", "content": prompt}], max_tokens=200, temperature=0.5)
    except Exception:
        return {"suggestions": _SUG["items"]}  # keep last good set on a transient proxy error
    items, m = [], re.search(r"\[.*\]", raw, re.S)
    if m:
        try:
            items = [str(x).strip() for x in _json.loads(m.group(0)) if str(x).strip()][:3]
        except Exception:
            pass
    if items:
        _SUG.update(ts=time.time(), items=items)
    return {"suggestions": items}


@app.get("/api/morning-brief")
def api_morning_brief():
    today = datetime.now().strftime("%Y-%m-%d")
    p = ROOT / "reviews" / f"morning-{today}.md"
    if p.exists():
        return {"date": today, "text": p.read_text(encoding="utf-8", errors="replace")}
    return {"date": today, "text": None}


@app.get("/api/calendar")
def api_calendar():
    return {"today": G.calendar_today(), "upcoming": G.calendar_upcoming(7), "status": G.status()}


@app.get("/api/conversations")
def get_conversations():
    if CONV_PATH.exists():
        try:
            return json.loads(CONV_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


@app.post("/api/conversations")
async def save_conversations(req: Request):
    body = await req.json()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONV_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(body), encoding="utf-8")
    tmp.replace(CONV_PATH)  # atomic
    return {"ok": True}


@app.get("/api/agent-order")
def get_agent_order():
    if ORDER_PATH.exists():
        try:
            return json.loads(ORDER_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


@app.post("/api/agent-order")
async def save_agent_order(req: Request):
    body = await req.json()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ORDER_PATH.write_text(json.dumps(body), encoding="utf-8")
    return {"ok": True}


app.mount("/web", StaticFiles(directory=WEB), name="web")
