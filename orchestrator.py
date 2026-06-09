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


def _build_user(agent: A.Agent, topic: str, transcript: list[tuple[str, str]]) -> str:
    if not transcript:
        return topic
    convo = "\n\n".join(f"{spk}:\n{txt}" for spk, txt in transcript)
    return (
        f"TOPIC FROM ME:\n{topic}\n\n"
        f"DISCUSSION SO FAR (other board members):\n{convo}\n\n"
        f"Now respond as {agent.name}. Engage with what the others said where it's "
        f"relevant -- agree, build on it, or push back -- but stay in your role. "
        f"Be concise and specific."
    )


def ask(agent: A.Agent, topic: str, transcript: list[tuple[str, str]] | None = None) -> str:
    transcript = transcript or []
    docs = C.load_docs() if agent.reads_docs else ""
    user = _build_user(agent, topic, transcript)
    return llm.complete(agent.system(docs), [{"role": "user", "content": user}], deep=_deep(agent))


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
        f"recommendation: the 1-2 highest-leverage moves for my L5 case, and what to "
        f"ignore. Name the tradeoffs.]"
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
        "promotion-worthy bullet (<=30 words, lead with impact)}. "
        f"If it does not serve my L5 narrative, use category \"Notes\".\n\nUPDATE:\n{text}"
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
