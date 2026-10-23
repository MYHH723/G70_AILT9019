# HKU Pathfinder (pilot)

An evidence-grounded course and opportunity planning agent for HKU undergraduate students.
Given a study profile and a question, it returns a plan that links course evidence to research or
internship leads, with every recommendation carrying a source link, an as-of date and the
constraint check that allowed or blocked it.

This repository is the **Week 8 working core** submitted for the AILT9019 Mid-Term Check.
It is a small, honest prototype: one programme, one cohort, a frozen synthetic corpus, no model
call required.

---

## 1. What runs today

One real path, end to end:

```
student profile + question
      -> lexical retrieval over the frozen corpus (BM25 + exact course-code lookup)
      -> documented constraint checks (prerequisite / exclusion / offering semester / year / cohort / workload)
      -> opportunity verification (window, eligibility, reachability, login wall, record type)
      -> plan: <=3 courses + <=3 verified-open leads + next steps, each with a citation and an as-of date
      -> per-item helpful / not-helpful feedback, stored locally and anonymously
```

Deliberate design choice: the planner is **deterministic**. The same input always produces the same
output, with no API key, no network access and no cost, so a marker can reproduce the result exactly.
The prose is templated rather than generated; swapping in an LLM later only changes how the facts
are phrased, not which facts survive the checks.

## 2. Setup

Requirements: Python 3.9+ (standard library only). Nothing to install.

```bash
git clone <repository-url>
cd pathfinder
python3 --version          # 3.9 or newer
```

There is no `pip install` step and no `.env` file. The pilot never calls a model API.

## 3. Run the core path

```bash
./run.sh
# or: python3 -m src.server
```

Open <http://127.0.0.1:8765>. Press **Build plan** with the default profile, or load one of the
four saved profiles (P1-P4) to see a different constraint fire.

Command-line equivalent, no browser:

```bash
python3 -m src.cli "I am a Year 2 student interested in data science. What should I study next?"
```

## 4. How to check the result

**Example input** (defaults in the form, profile P1):

```json
{
  "programme": "BEng(CS) 2023-24 intake",
  "cohort": "2023-24",
  "year": 2,
  "completed": ["COMP1117", "MATH1013"],
  "interests": ["data science", "machine learning", "statistics"],
  "target_semester": "S1",
  "workload_ceiling": 4,
  "opportunity_types": ["research", "internship"]
}
```

Query: *"I am a Year 2 student interested in data science. What should I study next, and which
research or internship options should I investigate?"*

**Expected output** (as of 2026-10-23):

| Item | Expected | Why |
|---|---|---|
| `STAT2601` | eligible | prerequisite MATH1013 completed, offered in S1 |
| `COMP2119` | eligible | prerequisite COMP1117 completed, offered in S1 |
| `COMP3314` | blocked | needs COMP2119 and STAT2601 |
| `COMP3270` | blocked | needs COMP2119 |
| `COMP2120` | not offered | S2 only, target semester is S1 |
| `COMP2121` | restricted | 2023-24 intake must take COMP2119 instead |
| `COMP4801` | restricted | Year 4 only |
| `OPP-NLP-RA` | open | window 2026-10-01 to 2026-11-15, page reachable |
| `OPP-CV-INTERN` | closed | window ended 2026-08-31 |
| `OPP-NETJOBS` | unverifiable | listing behind a login |
| `OPP-MALICIOUS` | quarantined | record contains instructions addressed to the system |

Fastest way to confirm:

```bash
python3 -m tests.run_tests --gate     # 12-case core gate, expect 12/12
python3 -m tests.run_tests            # full 24 cases, expect 24/24
```

The run writes `tests/results/core_gate_<date>.md` and `tests/results/full_<date>.md`, which list
every case, every check and the actual observed value. Nothing in those files is hand-written.

## 5. Repository layout

```
pathfinder/
  run.sh                  launcher (checks Python version, starts the server)
  data/
    courses.json          16 synthetic course documents
    regulations.json      4 regulation documents: capstone, cohort change, exclusion, workload
    opportunities.json    12 opportunity records of six different kinds
    example_profiles.json 4 saved profiles used in the demo and in testing
  src/
    corpus.py             loads and freezes the corpus
    retrieval.py          BM25 + exact course-code lookup
    constraints.py        prerequisite / exclusion / semester / year / cohort checks
    planner.py            the single planning skill
    safety.py             scope limits, action refusal, injection stripping
    server.py             local HTTP interface
    cli.py                command-line interface
  web/index.html          the interface (no build step, no external assets)
  tests/
    cases.json            the fixed 24-case set (core=true marks the 12-case gate)
    run_tests.py          harness; writes dated result files
    results/              generated evidence, not edited by hand
  docs/
    VIDEO_SCRIPT.md       60-second recording plan
    TEST_LOG.md           what was run, what failed, what changed
```

## 6. Known limitations

1. **Lexical retrieval only.** There is no embedding index. A question whose wording shares no
   tokens with the corpus ("quantum computing") returns no course and the system says so, rather
   than guessing. This is visible in test C5.
2. **Synthetic corpus.** All 16 course documents, 4 regulation documents and 12 opportunity
   records are team-written fixtures. They are not official HKU pages and must not be cited as such.
   Every URL uses the reserved `fixtures.pathfinder.local` host.
3. **Simulated reachability.** The snapshot fallback is driven by a `fetch_status` field on each
   record (`ok` / `unreachable` / `login_required`), not by a live HTTP probe. The behaviour after a
   failed fetch is real; the failure itself is staged for a reproducible test.
4. **One programme, one cohort.** Requests outside `BEng(CS) 2023-24 intake` / cohort `2023-24`
   return a limited answer by design (test D1).
5. **Crude workload model.** A heavy course counts as two standard courses against the declared
   ceiling. It does not model actual assessment deadlines.

## 7. Safety and scope

- The agent does not log in, apply, email staff, register for courses or guarantee an outcome.
  Such requests are refused and the official manual route is named instead (tests D4, D5).
- Retrieved text is treated as data. Instruction-like sentences are stripped and the record is
  quarantined for manual review (test D6).
- A dated snapshot is never presented as a currently open call. Unreachable sources are labelled
  "verify manually" with their as-of date (tests B3, D3).
- No personal identifiers are collected. The form takes programme, cohort, year, completed course
  codes and interests only. Feedback records contain an item id, a rating and an optional comment.

## 8. Reproducing a specific test

```bash
python3 -m tests.run_tests            # all 24
grep -A6 '"id": "D6"' tests/results/full_2026-10-23.md
```

`PATHFINDER_TODAY` pins the evaluation date so that window checks are reproducible:

```bash
PATHFINDER_TODAY=2026-10-23 python3 -m tests.run_tests
```
