#!/usr/bin/env python3
"""Weekly Career Mentor review.

Flow (per the blueprint): the PM produces a weekly summary from the Brag Doc +
working docs, then the Career Mentor reviews it and tells me where I'm playing
too small / where to protect my energy.

Run modes:
  python scheduler.py            -> run the review once, print it
  python scheduler.py --write    -> run once, save to reviews/weekly-<date>.md (for launchd/cron)
  python scheduler.py --daemon   -> stay resident, run every Thursday 09:00 local

For a hands-off setup, wire `python scheduler.py` to cron/launchd instead of
keeping the daemon running. (Off by default -- nothing schedules itself.)
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import agents as A
import context as C
import llm
import orchestrator as O

ROOT = Path(__file__).resolve().parent
LAST_SUMMARY = ROOT / ".last_weekly_summary.md"
REVIEWS_DIR = ROOT / "reviews"


def write_review() -> Path:
    """Run the review, save it, and deliver to Slack/email. Returns the path."""
    out = run_weekly_review()
    REVIEWS_DIR.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    path = REVIEWS_DIR / f"weekly-{today}.md"
    path.write_text(out, encoding="utf-8")
    try:
        import deliver as D
        results = D.deliver(f"[Advisory Board] Weekly Review — {today}", out, link=str(path))
        for chan, status in results:
            print(f"[deliver] {chan}: {status}")
    except Exception as e:
        print(f"[deliver] error: {type(e).__name__}: {e}")
    try:
        import subprocess
        subprocess.run(["osascript", "-e",
                        'display notification "Your weekly review is ready — open the board to read it." '
                        'with title "Advisory Board"'], timeout=10)
    except Exception:
        pass
    return path


def _pm_weekly_summary(since) -> str:
    pm = A.resolve("pm")
    docs = C.load_docs()
    activity = C.recent_activity(since)
    since_str = since.isoformat()
    prompt = (
        "Produce my WEEKLY SUMMARY for promotion tracking, covering ONLY the important "
        f"things I've done since last Thursday ({since_str}). Focus on what moved in that "
        "window; treat older work as background only and do not re-summarize it.\n\n"
        f"WHAT HAPPENED IN THIS WINDOW (since {since_str}):\n{activity}\n\n"
        "Write 3 short sections -- Business Impact, AI Leverage, Cross-functional "
        "Influence -- each with the key items from the window (2-4 bullets). Lead with "
        "impact. If the window is genuinely thin, say so plainly instead of padding. End "
        "with 'Gaps:' listing what's missing for my L5 narrative.\n\n"
        f"FULL WORKING DOCS (background context only):\n{docs}"
    )
    return llm.complete(pm.system(docs), [{"role": "user", "content": prompt}],
                        deep=O._deep(pm), max_tokens=1200, temperature=0.4)


def run_weekly_review() -> str:
    # Best-effort refresh of synced Google Docs (e.g. the 1:1 with Nathan).
    # Safe + non-fatal: if the Google token is stale, the last synced copy is used.
    try:
        import sync_gdoc
        for fname, status in sync_gdoc.sync_all():
            print(f"[sync] {fname}: {status}")
    except Exception as e:
        print(f"[sync] error (using last copy): {type(e).__name__}: {e}")

    today = datetime.now().date()
    since = today - timedelta(days=7)  # last Thursday, on a Thursday cadence
    summary = _pm_weekly_summary(since)
    LAST_SUMMARY.write_text(summary, encoding="utf-8")
    mentor = A.resolve("mentor")
    review = O.ask(
        mentor,
        f"Here is my PM's weekly summary covering my work since last Thursday "
        f"({since.isoformat()}). Give me your weekly review of this window.",
        transcript=[("The Design Project Manager (weekly summary)", summary)],
    )
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        f"# Weekly Review -- {stamp}  (window: {since.isoformat()} → {today.isoformat()})\n\n"
        f"## PM Weekly Summary\n{summary}\n\n"
        f"## Career Mentor Review\n{review}\n"
    )


def _daemon():
    import schedule
    import time

    def job():
        print("\n" + run_weekly_review())

    schedule.every().thursday.at("09:00").do(job)
    print("[scheduler] resident; Career Mentor review every Thursday 09:00 local. Ctrl-C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    if "--daemon" in sys.argv:
        _daemon()
    elif "--write" in sys.argv:
        p = write_review()
        print(f"[scheduler] wrote {p}")
    else:
        print(run_weekly_review())
