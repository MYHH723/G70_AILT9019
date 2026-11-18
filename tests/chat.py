"""Tests for the floating assistant, with a stubbed transport.

Same idea as ``tests/llm.py``: no key, no network. The fake transport returns
whatever the test wants, so the guard and the error paths are exercised rather
than the model. The question is not "is the answer good" but "can the assistant
ever promise something, or name a course that does not exist".

    python3 -m tests.chat
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import chat  # noqa: E402
from src.corpus import get_corpus  # noqa: E402

# The assistant throttles itself to protect a shared group key; tests should not
# wait for that.
chat.MIN_INTERVAL = 0.0

SETTINGS = chat.ChatSettings(api_key="test-key", base_url="https://example.invalid/v1", model="test-model")
HISTORY = [{"role": "user", "content": "Why is COMP3314 blocked for me?"}]


def _transport(text: str, captured: dict | None = None):
    def post(url, headers, payload, timeout):
        if captured is not None:
            captured.update({"url": url, "headers": headers, "payload": payload})
        return {"choices": [{"message": {"content": text}}]}

    return post


def _http_error(code: int, body: bytes = b'{"error":"nope"}'):
    def post(url, headers, payload, timeout):
        raise urllib.error.HTTPError(url, code, "err", {}, io.BytesIO(body))

    return post


def run() -> list[tuple[str, bool, str]]:
    corpus = get_corpus()
    rows: list[tuple[str, bool, str]] = []

    # 1. no key
    out = chat.reply(HISTORY, corpus, settings=chat.ChatSettings(api_key=""))
    rows.append(("without a key the error names the variable",
                 out["ok"] is False and "PATHFINDER_CHAT_API_KEY" in out["error"], out["error"][:70]))

    # 2. a normal answer is returned
    answer = "COMP3314 needs COMP2119 and STAT2601 first. Both are listed in your profile as not yet completed."
    out = chat.reply(HISTORY, corpus, settings=SETTINGS, transport=_transport(answer))
    rows.append(("a grounded answer is returned as written",
                 out["ok"] is True and out["text"] == answer, out["text"][:60]))

    # 3. an invented course code is withheld
    out = chat.reply(HISTORY, corpus, settings=SETTINGS,
                     transport=_transport("You could also take COMP9999, which is easier."))
    rows.append(("a reply naming an unknown course is withheld",
                 out["ok"] is False and "COMP9999" in out["error"], out["error"][:90]))

    # 4. a promise is withheld
    out = chat.reply(HISTORY, corpus, settings=SETTINGS,
                     transport=_transport("Apply to the lab and you are guaranteed a place."))
    rows.append(("a reply that promises an outcome is withheld",
                 out["ok"] is False and "guaranteed" in out["error"].lower(), out["error"][:90]))

    # 5. upstream 401 is explained, not dumped
    out = chat.reply(HISTORY, corpus, settings=SETTINGS, transport=_http_error(401))
    rows.append(("a rejected key is reported as a key problem",
                 out["ok"] is False and "key was rejected" in out["error"], out["error"][:80]))

    # 6. an empty message is refused before any call
    out = chat.reply([{"role": "user", "content": "   "}], corpus, settings=SETTINGS,
                     transport=_transport("should not be called"))
    rows.append(("an empty message never reaches the model",
                 out["ok"] is False and "empty" in out["error"].lower(), out["error"][:60]))

    # 7. the prompt carries the scope and the real course codes
    captured: dict = {}
    chat.reply(HISTORY, corpus, settings=SETTINGS, transport=_transport("ok", captured))
    payload = captured.get("payload", {})
    system = payload.get("messages", [{}])[0].get("content", "")
    rows.append(("the system prompt states the one-programme scope",
                 corpus.meta["programme"] in system and corpus.meta["cohort"] in system,
                 "programme and cohort present"))
    rows.append(("the system prompt lists only corpus course codes",
                 "COMP2119" in system and "COMP9999" not in system,
                 "corpus codes only"))
    rows.append(("the request uses the configured model and endpoint",
                 payload.get("model") == "test-model"
                 and captured.get("url", "").endswith("/chat/completions"),
                 f"{captured.get('url')} model={payload.get('model')}"))
    rows.append(("the key travels in the Authorization header",
                 captured.get("headers", {}).get("Authorization") == "Bearer test-key",
                 "bearer header set server-side"))

    # 8. history is capped so a long conversation cannot blow the context
    long_history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(40)]
    messages = chat.build_messages(long_history, corpus)
    rows.append(("history is capped before it is sent upstream",
                 1 <= len(messages) - 1 <= chat.MAX_MESSAGES,
                 f"{len(messages) - 1} history message(s) of 40"))

    # 9. quoting a prohibition is not making a promise - the false positive that
    #    made "what were you told?" fail the first time it was asked
    mentions = [
        "I was told never to promise an outcome, including any guarantee of admission.",
        "The rules forbid saying you are guaranteed a place.",
        "My instructions say to avoid words like guaranteed.",
    ]
    promises = [
        "You are guaranteed a place in the lab.",
        "I guarantee you will get the position.",
        "Apply now - admission is assured admission.",
    ]
    rows.append(("quoting a prohibition is allowed",
                 all(chat.check_reply(t, corpus)[0] for t in mentions),
                 f"{len(mentions)} mention(s) accepted"))
    rows.append(("an actual promise is still rejected",
                 all(not chat.check_reply(t, corpus)[0] for t in promises),
                 f"{len(promises)} promise(s) rejected"))

    # 10. the guard stands alone
    ok, reason = chat.check_reply("COMP4801 is restricted to Year 4.", corpus)
    rows.append(("the guard accepts a real code and a real rule", ok is True, reason))

    return rows


def main() -> int:
    rows = run()
    passed = sum(1 for _, ok, _ in rows if ok)
    for name, ok, detail in rows:
        print(f"  [{'x' if ok else ' '}] {name} -> {detail}")
    print(f"chat: {passed}/{len(rows)} checks passed")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
