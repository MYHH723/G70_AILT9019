"""Retrieval-vs-no-retrieval baseline on the six end-to-end planning cases.

The proposal asks for one comparison: the same six planning tasks answered with
and without retrieval, scored with the same checklist. This harness runs it.

What "without retrieval" means here, stated plainly because it is easy to
overclaim: the pilot has no language model, so the baseline is not "the same
LLM with the search box switched off". It is the same deterministic planner
with the corpus lookup removed - it can read the question and the declared
profile, and nothing else. That is a *harder* test than a no-retrieval LLM,
which would at least carry memorised facts about HKU courses. If the ablation
still loses on every evidence check, the gain from retrieval is a floor, not an
estimate.

    python3 -m tests.baseline
    python3 -m tests.baseline --today 2026-11-18
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.corpus import get_corpus  # noqa: E402
from src.planner import plan  # noqa: E402
from tests import run_tests as rt  # noqa: E402

CASES = ROOT / "tests" / "cases.json"
OUT_DIR = ROOT / "tests" / "results"
PLANNING_CATEGORY = "end-to-end planning"


def _measure(result: dict, case: dict) -> dict:
    courses = result["courses"] + result.get("checked_courses", [])
    leads = result["opportunities"] + result.get("checked_opportunities", [])
    recommended = result["courses"] + result["opportunities"]
    cited = [i for i in recommended if (i.get("citations") or [{}])[0].get("url")]
    checks = []
    for spec in case["checks"]:
        spec = dict(spec)
        kind = spec.pop("type")
        passed, detail = rt.check(kind, spec, result)
        checks.append({"check": kind, "passed": passed, "detail": detail})
    passed = sum(1 for c in checks if c["passed"])
    return {
        "status": result["status"],
        "mode": result["mode"],
        "recommended": len(recommended),
        "cited": len(cited),
        "courses_checked": len(courses),
        "leads_checked": len(leads),
        "rules_applied": len(result.get("trace", {}).get("rules_applied", [])),
        "windows_checked": sum(1 for o in leads if (o.get("window") or {}).get("end")),
        "next_steps": len(result["next_steps"]),
        "checks_passed": passed,
        "checks_total": len(checks),
        "checks": checks,
        # A pass with nothing to check is not evidence of anything.
        "vacuous_passes": passed if len(recommended) == 0 else 0,
        "summary": result["summary"],
    }


def run(today: _dt.date) -> dict:
    rt.TODAY = today
    corpus = get_corpus()
    cases = [c for c in json.loads(CASES.read_text(encoding="utf-8"))["cases"]
             if c["category"] == PLANNING_CATEGORY]
    rows = []
    for case in cases:
        with_retrieval = plan(case["profile"], case["query"], corpus, today=today)
        without = plan(case["profile"], case["query"], corpus, today=today, retrieve=False)
        rows.append(
            {
                "id": case["id"],
                "query": case["query"],
                "with": _measure(with_retrieval, case),
                "without": _measure(without, case),
            }
        )
    return {"date": today.isoformat(), "cases": rows, "corpus": corpus.stats()}


def _totals(rows: list[dict], arm: str) -> dict:
    return {
        "cases_passed": sum(1 for r in rows if r[arm]["checks_passed"] == r[arm]["checks_total"]),
        "checks_passed": sum(r[arm]["checks_passed"] for r in rows),
        "checks_total": sum(r[arm]["checks_total"] for r in rows),
        "recommended": sum(r[arm]["recommended"] for r in rows),
        "cited": sum(r[arm]["cited"] for r in rows),
        "rules": sum(r[arm]["rules_applied"] for r in rows),
        "windows": sum(r[arm]["windows_checked"] for r in rows),
        "vacuous": sum(r[arm]["vacuous_passes"] for r in rows),
    }


def render(report: dict) -> str:
    rows = report["cases"]
    on, off = _totals(rows, "with"), _totals(rows, "without")
    n = len(rows)
    lines = [
        "# Baseline comparison: retrieval on vs retrieval off",
        "",
        f"Run date: {report['date']}  |  Corpus: {report['corpus']}  |  "
        f"Cases: {n} end-to-end planning requests (C1-C6)  |  Same checklist as the 24-case suite",
        "",
        "## Per case",
        "",
        "| Case | Status (on / off) | Recommended (on / off) | Cited (on / off) | "
        "Constraint rules applied (on / off) | Checks (on / off) |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        a, b = row["with"], row["without"]
        lines.append(
            f"| {row['id']} | {a['status']} / {b['status']} | {a['recommended']} / {b['recommended']} | "
            f"{a['cited']} / {b['cited']} | {a['rules_applied']} / {b['rules_applied']} | "
            f"{a['checks_passed']}/{a['checks_total']} / {b['checks_passed']}/{b['checks_total']} |"
        )
    lines += [
        f"| **Total** | | **{on['recommended']} / {off['recommended']}** | **{on['cited']} / {off['cited']}** | "
        f"**{on['rules']} / {off['rules']}** | **{on['checks_passed']}/{on['checks_total']} / "
        f"{off['checks_passed']}/{off['checks_total']}** |",
        "",
        "## What the two arms actually produce",
        "",
        f"- **With retrieval:** {on['cases_passed']}/{n} cases pass every check "
        f"({on['checks_passed']}/{on['checks_total']} individual checks). "
        f"{on['recommended']} recommendations were made, {on['cited']} of them carry a source link; "
        f"{on['rules']} documented constraint rules were applied; {on['windows']} application windows were read.",
        f"- **Without retrieval:** {off['cases_passed']}/{n} cases pass "
        f"({off['checks_passed']}/{off['checks_total']} checks, of which {off['vacuous']} are vacuous - "
        f"they pass only because there is nothing to inspect). {off['recommended']} recommendations, "
        f"{off['cited']} citations, {off['rules']} constraint rules, {off['windows']} windows.",
        "",
        "A concrete example of the difference, verbatim from the run:",
        "",
    ]
    sample = rows[0]
    lines += [
        f"> **Case {sample['id']}:** _{sample['query']}_",
        "",
        f"> With retrieval - {sample['with']['summary']}",
        "",
        f"> Without retrieval - {sample['without']['summary']}",
        "",
        "## Reading the result",
        "",
        "The baseline is fluent, plausible and useless in a specific way: it names no course code, cites "
        "nothing, checks no prerequisite and reads no application window, because it has no source to do "
        "any of that from. A student cannot verify a single sentence of it. That is exactly the failure "
        "mode the proposal set out to remove, and it is the reason the retrieval layer is not optional.",
        "",
        "The honest caveat: this compares retrieval against *no evidence at all*, not against a strong "
        "retrieval baseline. It shows that the evidence layer is load-bearing; it does not show that this "
        "particular BM25 index is the best way to retrieve, and it does not measure answer fluency, which "
        "is the axis where a language model would win.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--today", default=rt.DEFAULT_TODAY.isoformat())
    args = parser.parse_args()
    today = _dt.date.fromisoformat(args.today)
    report = run(today)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = today.isoformat()
    (OUT_DIR / f"baseline_{stamp}.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (OUT_DIR / f"baseline_{stamp}.md").write_text(render(report), encoding="utf-8")

    rows = report["cases"]
    on, off = _totals(rows, "with"), _totals(rows, "without")
    print(f"baseline: retrieval {on['cases_passed']}/{len(rows)} cases, "
          f"no retrieval {off['cases_passed']}/{len(rows)} cases")
    print(f"  citations {on['cited']} vs {off['cited']} | "
          f"constraint rules {on['rules']} vs {off['rules']} | "
          f"windows {on['windows']} vs {off['windows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
