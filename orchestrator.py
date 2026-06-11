"""Routing + the three ways the board can talk.

A "transcript" is a list of (speaker_name, text) turns. Because the Anthropic
API only has one assistant role, each agent sees the prior turns folded into its
user prompt -- that's what lets the agents react to each other.
"""
from __future__ import annotations

import json
import os
import re

import agents as A
import context as C
import llm

DEEP_ENABLED = os.getenv("DEEP_THINKERS", "1") == "1"
MAX_BOARD_TURNS = int(os.getenv("MAX_BOARD_TURNS", "7"))


def _deep(agent: A.Agent) -> bool:
    return agent.deep and DEEP_ENABLED


# ---- routing (Career Mentor as concierge) --------------------------------

def route(topic: str, history: list | None = None, images: list | None = None) -> str:
    """The Career Mentor picks which board member should answer `topic`.

    Returns a canonical agent key. Defaults to "mentor" (answers itself) for
    career/leadership/growth/burnout topics or when the choice is unclear.
    """
    mentor = A.resolve("mentor")
    roster = A.roster()
    menu = "\n".join(f"- {a.key}: {a.name} — {a.goal}" for a in roster)
    convo = ""
    if history:
        recent = [h for h in history if isinstance(h, (list, tuple)) and len(h) == 2][-6:]
        if recent:
            convo = "\n\nRECENT CONVERSATION:\n" + "\n".join(f"{s}: {t}" for s, t in recent)
    instruction = (
        "You are routing my message to the single best board member. Pick the one whose role "
        "most directly fits. Choose \"mentor\" (yourself) for career, leadership, growth, "
        "burnout, or 'am I focused on the right things' questions.\n\n"
        f"BOARD MEMBERS:\n{menu}{convo}\n\nMY MESSAGE:\n{topic}\n\n"
        "Respond with ONLY a JSON object: {\"agent\": \"<key>\"}."
    )
    keys = {a.key for a in roster}
    try:
        raw = llm.complete(mentor.system(), [{"role": "user", "content": instruction}],
                           max_tokens=30, temperature=0)
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            key = str(json.loads(m.group(0)).get("agent", "")).lower().lstrip("@")
            resolved = A.resolve(key)
            if resolved and resolved.key in keys:
                return resolved.key
    except Exception:
        pass
    return "mentor"


def _build_user(agent: A.Agent, topic: str, transcript: list[tuple[str, str]]) -> str:
    if not transcript:
        return topic
    convo = "\n\n".join(f"{spk}:\n{txt}" for spk, txt in transcript)
    return (
        f"LATEST FROM ME:\n{topic}\n\n"
        f"EARLIER IN THIS SESSION:\n{convo}\n\n"
        f"Now respond as {agent.name}. Engage with what was said where it's relevant "
        f"-- build on it, reference it, or push back -- but stay in your role. "
        f"Be concise and specific."
    )


def ask(agent: A.Agent, topic: str, transcript: list[tuple[str, str]] | None = None) -> str:
    transcript = transcript or []
    docs = C.agent_context() if agent.reads_docs else ""
    user = _build_user(agent, topic, transcript)
    return llm.complete(agent.system(docs), [{"role": "user", "content": user}], deep=_deep(agent))


# ---- streaming (GUI) -----------------------------------------------------

def _content(user: str, images: list | None):
    """Build message content: image blocks + text, or just text."""
    if not images:
        return user
    blocks = [{"type": "image", "source": {"type": "base64",
              "media_type": im.get("media_type", "image/png"), "data": im.get("data", "")}}
              for im in images if im.get("data")]
    blocks.append({"type": "text", "text": user})
    return blocks or user


def _ask_stream(agent: A.Agent, topic: str, transcript: list[tuple[str, str]], images: list | None = None):
    """Yield text deltas for one agent's turn; appends its full reply to transcript."""
    docs = C.agent_context() if agent.reads_docs else ""
    user = _build_user(agent, topic, transcript)
    buf = []
    for delta in llm.stream(agent.system(docs), [{"role": "user", "content": _content(user, images)}], deep=_deep(agent)):
        buf.append(delta)
        yield delta
    transcript.append((agent.name, "".join(buf)))


def run_stream(mode: str, keys: list[str], topic: str, history: list | None = None, images: list | None = None):
    """Drive single/chain/board and yield UI events.

    `history` (list of [speaker, text]) seeds prior conversation turns so a
    single-agent chat has memory. `images` (list of {media_type,data}) are
    attached to each agent's turn. Events: agent_start, reacting_to, token,
    agent_done, done.
    """
    transcript: list[tuple[str, str]] = [(h[0], h[1]) for h in (history or []) if len(h) == 2]

    if mode == "auto":
        # Career Mentor concierge: pick the responder, tell the UI, then answer.
        target = route(topic, history=history, images=images)
        agent = A.resolve(target)
        yield {"type": "routed", "key": agent.key, "name": agent.name}
        order = [target]
        synth = False
    elif mode == "single":
        order = keys[:1]
        synth = False
    elif mode == "chain":
        order = keys
        synth = False
    else:  # board
        order = [k for k in A.BOARD_ORDER if k != "mentor"]
        synth = True

    for i, key in enumerate(order):
        agent = A.resolve(key)
        if not agent:
            continue
        yield {"type": "agent_start", "agent": agent.name, "key": agent.key, "deep": _deep(agent)}
        if i > 0 and transcript:
            yield {"type": "reacting_to", "agent": agent.name, "prior": transcript[-1][0]}
        for delta in _ask_stream(agent, topic, transcript, images):
            yield {"type": "token", "agent": agent.name, "key": agent.key, "text": delta}
        yield {"type": "agent_done", "agent": agent.name, "key": agent.key}

    if synth:
        mentor = A.resolve("mentor")
        synth_topic = (
            f"{topic}\n\n[Synthesize the board's discussion above into a clear "
            f"recommendation: the 1-2 highest-leverage moves for my growth as a designer and "
            f"thought leader, and what to "
            f"ignore. Name the tradeoffs.]"
        )
        label = mentor.name + " (synthesis)"
        yield {"type": "agent_start", "agent": label, "key": mentor.key, "deep": _deep(mentor)}
        yield {"type": "reacting_to", "agent": label, "prior": "the board"}
        docs = C.agent_context()
        user = _build_user(mentor, synth_topic, transcript)
        for delta in llm.stream(mentor.system(docs), [{"role": "user", "content": _content(user, images)}], deep=_deep(mentor)):
            yield {"type": "token", "agent": label, "key": mentor.key, "text": delta}
        yield {"type": "agent_done", "agent": label, "key": mentor.key}

    yield {"type": "done"}


# ---- modes ---------------------------------------------------------------

def single(agent: A.Agent, topic: str) -> list[tuple[str, str]]:
    return [(agent.name, ask(agent, topic))]


def chain(agent_keys: list[str], topic: str) -> list[tuple[str, str]]:
    transcript: list[tuple[str, str]] = []
    for key in agent_keys:
        agent = A.resolve(key)
        if not agent:
            continue
        reply = ask(agent, topic, transcript)
        transcript.append((agent.name, reply))
    return transcript


def boardroom(topic: str, order: list[str] | None = None) -> list[tuple[str, str]]:
    order = (order or A.BOARD_ORDER)[:MAX_BOARD_TURNS]
    transcript: list[tuple[str, str]] = []
    # Reserve the last slot for a synthesis pass by the Mentor.
    speak = [k for k in order if k != "mentor"]
    for key in speak:
        agent = A.resolve(key)
        if not agent:
            continue
        transcript.append((agent.name, ask(agent, topic, transcript)))
    mentor = A.resolve("mentor")
    synth_topic = (
        f"{topic}\n\n[Synthesize the board's discussion above into a clear "
        f"recommendation: the 1-2 highest-leverage moves for my growth as a designer and "
        f"thought leader, and what to ignore. Name the tradeoffs.]"
    )
    transcript.append((mentor.name + " (synthesis)", ask(mentor, synth_topic, transcript)))
    return transcript


# ---- PM brag-doc logging -------------------------------------------------

def pm_log(text: str) -> tuple[str, str]:
    """PM categorizes `text` and appends it to the Brag Doc.

    Returns (section_heading, one_line_summary).
    """
    pm = A.resolve("pm")
    instruction = (
        "Categorize the following work update for my Brag Doc. Respond with ONLY a "
        "JSON object: {\"category\": one of [\"Business Impact\",\"AI Leverage\","
        "\"Cross-functional Influence\",\"Notes\"], \"entry\": a single crisp "
        "noteworthy bullet (<=30 words, lead with impact)}. "
        f"If it doesn't reflect growth in craft, impact, or influence, use category \"Notes\".\n\nUPDATE:\n{text}"
    )
    raw = llm.complete(pm.system(), [{"role": "user", "content": instruction}],
                       max_tokens=300, temperature=0.3)
    category, entry = "Notes", text.strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            category = obj.get("category", category)
            entry = obj.get("entry", entry)
        except Exception:
            pass
    heading = C.append_brag(category, entry)
    return heading, entry
