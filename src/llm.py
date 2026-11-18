"""Optional model layer: wording only, never facts.

The pilot's decisions are made by a deterministic planner, and that is what
makes the 24-case evidence reproducible. A language model is added on top for
one job only: rewriting the summary paragraph so it reads like prose rather than
a template. It never chooses a course, never decides a status, never sees a
record the planner did not already accept.

Three rules make that boundary enforceable rather than aspirational:

1. The model receives the plan's facts as JSON and is told to add none.
2. Its output is checked against those facts before it is used: every course
   code, URL and date in the text must already exist in the plan. A single
   invented code, link or deadline throws the whole rewrite away.
3. Any failure - no key, timeout, HTTP error, malformed JSON, a rejected
   rewrite - silently falls back to the template. The plan is never worse for
   having tried.

Configuration is by environment variable, so no key is ever committed:

    PATHFINDER_LLM_API_KEY=...        # enables the layer
    PATHFINDER_LLM_BASE_URL=...       # default https://api.openai.com/v1
    PATHFINDER_LLM_MODEL=...          # default gpt-4o-mini
    PATHFINDER_LLM_TIMEOUT=20

Any OpenAI-compatible endpoint works; the request is a plain JSON POST with the
standard library, no SDK.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from .guards import find_promise

USER_AGENT = "HKUPathfinderPilot/1.0 (wording layer)"

MAX_CHARS = 900

CODE = re.compile(r"\b[A-Z]{2,4}\d{4}\b")
URL = re.compile(r"https?://[^\s)\]]+")
DATE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")

SYSTEM_PROMPT = (
    "You rewrite one paragraph of a study plan for an HKU student.\n"
    "Hard rules:\n"
    "- Use ONLY the facts in the JSON. Do not add a course, a date, a link, a deadline or a "
    "requirement that is not in it.\n"
    "- Keep every course code, URL and date exactly as written.\n"
    "- Never promise an outcome such as admission or a placement, and never predict eligibility.\n"
    "- Do not give personal course-selection advice; describe options and what still needs checking.\n"
    "- Two to four sentences, plain English, no markdown, no lists, under 600 characters.\n"
    "If the facts are too thin for a sentence, say less rather than inventing."
)


@dataclass
class Settings:
    api_key: str = ""
    base_url: str = "https://open.bigmodel.cn/api/coding/paas/v4"
    model: str = "glm-4.6"
    timeout: float = 60.0
    # Rewriting one paragraph needs no deliberation, and with thinking on the
    # model spent 1600 tokens reasoning and returned nothing.
    thinking: str = "disabled"

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)


def settings_from_env(env: dict[str, str] | None = None) -> Settings:
    env = env if env is not None else os.environ
    return Settings(
        api_key=(env.get("PATHFINDER_LLM_API_KEY") or "").strip(),
        base_url=(env.get("PATHFINDER_LLM_BASE_URL") or "https://open.bigmodel.cn/api/coding/paas/v4").rstrip("/"),
        model=(env.get("PATHFINDER_LLM_MODEL") or "glm-4.6").strip(),
        timeout=float(env.get("PATHFINDER_LLM_TIMEOUT") or 60),
        thinking="enabled" if (env.get("PATHFINDER_LLM_THINKING") or "").lower() == "enabled" else "disabled",
    )


# ---------------------------------------------------------------------------
# Facts the model is allowed to use
# ---------------------------------------------------------------------------
def build_facts(plan: dict[str, Any]) -> dict[str, Any]:
    courses = [
        {
            "code": item["code"],
            "title": item["title"],
            "status": item["status"],
            "reason": item["reasons"][0]["text"] if item["reasons"] else "",
        }
        for item in (plan.get("courses") or [])
    ]
    checked = [
        {"code": item["code"], "status": item["status"]}
        for item in (plan.get("checked_courses") or [])
    ][:8]
    leads = [
        {
            "title": item["title"],
            "status": item["status"],
            "window_end": (item.get("window") or {}).get("end"),
        }
        for item in (plan.get("opportunities") or [])
    ]
    return {
        "status": plan.get("status"),
        "as_of": plan.get("as_of"),
        "recommended_courses": courses,
        "checked_courses": checked,
        "open_leads": leads,
        "notices": list(plan.get("notices") or []),
        "template_summary": plan.get("summary", ""),
    }


def _allowed(plan: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
    codes, urls, dates = set(), set(), set()
    for group in ("courses", "checked_courses", "deferred", "opportunities", "checked_opportunities"):
        for item in plan.get(group) or []:
            if item.get("code"):
                codes.add(item["code"])
            for cite in item.get("citations") or []:
                if cite.get("url"):
                    urls.add(cite["url"].rstrip(".,)"))
            if item.get("as_of"):
                dates.add(item["as_of"])
            window = item.get("window") or {}
            for key in ("start", "end"):
                if window.get(key):
                    dates.add(window[key])
    for channel in plan.get("channels") or []:
        if channel.get("url"):
            urls.add(channel["url"].rstrip(".,)"))
    for source in (plan.get("live") or {}).get("sources") or []:
        if source.get("url"):
            urls.add(source["url"].rstrip(".,)"))
    if plan.get("as_of"):
        dates.add(plan["as_of"])
    return codes, urls, dates


# ---------------------------------------------------------------------------
# The call
# ---------------------------------------------------------------------------
def _post(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def call_model(messages: list[dict[str, str]], settings: Settings,
               transport: Callable[..., dict[str, Any]] | None = None) -> str:
    payload = {
        "model": settings.model,
        "messages": messages,
        "temperature": 0.2,
        # glm-4.6 spends a few hundred tokens on reasoning before writing the
        # paragraph; below roughly 1200 the content comes back empty.
        "max_tokens": 700,
    }
    if settings.thinking in {"enabled", "disabled"}:
        payload["thinking"] = {"type": settings.thinking}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.api_key}",
        "User-Agent": USER_AGENT,
    }
    post = transport or _post
    data = post(f"{settings.base_url}/chat/completions", headers, payload, settings.timeout)
    message = data["choices"][0]["message"]
    text = (message.get("content") or "").strip()
    if not text and message.get("reasoning_content"):
        raise RuntimeError("the model spent its whole token budget on reasoning and returned no text")
    return text


def check_wording(text: str, plan: dict[str, Any]) -> tuple[bool, str]:
    """Whether a rewrite may be shown to a student. Returns (ok, reason)."""
    if not text:
        return False, "empty output"
    if len(text) > MAX_CHARS:
        return False, f"too long ({len(text)} chars)"
    phrase = find_promise(text)
    if phrase:
        return False, f"forbidden phrase: {phrase}"

    codes, urls, dates = _allowed(plan)
    invented = [c for c in CODE.findall(text) if c not in codes]
    if invented:
        return False, f"invented course code(s): {', '.join(sorted(set(invented)))}"
    for url in URL.findall(text):
        if url.rstrip(".,)") not in urls:
            return False, f"invented link: {url[:60]}"
    for date in DATE.findall(text):
        if date not in dates:
            return False, f"invented date: {date}"
    return True, "facts preserved"


def rewrite(plan: dict[str, Any], settings: Settings | None = None,
            transport: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    """Replace the summary with model prose, if and only if it passes the guard."""
    settings = settings or settings_from_env()
    record: dict[str, Any] = {"used": False, "model": settings.model, "reason": ""}

    if not settings.enabled:
        record["reason"] = "no model configured (PATHFINDER_LLM_API_KEY unset)"
        plan["wording"] = record
        return plan

    facts = build_facts(plan)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(facts, ensure_ascii=False, indent=2)},
    ]
    try:
        text = call_model(messages, settings, transport=transport)
    except Exception as exc:  # noqa: BLE001 - any failure means fall back
        record["reason"] = f"model call failed: {type(exc).__name__}: {str(exc)[:120]}"
        plan["wording"] = record
        return plan

    ok, reason = check_wording(text, plan)
    record["reason"] = reason
    record["checked"] = ok
    if ok:
        record["used"] = True
        record["template_summary"] = plan.get("summary", "")
        plan["summary"] = text
    plan["wording"] = record
    return plan
