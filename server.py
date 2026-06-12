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


@app.get("/suggest")
def suggest():
    return FileResponse(WEB / "suggest.html")


@app.get("/chat")
def chat():
    return FileResponse(WEB / "chat.html")


@app.get("/api/agents")
def api_agents():
    return [
        {"key": a.key, "name": a.name, "goal": a.goal, "color": a.color,
         "reads_docs": a.reads_docs, "writes_brag": a.writes_brag, "deep": a.deep,
         "builtin": a.builtin, "has_kb": bool(a.kb)}
        for a in A.roster()
    ]


@app.get("/api/agents/{key}")
def api_agent_get(key: str):
    rec = A.record(key)
    if not rec:
        return JSONResponse({"error": "not found"}, status_code=404)
    return rec


@app.post("/api/agents")
async def api_agent_upsert(req: Request):
    body = await req.json()
    if not (body.get("name") or "").strip() and not (body.get("key") or "").strip():
        return JSONResponse({"error": "name is required"}, status_code=400)
    agent = A.upsert(body)
    return A.record(agent.key)


@app.delete("/api/agents/{key}")
def api_agent_delete(key: str):
    if not A.delete(key):
        return JSONResponse({"error": "built-in agents can't be deleted"}, status_code=400)
    return {"ok": True}


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
    if (not message and not images) or (mode not in ("board", "auto") and not keys):
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
    if _SUG["items"] and time.time() - _SUG["ts"] < 600:  # ~10 min: fresh through the day, still cheap
        return {"suggestions": _SUG["items"]}
    pm = A.resolve("pm")
    docs = C.agent_context()
    recent = C.recent_activity((datetime.now() - timedelta(days=3)).date())
    try:
        today_cal = G.calendar_today()
    except Exception:
        today_cal = []
    now = datetime.now().strftime("%A %-I:%M %p")
    cal_txt = "\n".join("- " + c for c in today_cal) if today_cal else "(nothing scheduled today)"
    prompt = (
        f"It's {now}. Looking at what's on my plate RIGHT NOW, suggest 3 short, actionable "
        "things I could ask you or do next to make today count. Each <=7 words, imperative, "
        "specific to my actual context (name the project/meeting/person). Favor time-sensitive "
        "items — an upcoming meeting today, a current priority, or a fresh Slack thread. "
        f"Respond ONLY as a JSON array of 3 strings.\n\nTODAY'S CALENDAR:\n{cal_txt}\n\nRECENT:\n{recent}"
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


@app.post("/api/savedoc")
async def api_savedoc(req: Request):
    """Save text (e.g. an agent's reply) to a new Google Doc; returns its URL."""
    body = await req.json()
    text = body.get("text") or ""
    title = (body.get("title") or "").strip() or "Yoda note"
    if not text.strip():
        return JSONResponse({"error": "nothing to save"}, status_code=400)
    url = G.create_doc(title, text)
    if not url:
        return JSONResponse(
            {"error": "Couldn't create the doc — Google Docs auth is likely expired. "
                      "Use the Docs MCP once (or re-auth) to refresh it."}, status_code=502)
    return {"url": url}


@app.get("/api/conversations")
def get_conversations():
    if CONV_PATH.exists():
        try:
            return json.loads(CONV_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


@app.post("/api/conversations/update")
async def update_conversation(req: Request):
    """Merge a single view's turns into the shared store (used by the mini chat)."""
    body = await req.json()
    vk = body.get("viewKey")
    turns = body.get("turns")
    if not vk or turns is None:
        return JSONResponse({"error": "need viewKey and turns"}, status_code=400)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    data = {}
    if CONV_PATH.exists():
        try:
            data = json.loads(CONV_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
    data[vk] = turns
    tmp = CONV_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(CONV_PATH)  # atomic
    return {"ok": True}


@app.post("/api/conversations")
async def save_conversations(req: Request):
    body = await req.json()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONV_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(body), encoding="utf-8")
    tmp.replace(CONV_PATH)  # atomic
    return {"ok": True}


_HANDOFF: dict = {"data": None}


@app.post("/api/handoff")
async def post_handoff(req: Request):
    """Stash a chat conversation so the big board can adopt it (single-shot)."""
    body = await req.json()
    _HANDOFF["data"] = {"viewKey": body.get("viewKey") or "single:mentor",
                        "turns": body.get("turns") or []}
    return {"ok": True}


@app.get("/api/handoff")
def get_handoff():
    """Return the pending handoff once, then clear it."""
    data = _HANDOFF["data"]
    _HANDOFF["data"] = None
    return data or {}


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
