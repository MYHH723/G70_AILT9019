"""Documented-constraint checks applied before any relevance ranking.

Every check returns a reason string that names the rule and the source
document it came from, so the plan can cite it. Nothing here guesses: when a
prerequisite status cannot be established from the student's declared record,
the course is marked ``needs_verification`` rather than eligible or blocked.
"""

from __future__ import annotations

from typing import Any

# Priority used when several checks fire at once: the most restrictive wins.
PRIORITY = [
    "completed",
    "restricted",
    "blocked",
    "needs_verification",
    "not_offered",
    "excluded",
    "eligible",
]


def _reason(text: str, label: str, cite: dict[str, str] | None = None) -> dict[str, Any]:
    return {"text": text, "label": label, "cite": cite or {}}


def evaluate_course(course: dict[str, Any], profile: dict[str, Any], corpus) -> dict[str, Any]:
    code = course["code"]
    year = int(profile.get("year") or 0)
    completed = [c.upper() for c in profile.get("completed", [])]
    completed_incomplete = bool(profile.get("completed_incomplete"))
    target_semester = profile.get("target_semester")

    reasons: list[dict[str, Any]] = []
    flags: set[str] = set()
    missing: list[str] = []
    citations: list[dict[str, str]] = [
        {
            "doc_id": course["doc_id"],
            "url": course["source_url"],
            "as_of": course["snapshot_date"],
        }
    ]

    # 0. Already completed ------------------------------------------------
    if code in completed:
        flags.add("completed")
        reasons.append(
            _reason(
                "Already recorded as completed in the declared profile; not a next-step option.",
                "agent reading",
            )
        )

    # 1. Cohort-specific curriculum rules --------------------------------
    for reg in corpus.regulation_for(code, "cohort_restricted"):
        if profile.get("cohort") == reg.get("cohort"):
            flags.add("restricted")
            reasons.append(
                _reason(
                    f"{code} does not satisfy the requirement for the {reg['cohort']} intake; "
                    f"the curriculum change names a replacement course.",
                    "published fact",
                    {"doc_id": reg["doc_id"], "url": reg["source_url"], "as_of": reg["snapshot_date"]},
                )
            )

    # 2. Year / capstone restrictions ------------------------------------
    min_year = course.get("min_year")
    if min_year and year and year < min_year:
        flags.add("restricted")
        cite = None
        for reg in corpus.regulation_for(code, "min_year"):
            cite = {"doc_id": reg["doc_id"], "url": reg["source_url"], "as_of": reg["snapshot_date"]}
        reasons.append(
            _reason(
                f"Restricted to Year {min_year} or above; the declared profile is Year {year}.",
                "published fact",
                cite,
            )
        )

    # 3. Prerequisites ----------------------------------------------------
    for prereq in course.get("prerequisites", []):
        if prereq in completed:
            continue
        prereq_doc = corpus.course(prereq)
        if completed_incomplete or prereq_doc is None:
            flags.add("needs_verification")
            reasons.append(
                _reason(
                    f"Prerequisite {prereq} cannot be confirmed from the declared record; "
                    "status must be checked with the programme office.",
                    "agent reading",
                    {"doc_id": course["doc_id"], "url": course["source_url"], "as_of": course["snapshot_date"]},
                )
            )
        else:
            missing.append(prereq)
    if missing:
        flags.add("blocked")
        reasons.append(
            _reason(
                "Blocked: prerequisite(s) not completed - " + ", ".join(missing) + ".",
                "published fact",
                {"doc_id": course["doc_id"], "url": course["source_url"], "as_of": course["snapshot_date"]},
            )
        )

    # 4. Semester availability -------------------------------------------
    if target_semester and target_semester not in course.get("offered", []):
        flags.add("not_offered")
        reasons.append(
            _reason(
                f"Not offered in {target_semester}; listed offerings are "
                + ", ".join(course.get("offered", []))
                + ".",
                "published fact",
                {"doc_id": course["doc_id"], "url": course["source_url"], "as_of": course["snapshot_date"]},
            )
        )

    status = next((s for s in PRIORITY if s in flags), "eligible")
    if status == "eligible":
        reasons.insert(
            0,
            _reason(
                "No documented prerequisite, exclusion or offering conflict was found for the declared profile.",
                "agent reading",
            ),
        )

    return {
        "code": code,
        "title": course["title"],
        "credits": course.get("credits"),
        "load": course.get("load", "standard"),
        "offered": course.get("offered", []),
        "skills": course.get("skills", []),
        "status": status,
        "reasons": reasons,
        "missing_prerequisites": missing,
        "citations": citations,
    }


def resolve_exclusions(items: list[dict[str, Any]], corpus) -> list[dict[str, Any]]:
    """Never present two mutually exclusive courses as a feasible combination.

    The higher-ranked item keeps its status; the other is demoted to
    ``excluded`` with the regulation cited. Ranking order is preserved.
    """
    kept: dict[str, str] = {}
    for item in items:
        course = corpus.course(item["code"])
        if not course:
            continue
        clash = None
        for other in course.get("exclusions", []):
            if other in kept:
                clash = other
                break
        if clash and item["status"] in {"eligible", "needs_verification"}:
            reg = corpus.regulation("REG-EXCLUSION")
            item["status"] = "excluded"
            item["reasons"] = [
                _reason(
                    f"Mutually exclusive with {clash}; only one of the pair may count towards the major, "
                    f"so it is listed separately rather than recommended together.",
                    "published fact",
                    {"doc_id": reg["doc_id"], "url": reg["source_url"], "as_of": reg["snapshot_date"]}
                    if reg
                    else None,
                )
            ] + item["reasons"]
        else:
            kept[item["code"]] = item["status"]
    return items
