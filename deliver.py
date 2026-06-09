"""Deliver the weekly review to Slack and/or email. Headless-safe.

Every channel is opt-in via .env; an unconfigured channel is silently skipped,
so the launchd job never fails just because a secret is missing. HTTPS goes
through `curl` (the corp TLS proxy is trusted by the system keychain, which
Python's ssl module may not pick up).

Config (.env):
  SLACK_WEBHOOK_URL   incoming webhook (simplest, durable)         -> Slack
  # or:
  SLACK_BOT_TOKEN     xoxb-... bot token       (used together)     -> Slack
  SLACK_CHANNEL       #channel or channel id

  EMAIL_TO            recipient address                            -> email
  SMTP_HOST           e.g. smtp.gmail.com                          (required for email)
  SMTP_PORT           default 587
  SMTP_USER           default = EMAIL_TO
  SMTP_PASS           app password / SMTP password
  EMAIL_FROM          default = SMTP_USER
  SMTP_TLS_NOVERIFY   set 1 to skip cert verification (corp TLS escape hatch)
"""
from __future__ import annotations

import json
import os
import subprocess

SLACK_MAX = 3500


def _curl_post(url: str, payload: dict, headers: dict | None = None) -> tuple[int, str]:
    args = ["curl", "-sS", "-X", "POST", url, "-H", "Content-Type: application/json; charset=utf-8"]
    for k, v in (headers or {}).items():
        args += ["-H", f"{k}: {v}"]
    args += ["--data-binary", "@-", "--max-time", "45"]
    p = subprocess.run(args, input=json.dumps(payload), capture_output=True, text=True)
    return p.returncode, (p.stdout or p.stderr or "").strip()[:400]


def to_slack(subject: str, body: str, link: str | None = None) -> tuple[str, str]:
    text = f"*{subject}*\n\n{body}"
    if len(text) > SLACK_MAX:
        tail = f"\n\n_…truncated. Full review: {link}_" if link else "\n\n_…truncated._"
        text = text[:SLACK_MAX] + tail

    webhook = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if webhook:
        rc, out = _curl_post(webhook, {"text": text})
        ok = rc == 0 and out.lower() == "ok"
        return ("slack:webhook", "ok" if ok else f"err: {out}")

    token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    channel = os.getenv("SLACK_CHANNEL", "").strip()
    if token and channel:
        rc, out = _curl_post("https://slack.com/api/chat.postMessage",
                             {"channel": channel, "text": text},
                             {"Authorization": f"Bearer {token}"})
        ok = rc == 0 and '"ok":true' in out.replace(" ", "")
        return ("slack:bot", "ok" if ok else f"err: {out}")

    return ("slack", "skipped (set SLACK_WEBHOOK_URL, or SLACK_BOT_TOKEN + SLACK_CHANNEL)")


def to_email(subject: str, body: str) -> tuple[str, str]:
    to = os.getenv("EMAIL_TO", "").strip()
    host = os.getenv("SMTP_HOST", "").strip()
    if not (to and host):
        return ("email", "skipped (set EMAIL_TO + SMTP_HOST)")

    import smtplib
    import ssl
    from email.mime.text import MIMEText

    user = os.getenv("SMTP_USER", to)
    pwd = os.getenv("SMTP_PASS", "")
    port = int(os.getenv("SMTP_PORT", "587"))
    msg = MIMEText(body, "plain", "utf-8")
    msg["To"] = to
    msg["From"] = os.getenv("EMAIL_FROM", user)
    msg["Subject"] = subject
    try:
        ctx = ssl.create_default_context()
        if os.getenv("SMTP_TLS_NOVERIFY") == "1":
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        with smtplib.SMTP(host, port, timeout=45) as s:
            s.starttls(context=ctx)
            if pwd:
                s.login(user, pwd)
            s.send_message(msg)
        return ("email", "ok")
    except Exception as e:
        return ("email", f"err: {type(e).__name__}: {e}")


def deliver(subject: str, body: str, link: str | None = None) -> list[tuple[str, str]]:
    return [to_slack(subject, body, link), to_email(subject, body)]
