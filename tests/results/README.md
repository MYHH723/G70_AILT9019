# Generated evidence

Everything in this folder is written by a script and must not be edited by hand. If a number is
wrong, fix the code or the corpus and re-run; do not touch the file.

| Pattern | Written by | Contents |
|---|---|---|
| `core_gate_<date>.{json,md}` | `python3 -m tests.run_tests --gate` | the 12-case phase-one gate |
| `full_<date>.{json,md}` | `python3 -m tests.run_tests` | all 24 cases, every check, freshness audit |
| `baseline_<date>.{json,md}` | `python3 -m tests.baseline` | retrieval on vs off, C1-C6 |
| `walkthrough_sessions.jsonl` | `python3 -m tests.walkthrough` | append-only volunteer session log |

The date in the file name is the **evaluation date**, not the wall-clock date of the run: the
harness pins it so that window checks reproduce. Pass `--today` to evaluate as of another day.

## Corpus revisions and reproducibility

| Revision | Date | Change |
|---|---|---|
| pre-revision | up to 2026-10-23 | original October windows; `OPP-NLP-RA` closed on 2026-11-15 |
| `2026-11-18` | 2026-11-18 | five active synthetic windows rolled forward; all `as_of` set to 2026-11-17 |

Files dated **2026-10-23** were produced before the revision and are **not** reproducible from the
current corpus. They are kept as history, not as a claim about the current data. Current evidence is
dated **2026-11-18**.
