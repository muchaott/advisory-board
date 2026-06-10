"""Weekday morning check-in.

The Design PM asks a few sharp, *personalized* questions (drawn from recent
activity + the 1:1 + current focus) to set up a high-leverage day toward L5,
then synthesizes today's focus from your answers.

- Interactive (a TTY): asks questions live, prints a game plan.
- Headless (no TTY): returns the questions as a brief instead of blocking.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta

import agents as A
import context as C
import llm
import orchestrator as O

FALLBACK_Q = [
    "What's the single most important outcome you want from today?",
    "What's the highest-leverage thing you could do toward L5 today?",
    "What will you say no to today to protect that?",
    "Where do you most need the board's help today?",
]


def questions(n: int = 4) -> list[str]:
    pm = A.resolve("pm")
    today = datetime.now()
    recent = C.recent_activity((today - timedelta(days=3)).date())
    docs = C.load_docs()
    prompt = (
        f"It's {today.strftime('%A, %B %d')}. As my Design PM, ask me the {n} most important "
        "questions RIGHT NOW to set up a high-leverage day toward my L5 promotion. Base them on "
        "my recent activity, my 1:1 with Nathan, and my current focus — make them specific to "
        "what's actually on my plate, not generic. Favor questions that force prioritization, "
        "surface the single most important outcome, flag what to decline, and tie today to my "
        "L5 narrative.\n\n"
        f"RECENT ACTIVITY (last few days):\n{recent}\n\n"
        f"WORKING DOCS + 1:1 (context):\n{docs}\n\n"
        f"Respond with ONLY a JSON array of exactly {n} question strings."
    )
    raw = llm.complete(pm.system(docs), [{"role": "user", "content": prompt}],
                       deep=O._deep(pm), max_tokens=500, temperature=0.5)
    m = re.search(r"\[.*\]", raw, re.S)
    if m:
        try:
            qs = [str(x).strip() for x in json.loads(m.group(0)) if str(x).strip()]
            if qs:
                return qs[:n]
        except Exception:
            pass
    return FALLBACK_Q[:n]


def plan(qa: list[tuple[str, str]]) -> str:
    pm = A.resolve("pm")
    convo = "\n".join(f"Q: {q}\nA: {a}" for q, a in qa)
    today = datetime.now().strftime("%A, %B %d")
    prompt = (
        f"It's {today}. Based on my answers to your morning questions, give me a tight game plan "
        "for today. Use exactly this format:\n"
        "TODAY'S FOCUS: 1-3 concrete priorities, ranked.\n"
        "SAY NO TO: one thing to drop or defer.\n"
        "L5 ANGLE: one sentence on how today advances my promotion narrative.\n"
        "Under 150 words, direct, no fluff.\n\n"
        f"MY ANSWERS:\n{convo}"
    )
    return llm.complete(pm.system(C.load_docs()), [{"role": "user", "content": prompt}],
                        deep=O._deep(pm), max_tokens=500, temperature=0.4)


def run(interactive: bool | None = None) -> str:
    if interactive is None:
        interactive = sys.stdin.isatty()

    qs = questions()

    if not interactive:
        lines = "\n".join(f"{i}. {q}" for i, q in enumerate(qs, 1))
        return ("Good morning. Today's high-leverage questions — open the board and run "
                f"/morning to work through them:\n\n{lines}")

    print("\n=== Morning check-in ===")
    print("A few quick questions to set up your day. Press Enter to skip any; Ctrl-C to stop.\n")
    qa = []
    for i, q in enumerate(qs, 1):
        print(f"{i}. {q}")
        try:
            a = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if a:
            qa.append((q, a))
        print()

    if not qa:
        return "No answers given — skipping today's plan. (Run /morning again anytime.)"
    print("Synthesizing today's focus...\n")
    return plan(qa)
