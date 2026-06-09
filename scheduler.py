#!/usr/bin/env python3
"""Weekly Career Mentor review.

Flow (per the blueprint): the PM produces a weekly summary from the Brag Doc +
working docs, then the Career Mentor reviews it and tells me where I'm playing
too small / where to protect my energy.

Run modes:
  python scheduler.py            -> run the review once, print it
  python scheduler.py --write    -> run once, save to reviews/weekly-<date>.md (for launchd/cron)
  python scheduler.py --daemon   -> stay resident, run every Friday 16:00 local

For a hands-off setup, wire `python scheduler.py` to cron/launchd instead of
keeping the daemon running. (Off by default -- nothing schedules itself.)
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import agents as A
import context as C
import llm
import orchestrator as O

ROOT = Path(__file__).resolve().parent
LAST_SUMMARY = ROOT / ".last_weekly_summary.md"
REVIEWS_DIR = ROOT / "reviews"


def write_review() -> Path:
    """Run the review and save it to reviews/weekly-<date>.md. Returns the path."""
    out = run_weekly_review()
    REVIEWS_DIR.mkdir(exist_ok=True)
    path = REVIEWS_DIR / f"weekly-{datetime.now().strftime('%Y-%m-%d')}.md"
    path.write_text(out, encoding="utf-8")
    return path


def _pm_weekly_summary() -> str:
    pm = A.resolve("pm")
    docs = C.load_docs()
    prompt = (
        "Produce my WEEKLY SUMMARY for promotion tracking. Using my Brag Doc and working "
        "docs below, write 3 short sections -- Business Impact, AI Leverage, "
        "Cross-functional Influence -- each with 2-4 bullets of what actually moved this "
        "week. End with 'Gaps:' listing what's missing for my L5 narrative.\n\n"
        f"WORKING DOCS:\n{docs}"
    )
    return llm.complete(pm.system(docs), [{"role": "user", "content": prompt}],
                        deep=O._deep(pm), max_tokens=1200, temperature=0.4)


def run_weekly_review() -> str:
    summary = _pm_weekly_summary()
    LAST_SUMMARY.write_text(summary, encoding="utf-8")
    mentor = A.resolve("mentor")
    review = O.ask(mentor, "Here is my PM's weekly summary. Give me your weekly review.",
                   transcript=[("The Design Project Manager (weekly summary)", summary)])
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        f"# Weekly Review -- {stamp}\n\n"
        f"## PM Weekly Summary\n{summary}\n\n"
        f"## Career Mentor Review\n{review}\n"
    )


def _daemon():
    import schedule
    import time

    def job():
        print("\n" + run_weekly_review())

    schedule.every().friday.at("16:00").do(job)
    print("[scheduler] resident; Career Mentor review every Friday 16:00 local. Ctrl-C to stop.")
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
