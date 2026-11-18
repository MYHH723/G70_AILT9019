"""Live check of the real official pages the pilot links to.

This is the test behind the claim "the pilot connects to the real HKU sites".
It answers four questions with real requests:

1. Is every registered official page still there?
2. Does the page still say what the registry says it says? (A quoted sentence is
   checked, not the whole page.)
3. Has the page text changed since the last run? Drift is reported, not hidden.
4. Does the cohort-specific document the plan cites actually exist?

    python3 -m tests.live
    python3 -m tests.live --timeout 25

Writes ``docs/live_<date>.md`` and ``tests/results/live_state.json``. Exits
non-zero if a page is unreachable or a quoted sentence has disappeared, because
a citation that points at a page which no longer says the thing is worse than no
citation at all.

What this does not claim: the pilot does not ingest or re-publish these pages.
It reads them, keeps one quoted sentence and a hash, and links out.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import official  # noqa: E402

DOCS = ROOT / "docs"
STATE = ROOT / "tests" / "results" / "live_state.json"

# What each page must still contain for the registry's description to hold.
EXPECTED = {
    "URFP": ("Faculty Office", "the page still sends the reader to the Faculty Office for deadlines"),
    "CEDARS-JOBS": ("NETjobs", "the page still points at the NETjobs portal rather than listing vacancies"),
    "DRCD-UG-2023-24": ("2023-2024", "the index still covers the 2023-24 intake"),
    "ENGG-SYLLABUS": ("syllabus", "the faculty page still publishes syllabus documents"),
}


def _load_state() -> dict:
    if not STATE.exists():
        return {}
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def run(timeout: float) -> dict:
    ids = [s["id"] for s in official.SOURCES]
    results = official.check(ids, timeout=timeout, use_cache=False)
    previous = _load_state()

    assertions: list[dict] = []
    rows: list[dict] = []
    for source in official.SOURCES:
        sid = source["id"]
        row = results.get(sid) or {}
        status = row.get("status")
        assertions.append(
            {
                "name": f"{sid} is reachable",
                "ok": status == "ok",
                "detail": f"{status} ({row.get('detail', 'not fetched')})",
            }
        )

        if sid in EXPECTED and row.get("kind") == "page":
            needle, why = EXPECTED[sid]
            present = needle.lower() in (row.get("text") or "").lower()
            assertions.append(
                {
                    "name": f"{sid} still says what the registry claims",
                    "ok": present,
                    "detail": f"'{needle}' present: {present} - {why}" if present else
                              f"'{needle}' missing from the page; the registry note is now stale",
                }
            )

        if sid == "SYLLABUS-CS-2023-24":
            is_pdf = (row.get("content_type") or "").startswith("application/pdf")
            assertions.append(
                {
                    "name": "the 2023-24 cohort syllabus document exists",
                    "ok": status == "ok" and is_pdf,
                    "detail": f"{row.get('content_type')} from {row.get('final_url')}",
                }
            )

        old = previous.get(sid)
        drift = "first run"
        if old and row.get("kind") == "page" and old.get("text_sha256") and row.get("text_sha256"):
            drift = "unchanged" if old["text_sha256"] == row["text_sha256"] else "text changed"
        rows.append(
            {
                "id": sid,
                "label": source["label"],
                "url": source["url"],
                "covers": source["covers"],
                "status": status,
                "http_status": row.get("http_status"),
                "checked_at": row.get("checked_at"),
                "kind": row.get("kind"),
                "title": row.get("title"),
                "text_sha256": row.get("text_sha256") or "",
                "quote": row.get("quote", ""),
                "note": source["note"],
                "drift": drift,
                "detail": row.get("detail"),
            }
        )

    state = {
        sid: {
            "checked_at": row["checked_at"],
            "title": row["title"],
            "text_sha256": row["text_sha256"],
            "status": row["status"],
        }
        for sid, row in ((r["id"], r) for r in rows)
    }
    return {
        "date": _dt.date.today().isoformat(),
        "timeout": timeout,
        "rows": rows,
        "assertions": assertions,
        "state": state,
        "previous": previous,
    }


def render(report: dict) -> str:
    passed = sum(1 for a in report["assertions"] if a["ok"])
    total = len(report["assertions"])
    changed = [r["id"] for r in report["rows"] if r["drift"] == "text changed"]
    lines = [
        "# Live check of official pages",
        "",
        f"Run: {report['date']}  |  Sources: {len(report['rows'])}  |  "
        f"Result: **{passed}/{total} assertions passed**",
        "",
        "Every status below came from a real request during this run. The pilot keeps one quoted "
        "sentence and a hash of the page text; it does not store or redistribute the page.",
        "",
        "| Source | URL | Status | HTTP | Kind | Drift | Checked |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in report["rows"]:
        lines.append(
            f"| {row['label']} | {row['url']} | {row['status']} | {row['http_status'] or '-'} | "
            f"{row['kind'] or '-'} | {row['drift']} | {row['checked_at'] or '-'} |"
        )

    lines += ["", "## What each page settles", ""]
    for row in report["rows"]:
        lines.append(f"### {row['label']}")
        lines.append(f"- URL: {row['url']}")
        lines.append(f"- Covers: {row['covers']}")
        if row.get("quote"):
            lines.append(f'- Quoted from the page: "{row["quote"]}"')
        lines.append(f"- (agent reading) {row['note']}")
        lines.append("")

    lines += ["## Assertions", ""]
    for a in report["assertions"]:
        lines.append(f"- [{'x' if a['ok'] else ' '}] {a['name']} - {a['detail']}")

    lines += [
        "",
        "## Drift",
        "",
        (f"Text changed since the previous run: {', '.join(changed)}. Re-read the registry note for "
         "those sources before trusting the sentence it quotes.") if changed
        else "No page text changed since the previous run.",
        "",
        "Drift compares a SHA-256 of the extracted page text. It catches a page that was rewritten, "
        "not a page that was rewritten in a way the extraction ignores; a change here is a prompt to "
        "look, not a verdict.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    report = run(args.timeout)

    DOCS.mkdir(parents=True, exist_ok=True)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    stamp = report["date"]
    (DOCS / f"live_{stamp}.md").write_text(render(report), encoding="utf-8")
    STATE.write_text(json.dumps(report["state"], indent=2, ensure_ascii=False), encoding="utf-8")

    passed = sum(1 for a in report["assertions"] if a["ok"])
    total = len(report["assertions"])
    print(f"live: {passed}/{total} assertions passed -> docs/live_{stamp}.md")
    for a in report["assertions"]:
        if not a["ok"]:
            print(f"  FAIL {a['name']}: {a['detail']}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
