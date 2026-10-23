# Test log

All entries are from actual runs on the dates shown. Commands are reproducible from a clean clone.
Generated result files live in `tests/results/` and are never edited by hand.

---

## 2026-10-23 - run 1, development defects found by manual spot-checks

Before the fixed suite existed, the four saved profiles were run by hand. Two defects surfaced.

**Defect 1 - a completed course was recommended again.**
Profile P3 (Year 3, `COMP2119`/`STAT2601` already completed) returned `MATH1013` as a next step.
Cause: the constraint engine had no "already completed" rule, so a course with no prerequisites
always looked eligible. Fix: added a `completed` status that outranks every other check
(`src/constraints.py`, `PRIORITY`), plus the matching branch in `evaluate_course`.

**Defect 2 - a generic question was answered with one unrelated course.**
The question "which research or internship options should I investigate?" caused `COMP4801 Final
Year Project` to be named in the headline, because the lexical matcher scored the words "research"
and "project". Fix: the headline is now only produced when the student names a course explicitly
(by code) or matches at least two distinctive title words (`_focus_course` in `src/planner.py`).

Both fixes were made before the fixed 24-case set was written, so they are recorded here rather
than in the generated result files.

---

## 2026-10-23 - core gate, run 1

```
$ python3 -m tests.run_tests --gate
core_gate: 12/12 cases passed
```

Result file: `tests/results/core_gate_2026-10-23.md`.

---

## 2026-10-23 - full set, run 1 (failed)

```
$ python3 -m tests.run_tests
full: 23/24 cases passed
  FAIL C5: status_in -> status=ok
```

**Case C5** - "I want a plan for quantum computing research placements", profile with no lexical
overlap with the corpus.

- Expected: `limited` or `partial` - no course should be recommended.
- Actual: `status = ok`, zero courses, one opportunity lead.
- Cause: the summary branch set `ok` whenever at least one lead was verified, without checking
  whether any course had survived the constraint checks. The zero-course outcome was therefore
  reported as a full success.
- Fix: replaced the two-branch summary with four explicit branches
  (`courses+leads`, `courses only`, `leads only`, `neither`) in `src/planner.py`, so a request with
  no course evidence can never be labelled `ok`.

This is the failure the current limitation note refers to: lexical retrieval has no way to connect
"quantum computing" to any document in the corpus, and the system now says so instead of returning
an empty plan that looks complete.

---

## 2026-10-23 - full set, run 2 (after the fix)

```
$ python3 -m tests.run_tests
full: 24/24 cases passed
```

```
$ python3 -m tests.run_tests --gate
core_gate: 12/12 cases passed
```

Result files: `tests/results/full_2026-10-23.md`, `tests/results/core_gate_2026-10-23.md`.

Coverage of the 24 cases:

| Category | Cases | What is exercised |
|---|---|---|
| Course feasibility | A1-A6 | unmet prerequisite, mutual exclusion, semester not offered, cohort rule, capstone year rule, plain relevance |
| Opportunity check | B1-B6 | open vacancy, expired call, unreachable page, login wall, research-interest page, eligibility restriction |
| End-to-end planning | C1-C6 | full plan, research-only plan, internship-only plan, workload ceiling, no verified match, blocked pathway |
| Safety | D1-D6 | unsupported programme, incomplete record, snapshot fallback, login request, apply/guarantee request, prompt injection |

---

## What these tests do not cover

- **No live network probe.** Reachability is a staged field, so the snapshot fallback is tested
  end to end but the failure itself is simulated.
- **No human usability test yet.** The five-volunteer walkthrough named in the proposal has not
  run; it is the first milestone in the status sheet.
- **No baseline comparison.** The retrieval-vs-no-retrieval comparison is not part of the core gate.
- **One programme only.** Every case uses the single supported programme and cohort.
