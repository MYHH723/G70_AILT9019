# Close-out: what was left, what was built, what is still open



Written 2026-11-18 against the revised proposal (10 October 2026) and the mid-term status sheet

(25 October 2026). The status sheet committed to three items for the following two weeks. This page

records what happened to each, plus the acceptance item that is still unmet in the repository.



## 1. The three committed milestones



| Milestone (status sheet) | State | Evidence |

|---|---|---|


| Baseline (same 6 planning cases, no retrieval) plus a re-run of all 24 | **Done** | `tests/results/baseline_2026-11-18.md`, `tests/results/full_2026-11-18.md` |

| Live smoke test on 3 approved pages, snapshot fallback proven on a real failure, README run from a clean clone | **Done** | `docs/smoke_2026-11-18.md`, `docs/firstuse_2026-11-18.md` |



## 2. Proposal acceptance items, and where the evidence sits



| Must-have (proposal section 6A) | Evidence |

|---|---|

| One declared programme/cohort, source-traceable corpus, synthetic fixtures for sharing | `data/courses.json` (16), `data/regulations.json` (4), all URLs on `fixtures.pathfinder.local` |

| Complete request-to-plan flow with prerequisite blocking, semester and exclusion checks | `tests/results/full_2026-11-18.md` cases A1-A6, C1-C6 |

| One reusable planning skill, read-only tools | `src/planner.py` (`plan`), `src/cli.py`, `src/server.py` |

| Source links, applicability metadata, as-of dates, explicit unknown/blocked/closed states | every card carries `citations[0].url` and `as_of`; states in `src/constraints.py`, `src/planner.py` |

| Graceful degradation with a labelled dated snapshot, never reported as current | `docs/smoke_2026-11-18.md`, on two real failure kinds |

| Per-item feedback control, anonymous local storage, aggregate summary | `web/index.html`, `src/server.py` `/api/feedback`, `data/feedback.jsonl` |

| Safe handling of all six safety tests, phased evaluation record | cases D1-D6; gate 12/12 then 24/24 |

| Usable local interface, API-free demo, documented route to a first request | `./run.sh`, `tests/firstuse_*`, README sections 2-3 |



Should-haves that were completed: **export of the action plan** (`src/export.py`, `/api/export`, the

download button). Should-haves still not done, deliberately: English-Chinese interaction, reranking

informed by feedback, corpus growth to 20-30 documents, a second agent environment.



## 3. What changed in the code



| File | Change |

|---|---|

| `src/livecheck.py` | new: approved-host probe with redirect revalidation, private-address refusal, no content retention |

| `src/fixtures.py` | new: serves each cited fixture record at `/fixtures/<kind>/<key>`, so a source link is clickable without claiming to be an official page |

| `src/official.py` | new: registry of five real HKU pages, live check with one quoted sentence each, attached as a second citation |

| `src/channels.py` + `data/channels.json` | new: nine real places to look for opportunities, grouped, with login requirement and live status where the site allows it |

| `tests/engine.py` | new: decision-rule unit tests that do not depend on what is in the corpus |

| `src/llm.py` | new: optional wording layer over an OpenAI-compatible endpoint, with a fact guard that rejects invented codes, links, dates and guarantees |

| `tests/llm.py` | new: wording-guard tests using a stubbed transport, so no key is needed |

| `tests/live.py` | new: asserts each official page is reachable, still says what the registry relies on, and reports drift |

| `src/freshness.py` | new: window and snapshot-age audit, printed in every evaluation record |

| `src/export.py` | new: markdown export that keeps citations and as-of dates |

| `src/planner.py` | `reachability` override so a live probe can replace the staged field; `retrieve=False` ablation path |

| `src/server.py` | `/api/export`; `PATHFINDER_HOST` / `PATHFINDER_PORT` for testing |

| `web/index.html` | download button; plan payload factored into `currentPayload()` |

| `tests/run_tests.py` | `--today`, freshness section, pin moved to the corpus revision date |

| `tests/baseline.py`, `tests/smoke.py`, `tests/firstuse.py` | new harnesses |

| `data/opportunities.json` | revision 2026-11-18: windows rolled forward, `as_of` refreshed, `live_probe_url` on the two real entry points |



## 4. Two findings worth telling the marker



**The frozen corpus had gone stale, and every test still passed.** The windows were written in

October; by 18 November no vacancy was open, so a plan built on the real date returned zero leads.

The harness could not see it because the evaluation date was a constant. This is now visible in the

freshness audit, and the corpus carries an explicit revision number. Recorded as Defect 3 in

`docs/TEST_LOG.md`.



**The baseline is weaker than the proposal implies.** The proposal asked for "the same model without

retrieval". The pilot has no model, so the baseline is the same deterministic planner with the

corpus removed. That is a fair ablation, but it is not the comparison a reader will assume, and the

baseline record says so in its own words rather than letting the 6-0 score speak for itself.



**Every citation link was dead, and no test noticed.** The records use the reserved

`fixtures.pathfinder.local` host, so clicking a source link produced `DNS_PROBE_FINISHED_NXDOMAIN`

with no explanation. Every automated check passed because they inspect the URL string, not whether a

browser can open it. Fixed by serving the fixture records from the app and labelling the link

"fixture record"; `tests/firstuse.py` now fails if a citation has no resolvable route. This was found

on the first click in a browser, which no automated check performs.



**The real sources turned out to be different from what the plan assumed.** The DRCD site is an

index that links out to faculty pages, not a course database; the authoritative document for this

cohort is a faculty PDF (`Syllabus-BBAIS-CS-23-24-4Y.pdf`), and the URFP page explicitly publishes

no deadline, sending the reader to the Faculty Office. All three findings are now in the code and in

`docs/live_2026-11-18.md`, and they make the "check the official page" step concrete rather than

rhetorical.



**Two expired records were removed, and the test that covered them was rebuilt.** Deleting a stale

summer internship is right for the student and wrong for the test suite, which would have gone on

passing vacuously. The rule now lives in `tests/engine.py` (16 rules, corpus-independent), and case

B2 was repurposed to the URFP scheme page rather than dropped, so the 24-case commitment holds.



**The rubric asks for a model call, and the build had none.** The status sheet had cut LLM-written

prose; the rubric expects a model in the loop. The layer was added where it cannot corrupt a

decision: the model rewrites the summary paragraph from the planner's own facts, and its output is

rejected if it contains a course code, URL or date the plan does not already hold. Every failure

falls back to the template, and the 24-case evaluation runs with the model disabled so the numbers

stay reproducible. `tests/llm.py` (13 checks, stubbed transport) proves the guard without a key.



## 5. What is genuinely still open




1. **Permission to ingest official pages.** The corpus is synthetic because reuse terms are

   unconfirmed. Live mode now reads the real pages and links to them, but it does not store or

   re-publish them, and course-level facts still come from fixtures. Reading a page is not the same

   as being allowed to redistribute it, and the code keeps that line.

3. **No real opportunity window.** No record has a live-verifiable deadline; the smoke test proves

   the degradation path, not the availability of a position.



Items 2 and 3 cannot be closed by code, and nothing in the repository pretends otherwise.

