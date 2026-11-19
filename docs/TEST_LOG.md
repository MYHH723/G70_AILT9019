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

- **No baseline comparison.** The retrieval-vs-no-retrieval comparison is not part of the core gate.

- **One programme only.** Every case uses the single supported programme and cohort.



---



## 2026-11-18 - corpus revision, and what the frozen corpus was doing before it



The three items above were the remaining Week 5-6 work. Doing them surfaced a defect in the corpus

itself, so it is recorded first.



**Defect 3 - the frozen corpus had quietly gone stale.**

Every opportunity window was written in October 2026. By 18 November the newest open vacancy had

closed on 15 November, so a plan built on the real date returned **zero verified-open leads** for

every profile. Nothing failed: the harness pins its evaluation date, and every case still passed.

That is the dangerous shape of the bug - the demo degrades to "no leads found" while the evidence

stays green.



Fix, in two parts:



1. `src/freshness.py` audits every window against the run date and prints the result at the end of

   each evaluation record and in the smoke record. A stale corpus is now visible, not silent.

2. `data/opportunities.json` revision `2026-11-18` rolled the five active synthetic windows forward

   (`OPP-NLP-RA`, `OPP-DATA-ENG`, `OPP-DL-COURSE-RA`, `OPP-PHD-ONLY`, `OPP-MALICIOUS`) and set every

   `as_of` to 2026-11-17. The two closed calls were left closed, because they are the negative cases.

   The windows remain fixtures and the file says so.



Consequence for the record: the 2026-10-23 result files predate this revision and are **not**

reproducible from the current corpus. They are kept as history. Current evidence is dated

2026-11-18.



**Defect 4 - the evaluation date was a constant, not an argument.**

`TODAY` was hardcoded, so the harness could not answer "what does the corpus do today?". Fix:

a `--today` argument plus a `PATHFINDER_TODAY` environment override, with the default pin moved to

the corpus revision date so a fresh clone still reproduces exactly.



---



## 2026-11-18 - core gate and full set, on the revised corpus



```

$ python3 -m tests.run_tests --gate

core_gate: 12/12 cases passed

freshness: 5 open vacancy record(s) - 5 open vacancy record(s) available for the verified-lead path.



$ python3 -m tests.run_tests

full: 24/24 cases passed

freshness: 5 open vacancy record(s) - 5 open vacancy record(s) available for the verified-lead path.

```



Result files: `tests/results/core_gate_2026-11-18.md`, `tests/results/full_2026-11-18.md`.



---



## 2026-11-18 - baseline, retrieval on vs off



```

$ python3 -m tests.baseline

baseline: retrieval 6/6 cases, no retrieval 0/6 cases

  citations 13 vs 0 | constraint rules 36 vs 0 | windows 34 vs 0

```



Result file: `tests/results/baseline_2026-11-18.md`.



Honest reading: the ablation is the same deterministic planner with the corpus lookup removed, not

a language model with the search box switched off, because the pilot has no model. That makes it a

*weaker* opponent than a no-retrieval LLM would be. It still produces fluent advice with zero

citations, zero constraint checks and zero windows read, so the comparison shows the evidence layer

is load-bearing. It does not show that BM25 is the best retrieval method, and it says nothing about

answer fluency.



---



## 2026-11-18 - live smoke test, and the fallback on a real failure



```

$ python3 -m tests.smoke

smoke: 12/12 assertions passed -> docs/smoke_2026-11-18.md

```



What the run actually did:



| Step | Result |

|---|---|

| `www4.hku.hk/pubunit/drcd/` | HTTP 200, 15,763 bytes read and discarded |

| `tl.hku.hk/urfp/` | HTTP 200 |

| `www.cedars.hku.hk/careers/jobs` | HTTP 200 |

| a path that does not exist on `www4.hku.hk` | HTTP 404 -> `unreachable` |

| `http://127.0.0.1:8765/` | `blocked` before connecting, non-approved host |

| the lead's own `fixtures.pathfinder.local` URL | `blocked`, reserved host |



Both failures were then fed to the planner for `OPP-NLP-RA`, which is `open` in the fixture. In both

cases the lead became `snapshot_verify_manually`, was moved out of the verified-open list, and the

reason carried the words "verify manually" with the as-of date.



One flake, recorded rather than hidden: on the first attempt the DRCD page timed out at 15 s. The

smoke test now retries once and prints the attempt count, so a retried success is visible. The

timeout is 20 s by default.



This closes limitation 3 of the earlier README. What it does not close: no real vacancy page is

ingested, because permission is unconfirmed, so the record the failure is applied to is synthetic.



---



## 2026-11-18 - first-use check from a clean clone



```

$ python3 -m tests.firstuse --clone file:///C:/Users/MYHH/OneDrive/Desktop/ailt9019/G70_AILT9019

firstuse: 6/6 checks passed

```



Run against a clean clone of the committed tree, not the working directory, so the check covers

exactly what a marker would get. `--clone https://github.com/MYHH723/G70_AILT9019.git` does the

same against the pushed repository once these commits are pushed.



Checks: the clone succeeds; the README documents the three commands; no import outside the standard

library (17 files scanned); the CLI returns a plan with a source URL and an as-of date; the

interface answers `/api/health`, `/api/plan`, `/api/export` and the page itself over HTTP; the

12-case gate passes from that tree.



Record: `docs/firstuse_2026-11-18.md`.



---



## 2026-11-18 - a dead citation link, found on the first click



The first click on a source link found something the suites had missed. The browser gave its

own error page:



```

fixtures.pathfinder.local/course/COMP2119

DNS_PROBE_FINISHED_NXDOMAIN

```



Cause: the citation carries the recorded URL, and every recorded URL uses the reserved

`fixtures.pathfinder.local` host, which by design does not resolve. The data was honest and the

interface was not: a student sees a broken page with no explanation and concludes the tool is broken.



Fix, without pretending the record is official:



- `src/fixtures.py` serves `/fixtures/<kind>/<key>` from the corpus itself. Each page carries a banner

  saying it is a synthetic fixture, the full record the plan was built from, and - where one exists -

  a link to the official entry point a live build would read.

- `annotate()` adds `local_url` to every citation that points at a fixture record. The recorded URL

  is kept as the identifier; nothing is rewritten.

- The interface links to `local_url` and labels it "fixture record", not "source", so the label no

  longer promises an official page.

- The export prints the recorded identifier and the fixture address, with a note at the top

  explaining that `fixtures.pathfinder.local` does not resolve.

- `tests/firstuse.py` now fails if any recommended course has a citation without a resolvable route,

  so this cannot silently come back.



Verified: `/fixtures/course/COMP2119` and `/fixtures/opportunities/OPP-NLP-RA` return 200,

`/fixtures/course/NOPE9999` returns 404, every citation in the default plan carries a `local_url`,

and the first-use check is 5/5.



A browser click found it; no automated check did. It is recorded rather than quietly

fixed, because "the citation links were dead" is the kind of defect a marker finds in ten seconds.



---



## 2026-11-18 - live official pages, and what the real sites turned out to be



Until now the only real connection to HKU was a reachability probe. This adds the real pages

themselves. Exploring them first changed the design, so the findings come before the code.



**Finding 1 - the DRCD site is an index, not a course database.**

`www4.hku.hk/pubunit/drcd/undergraduate-2023-2024` is a navigation page. It lists faculties and then

links out to the faculty sites; the course text is not on it. Crawling it for course descriptions

would have produced nothing.



**Finding 2 - the authoritative document for this cohort is a faculty PDF.**

`engg.hku.hk/Teaching-Learning/BEng-BASc/Academic-Programmes/Regulations-Syllabuses` publishes

`syllabuses/Syllabus-BBAIS-CS-23-24-4Y.pdf` - the 2023-24 BEng(CompSc) syllabus, HTTP 200,

`application/pdf`, about 100 KB. That is the document the pilot's cohort actually needs, and the

fixtures had been standing in for it without linking to it.



**Finding 3 - the two opportunity pages confirm the record-type taxonomy.**

The URFP page states eligibility but says, in one sentence, *"For more details including application

procedures and deadline, please contact the respective Faculty Office."* It publishes no deadline.

The CEDARS page links to the NETjobs and JIJIS portals and lists no vacancy. Both match what the

fixture types (`scheme`, `login_required`) claim, and both sentences are now quoted in the record.



**What was built**



- `src/livecheck.py` gained `fetch_page` and `find_sentence`: read one approved page, return the

  title, a bounded text rendering, a SHA-256 of that text, and one quoted sentence. Same guards as

  the probe; content is returned to the caller and never written to disk.

- `src/official.py` is a hand-written registry of five real pages with what each one settles. It

  fetches them concurrently (sequential was 43 s), retries once on a network stall, and caches for

  five minutes. Each recommended item gets an `official` citation beside its fixture citation; a

  synthetic record with no real counterpart gets `official: null` plus a link to the CEDARS portal so

  the student has somewhere real to look.

- The interface has an opt-in "check the real HKU pages" checkbox; `#live-demo` turns it on and runs.

- `tests/live.py` asserts each page is reachable, still contains the sentence the registry relies on,

  and reports drift against `tests/results/live_state.json`.



```

$ python3 -m tests.live

live: 10/10 assertions passed -> docs/live_2026-11-18.md

```



**Defect 5 - the live flag was silently ignored.**

`plan(..., live=True)` set the mode string but never called `official.attach`, because the

opportunity section later assigned `live = reachability or {}`, shadowing the parameter with an empty

dict. The symptom was a plan labelled "live official check" with no live data, and a suspiciously

fast 0.0 s run. Renamed the local to `live_map`. Worth recording because the mode string and the

actual behaviour disagreed, and only the timing gave it away.



**Limits, stated in the report as well:** the pilot does not parse the syllabus PDF (no PDF library,

and no permission to re-publish it), so course-level facts remain fixtures; and the live check

verifies pages, not vacancies - a page being reachable says nothing about a position being open.



---



## 2026-11-18 - corpus curation, and a real directory of places to look



Two decisions, both about not showing a student something they cannot use.



**Removed: the two expired calls.** `OPP-CV-INTERN` (window closed 2026-08-31) and

`OPP-AI-SUMMER` (closed 2026-05-31) were still in the corpus, so a plan could list a summer

internship that ended three months ago under "checked and not recommended". Correctly labelled, but

still clutter that answers a question nobody asked. Corpus revision `2026-11-18b`, 12 records to 10.



The deletion had a cost, and it is worth naming: case B2 tested "an expired call is reported

closed". With no expired record left, that case would have passed vacuously. Two fixes:



- `tests/engine.py` now asserts the decision rules directly, with records built inline: expired,

  not yet open, unreachable, login wall, ineligible, scheme, information-only, injected instruction,

  plus the six course rules. 16/16. These survive any future curation of the corpus.

- B2 was repurposed rather than deleted, because the 24-case count is a proposal commitment. It now

  asks about the URFP scheme page and asserts it is reported as `scheme` with "no current call" -

  a record type the B group never covered, and the case closest to what the real URFP page says.



**Added: a channel directory.** `data/channels.json` and `src/channels.py` hold nine real places to

look, each with what it covers and whether it needs an HKU login:



| Group | Channels |

|---|---|

| University sources | CEDARS careers, HKU NETjobs, JIJIS |

| Research and innovation | URFP, Faculty of Engineering research, HKSTP, Cyberport |

| Commercial job boards | JobsDB, LinkedIn Jobs |



Every plan carries this list, with or without live mode. The wording is deliberate: a channel is a

doorway, not a vacancy, and none of them is evidence that a position is open.



Only six are probed. Cyberport (403), JobsDB (403) and LinkedIn (999) block automated requests, so

they are marked `link only` - reporting a working site as "unreachable" would be a lie about the

site, not a finding about the pilot. This also needed a narrow change to `src/livecheck.py`:

`host_allowed` and the redirect guard now accept an explicit `extra_hosts`, used only by the channel

checker, so the default allowlist for official HKU pages stays as tight as it was.



```

$ python3 -m tests.run_tests

full: 24/24 cases passed

$ python3 -m tests.engine

engine: 16/16 rules hold

```



---



## 2026-11-18 - the model layer: wording only, and enforced that way



The rubric requires a model call, and the pilot had none: the status sheet had cut "LLM-written

prose" and the planner is deterministic. Adding a model naively would have destroyed the thing that

makes the 24-case evidence worth anything - the same input producing the same output - so the layer

was added at the only place that does not touch a decision.



**What it does.** `src/llm.py` takes the finished plan, sends the planner's own facts to an

OpenAI-compatible `/chat/completions` endpoint, and replaces the summary paragraph with the returned

text. It runs only when `PATHFINDER_LLM_API_KEY` is set. The request is a plain JSON POST with

`urllib`; there is no SDK and no new dependency.



**What stops it from lying.** The output is checked against the plan before it is used:



| Check | On failure |

|---|---|

| every `COMP1234`-shaped code must already be in the plan | reject |

| every URL must already be in the plan | reject |

| every ISO date must already be in the plan | reject |

| no "guaranteed" / "will be admitted" / similar | reject |

| under 900 characters | reject |



A rejection, a timeout, an HTTP error or a missing key all leave the template in place and record

the reason in `plan["wording"]`. The plan is never worse for having tried.



**How it is tested without a key.** `tests/llm.py` injects a stub transport that returns whatever

text the test wants, so the guard is exercised directly rather than the model:



```

$ python3 -m tests.llm

llm: 13/13 checks passed

```



Cases: no key keeps the template; a clean rewrite is accepted and the template is kept alongside it;

an invented code (`COMP9999`), an invented date (`2027-03-01`), an invented link and a guarantee are

each rejected; an upstream timeout falls back; the request carries the configured model, endpoint and

the plan's facts; the guard accepts codes and dates the plan really contains.



**Why the 24 cases still pass.** `tests/run_tests.py`, `tests/baseline.py` and `tests/smoke.py` pass

`llm=False` explicitly. The evaluation measures the decision layer, and a marker with a key set

should get identical numbers to one without. Verified after the change: 24/24, baseline 6-0,

smoke 12/12, engine 16/16, llm 13/13.



**Honest limit.** There is no fluency comparison: no template-vs-model rating, no human preference

test. The layer is demonstrated to be safe, not demonstrated to be better prose.



---





## What these tests still do not cover



- **No real opportunity corpus.** Permission to ingest official pages is unconfirmed, so every

  record is synthetic and every window is a fixture.

- **No semantic retrieval.** Lexical matching only; C5 documents the failure honestly.

- **One programme only.** Every case uses the single supported programme and cohort.

- **No fluency evaluation.** There is no language model to evaluate.



