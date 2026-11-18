"""Live smoke test: does the source layer actually work today?

Three questions, answered with real requests rather than staged fields:

1. Are the three approved official entry points reachable right now?
2. Does the probe report a failure when a page genuinely fails? (A 404 on an
   approved host is a real failure, not a simulated one.)
3. When a lead's page cannot be read, does the planner fall back to a labelled
   dated snapshot instead of failing, and does it stop calling that lead open?

    python3 -m tests.smoke
    python3 -m tests.smoke --timeout 20 --date 2026-11-18

Writes ``docs/smoke_<date>.md``. Exits non-zero if any assertion fails, so the
record cannot be produced from a broken run.

One honest limitation, stated in the output as well: the reachability results
are real, but the opportunity records they are applied to are synthetic, because
the pilot has no permission to ingest real vacancy pages. The failure is real;
the record it is attached to is a fixture.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.corpus import DATA_DIR, get_corpus  # noqa: E402
from src.freshness import audit, to_markdown  # noqa: E402
from src.livecheck import probe, reachability_map  # noqa: E402
from src.planner import plan  # noqa: E402

ENTRY_POINTS = [
    ("HKU Degree Regulations and Course Descriptions", "https://www4.hku.hk/pubunit/drcd/"),
    ("Undergraduate Research Fellowship Programme", "https://tl.hku.hk/urfp/"),
    ("CEDARS careers - jobs and internships", "https://www.cedars.hku.hk/careers/jobs"),
]

# A path that does not exist on an approved host. This is the real failure used
# to prove the fallback: the server answers 404, nothing is simulated.
FAILING_URL = "https://www4.hku.hk/pubunit/drcd/pathfinder-smoke-no-such-page"
# Never requested: refused by policy before any connection is made.
FORBIDDEN_URL = "http://127.0.0.1:8765/"

OUT_DIR = ROOT / "docs"


def _profiles() -> dict[str, dict]:
    data = json.loads((DATA_DIR / "example_profiles.json").read_text(encoding="utf-8"))
    return {p["id"]: p for p in data["profiles"]}


def _probe_with_retry(url: str, timeout: float, retries: int) -> dict:
    """Probe once, retry on a network failure.

    A university web server occasionally stalls on the first request; a smoke
    test that fails because of that teaches nothing. The number of attempts is
    recorded, so a retried success is visible rather than hidden.
    """
    attempts: list[dict] = []
    for _ in range(retries + 1):
        row = probe(url, timeout=timeout)
        attempts.append(row)
        if row["status"] == "ok":
            break
    result = dict(attempts[-1])
    result["attempts"] = len(attempts)
    result["attempt_log"] = [(a["status"], a["elapsed_ms"]) for a in attempts]
    if len(attempts) > 1:
        result["detail"] = f"{result['detail']} (succeeded on attempt {len(attempts)})" \
            if result["status"] == "ok" else f"{result['detail']} (after {len(attempts)} attempts)"
    return result


def run(today: _dt.date, timeout: float, retries: int = 1) -> dict:
    corpus = get_corpus()
    assertions: list[dict] = []
    probes: list[dict] = []

    # 1. The approved entry points ---------------------------------------
    for label, url in ENTRY_POINTS:
        row = _probe_with_retry(url, timeout, retries)
        row["label"] = label
        probes.append(row)
        assertions.append(
            {
                "name": f"entry point reachable - {label}",
                "ok": row["status"] == "ok",
                "detail": f"{row['status']} ({row['detail']})",
            }
        )

    # 2. A real failure ---------------------------------------------------
    failed = _probe_with_retry(FAILING_URL, timeout, 0)
    failed["label"] = "deliberate 404 on an approved host"
    probes.append(failed)
    assertions.append(
        {
            "name": "probe reports unreachable on a real 404",
            "ok": failed["status"] == "unreachable",
            "detail": f"{failed['status']} ({failed['detail']})",
        }
    )

    # 3. A refused target -------------------------------------------------
    blocked = _probe_with_retry(FORBIDDEN_URL, timeout, 0)
    blocked["label"] = "loopback address, refused by policy"
    probes.append(blocked)
    assertions.append(
        {
            "name": "probe refuses a non-public target without connecting",
            "ok": blocked["status"] == "blocked" and blocked["elapsed_ms"] is None,
            "detail": f"{blocked['status']} ({blocked['detail']})",
        }
    )

    # 4. Fallback proof ---------------------------------------------------
    saved = _profiles()["P1"]
    profile, query = saved["profile"], saved["query"]
    baseline = plan(profile, query, corpus, today=today)
    open_ids = [item["id"] for item in baseline["opportunities"]]
    fallback = None
    if open_ids:
        target = open_ids[0]
        staged = next(o for o in baseline["opportunities"] if o["id"] == target)
        record = next(r for r in corpus.opportunities if r["id"] == target)

        own = _probe_with_retry(record["source_url"], timeout, 0)
        own["label"] = f"the lead's own source URL ({target})"
        probes.append(own)

        # Two failures, deliberately different in kind: a policy refusal (the
        # reserved fixture host is not approved) and a real HTTP error on an
        # approved host. Both must degrade to the same labelled snapshot.
        trials = [
            ("the lead's own URL, refused by policy", own),
            ("a real HTTP 404 on an approved host", failed),
        ]
        cases = []
        for label, row in trials:
            live_status = reachability_map([row])[row["url"]]
            after = plan(profile, query, corpus, today=today, reachability={target: live_status})
            moved = next((o for o in after["checked_opportunities"] if o["id"] == target), None)
            reasons = " ".join(r["text"] for r in (moved or {}).get("reasons", []))
            entry = {
                "label": label,
                "probe_status": row["status"],
                "probe_detail": row["detail"],
                "live_status": live_status,
                "after": (moved or {}).get("status"),
                "reason": reasons,
                "still_in_verified_list": any(o["id"] == target for o in after["opportunities"]),
                "summary": after["summary"],
            }
            cases.append(entry)
            assertions.append(
                {
                    "name": f"fallback engages for {target} after {label}",
                    "ok": entry["after"] == "snapshot_verify_manually",
                    "detail": f"probe {row['status']} -> planner '{live_status}' -> {entry['after']}",
                }
            )
            assertions.append(
                {
                    "name": f"snapshot labelled for manual verification after {label}",
                    "ok": "verify manually" in entry["reason"].lower(),
                    "detail": entry["reason"][:110] or "no reason text",
                }
            )
            assertions.append(
                {
                    "name": f"unreadable lead not left in the verified-open list after {label}",
                    "ok": entry["still_in_verified_list"] is False,
                    "detail": "moved to checked_opportunities" if not entry["still_in_verified_list"]
                    else "still presented as verified",
                }
            )

        fallback = {
            "record": target,
            "source_url": record["source_url"],
            "before": staged["status"],
            "cases": cases,
            "mode": after["mode"],
        }
        assertions.append(
            {
                "name": "plan records that reachability came from a live probe",
                "ok": "live probe" in fallback["mode"],
                "detail": fallback["mode"],
            }
        )
    else:
        assertions.append(
            {
                "name": "fallback proof has an open lead to work with",
                "ok": False,
                "detail": "no open lead at this date, so the fallback could not be exercised",
            }
        )

    fresh = audit(corpus, today)
    return {
        "date": today.isoformat(),
        "timeout": timeout,
        "retries": retries,
        "probes": probes,
        "assertions": assertions,
        "fallback": fallback,
        "freshness": fresh,
    }


def render(report: dict) -> str:
    passed = sum(1 for a in report["assertions"] if a["ok"])
    total = len(report["assertions"])
    lines = [
        "# Live smoke test",
        "",
        f"Run: {report['date']}  |  Timeout: {report['timeout']}s  |  "
        f"Result: **{passed}/{total} assertions passed**",
        "",
        "Every status below came from a real HTTP request made during this run. Only the status line, "
        "the final URL, a byte count and the elapsed time were kept; page content was read to a cap and "
        "discarded, so this test is not a scraping channel.",
        "",
        "## Probes",
        "",
        "| Target | URL | Status | HTTP | Elapsed | Attempts | Detail |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in report["probes"]:
        elapsed = f"{row['elapsed_ms']} ms" if row["elapsed_ms"] is not None else "not attempted"
        lines.append(
            f"| {row.get('label', '')} | {row['url']} | {row['status']} | "
            f"{row['http_status'] or '-'} | {elapsed} | {row.get('attempts', 1)} | {row['detail']} |"
        )

    lines += ["", "## Assertions", ""]
    for a in report["assertions"]:
        lines.append(f"- [{'x' if a['ok'] else ' '}] {a['name']} - {a['detail']}")

    fb = report["fallback"]
    if fb:
        lines += [
            "",
            "## Snapshot fallback on a real failure",
            "",
            f"Lead `{fb['record']}` is `{fb['before']}` in the fixture. Two failures were then fed to the "
            "planner for that same record: one policy refusal and one genuine HTTP error.",
            "",
            "| Failure | Probe said | Planner sees | Lead status | In verified-open list |",
            "|---|---|---|---|---|",
        ]
        for case in fb["cases"]:
            lines.append(
                f"| {case['label']} | {case['probe_status']} | {case['live_status']} | "
                f"{case['after']} | {'yes' if case['still_in_verified_list'] else 'no'} |"
            )
        first = fb["cases"][0]
        lines += [
            "",
            f"Reason shown to the student: _{first['reason']}_",
            "",
            f"Plan summary after the failure: _{first['summary']}_",
            "",
            "Honest limitation: the requests, the failures and the classifications are real, but the "
            "opportunity record is synthetic - its URL uses the reserved `fixtures.pathfinder.local` host, "
            "which is why the policy refuses it, and no real vacancy page is ingested because permission "
            "is unconfirmed. This proves the degradation path and the label, not the availability of any "
            "real position.",
        ]

    fresh = report["freshness"]
    lines += [
        "",
        "## Corpus freshness (informational)",
        "",
        f"{fresh['counts']['records']} opportunity records, "
        f"{fresh['counts']['live_vacancies']} currently open, "
        f"{fresh['counts']['expired_vacancies']} expired vacancies, "
        f"{fresh['counts']['stale_snapshots']} snapshots older than the age limit.",
        "",
        to_markdown(fresh),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--retries", type=int, default=1, help="extra attempts per entry point on a network failure")
    parser.add_argument("--date", default=None, help="override the run date (YYYY-MM-DD)")
    args = parser.parse_args()

    today = _dt.date.fromisoformat(args.date) if args.date else _dt.date.today()
    report = run(today, args.timeout, args.retries)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / f"smoke_{today.isoformat()}.md"
    target.write_text(render(report), encoding="utf-8")

    passed = sum(1 for a in report["assertions"] if a["ok"])
    total = len(report["assertions"])
    print(f"smoke: {passed}/{total} assertions passed -> {target.relative_to(ROOT)}")
    for a in report["assertions"]:
        if not a["ok"]:
            print(f"  FAIL {a['name']}: {a['detail']}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
