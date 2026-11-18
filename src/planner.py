"""The single planning skill: request -> evidence -> constraints -> plan.

The planner is deterministic on purpose. The midterm check asks for a working
core path with reproducible evidence, and a deterministic planner can be
re-run by staff byte-for-byte with no API key, no model download and no cost.
The same interface can later be driven by an LLM that only fills the prose
around these facts.
"""

from __future__ import annotations

import datetime as _dt
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from . import channels, official, safety
from .constraints import evaluate_course, resolve_exclusions
from .retrieval import BM25, explicit_codes, opportunity_index, course_index, tokenize

MAX_COURSES = 3
MAX_OPPORTUNITIES = 3
MAX_CANDIDATES = 16

OPPORTUNITY_PRIORITY = [
    "snapshot_verify_manually",
    "unverifiable",
    "info_only",
    "scheme",
    "closed",
    "ineligible",
    "not_yet_open",
    "open",
]


def _today(today: _dt.date | None = None) -> _dt.date:
    if today:
        return today
    override = os.environ.get("PATHFINDER_TODAY")
    if override:
        return _dt.date.fromisoformat(override)
    return _dt.date.today()


def _cite(doc_id: str, url: str, as_of: str) -> dict[str, str]:
    return {"doc_id": doc_id, "url": url, "as_of": as_of}


# ---------------------------------------------------------------------------
# Opportunities
# ---------------------------------------------------------------------------
def evaluate_opportunity(record: dict[str, Any], profile: dict[str, Any], today: _dt.date,
                         fetch_status: str | None = None) -> dict[str, Any]:
    """Check one opportunity record.

    ``fetch_status`` lets a live probe override the record's staged field. When
    it is omitted the fixture value is used, so every recorded test stays
    reproducible without network access.
    """
    clean_summary, injected = safety.strip_injection(record.get("summary", ""))
    year = int(profile.get("year") or 0)
    fetch = fetch_status or record.get("fetch_status", "ok")
    window_start = record.get("window_start")
    window_end = record.get("window_end")
    flags: set[str] = set()
    reasons: list[dict[str, Any]] = []

    cite = _cite(record["id"], record["source_url"], record.get("as_of", ""))

    if fetch == "unreachable":
        flags.add("snapshot_verify_manually")
        reasons.append(
            {
                "text": (
                    "Source page could not be reached. Showing the dated snapshot of "
                    f"{record.get('as_of')} - verify manually before relying on it. "
                    "The snapshot is not evidence of a currently open call."
                ),
                "label": "agent reading",
                "cite": cite,
            }
        )
    elif fetch == "login_required":
        flags.add("unverifiable")
        reasons.append(
            {
                "text": "Listing sits behind a university login; eligibility and deadline cannot be verified without signing in.",
                "label": "agent reading",
                "cite": cite,
            }
        )
    elif record.get("type") == "info_only":
        flags.add("info_only")
        reasons.append(
            {
                "text": "This is a research-interest page, not a recruitment notice; it does not show that the group is hiring.",
                "label": "published fact",
                "cite": cite,
            }
        )
    elif record.get("type") == "scheme":
        flags.add("scheme")
        reasons.append(
            {
                "text": "Programme information page. It announces no current call and carries no deadline of its own.",
                "label": "published fact",
                "cite": cite,
            }
        )

    # Window and eligibility only matter once the record is a real vacancy.
    if not flags:
        if window_end and _dt.date.fromisoformat(window_end) < today:
            flags.add("closed")
            reasons.append(
                {
                    "text": f"Application window closed on {window_end}; it must not be shown as open.",
                    "label": "published fact",
                    "cite": cite,
                }
            )
        elif record.get("min_year") and year and year < int(record["min_year"]):
            flags.add("ineligible")
            reasons.append(
                {
                    "text": f"Eligibility is restricted beyond Year {year}: {record.get('eligibility_text', '')}",
                    "label": "published fact",
                    "cite": cite,
                }
            )
        elif window_start and _dt.date.fromisoformat(window_start) > today:
            flags.add("not_yet_open")
            reasons.append(
                {
                    "text": f"Applications open on {window_start}.",
                    "label": "published fact",
                    "cite": cite,
                }
            )
        else:
            flags.add("open")
            reasons.append(
                {
                    "text": "A current call is open: the source page was reachable and the window covers today.",
                    "label": "published fact",
                    "cite": cite,
                }
            )

    status = next((s for s in OPPORTUNITY_PRIORITY if s in flags), "open")

    if injected:
        # A record that talks to the system is quarantined, not recommended.
        # The open/closed reasoning is discarded: the record cannot be trusted
        # as evidence until a human has read the original page.
        status = "quarantined"
        reasons = [
            {
                "text": "This record contained instructions addressed to the system. They were treated as data, ignored, and the record is held for manual review.",
                "label": "agent reading",
                "cite": cite,
            }
        ]

    return {
        "id": record["id"],
        "type": record.get("type"),
        "title": record["title"],
        "host": record.get("host", ""),
        "topics": record.get("topics", []),
        "status": status,
        "eligibility": record.get("eligibility_text", ""),
        "window": {"start": window_start, "end": window_end},
        "apply_url": record.get("apply_url"),
        "summary": clean_summary,
        "reasons": reasons,
        "citations": [cite],
        "injection_flagged": injected,
        "as_of": record.get("as_of"),
    }


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------
def _select_candidates(query: str, profile: dict[str, Any], corpus, index: BM25) -> list[tuple[dict[str, Any], float]]:
    picked: dict[str, tuple[dict[str, Any], float]] = {}
    for code in explicit_codes(query, corpus):
        picked[code] = (corpus.course(code), 99.0)
    interest_query = " ".join(profile.get("interests", []))
    for record, score in index.search(query, top_k=MAX_CANDIDATES):
        picked.setdefault(record["code"], (record, score))
    for record, score in index.search(interest_query, top_k=MAX_CANDIDATES):
        if record["code"] not in picked:
            picked[record["code"]] = (record, score * 0.9)
    return sorted(picked.values(), key=lambda pair: pair[1], reverse=True)[:MAX_CANDIDATES]


TITLE_STOP = {
    "introduction", "to", "and", "of", "the", "for", "principles", "applied",
    "final", "year", "project", "i", "ii", "data",
}


def _focus_course(query: str, evaluated: list[dict[str, Any]], corpus) -> dict[str, Any] | None:
    """The single course the student is asking *about*, if one is named.

    Deliberately conservative: an explicit course code, or at least two
    distinctive words from a course title. This stops a generic request such as
    "which research options are there" from being answered with a lecture on
    one unrelated course.
    """
    codes = explicit_codes(query, corpus)
    if codes:
        return next((i for i in evaluated if i["code"] == codes[0]), None)

    lowered = query.lower()
    best: tuple[int, dict[str, Any]] | None = None
    for item in evaluated:
        tokens = [t for t in tokenize(item["title"]) if t not in TITLE_STOP and len(t) > 3]
        hits = sum(1 for t in tokens if t in lowered)
        if hits >= 2 and (best is None or hits > best[0]):
            best = (hits, item)
    return best[1] if best else None


def _apply_workload(items: list[dict[str, Any]], profile: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Trim the recommendation to the declared workload ceiling."""
    ceiling = profile.get("workload_ceiling")
    if not ceiling:
        return items, []
    used = 0
    keep: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for item in items:
        cost = 2 if item.get("load") == "heavy" else 1
        if used + cost > int(ceiling):
            item = dict(item)
            item["status"] = "deferred"
            item["reasons"] = [
                {
                    "text": f"Exceeds the declared workload ceiling of {ceiling} standard-course units; deferred to a later semester.",
                    "label": "agent reading",
                    "cite": {},
                }
            ] + item["reasons"]
            dropped.append(item)
            continue
        used += cost
        keep.append(item)
    return keep, dropped


# ---------------------------------------------------------------------------
# Retrieval-disabled ablation
# ---------------------------------------------------------------------------
def _ablation_answer(profile: dict[str, Any], query: str) -> tuple[str, list[str]]:
    """What the same agent says when it cannot look anything up.

    Used only by ``tests/baseline.py`` to measure what retrieval contributes.
    The wording is deliberately the *best* a no-retrieval agent can do: fluent,
    plausible, and specific enough to sound useful - which is exactly why it is
    dangerous. It names no course code, cites nothing, checks no prerequisite
    and reads no application window, because it has no source to do it from.
    """
    interests = [i for i in (profile.get("interests") or []) if i]
    focus = interests[0] if interests else "your stated interest"
    year = profile.get("year") or "current"
    semester = profile.get("target_semester") or "next semester"
    summary = (
        f"For a Year {year} student interested in {focus}, a reasonable {semester} plan is to take an "
        f"advanced course in {focus} together with a supporting statistics or database course, and to "
        f"approach a faculty group working on {focus} about research openings. Internships in the same "
        f"area are usually advertised through the careers office."
    )
    steps = [
        f"Choose one advanced {focus} course and one supporting course for {semester}.",
        f"Contact a faculty group working on {focus} to ask about research openings.",
        "Check the careers office listings for internships in this area.",
    ]
    return summary, steps


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def plan(profile: dict[str, Any], query: str, corpus, today: _dt.date | None = None,
         reachability: dict[str, str] | None = None,
         retrieve: bool = True, live: bool = False) -> dict[str, Any]:
    """Build a plan.

    ``reachability`` maps an opportunity id to a live probe result
    (``ok`` / ``unreachable`` / ``login_required``). ``retrieve=False`` runs the
    retrieval-disabled ablation used by the baseline comparison. ``live=True``
    also checks the real official pages this plan depends on and attaches them as
    a second, higher-authority citation; it needs network access and is therefore
    opt-in.
    """
    today = _today(today)
    notices: list[str] = []
    refused = safety.refusal_block(safety.scan_query(query))
    scope = safety.scope_check(profile, corpus)

    mode = "offline-fixture"
    if not retrieve:
        mode = "no-retrieval-ablation"
    elif reachability:
        mode = "offline-fixture + live probe"
    if live and retrieve:
        mode += " + live official check"

    base = {
        "mode": mode,
        "as_of": today.isoformat(),
        "corpus": corpus.stats(),
        "notices": notices,
        "refused_actions": refused,
        "courses": [],
        "opportunities": [],
        "deferred": [],
        "checked_courses": [],
        "next_steps": [],
        "scope": scope,
    }

    if not scope["supported"]:
        notices.append(
            "Limited answer: " + "; ".join(scope["problems"]) + ". The pilot covers one programme and cohort only, so no plan is produced."
        )
        base["status"] = "limited"
        base["summary"] = (
            "I cannot build a verified plan for this request. The pilot corpus covers "
            f"{corpus.meta['programme']} (cohort {corpus.meta['cohort']}) only, and I will not guess rules for another programme."
        )
        base["next_steps"] = [
            "Check the current curriculum document for your own programme and cohort.",
            "Ask your programme office which course list applies to your intake year.",
        ]
        channels.attach(base)
        return base

    if not retrieve:
        summary, steps = _ablation_answer(profile, query)
        notices.append(
            "Ablation mode: no corpus lookup, no documented constraint check and no source citation. "
            "This answer exists only to measure what retrieval contributes and must not be shown to a student."
        )
        base["status"] = "unverified"
        base["summary"] = summary
        base["next_steps"] = steps
        base["trace"] = {"query": query, "candidates": [], "opportunity_candidates": [], "rules_applied": []}
        return base

    # --- courses ---------------------------------------------------------
    index = course_index(corpus)
    evaluated: list[dict[str, Any]] = []
    for course, score in _select_candidates(query, profile, corpus, index):
        item = evaluate_course(course, profile, corpus)
        item["score"] = score
        evaluated.append(item)
    evaluated = resolve_exclusions(evaluated, corpus)

    eligible = [i for i in evaluated if i["status"] == "eligible"][:MAX_COURSES]
    eligible, deferred = _apply_workload(eligible, profile)
    others = [i for i in evaluated if i["status"] != "eligible"]

    base["courses"] = eligible
    base["deferred"] = deferred
    base["checked_courses"] = sorted(others, key=lambda i: i.get("score", 0), reverse=True)

    # --- opportunities ---------------------------------------------------
    opp_index = opportunity_index(corpus)
    opp_query = " ".join(
        [query] + list(profile.get("interests", [])) + list(profile.get("opportunity_types", []))
    )
    opp_hits = opp_index.search(opp_query, top_k=len(corpus.opportunities))
    if not opp_hits:
        opp_hits = [(r, 0.0) for r in corpus.opportunities[:MAX_CANDIDATES]]

    live_map = reachability or {}
    if live_map:
        base["reachability_source"] = "live probe"
        base["reachability"] = dict(live_map)
    opp_items = [
        evaluate_opportunity(rec, profile, today, fetch_status=live_map.get(rec["id"]))
        for rec, _ in opp_hits
    ]
    allowed_types = [t.lower() for t in profile.get("opportunity_types", [])]

    def type_ok(item: dict[str, Any]) -> bool:
        if not allowed_types:
            return True
        blob = (item["title"] + " " + " ".join(item.get("topics", [])) + " " + item.get("host", "")).lower()
        for wanted in allowed_types:
            if wanted == "research" and ("research" in blob or "lab" in blob):
                return True
            if wanted == "internship" and "intern" in blob:
                return True
        return False

    open_items = [i for i in opp_items if i["status"] == "open"]
    preferred = [i for i in open_items if type_ok(i)]
    if open_items and not preferred:
        notices.append("No open lead matched the preferred opportunity types; the closest open leads are shown instead.")
        preferred = open_items
    verified = preferred[:MAX_OPPORTUNITIES]
    rest = [i for i in opp_items if i not in verified]

    display_order = {
        "snapshot_verify_manually": 0, "closed": 1, "unverifiable": 2, "quarantined": 3,
        "ineligible": 4, "scheme": 5, "info_only": 6, "not_yet_open": 7,
    }
    base["opportunities"] = verified
    base["checked_opportunities"] = sorted(
        rest, key=lambda i: (display_order.get(i["status"], 9), i["id"])
    )

    # --- narrative -------------------------------------------------------
    focus = _focus_course(query, evaluated, corpus)
    focus_blocked = focus is not None and focus["status"] != "eligible"

    if eligible and verified:
        base["status"] = "ok"
        base["summary"] = (
            f"Found {len(eligible)} course option(s) that pass the documented checks and "
            f"{len(verified)} currently open opportunity lead(s) for a Year {profile.get('year')} "
            f"student in {profile.get('target_semester')}."
        )
    elif eligible:
        base["status"] = "partial"
        base["summary"] = (
            f"Found {len(eligible)} course option(s) that pass the documented checks, but no opportunity "
            "could be verified as currently open. The leads below are shown with the reason they cannot be confirmed."
        )
    elif verified:
        base["status"] = "partial"
        base["summary"] = (
            "No course in the frozen corpus passed the documented checks for this request, so no study plan is "
            f"offered. {len(verified)} opportunity lead(s) are currently open and are listed separately."
        )
    else:
        base["status"] = "limited"
        base["summary"] = (
            "No course or opportunity passed the documented checks for this request. "
            "The blocked and unverified items are listed with the reason, rather than offered as available."
        )

    # --- next steps ------------------------------------------------------
    if focus_blocked:
        base["summary"] = (
            f"{focus['code']} {focus['title']} is {focus['status']}: "
            f"{focus['reasons'][0]['text']} " + base["summary"]
        )

    steps: list[str] = []
    for item in eligible:
        steps.append(f"Confirm {item['code']} {item['title']} on the official course page and check the exam timetable before committing.")
    for item in verified:
        steps.append(f"Check {item['title']} ({item['host']}) against its source page and note the closing date {item['window']['end'] or 'not stated'}.")
    if any(i["status"] == "blocked" for i in others):
        blocked = next(i for i in others if i["status"] == "blocked")
        steps.append(f"Plan {', '.join(blocked['missing_prerequisites'])} before {blocked['code']}; it is the documented blocker.")
    if any(i["status"] == "snapshot_verify_manually" for i in base.get("checked_opportunities", [])):
        steps.append("Re-check the snapshot-only lead by hand; the page was unreachable when the plan was built.")
    if not steps:
        steps.append("Take the request to your programme office; no verified option could be produced from the current corpus.")
    base["next_steps"] = steps

    # --- transparency ----------------------------------------------------
    if refused:
        notices.append("The request asked for actions the agent does not perform; the manual route is listed instead.")
    if any(i.get("injection_flagged") for i in opp_items):
        notices.append("A retrieved record contained instructions addressed to the system. They were treated as data and ignored.")
    if any(i["status"] == "needs_verification" for i in evaluated):
        notices.append("At least one course needs verification because the declared record is incomplete.")
    if deferred:
        notices.append(f"{len(deferred)} otherwise-eligible course(s) were deferred to respect the declared workload ceiling.")

    base["trace"] = {
        "query": query,
        "candidates": [i["code"] for i in evaluated],
        "opportunity_candidates": [i["id"] for i in opp_items],
        "rules_applied": sorted({"prerequisite", "exclusion", "semester", "min_year", "cohort", "workload"}),
    }

    if live:
        # Both checks are network-bound and independent; run them together so a
        # live request costs roughly the slower one, not the sum.
        with ThreadPoolExecutor(max_workers=2) as pool:
            official_check = pool.submit(official.attach, base)
            channel_check = pool.submit(channels.attach, base, True)
            official_check.result()
            channel_check.result()
    else:
        channels.attach(base)
    return base
