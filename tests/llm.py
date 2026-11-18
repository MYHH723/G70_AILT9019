"""Tests for the optional wording layer, with a stubbed transport.

No API key and no network: a fake transport returns whatever text the test
wants, which is exactly what is needed to prove the guard, not the model. The
question these tests answer is not "is the prose good" but "can the prose ever
change a fact".

    python3 -m tests.llm
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import llm  # noqa: E402
from src.corpus import get_corpus  # noqa: E402
from src.planner import plan  # noqa: E402

PROFILE = {
    "programme": "BEng(CS) 2023-24 intake",
    "cohort": "2023-24",
    "year": 2,
    "completed": ["COMP1117", "MATH1013"],
    "interests": ["data science"],
    "target_semester": "S1",
    "workload_ceiling": 4,
    "opportunity_types": ["research"],
}
QUERY = "I am a Year 2 student interested in data science. What should I study next?"


def _plan() -> dict:
    return plan(PROFILE, QUERY, get_corpus(), llm=False)


def _transport(text: str, captured: dict | None = None):
    def post(url, headers, payload, timeout):
        if captured is not None:
            captured.update({"url": url, "headers": headers, "payload": payload})
        return {"choices": [{"message": {"content": text}}]}

    return post


def _boom(url, headers, payload, timeout):
    raise TimeoutError("simulated upstream timeout")


def run() -> list[tuple[str, bool, str]]:
    rows: list[tuple[str, bool, str]] = []
    settings = llm.Settings(api_key="test-key", base_url="https://example.invalid/v1", model="test-model")

    # 1. no key -> template stands
    base = _plan()
    llm.rewrite(base, settings=llm.Settings(api_key=""))
    rows.append(("without a key the template stands",
                 base["wording"]["used"] is False and base["summary"] == _plan()["summary"],
                 base["wording"]["reason"]))

    # 2. a clean rewrite is accepted
    base = _plan()
    original = base["summary"]
    codes = [c["code"] for c in base["courses"]]
    clean = f"Your plan is ready as of {base['as_of']}: {', '.join(codes)} passed every documented check. Check each source before you commit."
    llm.rewrite(base, settings=settings, transport=_transport(clean))
    rows.append(("a rewrite that keeps every fact is accepted",
                 base["wording"]["used"] is True and base["summary"] == clean,
                 base["wording"]["reason"]))
    rows.append(("the template is kept alongside the rewrite",
                 base["wording"].get("template_summary") == original,
                 "template_summary recorded" if base["wording"].get("template_summary") else "missing"))

    # 3. an invented course code is rejected
    base = _plan()
    before = base["summary"]
    llm.rewrite(base, settings=settings,
                transport=_transport("You should also take COMP9999, which fits your interests."))
    rows.append(("an invented course code is rejected",
                 base["wording"]["used"] is False and base["summary"] == before,
                 base["wording"]["reason"]))

    # 4. an invented date is rejected
    base = _plan()
    before = base["summary"]
    llm.rewrite(base, settings=settings,
                transport=_transport("The application closes on 2027-03-01, so apply soon."))
    rows.append(("an invented date is rejected",
                 base["wording"]["used"] is False and base["summary"] == before,
                 base["wording"]["reason"]))

    # 5. an invented link is rejected
    base = _plan()
    llm.rewrite(base, settings=settings,
                transport=_transport("Details are at https://example.com/handbook for reference."))
    rows.append(("an invented link is rejected",
                 base["wording"]["used"] is False, base["wording"]["reason"]))

    # 6. a promise of an outcome is rejected
    base = _plan()
    llm.rewrite(base, settings=settings,
                transport=_transport("Take COMP2119 and you are guaranteed a place in the lab."))
    rows.append(("a guarantee is rejected",
                 base["wording"]["used"] is False, base["wording"]["reason"]))

    # 7. upstream failure falls back silently
    base = _plan()
    before = base["summary"]
    llm.rewrite(base, settings=settings, transport=_boom)
    rows.append(("an upstream failure falls back to the template",
                 base["wording"]["used"] is False and base["summary"] == before,
                 base["wording"]["reason"]))

    # 8. the request carries the facts and the model settings
    captured: dict = {}
    base = _plan()
    llm.rewrite(base, settings=settings, transport=_transport("Fine.", captured=captured))
    payload = captured.get("payload", {})
    system = payload.get("messages", [{}])[0].get("content", "")
    user = payload.get("messages", [{}, {}])[1].get("content", "{}")
    facts = json.loads(user)
    rows.append(("the request uses the configured model and endpoint",
                 payload.get("model") == "test-model" and captured.get("url", "").endswith("/chat/completions"),
                 f"{captured.get('url')} model={payload.get('model')}"))
    # The prompt deliberately no longer quotes the banned words: a model asked
    # to summarise its rules would quote them, and the guard would then read the
    # quotation as a promise. So the test checks the rule, not the vocabulary.
    rows.append(("the prompt forbids adding facts and promising outcomes",
                 "Do not add a course" in system and "promise an outcome" in system.lower(),
                 "system prompt states both rules without quoting the banned words"))
    rows.append(("the model receives the plan's own facts",
                 facts.get("status") == base["status"]
                 and [c["code"] for c in facts["recommended_courses"]] == [c["code"] for c in base["courses"]],
                 f"{len(facts['recommended_courses'])} course(s), {len(facts['open_leads'])} lead(s)"))

    # 9. the guard is independent of the model: it rejects a bad string on its own
    # COMP4801 and 2026-12-31 are both real facts in this plan, so the guard
    # must accept them; COMP7777 and 2027-01-01 are not, so it must not.
    plan_now = _plan()
    ok_real, reason_real = llm.check_wording("COMP4801 is restricted; the window ends 2026-12-31.", plan_now)
    ok_fake, reason_fake = llm.check_wording("Take COMP7777 from 2027-01-01.", plan_now)
    rows.append(("the guard accepts codes and dates the plan really contains",
                 ok_real is True, reason_real))
    rows.append(("the guard can be called without any model",
                 ok_fake is False, reason_fake))

    return rows


def main() -> int:
    rows = run()
    passed = sum(1 for _, ok, _ in rows if ok)
    for name, ok, detail in rows:
        print(f"  [{'x' if ok else ' '}] {name} -> {detail}")
    print(f"llm: {passed}/{len(rows)} checks passed")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
