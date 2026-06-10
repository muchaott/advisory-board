"""Anthropic client wired to the SoFi llm-proxy.

Handles the ~3-day key expiry by auto-refreshing via `llm-proxy-keys -q`
and retrying once on an auth failure.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import anthropic
from dotenv import load_dotenv, set_key

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"

load_dotenv(ENV_PATH)

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "claude-sonnet-4-6")
DEEP_MODEL = os.getenv("DEEP_MODEL", "claude-opus-4-6")
BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://internal.sofitest.com/llm-proxy")


def _refresh_key() -> str | None:
    """Mint a fresh proxy key with `llm-proxy-keys -q` and persist it to .env."""
    exe = shutil.which("llm-proxy-keys") or os.path.expanduser("~/.local/bin/llm-proxy-keys")
    if not Path(exe).exists():
        return None
    try:
        out = subprocess.run([exe, "-q"], capture_output=True, text=True, timeout=60)
    except Exception:
        return None
    key = (out.stdout or "").strip().splitlines()[-1].strip() if out.stdout else ""
    if not key:
        return None
    os.environ["ANTHROPIC_API_KEY"] = key
    try:
        ENV_PATH.touch(exist_ok=True)
        set_key(str(ENV_PATH), "ANTHROPIC_API_KEY", key)
    except Exception:
        pass
    return key


def _client(api_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key, base_url=BASE_URL)


def _ensure_key() -> str:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        key = _refresh_key() or ""
    if not key:
        raise RuntimeError(
            "No ANTHROPIC_API_KEY. Run `llm-proxy-keys -q` and put the key in .env, "
            "or ensure `llm-proxy-keys` is on PATH."
        )
    return key


def complete(system: str, messages: list[dict], *, deep: bool = False,
             max_tokens: int = 1500, temperature: float = 0.7) -> str:
    """Single completion. Retries once with a fresh key on auth error."""
    model = DEEP_MODEL if deep else DEFAULT_MODEL
    key = _ensure_key()

    for attempt in range(2):
        try:
            resp = _client(key).messages.create(
                model=model,
                system=system,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        except anthropic.AuthenticationError:
            if attempt == 0:
                key = _refresh_key() or key
                continue
            raise
        except anthropic.APIStatusError as e:
            if attempt == 0 and e.status_code in (401, 403):
                key = _refresh_key() or key
                continue
            raise
    raise RuntimeError("LLM call failed after key refresh.")


def stream(system: str, messages: list[dict], *, deep: bool = False,
           max_tokens: int = 1500, temperature: float = 0.7):
    """Yield text deltas for a completion. Retries once with a fresh key on auth error."""
    model = DEEP_MODEL if deep else DEFAULT_MODEL
    key = _ensure_key()

    for attempt in range(2):
        try:
            with _client(key).messages.stream(
                model=model,
                system=system,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            ) as s:
                for text in s.text_stream:
                    yield text
            return
        except anthropic.AuthenticationError:
            if attempt == 0:
                key = _refresh_key() or key
                continue
            raise
        except anthropic.APIStatusError as e:
            if attempt == 0 and e.status_code in (401, 403):
                key = _refresh_key() or key
                continue
            raise
    raise RuntimeError("LLM stream failed after key refresh.")
