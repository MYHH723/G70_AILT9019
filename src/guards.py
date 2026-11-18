"""Shared check for promises of an outcome.

Both the wording layer and the assistant must never tell a student that
something is assured. The naive version of this check rejected the word
"guarantee" wherever it appeared, which produced a false positive the moment a
model was asked to summarise its own instructions: the summary quoted the rule
"no 'guaranteed'" and the guard refused to show it.

A promise and a disclaimer use the same words. The difference is grammatical,
not lexical, so the check looks at what precedes the phrase:

    "you are guaranteed a place"        -> promise, reject
    "I can never guarantee a place"     -> disclaimer, allow
    "the rules say no 'guaranteed'"     -> quotation, allow

This is a heuristic, not a parser. It is deliberately conservative in one
direction only: it lets a few disclaimers through, and it never lets a plain
promise through.
"""

from __future__ import annotations

import re

FORBIDDEN = (
    "guaranteed", "guarantee", "will be admitted", "assured admission",
    "definitely eligible", "you will get the position", "you will get the place",
)

# Words that turn a promise into its opposite, or into a quotation of the rule.
NEGATIONS = (
    "never", "not ", "no ", "don't", "do not", "does not", "cannot", "can't",
    "won't", "will not", "without", "unable to", "isn't", "aren't",
    # Prohibition and quotation frames: "the rules forbid saying you are
    # guaranteed a place" mentions the phrase rather than promising anything.
    "forbid", "forbidden", "prohibit", "banned", "not allowed", "not permitted",
    "rule", "instruction", "told", "says to", "avoid",
)

WINDOW = 70


def _is_mention(text: str, index: int) -> bool:
    """True when the phrase is negated or quoted rather than asserted."""
    before = text[max(0, index - WINDOW):index].lower()
    if any(marker in before for marker in NEGATIONS):
        return True
    # A quoted phrase is a quotation of the rule, not a claim about the student.
    if before.rstrip().endswith(("'", '"', "“", "‘")) or before.rstrip().endswith(("`",)):
        return True
    return False


def find_promise(text: str) -> str | None:
    """The first phrase used as a promise, or None.

    Returns the phrase itself so the caller can report what tripped the check.
    """
    if not text:
        return None
    lowered = text.lower()
    for phrase in FORBIDDEN:
        start = 0
        while True:
            index = lowered.find(phrase, start)
            if index < 0:
                break
            if not _is_mention(lowered, index):
                return phrase
            start = index + len(phrase)
    return None
