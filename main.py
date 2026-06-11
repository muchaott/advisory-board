#!/usr/bin/env python3
"""Advisory Board -- local CLI.

Talk to a board of 6 AI agents that help you grow as a designer and thought leader.

Usage examples (type these at the prompt):
  @critic review this flow: a user taps a pending P2P payment and ...
  @strategist > @critic > @translator redesign the Activity L1 module
  @board should we surface scheduled payments above or below pending?
  /morning                 -> start the morning check-in (sets up your day)
  /brag Shipped the Activity redesign spec; cut support tickets 12%
  /weekly                  -> run the Career Mentor's weekly review now
  /agents                  -> list the board
  /help                    -> commands
  /quit
"""
from __future__ import annotations

import sys

import agents as A
import orchestrator as O

BAR = "-" * 70


def banner():
    print("\n=== SoFi Advisory Board ===")
    print("Design + thought-leadership coaching from 6 agents. /help for commands, /quit to exit.\n")


def list_agents():
    print("\nThe board:")
    for a in A.roster():
        tags = []
        if a.reads_docs:
            tags.append("reads docs")
        if a.writes_brag:
            tags.append("writes brag doc")
        if a.deep:
            tags.append("deep model")
        tag = f"  ({', '.join(tags)})" if tags else ""
        print(f"  @{a.key:<11} {a.name}{tag}")
    print("\nModes:")
    print("  @agent <msg>                         single")
    print("  @a > @b > @c <msg>                   chain (output flows down)")
    print("  @board <msg>                         boardroom (they react, Mentor synthesizes)")
    print()


def render(transcript):
    for speaker, text in transcript:
        print(f"\n{BAR}\n{speaker}\n{BAR}\n{text}")
    print()


def handle(line: str) -> bool:
    """Return False to exit."""
    line = line.strip()
    if not line:
        return True

    low = line.lower()
    if low in ("/quit", "/exit", "/q"):
        return False
    if low in ("/help", "/h", "?"):
        print(__doc__)
        return True
    if low in ("/agents", "/board", "/list"):
        list_agents()
        return True

    if low.startswith("/brag"):
        text = line[len("/brag"):].strip()
        if not text:
            print("Usage: /brag <what you did>")
            return True
        heading, entry = O.pm_log(text)
        print(f"\nLogged under {heading}:\n  {entry}\n")
        return True

    if low in ("/morning", "/standup", "/today"):
        import morning
        print(morning.run(interactive=True))
        return True

    if low.startswith("/weekly"):
        from scheduler import run_weekly_review
        print("\nRunning the Career Mentor's weekly review...\n")
        print(run_weekly_review())
        return True

    # Boardroom
    if low.startswith("@board"):
        topic = line[len("@board"):].strip()
        if not topic:
            print("Usage: @board <topic>")
            return True
        render(O.boardroom(topic))
        return True

    # @mention routing (single or chain)
    if line.startswith("@"):
        # split leading @handles separated by '>'
        head, _, rest = line.partition(" ")
        # support "@a > @b > @c msg" where chevrons are inside
        m = _parse_mentions(line)
        if m:
            keys, topic = m
            unknown = [k for k in keys if not A.resolve(k)]
            if unknown:
                print(f"Unknown agent(s): {', '.join('@'+u for u in unknown)}. Try /agents.")
                return True
            if not topic:
                print("Add a message after the agent(s).")
                return True
            if len(keys) == 1:
                render(O.single(A.resolve(keys[0]), topic))
            else:
                render(O.chain(keys, topic))
            return True

    print("Start with @agent, a @a > @b chain, or @board. Try /help.")
    return True


def _parse_mentions(line: str):
    """Parse '@a > @b > @c rest of message' -> (['a','b','c'], 'rest of message')."""
    tokens = line.split()
    keys, i = [], 0
    while i < len(tokens):
        t = tokens[i]
        if t == ">":
            i += 1
            continue
        if t.startswith("@"):
            keys.append(t[1:].lower())
            i += 1
            # consume an optional '>' between mentions
            if i < len(tokens) and tokens[i] == ">":
                i += 1
                continue
            # if next token is another @mention, keep collecting (chain w/o '>')
            if i < len(tokens) and tokens[i].startswith("@"):
                continue
            break
        break
    topic = " ".join(tokens[i:]).strip()
    return (keys, topic) if keys else None


def main():
    banner()
    if "--morning" in sys.argv:
        import morning
        print(morning.run())
        print()
    while True:
        try:
            line = input("board> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        try:
            if not handle(line):
                break
        except Exception as e:
            print(f"\n[error] {type(e).__name__}: {e}\n")
    print("Bye.")


if __name__ == "__main__":
    sys.exit(main())
