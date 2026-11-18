"""Lexical retrieval over the frozen corpus.

The pilot deliberately avoids a vector store: the corpus is 15 course
documents and 12 opportunity records, so a BM25 ranking over tokenised text
plus exact course-code lookup is sufficient, auditable, and needs no model
download. Swapping in an embedding index later only requires replacing
``search`` while keeping the same return shape.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Iterable

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "with", "on",
    "is", "are", "be", "as", "by", "at", "from", "this", "that", "it",
    "i", "my", "me", "we", "you", "what", "which", "should", "can", "how",
    "do", "does", "next", "take", "want",
}


def tokenize(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1]


def _doc_text(record: dict[str, Any]) -> str:
    parts: Iterable[str] = [
        record.get("code", ""),
        record.get("title", ""),
        record.get("summary", ""),
        " ".join(record.get("skills", [])),
        " ".join(record.get("topics", [])),
        record.get("eligibility_text", ""),
        record.get("host", ""),
        record.get("text", ""),
    ]
    return " ".join(p for p in parts if p)


class BM25:
    """Small, dependency-free BM25 (k1=1.5, b=0.75)."""

    def __init__(self, records: list[dict[str, Any]], k1: float = 1.5, b: float = 0.75) -> None:
        self.records = records
        self.k1 = k1
        self.b = b
        self.docs = [Counter(tokenize(_doc_text(r))) for r in records]
        self.lengths = [sum(d.values()) or 1 for d in self.docs]
        self.avg_len = sum(self.lengths) / max(len(self.lengths), 1)
        self.df: Counter[str] = Counter()
        for doc in self.docs:
            self.df.update(doc.keys())
        self.n = max(len(self.docs), 1)

    def _idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def search(self, query: str, top_k: int = 5) -> list[tuple[dict[str, Any], float]]:
        terms = tokenize(query)
        if not terms:
            return []
        scored: list[tuple[dict[str, Any], float]] = []
        for record, doc, length in zip(self.records, self.docs, self.lengths):
            score = 0.0
            for term in terms:
                tf = doc.get(term, 0)
                if not tf:
                    continue
                denom = tf + self.k1 * (1 - self.b + self.b * length / self.avg_len)
                score += self._idf(term) * tf * (self.k1 + 1) / denom
            if score > 0:
                scored.append((record, round(score, 4)))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]


def course_index(corpus) -> BM25:
    return BM25(corpus.courses)


def opportunity_index(corpus) -> BM25:
    return BM25(corpus.opportunities)


def explicit_codes(query: str, corpus) -> list[str]:
    """Course codes the student named directly, in query order."""
    found: list[str] = []
    for token in re.findall(r"\b[A-Z]{2,4}\d{4}\b", query.upper()):
        if corpus.course(token) and token not in found:
            found.append(token)
    return found
