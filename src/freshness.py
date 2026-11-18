"""Corpus freshness audit.

The peer review of the proposal asked a question the pilot could not answer:
how much drift is tolerated before a record stops being usable? A frozen
corpus of synthetic records silently rots - the application windows written in
October fall into the past, every lead becomes ``closed``, and the
"verified open lead" path quietly stops producing anything while every unit
test still passes because the test date is pinned.

This module makes that visible instead of letting it happen. It is a read-only
audit: it changes no record and no status, it only reports what a student would
actually see on a given day.
"""

from __future__ import annotations

from datetime import date
from typing import Any

# A window ending within this many days is "closing soon" and worth surfacing.
CLOSING_SOON_DAYS = 30
# A snapshot older than this is called stale in the report.
MAX_SNAPSHOT_AGE_DAYS = 120


def _age_days(stamp: str | None, today: date) -> int | None:
    if not stamp:
        return None
    return (today - date.fromisoformat(stamp)).days


def audit(corpus, today: date) -> dict[str, Any]:
    """Classify every opportunity record relative to ``today``."""
    rows: list[dict[str, Any]] = []
    for record in corpus.opportunities:
        window_end = record.get("window_end")
        window_start = record.get("window_start")
        if not window_end:
            state = "no_window"
            days_left = None
        else:
            days_left = (date.fromisoformat(window_end) - today).days
            if days_left < 0:
                state = "expired"
            elif days_left <= CLOSING_SOON_DAYS:
                state = "closing_soon"
            else:
                state = "current"
        if window_start and date.fromisoformat(window_start) > today:
            state = "not_yet_open"
        rows.append(
            {
                "id": record["id"],
                "type": record.get("type"),
                "title": record["title"],
                "state": state,
                "window_start": window_start,
                "window_end": window_end,
                "days_left": days_left,
                "as_of": record.get("as_of"),
                "snapshot_age_days": _age_days(record.get("as_of"), today),
            }
        )

    live = [r for r in rows if r["state"] in {"current", "closing_soon"} and r["type"] == "open_vacancy"]
    expired_vacancies = [r for r in rows if r["state"] == "expired" and r["type"] == "open_vacancy"]
    stale_snapshots = [r for r in rows if (r["snapshot_age_days"] or 0) > MAX_SNAPSHOT_AGE_DAYS]
    ages = [r["snapshot_age_days"] for r in rows if r["snapshot_age_days"] is not None]

    if not live:
        verdict = (
            "No vacancy in the corpus is currently open, so the verified-open path cannot return a lead. "
            "Either refresh the synthetic windows or report the plan as limited - do not widen the "
            "window check to make the demo look better."
        )
    elif len(live) <= 2:
        verdict = f"Only {len(live)} open vacancy record(s) remain; the demo is close to producing no lead."
    else:
        verdict = f"{len(live)} open vacancy record(s) available for the verified-lead path."

    return {
        "date": today.isoformat(),
        "rows": rows,
        "counts": {
            "records": len(rows),
            "live_vacancies": len(live),
            "expired_vacancies": len(expired_vacancies),
            "closing_soon": sum(1 for r in rows if r["state"] == "closing_soon"),
            "stale_snapshots": len(stale_snapshots),
        },
        "oldest_snapshot_days": max(ages) if ages else None,
        "expired_vacancies": [r["id"] for r in expired_vacancies],
        "verdict": verdict,
    }


def to_markdown(report: dict[str, Any]) -> str:
    """Render an audit as a small table for a smoke or evaluation record."""
    lines = [
        f"| Record | Type | Window | State | As of | Age |",
        "|---|---|---|---|---|---|",
    ]
    for row in report["rows"]:
        window = f"{row['window_start'] or '-'} to {row['window_end'] or '-'}"
        age = f"{row['snapshot_age_days']}d" if row["snapshot_age_days"] is not None else "-"
        lines.append(
            f"| {row['id']} | {row['type']} | {window} | {row['state']} | {row['as_of'] or '-'} | {age} |"
        )
    lines += ["", f"**Verdict:** {report['verdict']}"]
    return "\n".join(lines)
