"""Anthropic client wired to the SoFi llm-proxy.

Handles the ~3-day key expiry by auto-refreshing via `llm-proxy-keys -q`
and retrying once on an auth failure.
"""
from __future__ import annotations

import json
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


def _is_key_error(e: Exception) -> bool:
    """True if an API error looks like an expired/invalid proxy key (worth refreshing)."""
    if isinstance(e, anthropic.AuthenticationError):
        return True
    code = getattr(e, "status_code", None)
    if code in (401, 403):
        return True
    msg = str(getattr(e, "message", "") or e).lower()
    return "expired" in msg or ("invalid" in msg and "key" in msg)


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
        except anthropic.APIStatusError as e:
            if attempt == 0 and _is_key_error(e):
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
        except anthropic.APIStatusError as e:
            if attempt == 0 and _is_key_error(e):
                key = _refresh_key() or key
                continue
            raise
    raise RuntimeError("LLM stream failed after key refresh.")


def stream_events(system: str, messages: list[dict], *, deep: bool = False,
                  max_tokens: int = 1500, temperature: float = 0.7,
                  tools: list | None = None, run_tool=None, max_rounds: int = 4):
    """Stream a completion that may call tools.

    Yields dicts: {"text": delta} for streamed text, and {"tool": {...}} when a
    tool runs (status "running" then "done" with its result). Tool calls are
    executed via `run_tool(name, input)` and fed back to the model until it
    produces a final answer (capped at `max_rounds`).
    """
    model = DEEP_MODEL if deep else DEFAULT_MODEL
    key = _ensure_key()
    msgs = [dict(m) for m in messages]
    tools = tools or []

    for _round in range(max_rounds):
        final = None
        for attempt in range(2):
            try:
                with _client(key).messages.stream(
                    model=model, system=system, messages=msgs,
                    max_tokens=max_tokens, temperature=temperature, tools=tools,
                ) as s:
                    for delta in s.text_stream:
                        yield {"text": delta}
                    final = s.get_final_message()
                break
            except anthropic.APIStatusError as e:
                if attempt == 0 and _is_key_error(e):
                    key = _refresh_key() or key
                    continue
                raise

        if final is None or final.stop_reason != "tool_use" or not run_tool:
            return

        # Re-send the assistant turn (text + tool_use), then the tool results.
        assistant = []
        for b in final.content:
            if b.type == "text":
                assistant.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                assistant.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
        msgs.append({"role": "assistant", "content": assistant})

        results = []
        for b in final.content:
            if getattr(b, "type", None) == "tool_use":
                yield {"tool": {"name": b.name, "input": b.input, "status": "running"}}
                res = run_tool(b.name, b.input)
                yield {"tool": {"name": b.name, "result": res, "status": "done"}}
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(res)})
        msgs.append({"role": "user", "content": results})
