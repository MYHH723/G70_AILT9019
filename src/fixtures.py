"""Serve the fixture records behind their citation links.

The pilot's citations point at `https://fixtures.pathfinder.local/...`, a reserved
host that deliberately does not resolve. That is honest in the data and terrible
in the interface: a student who clicks a source link gets the browser's
`DNS_PROBE_FINISHED_NXDOMAIN` page, which looks like the tool is broken rather
than like the corpus is synthetic.

This module makes the citation clickable without pretending the record is an
official page. Each link resolves to a page served by the app itself that shows
the exact record the plan was built from, a banner saying it is a synthetic
fixture, and - where the record stands in for a real page - a link to the
official entry point that a live build would read instead.

Nothing here rewrites the recorded URL. The citation keeps its original
identifier; `local_url` is added alongside it for the interface and the export.
"""

from __future__ import annotations

import html
import urllib.parse
from typing import Any

FIXTURE_HOST = "fixtures.pathfinder.local"

# Where a live build would read the real thing. Shown on the fixture page so the
# gap between "this record" and "the official page" is visible rather than implied.
OFFICIAL_ENTRY = {
    "course": ("HKU Degree Regulations and Course Descriptions", "https://www4.hku.hk/pubunit/drcd/"),
    "regulations": ("HKU Degree Regulations and Course Descriptions", "https://www4.hku.hk/pubunit/drcd/"),
    "opportunities": ("CEDARS careers - jobs and internships", "https://www.cedars.hku.hk/careers/jobs"),
}

KIND_LABEL = {
    "course": "Course description",
    "regulations": "Programme regulation",
    "opportunities": "Opportunity record",
}


def parse(url: str) -> tuple[str, str] | None:
    """Split a fixture URL into (kind, key), or return None for anything else."""
    if not url:
        return None
    parts = urllib.parse.urlsplit(url)
    if parts.hostname != FIXTURE_HOST:
        return None
    segments = [s for s in parts.path.split("/") if s]
    if len(segments) != 2:
        return None
    kind, key = segments
    if kind not in KIND_LABEL:
        return None
    return kind, key


def local_route(url: str) -> str | None:
    """The in-app path that shows this record, or None for a non-fixture URL."""
    parsed = parse(url)
    if not parsed:
        return None
    kind, key = parsed
    return f"/fixtures/{kind}/{urllib.parse.quote(key)}"


def annotate(plan: dict[str, Any]) -> dict[str, Any]:
    """Add ``local_url`` to every citation that points at a fixture record.

    Mutates and returns the plan for convenience; the plan is a fresh dict per
    request, so there is no shared state to corrupt.
    """
    groups = ("courses", "checked_courses", "deferred", "opportunities", "checked_opportunities")
    for group in groups:
        for item in plan.get(group) or []:
            for cite in item.get("citations") or []:
                route = local_route(cite.get("url", ""))
                if route:
                    cite["local_url"] = route
    return plan


def _row(label: str, value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value)
    return f"<tr><th>{html.escape(label)}</th><td>{html.escape(str(value))}</td></tr>"


def _record(kind: str, key: str, corpus) -> dict[str, Any] | None:
    if kind == "course":
        return corpus.course(key)
    if kind == "regulations":
        return corpus.regulation(key)
    if kind == "opportunities":
        return next((r for r in corpus.opportunities if r["id"] == key), None)
    return None


def _fields(kind: str, record: dict[str, Any]) -> str:
    if kind == "course":
        rows = [
            _row("Course code", record.get("code")),
            _row("Title", record.get("title")),
            _row("Credits", record.get("credits")),
            _row("Offered in", record.get("offered")),
            _row("Prerequisites", record.get("prerequisites") or "none listed"),
            _row("Mutually exclusive with", record.get("exclusions")),
            _row("Minimum year", record.get("min_year")),
            _row("Workload", record.get("load")),
            _row("Skills", record.get("skills")),
            _row("Summary", record.get("summary")),
            _row("Document id", record.get("doc_id")),
            _row("Snapshot date", record.get("snapshot_date")),
        ]
    elif kind == "regulations":
        rows = [
            _row("Regulation id", record.get("id")),
            _row("Title", record.get("title")),
            _row("Section", record.get("section")),
            _row("Applies to", record.get("applies_to")),
            _row("Cohort", record.get("cohort")),
            _row("Rule encoded", record.get("rule")),
            _row("Text", record.get("text")),
            _row("Snapshot date", record.get("snapshot_date")),
        ]
    else:
        rows = [
            _row("Record id", record.get("id")),
            _row("Title", record.get("title")),
            _row("Host", record.get("host")),
            _row("Record type", record.get("type")),
            _row("Application window", f"{record.get('window_start') or 'not stated'} to {record.get('window_end') or 'not stated'}"),
            _row("Eligibility", record.get("eligibility_text")),
            _row("Minimum year", record.get("min_year")),
            _row("Summary", record.get("summary")),
            _row("Recorded fetch status", record.get("fetch_status")),
            _row("As of", record.get("as_of")),
        ]
    return "".join(r for r in rows if r)


def render(kind: str, key: str, corpus) -> str | None:
    """A small standalone page for one fixture record, or None if unknown."""
    record = _record(kind, key, corpus)
    if not record:
        return None

    live_url = record.get("live_probe_url")
    if live_url:
        live_block = (
            '<p class="live">This record stands in for a real page. A live build would read '
            f'<a href="{html.escape(live_url)}" target="_blank" rel="noopener">{html.escape(live_url)}</a> '
            "instead of this record.</p>"
        )
    else:
        entry_label, entry_url = OFFICIAL_ENTRY.get(kind, ("the official source", ""))
        live_block = (
            '<p class="live">No official page for this record has been ingested: reuse permission is '
            f'unconfirmed. A live build would read {html.escape(entry_label)} at '
            f'<a href="{html.escape(entry_url)}" target="_blank" rel="noopener">{html.escape(entry_url)}</a>.</p>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Fixture record - {html.escape(key)}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ margin: 0; padding: 36px 24px; background: #f6f7f9; color: #1b2330;
         font: 14px/1.65 -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif; }}
  main {{ max-width: 760px; margin: 0 auto; background: #fff; border: 1px solid #e2e6ec;
          border-radius: 12px; overflow: hidden; }}
  header {{ padding: 18px 24px; background: #fff8e6; border-bottom: 1px solid #f0dfae; }}
  header strong {{ display: block; font-size: 15px; color: #7a5a00; }}
  header span {{ color: #8a6d1f; font-size: 13px; }}
  .body {{ padding: 20px 24px 26px; }}
  h1 {{ font-size: 18px; margin: 0 0 4px; }}
  .kind {{ color: #6b7684; font-size: 13px; margin-bottom: 18px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 18px; }}
  th, td {{ text-align: left; vertical-align: top; padding: 8px 0; border-bottom: 1px solid #eef1f5;
            font-size: 13.5px; }}
  th {{ width: 180px; color: #6b7684; font-weight: 500; }}
  .live {{ background: #f2f6ff; border: 1px solid #d8e3ff; border-radius: 8px; padding: 12px 14px;
           font-size: 13px; color: #2a3b5c; }}
  a {{ color: #1f5fd0; word-break: break-all; }}
  footer {{ padding: 0 24px 26px; color: #6b7684; font-size: 12px; }}
</style>
</head>
<body>
<main>
  <header>
    <strong>Synthetic fixture record - not an official HKU page</strong>
    <span>The pilot corpus is written by the team. Do not cite this as a university document.</span>
  </header>
  <div class="body">
    <h1>{html.escape(str(record.get("title") or key))}</h1>
    <div class="kind">{html.escape(KIND_LABEL[kind])} &middot; {html.escape(key)}</div>
    <table>{_fields(kind, record)}</table>
    {live_block}
  </div>
  <footer>Recorded identifier: {html.escape(str(record.get("source_url") or ""))}</footer>
</main>
</body>
</html>
"""
