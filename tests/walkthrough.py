"""Five-volunteer walkthrough recorder.

The proposal's usability target is specific: five volunteers try a synthetic
task, and at least four reach a cited result without editing code. That is a
claim about people, so it cannot be produced by a script - what a script can do
is make the session take three minutes and leave a record that is hard to
misread.

    python3 -m tests.walkthrough --start --task A
    python3 -m tests.walkthrough --finish 4f2a9c --cited yes --edited no --seconds 187
    python3 -m tests.walkthrough --report

Sessions are anonymous by construction: a random id, a task letter, timings and
two yes/no answers. No name, no student number, no transcript. If you add a
note, do not put a name in it.

The report is written to ``docs/walkthrough_<date>.md``. Until five sessions
exist it reports INCOMPLETE rather than a partial pass, because "3 of 3
succeeded" is not the same claim as "4 of 5 succeeded".
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import secrets
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "tests" / "results" / "walkthrough_sessions.jsonl"
DOCS = ROOT / "docs"

REQUIRED_SESSIONS = 5
REQUIRED_SUCCESSES = 4

TASKS = {
    "A": "Build a plan with the default profile. Open one source link and confirm it matches the plan.",
    "B": "Load preset P3, build a plan, and say in one sentence why a course was blocked or deferred.",
    "C": "Ask whether the computer vision internship is still open, and say what the answer means.",
    "D": "Try a question the pilot cannot answer (another programme) and check the refusal is clear.",
}


def _load() -> list[dict]:
    if not STATE.exists():
        return []
    return [json.loads(line) for line in STATE.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append(row: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _sessions() -> list[dict]:
    started: dict[str, dict] = {}
    finished: dict[str, dict] = {}
    for row in _load():
        if row["event"] == "start":
            started[row["session"]] = row
        else:
            finished[row["session"]] = row
    joined = []
    for sid, start in started.items():
        end = finished.get(sid, {})
        joined.append({**start, **{k: v for k, v in end.items() if k not in {"event", "session"}}})
    return sorted(joined, key=lambda r: r["started_at"])


def cmd_start(task: str) -> int:
    if task not in TASKS:
        print(f"unknown task '{task}'; choose from {', '.join(TASKS)}")
        return 2
    session = secrets.token_hex(3)
    _append(
        {
            "event": "start",
            "session": session,
            "task": task,
            "started_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        }
    )
    # The launcher differs by platform: run.sh is a shell script, so Windows
    # needs the module form. Printing the wrong one sends the observer to a
    # command that fails, which is exactly what this tool is meant to prevent.
    windows = os.name == "nt"
    launcher = "python -m src.server" if windows else "./run.sh"
    py = "python" if windows else "python3"
    print(f"session {session}")
    print(f"task {task}: {TASKS[task]}")
    print(f"start the app:  {launcher}   then open http://127.0.0.1:8765")
    print(f"when done:      {py} -m tests.walkthrough --finish {session} --cited yes --edited no --seconds 180")
    return 0


def cmd_finish(session: str, cited: str, edited: str, seconds: int | None, notes: str) -> int:
    if not any(r["session"] == session and r["event"] == "start" for r in _load()):
        print(f"no session '{session}'; run --start first")
        return 2
    started = next(r for r in _load() if r["session"] == session and r["event"] == "start")
    if seconds is None:
        began = _dt.datetime.fromisoformat(started["started_at"])
        seconds = int((_dt.datetime.now().astimezone() - began).total_seconds())
    _append(
        {
            "event": "finish",
            "session": session,
            "task": started["task"],
            "cited": cited == "yes",
            "edited_code": edited == "yes",
            "seconds": seconds,
            "notes": notes[:240],
            "finished_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        }
    )
    print(f"recorded session {session}: cited={cited} edited_code={edited} seconds={seconds}")
    remaining = REQUIRED_SESSIONS - len([s for s in _sessions() if "cited" in s])
    if remaining > 0:
        print(f"{remaining} more session(s) needed before the 4-of-5 target can be judged")
    return 0


def build_report(today: _dt.date) -> tuple[str, bool]:
    sessions = [s for s in _sessions() if "cited" in s]
    complete = [s for s in sessions if s.get("cited") and not s.get("edited_code")]
    seconds = [s["seconds"] for s in sessions if s.get("seconds")]
    median = int(statistics.median(seconds)) if seconds else None
    met = len(sessions) >= REQUIRED_SESSIONS and len(complete) >= REQUIRED_SUCCESSES

    if len(sessions) < REQUIRED_SESSIONS:
        verdict = (
            f"INCOMPLETE - {len(sessions)} of {REQUIRED_SESSIONS} sessions recorded. "
            f"{REQUIRED_SESSIONS - len(sessions)} more are needed; the 4-of-5 target cannot be claimed yet."
        )
    elif met:
        verdict = (
            f"MET - {len(complete)} of {len(sessions)} volunteers reached a cited result without editing code, "
            f"against a target of {REQUIRED_SUCCESSES} of {REQUIRED_SESSIONS}."
        )
    else:
        verdict = (
            f"NOT MET - {len(complete)} of {len(sessions)} volunteers reached a cited result without editing "
            f"code, against a target of {REQUIRED_SUCCESSES} of {REQUIRED_SESSIONS}. Treat this as a usability "
            "defect to fix, not as a number to explain away."
        )

    lines = [
        "# Five-volunteer walkthrough",
        "",
        f"Report date: {today.isoformat()}  |  Sessions: {len(sessions)}/{REQUIRED_SESSIONS}  |  "
        f"Median completion time: {median if median is not None else 'n/a'} s",
        "",
        f"**Verdict: {verdict}**",
        "",
        "## Sessions",
        "",
        "| Session | Task | Started | Seconds | Cited result | Edited code | Note |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in sessions:
        lines.append(
            f"| {s['session']} | {s['task']} | {s['started_at']} | {s.get('seconds', '-')} | "
            f"{'yes' if s.get('cited') else 'no'} | {'yes' if s.get('edited_code') else 'no'} | "
            f"{s.get('notes') or '-'} |"
        )
    if not sessions:
        lines.append("| - | - | - | - | - | - | no sessions recorded |")

    lines += [
        "",
        "## How this was measured",
        "",
        "Each volunteer received the task text and the repository, nothing else. The observer started the "
        "session timer, recorded whether the volunteer reached a result that showed a source link and an "
        "as-of date, and whether anyone had to edit code, change configuration or install a dependency to "
        "get there. Editing code counts as a failure even if the result was eventually correct, because "
        "the acceptance criterion in the proposal is first use without editing.",
        "",
        "The record contains no names: a random session id, a task letter, timings and two yes/no answers. "
        "Notes must not contain personal identifiers. Protocol: `docs/WALKTHROUGH_PROTOCOL.md`.",
        "",
        "Known limitation: five volunteers who are computing students are not representative of the wider "
        "undergraduate population, and an observer in the room makes the task easier than using the tool "
        "alone. Both weaken the claim; neither is hidden here.",
        "",
    ]
    return "\n".join(lines), met


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--task", default="A")
    parser.add_argument("--finish", default=None, metavar="SESSION")
    parser.add_argument("--cited", choices=["yes", "no"], default="no")
    parser.add_argument("--edited", choices=["yes", "no"], default="no")
    parser.add_argument("--seconds", type=int, default=None)
    parser.add_argument("--notes", default="")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    if args.start:
        return cmd_start(args.task)
    if args.finish:
        return cmd_finish(args.finish, args.cited, args.edited, args.seconds, args.notes)

    today = _dt.date.today()
    text, met = build_report(today)
    DOCS.mkdir(parents=True, exist_ok=True)
    target = DOCS / f"walkthrough_{today.isoformat()}.md"
    target.write_text(text, encoding="utf-8")
    print(text.splitlines()[4])
    print(f"written: {target.relative_to(ROOT)}")
    return 0 if met else 1


if __name__ == "__main__":
    raise SystemExit(main())
