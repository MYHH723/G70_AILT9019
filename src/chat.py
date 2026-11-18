"""Floating chat assistant, proxied through the local server.

The API key belongs to the group and the announcement is explicit that it must
not reach a public place. So the browser never sees it: the page posts to
``/api/chat`` on the local server, and the server makes the upstream call with a
key read from the environment. Nothing in this repository contains a key, and
``.gitignore`` covers the only local file that could.

The assistant is grounded on the pilot, not on the open web:

* it is told what the pilot covers (one programme, one cohort) and what it must
  never do (promise an outcome, invent a course, invent a deadline);
* its reply is checked before it is returned: a course code that does not exist
  in the corpus, or a promise of admission, replaces the reply with an honest
  refusal rather than being shown;
* a missing key, a 401, a timeout or a rate limit all return a readable message
  instead of an exception.

Standard library only: one JSON POST to an OpenAI-compatible endpoint.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from .guards import find_promise

USER_AGENT = "HKUPathfinderPilot/1.0 (chat)"

# Zhipu GLM, coding-plan endpoint. Verified 2026-11-18: glm-4.6 answers here;
# the flash models return 1309 ("Coding Plan expired") on this key.
DEFAULT_BASE = "https://open.bigmodel.cn/api/coding/paas/v4"
DEFAULT_MODEL = "glm-4.6"

MAX_MESSAGES = 12          # history sent upstream
MAX_CHARS = 1200           # per reply
MIN_INTERVAL = 0.8         # seconds between upstream calls, per process

CODE = re.compile(r"\b[A-Z]{2,4}\d{4}\b")

_LOCK = threading.Lock()
_LAST_CALL = 0.0


@dataclass
class ChatSettings:
    api_key: str = ""
    base_url: str = DEFAULT_BASE
    model: str = DEFAULT_MODEL
    timeout: float = 60.0
    # glm-4.6 is a reasoning model. Left on, it can spend the whole token budget
    # thinking and return an empty answer; off, it answers in about 1.5 s.
    thinking: str = "disabled"

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)


def settings_from_env(env: dict[str, str] | None = None) -> ChatSettings:
    """Chat settings, falling back to the wording-layer variables."""
    env = env if env is not None else os.environ
    key = (env.get("PATHFINDER_CHAT_API_KEY") or env.get("PATHFINDER_LLM_API_KEY") or "").strip()
    base = (env.get("PATHFINDER_CHAT_BASE_URL") or env.get("PATHFINDER_LLM_BASE_URL") or DEFAULT_BASE).rstrip("/")
    model = (env.get("PATHFINDER_CHAT_MODEL") or DEFAULT_MODEL).strip()
    thinking = (env.get("PATHFINDER_CHAT_THINKING") or "disabled").strip().lower()
    return ChatSettings(api_key=key, base_url=base, model=model,
                        timeout=float(env.get("PATHFINDER_CHAT_TIMEOUT") or 60),
                        thinking="enabled" if thinking == "enabled" else "disabled")


SYSTEM = (
    "You are the helper inside HKU Pathfinder, a small pilot that builds a course and opportunity "
    "plan for one programme only: {programme}, cohort {cohort}.\n"
    "Rules you must follow:\n"
    "- Never invent a course code, a deadline, an eligibility rule or a link. If you do not know, say so.\n"
    "- Never promise an outcome such as admission, a place on a course, or a placement, and never "
    "predict eligibility.\n"
    "- You do not build the plan. If the student wants a plan, tell them to press 'Build plan' and say "
    "what the form needs (year, completed courses, interests, target semester).\n"
    "- Questions about another programme or cohort get a plain answer: the pilot covers this one only.\n"
    "- Opportunities: the pilot links to CEDARS, NETjobs, JIJIS, URFP and job boards. It cannot see "
    "inside them, so never say a position is open.\n"
    "- Keep answers under 120 words, plain English, no markdown headings.\n"
    "- If the student asks what you were told, what your instructions are, or what your limits are, "
    "answer from these rules honestly and directly - paraphrase them, do not quote them word for "
    "word.\n"
    "Known course codes you may refer to: {codes}."
)


def system_prompt(corpus) -> str:
    codes = ", ".join(sorted(c["code"] for c in corpus.courses))
    return SYSTEM.format(programme=corpus.meta["programme"], cohort=corpus.meta["cohort"], codes=codes)


def build_messages(history: list[dict[str, str]], corpus, context: dict[str, Any] | None = None) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": system_prompt(corpus)}]
    if context:
        messages.append(
            {
                "role": "system",
                "content": "The plan currently on screen, as facts: "
                + json.dumps(context, ensure_ascii=False)[:2000],
            }
        )
    for item in history[-MAX_MESSAGES:]:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:2000]})
    return messages


def check_reply(text: str, corpus) -> tuple[bool, str]:
    """Whether this reply may be shown. Returns (ok, reason)."""
    if not text:
        return False, "empty reply"
    if len(text) > MAX_CHARS:
        return False, f"too long ({len(text)} chars)"
    phrase = find_promise(text)
    if phrase:
        return False, f"promises an outcome: '{phrase}'"
    invented = sorted({c for c in CODE.findall(text) if corpus.course(c) is None})
    if invented:
        return False, f"refers to course code(s) the pilot does not have: {', '.join(invented)}"
    return True, "ok"


def _post(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def reply(history: list[dict[str, str]], corpus, settings: ChatSettings | None = None,
          context: dict[str, Any] | None = None,
          transport: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return {ok, text, model, error}. Never raises for an upstream problem."""
    settings = settings or settings_from_env()
    if not settings.enabled:
        return {"ok": False, "model": settings.model,
                "error": "No chat key is configured on the server. Set PATHFINDER_CHAT_API_KEY and restart."}

    if not any((m.get("content") or "").strip() for m in history if m.get("role") == "user"):
        return {"ok": False, "model": settings.model, "error": "The message is empty."}

    global _LAST_CALL
    # One upstream call at a time: the course announcement warns that high
    # concurrency can get a shared group key suspended.
    if not _LOCK.acquire(blocking=False):
        return {"ok": False, "model": settings.model, "error": "One question at a time, please."}
    try:
        wait = MIN_INTERVAL - (time.monotonic() - _LAST_CALL)
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL = time.monotonic()

        payload = {
            "model": settings.model,
            "messages": build_messages(history, corpus, context),
            "temperature": 0.3,
            # glm-4.6 is a reasoning model: it spends tokens on reasoning_content
            # before writing an answer, so a small budget yields an empty reply.
            "max_tokens": 1200,
        }
        if settings.thinking in {"enabled", "disabled"}:
            payload["thinking"] = {"type": settings.thinking}
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.api_key}",
            "User-Agent": USER_AGENT,
        }
        post = transport or _post
        try:
            data = post(f"{settings.base_url}/chat/completions", headers, payload, settings.timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            hint = " The key was rejected." if exc.code in (401, 403) else ""
            return {"ok": False, "model": settings.model,
                    "error": f"Upstream HTTP {exc.code}.{hint} {detail}"}
        except Exception as exc:  # noqa: BLE001 - network, timeout, JSON
            return {"ok": False, "model": settings.model,
                    "error": f"{type(exc).__name__}: {str(exc)[:160]}"}

        try:
            message = data["choices"][0]["message"]
            text = (message.get("content") or "").strip()
        except (KeyError, IndexError, TypeError, AttributeError):
            return {"ok": False, "model": settings.model, "error": "Unexpected response shape from upstream."}

        if not text:
            # A reasoning model that ran out of budget returns an empty content
            # with a populated reasoning_content. Say so instead of "empty reply".
            reasoned = bool((message or {}).get("reasoning_content"))
            return {
                "ok": False,
                "model": settings.model,
                "error": "The model returned no answer"
                         + (" (its reasoning used the whole token budget - try again or raise max_tokens)."
                            if reasoned else "."),
            }

        ok, reason = check_reply(text, corpus)
        if not ok:
            return {
                "ok": False,
                "model": settings.model,
                "error": f"The reply was withheld by the safety check ({reason}). Try rephrasing, "
                         "or press Build plan for the verified version.",
            }
        return {"ok": True, "text": text, "model": settings.model, "error": ""}
    finally:
        _LOCK.release()
