"""Real official pages the pilot can check at query time.

Until now every citation pointed at a synthetic record, and the only real
connection to HKU was a reachability probe. This module adds the missing layer:
a small registry of genuine official pages, fetched live, attached to the plan as
a second citation alongside the fixture record.

What is real here, and what is not, stated once so the interface can stay honest:

* the URLs, the HTTP status, the page title, the timestamp and the quoted
  sentence are real - they come from the page as it is right now;
* the course-level facts (prerequisites, exclusions, windows) are still fixtures,
  because parsing the official syllabus and re-publishing it is not something the
  pilot has permission to do;
* nothing is written to disk. A page is read into memory for one request, a
  bounded excerpt and a hash are kept, and the page itself is discarded.

The registry is deliberately small and versioned by hand. A crawler that
discovers URLs would be a different project with a different permission story.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Iterable

from .livecheck import fetch_page, find_sentence

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
# `quote_needle` is the sentence worth showing: the one line on the page that
# settles the question the student is asking. Keeping a single quoted sentence
# is both more useful and more defensible than reproducing the page.
SOURCES: list[dict[str, Any]] = [
    {
        "id": "DRCD-UG-2023-24",
        "url": "https://www4.hku.hk/pubunit/drcd/undergraduate-2023-2024",
        "label": "HKU Degree Regulations and Course Descriptions - Undergraduate 2023-2024",
        "covers": "university curriculum index for the 2023-24 intake",
        "applies_to": ["course", "regulations"],
        "note": "The university-level index for this cohort. It links each faculty's own regulations rather than holding the course text itself.",
    },
    {
        "id": "ENGG-SYLLABUS",
        "url": "https://engg.hku.hk/Teaching-Learning/BEng-BASc/Academic-Programmes/Regulations-Syllabuses",
        "label": "Faculty of Engineering - BEng regulations and syllabuses",
        "covers": "the BEng(CompSc) regulation and syllabus documents, listed by intake year",
        "applies_to": ["course", "regulations"],
        "note": "The faculty page that publishes the syllabus PDFs. It is the page a student would actually land on.",
    },
    {
        "id": "SYLLABUS-CS-2023-24",
        "url": "https://engg.hku.hk/Portals/0/UG/syllabuses/Syllabus-BBAIS-CS-23-24-4Y.pdf",
        "label": "BEng(CompSc) syllabus, 2023-24 intake (PDF)",
        "covers": "course-level syllabus for the pilot cohort",
        "applies_to": ["course"],
        "note": "The authoritative course-level document for this cohort. The pilot links to it and does not parse or reproduce it.",
    },
    {
        "id": "URFP",
        "url": "https://tl.hku.hk/urfp/",
        "label": "Undergraduate Research Fellowship Programme",
        "covers": "research programme information and eligibility",
        "applies_to": ["opportunity"],
        "quote_needle": "Faculty Office",
        "note": "The page states eligibility but sets no deadline of its own: it sends the reader to the relevant Faculty Office. So a deadline cannot be quoted from it, only checked with the faculty.",
    },
    {
        "id": "CEDARS-JOBS",
        "url": "https://www.cedars.hku.hk/careers/jobs",
        "label": "CEDARS careers - jobs and internships",
        "covers": "entry point to the NETjobs and JIJIS portals",
        "applies_to": ["opportunity"],
        "quote_needle": "NETjobs",
        "note": "The page is a doorway to the NETjobs and JIJIS portals. It lists no vacancy itself, so a link from here is not evidence that a position is open.",
    },
]

OPPORTUNITY_SOURCES = {
    "OPP-URF": "URFP",
    "OPP-CEDARS": "CEDARS-JOBS",
    "OPP-DS-MENTOR": "CEDARS-JOBS",
}

BY_ID = {source["id"]: source for source in SOURCES}

# Process-local cache: a page is fetched at most once every few minutes, so a
# student pressing "build plan" repeatedly does not hammer a university server.
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
CACHE_TTL = 300.0


def sources_for(kind: str) -> list[dict[str, Any]]:
    return [s for s in SOURCES if kind in s["applies_to"]]


def check(source_ids: Iterable[str], timeout: float = 10.0, use_cache: bool = True) -> dict[str, dict[str, Any]]:
    """Fetch each requested source, reusing a recent result when there is one.

    Fetched concurrently: five sequential requests to a university server took
    over forty seconds on a slow link, which is too slow to sit behind a button.
    Each host still sees one request per source per cache window.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor

    results: dict[str, dict[str, Any]] = {}
    pending: list[dict[str, Any]] = []
    for source_id in dict.fromkeys(source_ids):
        source = BY_ID.get(source_id)
        if not source:
            continue
        cached = _CACHE.get(source["url"])
        if use_cache and cached and (time.monotonic() - cached[0]) < CACHE_TTL:
            results[source_id] = cached[1]
        else:
            pending.append(source)

    def fetch(source: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        row = fetch_page(source["url"], timeout=timeout)
        # One retry, only for a network failure: the HKU hosts intermittently
        # stall on the first request, and a stall is not the same finding as a
        # page that has gone away. The attempt count is kept in the record.
        if row.get("status") == "unreachable":
            row = fetch_page(source["url"], timeout=timeout)
            row["retried"] = True
        row["source_id"] = source["id"]
        row["label"] = source["label"]
        row["covers"] = source["covers"]
        row["note"] = source["note"]
        if source.get("quote_needle") and row.get("text"):
            row["quote"] = find_sentence(row["text"], source["quote_needle"])
        return source["id"], row

    if pending:
        with ThreadPoolExecutor(max_workers=min(6, len(pending))) as pool:
            for source_id, row in pool.map(fetch, pending):
                _CACHE[row["url"]] = (time.monotonic(), row)
                results[source_id] = row
    return results


def _needed(plan: dict[str, Any]) -> list[str]:
    """Which sources this particular plan should check - no more than that."""
    ids: list[str] = []
    if plan.get("courses") or plan.get("checked_courses"):
        ids.append("SYLLABUS-CS-2023-24")
        ids.append("ENGG-SYLLABUS")
    if plan.get("checked_courses") or plan.get("notices"):
        ids.append("DRCD-UG-2023-24")
    for item in (plan.get("opportunities") or []) + (plan.get("checked_opportunities") or []):
        ids.append("CEDARS-JOBS")
        source_id = OPPORTUNITY_SOURCES.get(item.get("id", ""))
        if source_id:
            ids.append(source_id)
    return list(dict.fromkeys(ids))


def _summary(source_id: str, row: dict[str, Any]) -> dict[str, Any]:
    source = BY_ID[source_id]
    return {
        "id": source_id,
        "label": source["label"],
        "url": source["url"],
        "covers": source["covers"],
        "note": source["note"],
        "status": row.get("status"),
        "http_status": row.get("http_status"),
        "checked_at": row.get("checked_at"),
        "title": row.get("title"),
        "content_type": row.get("content_type"),
        "kind": row.get("kind"),
        "text_sha256": row.get("text_sha256"),
        "quote": row.get("quote", ""),
        "detail": row.get("detail"),
    }


def attach(plan: dict[str, Any], timeout: float = 10.0, use_cache: bool = True) -> dict[str, Any]:
    """Check the official pages this plan depends on and attach them to it.

    Each item gets an ``official`` citation next to its fixture citation. The
    fixture citation says what this build believes; the official one says where
    to check it. The two are never merged into one line, because they carry
    different levels of authority.
    """
    wanted = _needed(plan)
    if not wanted:
        plan["live"] = {"checked_at": None, "sources": [],
                        "note": "No official page is mapped to this request."}
        return plan

    results = check(wanted, timeout=timeout, use_cache=use_cache)
    summaries = [_summary(sid, row) for sid, row in results.items()]

    course_source = "SYLLABUS-CS-2023-24" if "SYLLABUS-CS-2023-24" in results else "ENGG-SYLLABUS"
    for group, source_id in (
        ("courses", course_source),
        ("deferred", course_source),
        ("checked_courses", "ENGG-SYLLABUS"),
    ):
        for item in plan.get(group) or []:
            row = results.get(source_id)
            if row:
                item["official"] = {
                    "source_id": source_id,
                    "url": row["url"],
                    "label": row["label"],
                    "status": row.get("status"),
                    "checked_at": row.get("checked_at"),
                }

    fallback = results.get("CEDARS-JOBS")
    fallback = results.get("CEDARS-JOBS")
    for item in (plan.get("opportunities") or []) + (plan.get("checked_opportunities") or []):
        source_id = OPPORTUNITY_SOURCES.get(item.get("id", ""))
        row = results.get(source_id) if source_id else None
        if row:
            item["official"] = {
                "source_id": source_id,
                "url": row["url"],
                "label": row["label"],
                "status": row.get("status"),
                "checked_at": row.get("checked_at"),
            }
        else:
            # Explicit None, not a missing key: the interface has to be able to
            # say "this record has no official page" rather than staying silent.
            item["official"] = None
            if fallback:
                # Not a verification of this record - a real place to go and look
                # for yourself, which is more useful than a dead end.
                item["official_fallback"] = {
                    "url": fallback["url"],
                    "label": fallback["label"],
                    "checked_at": fallback.get("checked_at"),
                }

    reachable = sum(1 for s in summaries if s["status"] == "ok")
    plan["live"] = {
        "checked_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "sources": summaries,
        "note": (
            f"{reachable} of {len(summaries)} official page(s) were readable during this request. "
            "Course-level facts still come from the pilot fixtures; the official pages are linked so "
            "they can be checked, not so they can be quoted as this build's source."
        ),
    }
    return plan


def markdown(summaries: list[dict[str, Any]]) -> str:
    lines = [
        "| Source | URL | Status | Checked | Quote |",
        "|---|---|---|---|---|",
    ]
    for row in summaries:
        quote = (row.get("quote") or "").replace("|", "/")
        lines.append(
            f"| {row['label']} | {row['url']} | {row['status']} "
            f"({row.get('http_status') or '-'}) | {row.get('checked_at') or '-'} | {quote[:160] or '-'} |"
        )
    return "\n".join(lines)
