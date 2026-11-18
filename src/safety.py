"""Safety layer: scope limits, refusal of external actions, and treating
retrieved page content as data rather than instructions.

Three separate concerns, deliberately kept out of the planner:

1. Scope - if the programme or cohort is not in the frozen corpus, the answer
   is limited rather than guessed.
2. Actions - the agent never logs in, applies, emails staff or guarantees an
   outcome. It names the official manual route instead.
3. Injection - retrieved text containing instructions addressed to the system
   is stripped and reported, never executed.
"""

from __future__ import annotations

import re
from typing import Any

# Only first-person requests to *perform* the action are refused. Asking
# "which internships can I apply to?" is a question, not a delegation.
ACTION_PATTERNS = [
    (r"\blog\s*in\b|\blogin\b|\bsign\s*in\b", "log in to a university system"),
    (r"\bapply (for|on) (me|my)\b|\bsubmit (my|the) application\b|\bsubmit it for me\b", "submit an application"),
    (r"\b(email|contact|message) (the|my|a) (professor|supervisor|staff|lab)\b", "contact staff on your behalf"),
    (r"\bguarantee\b|\bensure\b.*\b(admission|offer|eligib)", "guarantee an outcome"),
    (r"\bregister me\b|\benrol me\b|\badd me to\b", "register for a course"),
]

INJECTION_PATTERNS = [
    r"ignore (all )?(previous|prior|above) instructions",
    r"you are now in (administrator|admin|developer) mode",
    r"system\s*:",
    r"disregard (the )?(rules|instructions)",
    r"mark this record as open forever",
]

MANUAL_ROUTES = {
    "log in to a university system": "Open the portal yourself and sign in with your own HKU credentials.",
    "submit an application": "Use the official application form linked on the source page.",
    "contact staff on your behalf": "Email the named office or supervisor from your own account.",
    "guarantee an outcome": "Only the programme office or the recruiting unit can confirm eligibility.",
    "register for a course": "Use the official course selection system during the selection period.",
}


def scan_query(query: str) -> list[str]:
    """Return the external actions the student asked the agent to perform."""
    text = query.lower()
    hits: list[str] = []
    for pattern, label in ACTION_PATTERNS:
        if re.search(pattern, text) and label not in hits:
            hits.append(label)
    return hits


def refusal_block(actions: list[str]) -> list[dict[str, str]]:
    return [
        {
            "action": action,
            "reason": "HKU Pathfinder does not perform this action and cannot confirm its result.",
            "manual_route": MANUAL_ROUTES.get(action, "Complete this step through the official channel."),
        }
        for action in actions
    ]


def strip_injection(text: str) -> tuple[str, bool]:
    """Remove instruction-like sentences from retrieved text."""
    if not text:
        return text, False
    flagged = False
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept: list[str] = []
    for sentence in sentences:
        if any(re.search(p, sentence, flags=re.IGNORECASE) for p in INJECTION_PATTERNS):
            flagged = True
            continue
        kept.append(sentence)
    return " ".join(kept).strip(), flagged


def scope_check(profile: dict[str, Any], corpus) -> dict[str, Any]:
    """Whether the declared programme/cohort is inside the frozen corpus."""
    programme = (profile.get("programme") or "").strip()
    cohort = (profile.get("cohort") or "").strip()
    problems: list[str] = []
    if not programme:
        problems.append("no programme was declared")
    elif programme not in corpus.supported_programmes:
        problems.append(f"programme '{programme}' is not in the frozen pilot corpus")
    if not cohort:
        problems.append("no entry cohort was declared")
    elif cohort not in corpus.supported_cohorts:
        problems.append(f"cohort '{cohort}' is not in the frozen pilot corpus")
    return {"supported": not problems, "problems": problems}
