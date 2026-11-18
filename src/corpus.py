"""Corpus loading for the HKU Pathfinder pilot.

The pilot runs entirely on team-written synthetic fixtures stored in ``data/``.
No third-party document is redistributed and no network access is required.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def _load(name: str) -> dict[str, Any]:
    with open(DATA_DIR / name, encoding="utf-8") as handle:
        return json.load(handle)


class Corpus:
    """Immutable in-memory view of the frozen pilot corpus."""

    def __init__(self) -> None:
        courses_doc = _load("courses.json")
        regs_doc = _load("regulations.json")
        opps_doc = _load("opportunities.json")

        self.meta: dict[str, Any] = courses_doc["corpus"]
        self.courses: list[dict[str, Any]] = courses_doc["courses"]
        self.regulations: list[dict[str, Any]] = regs_doc["regulations"]
        self.opportunities: list[dict[str, Any]] = opps_doc["opportunities"]

        self.course_by_code = {c["code"]: c for c in self.courses}
        self.reg_by_id = {r["id"]: r for r in self.regulations}

        # A minimal, deliberately narrow notion of "supported scope".
        # Anything outside this must produce a limited answer, not a guess.
        self.supported_programmes = {self.meta["programme"]}
        self.supported_cohorts = {self.meta["cohort"]}

    # -- lookups -----------------------------------------------------------
    def course(self, code: str) -> dict[str, Any] | None:
        return self.course_by_code.get(code.strip().upper())

    def regulation_for(self, course_code: str, rule: str | None = None) -> list[dict[str, Any]]:
        hits = [r for r in self.regulations if course_code in r.get("applies_to", [])]
        if rule:
            hits = [r for r in hits if r.get("rule") == rule]
        return hits

    def regulation(self, reg_id: str) -> dict[str, Any] | None:
        return self.reg_by_id.get(reg_id)

    def stats(self) -> dict[str, int]:
        return {
            "courses": len(self.courses),
            "regulations": len(self.regulations),
            "opportunities": len(self.opportunities),
        }


_CORPUS: Corpus | None = None


def get_corpus() -> Corpus:
    global _CORPUS
    if _CORPUS is None:
        _CORPUS = Corpus()
    return _CORPUS
