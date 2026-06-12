"""The advisory-board personas.

Six built-in personas ship as defaults. The user can edit any of them and add
their own agents — each with a Knowledge Base (like a Gemini Gem's context) —
through the GUI. Edits/additions persist to data/agents.json (+ a markdown file
per agent's knowledge in data/agent-kb/), and are merged over the defaults at
load time. The shared GLOBAL_CONTEXT is prepended to every agent.
"""
from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
AGENTS_JSON = DATA_DIR / "agents.json"     # overrides for built-ins + custom agents
KB_DIR = DATA_DIR / "agent-kb"             # <key>.md per agent (the Knowledge Base)
KB_MAX = 40_000                            # cap injected knowledge

GLOBAL_CONTEXT = """\
GLOBAL CONTEXT (applies to every agent):
- My Role: Staff Product Designer at SoFi.
- My Company: SoFi (Fintech, Banking, Money Movement, P2P).
- My Current Focus:
  * Drive Money Movement Innovation: define and drive the 12-month strategy for
    Money Movement features and the FY26 roadmap to grow P2P adoption and volume.
  * Transaction Activity Strategy: redesign high-traffic Activity surfaces (the L1
    module and list) to improve information architecture and scannability, reduce
    confusion around pending/scheduled items, and increase member trust.
- My Growth Goal: become a better designer -- sharpen my craft, first-principles
  design thinking, problem framing, and cross-functional collaboration so my work
  has clear user and business impact. Push the quality of my thinking, not just pixels.

TOOLS YOU CAN USE (call them — don't claim you "can't access Google"):
- search_drive — find my Google files by name (then read them).
- read_google_doc / read_google_sheet — read a Google Doc or Sheet by URL or ID.
  When I paste a Google link or ask you to open/read/summarize one, CALL these.
- create_google_doc / create_google_sheet — create a doc or sheet and return its link.
- append_to_google_doc — add to an existing doc.
- create_calendar_event — schedule something on my calendar.
- send_email — send an email via Gmail (only when I explicitly ask; confirm recipient/subject/body).
- send_slack_message — post to a Slack channel/DM (only when I explicitly ask; confirm first).
Every reply also has a "⤓ Doc" button to save it. So when I ask you to write or read
something in Google, use the tool — never say you lack access. If a tool reports an
auth problem, tell me exactly how to reconnect it.
"""


@dataclass(frozen=True)
class Agent:
    key: str            # @mention handle (lowercase)
    name: str           # display name
    goal: str
    system_prompt: str  # the persona's instructions
    reads_docs: bool = False      # gets the shared docs/calendar/Google/Slack context
    writes_brag: bool = False     # may append to the Brag Doc
    deep: bool = False            # routed to Opus when DEEP_THINKERS=1
    aliases: tuple = field(default_factory=tuple)
    color: str = "#7c8cf8"        # accent color in the UI
    kb: str = ""                  # Knowledge Base — authoritative context for this agent
    builtin: bool = True          # built-ins can be edited but not deleted

    def system(self, docs_context: str = "") -> str:
        parts = [GLOBAL_CONTEXT, "", f"YOUR ROLE: {self.name} -- {self.goal}", "", self.system_prompt]
        if self.kb:
            parts += ["", "YOUR KNOWLEDGE BASE (authoritative context you operate on):", self.kb]
        if self.reads_docs and docs_context:
            parts += ["", "MY WORKING DOCUMENTS (read-only context):", docs_context]
        return "\n".join(parts)


# ---- built-in defaults ---------------------------------------------------

DEFAULT_AGENTS: list[Agent] = [
    Agent(
        key="strategist", name="The Product & Design Strategist",
        goal="Identify high-leverage opportunities in SoFi Money/Banking.",
        system_prompt=(
            "You are a top-tier fintech product strategist. You think in first "
            "principles. When I present a design or feature, analyze it strictly through "
            "the lens of user retention, transaction volume, and operational efficiency. "
            "Ignore aesthetics; focus on structural UX and financial mental models."
        ),
        reads_docs=True, deep=True, aliases=("strategy", "product"), color="#3fd0c9",
    ),
    Agent(
        key="pm", name="The Design Project Manager",
        goal='Track work streams, force prioritization, and manage the "Brag Doc."',
        system_prompt=(
            "You are a ruthless, detail-oriented project manager. Your job is to keep me "
            "aligned with my growth as a designer. Categorize my daily "
            "outputs into: Business Impact, AI Leverage, and Cross-functional Influence. Flag "
            "any tasks I mention that don't build my craft, impact, or influence."
        ),
        reads_docs=True, writes_brag=True, aliases=("projectmanager", "manager"), color="#f0b65e",
    ),
    Agent(
        key="mentor", name="The Career Mentor",
        goal="Review weekly progress, provide long-term career perspective, and manage burnout.",
        system_prompt=(
            "You are a seasoned Silicon Valley design executive. You balance empathy with "
            "extreme candor. Review my weekly outputs and tell me where I am playing too "
            "small. Remind me to protect my energy and focus on the highest leverage work."
        ),
        reads_docs=True, deep=True, aliases=("career", "coach"), color="#9ccb6a",
    ),
    Agent(
        key="ai", name="The AI Specialist",
        goal="Supercharge my personal productivity.",
        system_prompt=(
            "You are an AI UX engineer. Review the tasks I am doing manually (e.g., renaming "
            "layers, writing release notes, synthesizing research) and write custom scripts, "
            "Figma plugin code, or Cursor prompts to automate them. Your goal is to make me a "
            "100x designer."
        ),
        aliases=("aispecialist", "automation"), color="#68d391",
    ),
    Agent(
        key="critic", name='The "Red Team" Critic',
        goal="Ruthlessly tear down my designs to find flaws before stakeholders do.",
        system_prompt=(
            "You are a highly critical, impatient SoFi user and a skeptical compliance officer "
            "rolled into one. Your job is to find the breaking points in my product flows. "
            "Highlight edge cases, cognitive overload, potential fraud vectors, and accessibility "
            "failures. Do not be polite."
        ),
        aliases=("redteam", "red"), color="#fc8181",
    ),
    Agent(
        key="translator", name="The Executive Translator",
        goal="Translate UX rationale into business impact.",
        system_prompt=(
            "You are a Chief Marketing Officer and VP of Product. I will give you my design "
            "rationales. You will rewrite them into brief, high-impact statements focused on "
            "Customer Acquisition Cost (CAC), Lifetime Value (LTV), and strategic business moats. "
            "Make me sound like a strong, senior designer."
        ),
        aliases=("exec", "translate"), color="#63b3ed",
    ),
]

# Order the board speaks in for @board runs (built-ins; customs append in roster()).
BOARD_ORDER = ["strategist", "critic", "translator", "pm", "mentor"]

AGENTS: dict[str, Agent] = {}
CANON: list[Agent] = []   # canonical agents in display order


# ---- persistence ---------------------------------------------------------

def _load_overrides() -> dict:
    if AGENTS_JSON.exists():
        try:
            return json.loads(AGENTS_JSON.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
    return {}


def _save_overrides(d: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = AGENTS_JSON.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
    tmp.replace(AGENTS_JSON)


def _kb_path(key: str) -> Path:
    return KB_DIR / f"{key}.md"


def _read_kb(key: str) -> str:
    p = _kb_path(key)
    if p.exists():
        try:
            return p.read_text(encoding="utf-8", errors="replace")[:KB_MAX]
        except Exception:
            return ""
    return ""


def _write_kb(key: str, text: str) -> None:
    KB_DIR.mkdir(parents=True, exist_ok=True)
    p = _kb_path(key)
    if (text or "").strip():
        p.write_text(text, encoding="utf-8")
    elif p.exists():
        p.unlink()


_OVERRIDE_FIELDS = {"name", "goal", "system_prompt", "reads_docs", "deep", "color"}


def _register(a: Agent) -> None:
    AGENTS[a.key] = a
    for al in a.aliases:
        AGENTS.setdefault(al, a)
    CANON.append(a)


def reload() -> None:
    """Rebuild the live agent registry from defaults + persisted overrides/additions."""
    AGENTS.clear()
    CANON.clear()
    overrides = _load_overrides()
    default_keys = {d.key for d in DEFAULT_AGENTS}

    for d in DEFAULT_AGENTS:
        ov = overrides.get(d.key, {})
        fields = {k: v for k, v in ov.items() if k in _OVERRIDE_FIELDS}
        _register(dataclasses.replace(d, kb=_read_kb(d.key), **fields))

    for key, rec in overrides.items():
        if key in default_keys:
            continue
        _register(Agent(
            key=key, name=rec.get("name", key), goal=rec.get("goal", ""),
            system_prompt=rec.get("system_prompt", ""),
            reads_docs=bool(rec.get("reads_docs", False)), deep=bool(rec.get("deep", False)),
            color=rec.get("color", "#7c8cf8"), kb=_read_kb(key), builtin=False,
        ))


def roster() -> list[Agent]:
    """Canonical agents (no alias dupes), built-ins first then custom."""
    return list(CANON)


def resolve(handle: str) -> Agent | None:
    return AGENTS.get(handle.lower().lstrip("@"))


# ---- CRUD (used by the server) -------------------------------------------

def _slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "agent").lower()).strip("-") or "agent"
    key = base
    i = 2
    while key in taken:
        key = f"{base}-{i}"
        i += 1
    return key


def record(key: str) -> dict | None:
    """Full editable record for an agent, or None."""
    a = resolve(key)
    if not a:
        return None
    return {
        "key": a.key, "name": a.name, "goal": a.goal, "system_prompt": a.system_prompt,
        "kb": a.kb, "color": a.color, "reads_docs": a.reads_docs, "deep": a.deep,
        "writes_brag": a.writes_brag, "builtin": a.builtin,
    }


def upsert(rec: dict) -> Agent:
    """Create or update an agent from an editor record. Returns the saved agent."""
    overrides = _load_overrides()
    default_keys = {d.key for d in DEFAULT_AGENTS}
    key = (rec.get("key") or "").strip().lower()
    if not key:
        key = _slug(rec.get("name", ""), set(AGENTS.keys()) | set(overrides.keys()))

    entry = overrides.get(key, {})
    for f in _OVERRIDE_FIELDS:
        if f in rec and rec[f] is not None:
            entry[f] = rec[f]
    if key not in default_keys:
        entry["builtin"] = False
    overrides[key] = entry
    _save_overrides(overrides)
    if "kb" in rec:
        _write_kb(key, rec.get("kb") or "")
    reload()
    return resolve(key)


def delete(key: str) -> bool:
    """Delete a custom agent (built-ins cannot be deleted). True if removed."""
    key = (key or "").strip().lower()
    if key in {d.key for d in DEFAULT_AGENTS}:
        return False
    overrides = _load_overrides()
    if key in overrides:
        del overrides[key]
        _save_overrides(overrides)
    p = _kb_path(key)
    if p.exists():
        p.unlink()
    reload()
    return True


reload()  # build the registry at import
