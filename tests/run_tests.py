"""Evaluation harness for the HKU Pathfinder pilot.

Runs the fixed 24-case set against the planner and writes a dated record.
The 12-case core gate (``--gate``) is the phase-one subset named in the
proposal; the full set runs only after the gate passes.

    python3 -m tests.run_tests --gate
    python3 -m tests.run_tests
    python3 -m tests.run_tests --today 2026-11-18

The run date is pinned by default so that window checks are reproducible. Pass
``--today`` (or set ``PATHFINDER_TODAY``) to evaluate as of another day; the
corpus freshness audit in the written record shows what that day does to the
opportunity windows.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.corpus import get_corpus  # noqa: E402
from src.freshness import audit, to_markdown  # noqa: E402
from src.planner import plan  # noqa: E402

# Pinned evaluation date. It matches the corpus revision so that a fresh clone
# reproduces the same result on any day.
DEFAULT_TODAY = _dt.date(2026, 11, 18)
TODAY = DEFAULT_TODAY
CASES = ROOT / "tests" / "cases.json"
OUT_DIR = ROOT / "tests" / "results"


def _all_courses(result: dict) -> list[dict]:
    return result["courses"] + result["checked_courses"] + result.get("deferred", [])


def _all_opps(result: dict) -> list[dict]:
    return result["opportunities"] + result.get("checked_opportunities", [])


def _text(result: dict) -> str:
    chunks = [result.get("summary", "")] + result.get("notices", [])
    for item in _all_courses(result):
        chunks += [r["text"] for r in item["reasons"]]
    for item in _all_opps(result):
        chunks += [r["text"] for r in item["reasons"]]
    return " ".join(chunks).lower()


# ---------------------------------------------------------------------------
# Check primitives. Each returns (passed, detail).
# ---------------------------------------------------------------------------
def check(kind: str, spec: dict, result: dict) -> tuple[bool, str]:
    courses = _all_courses(result)
    opps = _all_opps(result)
    blob = _text(result)

    if kind == "course_status":
        item = next((c for c in courses if c["code"] == spec["code"]), None)
        if not item:
            return False, f"{spec['code']} was not checked at all"
        return item["status"] == spec["equals"], f"{spec['code']}={item['status']}"

    if kind == "opportunity_status":
        item = next((o for o in opps if o["id"] == spec["id"]), None)
        if not item:
            return False, f"{spec['id']} was not retrieved"
        return item["status"] == spec["equals"], f"{spec['id']}={item['status']}"

    if kind == "at_most_one_eligible":
        eligible = [c["code"] for c in courses if c["code"] in spec["codes"] and c["status"] == "eligible"]
        return len(eligible) <= 1, f"eligible among {spec['codes']}: {eligible or 'none'}"

    if kind == "no_expired_open":
        bad = [o["id"] for o in opps if o["status"] == "open" and o["window"]["end"]
               and _dt.date.fromisoformat(o["window"]["end"]) < TODAY]
        return not bad, f"expired-but-open: {bad or 'none'}"

    if kind == "status":
        return result["status"] == spec["equals"], f"status={result['status']}"

    if kind == "status_in":
        return result["status"] in spec["values"], f"status={result['status']}"

    if kind == "min_courses":
        return len(result["courses"]) >= spec["n"], f"{len(result['courses'])} recommended"

    if kind == "max_courses":
        return len(result["courses"]) <= spec["n"], f"{len(result['courses'])} recommended"

    if kind == "min_opportunities":
        return len(result["opportunities"]) >= spec["n"], f"{len(result['opportunities'])} verified open"

    if kind == "deferred_at_least":
        return len(result.get("deferred", [])) >= spec["n"], f"{len(result.get('deferred', []))} deferred"

    if kind == "all_courses_cited":
        missing = [c["code"] for c in result["courses"] if not c["citations"] or not c["citations"][0].get("url")]
        return not missing, f"uncited: {missing or 'none'}"

    if kind == "all_opportunities_dated":
        missing = [o["id"] for o in result["opportunities"] if not o.get("as_of") or not o["citations"][0].get("url")]
        return not missing, f"undated/uncited: {missing or 'none'}"

    if kind == "labelled_interpretation":
        has = any(r["label"] == "agent reading" for c in courses for r in c["reasons"])
        return has, "agent-reading label present" if has else "no agent-reading label"

    if kind == "next_steps_at_least":
        return len(result["next_steps"]) >= spec["n"], f"{len(result['next_steps'])} steps"

    if kind == "summary_contains":
        return spec["text"].lower() in result["summary"].lower(), f"summary has '{spec['text']}': {spec['text'].lower() in result['summary'].lower()}"

    if kind == "summary_not_contains":
        ok = spec["text"].lower() not in blob
        return ok, f"'{spec['text']}' absent from all output text: {ok}"

    if kind == "notice_contains":
        joined = " ".join(result["notices"]).lower()
        return spec["text"].lower() in joined, f"notices mention '{spec['text']}': {spec['text'].lower() in joined}"

    if kind == "refused_contains":
        actions = " ".join(r["action"] for r in result["refused_actions"]).lower()
        return spec["text"].lower() in actions, f"refused actions: {[r['action'] for r in result['refused_actions']]}"

    if kind == "reason_contains":
        item = next((c for c in courses if c["code"] == spec.get("code")), None) or \
               next((o for o in opps if o["id"] == spec.get("id")), None)
        if not item:
            return False, "item not found"
        joined = " ".join(r["text"] for r in item["reasons"]).lower()
        return spec["text"].lower() in joined, f"reason mentions '{spec['text']}'"

    if kind == "opportunities_match_type":
        bad = [o["id"] for o in result["opportunities"]
               if spec["contains"].lower() not in (o["title"] + " " + " ".join(o["topics"])).lower()]
        return not bad, f"non-matching leads: {bad or 'none'}"

    if kind == "no_guarantee_language":
        forbidden = ["you are guaranteed", "guaranteed admission", "guaranteed offer", "will be admitted"]
        hits = [f for f in forbidden if f in blob]
        return not hits, f"guarantee phrasing: {hits or 'none'}"

    raise ValueError(f"unknown check kind: {kind}")


def run_case(case: dict, corpus) -> dict:
    result = plan(case["profile"], case["query"], corpus, today=TODAY, llm=False)
    checks = []
    for spec in case["checks"]:
        spec = dict(spec)
        kind = spec.pop("type")
        passed, detail = check(kind, spec, result)
        checks.append({"check": kind, "spec": spec, "passed": passed, "detail": detail})
    return {
        "id": case["id"],
        "category": case["category"],
        "core": case.get("core", False),
        "query": case["query"],
        "status": result["status"],
        "courses": [(c["code"], c["status"]) for c in result["courses"]],
        "opportunities": [(o["id"], o["status"]) for o in result["opportunities"]],
        "checks": checks,
        "passed": all(c["passed"] for c in checks),
    }


def main() -> int:
    global TODAY
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", action="store_true", help="run the 12-case core gate only")
    parser.add_argument("--today", default=None, help="evaluate as of this date (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.today:
        TODAY = _dt.date.fromisoformat(args.today)
    elif os.environ.get("PATHFINDER_TODAY"):
        TODAY = _dt.date.fromisoformat(os.environ["PATHFINDER_TODAY"])

    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    if args.gate:
        cases = [c for c in cases if c.get("core")]

    corpus = get_corpus()
    records = [run_case(case, corpus) for case in cases]
    passed = sum(1 for r in records if r["passed"])
    total = len(records)
    fresh = audit(corpus, TODAY)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    label = "core_gate" if args.gate else "full"
    stamp = TODAY.isoformat()
    (OUT_DIR / f"{label}_{stamp}.json").write_text(
        json.dumps({"run": label, "date": stamp, "passed": passed, "total": total,
                    "freshness": fresh, "records": records},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    lines = [
        f"# Pathfinder evaluation - {label.replace('_', ' ')}",
        "",
        f"Run date: {stamp}  |  Corpus: {corpus.stats()}  |  Result: **{passed}/{total} cases passed**",
        "",
        "| Case | Category | Query (truncated) | Result | Failing check |",
        "|---|---|---|---|---|",
    ]
    for r in records:
        failing = next((c for c in r["checks"] if not c["passed"]), None)
        lines.append(
            f"| {r['id']} | {r['category']} | {r['query'][:58]} | {'PASS' if r['passed'] else 'FAIL'} | "
            f"{failing['check'] + ': ' + failing['detail'] if failing else '-'} |"
        )
    lines += ["", "## Check detail", ""]
    for r in records:
        lines.append(f"### {r['id']} - {'PASS' if r['passed'] else 'FAIL'}")
        lines.append(f"- Query: {r['query']}")
        lines.append(f"- Response status: {r['status']}; recommended courses {r['courses'] or 'none'}; open leads {r['opportunities'] or 'none'}")
        for c in r["checks"]:
            lines.append(f"- [{'x' if c['passed'] else ' '}] {c['check']}: {c['detail']}")
        lines.append("")

    lines += [
        "## Corpus freshness on the run date",
        "",
        f"Opportunity records: {fresh['counts']['records']}, currently open vacancies: "
        f"{fresh['counts']['live_vacancies']}, expired vacancies: {fresh['counts']['expired_vacancies']}, "
        f"snapshots older than {120} days: {fresh['counts']['stale_snapshots']}.",
        "",
        to_markdown(fresh),
        "",
    ]
    (OUT_DIR / f"{label}_{stamp}.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"{label}: {passed}/{total} cases passed")
    print(f"freshness: {fresh['counts']['live_vacancies']} open vacancy record(s) - {fresh['verdict']}")
    for r in records:
        if not r["passed"]:
            failing = [c for c in r["checks"] if not c["passed"]]
            print(f"  FAIL {r['id']}: " + "; ".join(f"{c['check']} -> {c['detail']}" for c in failing))
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
