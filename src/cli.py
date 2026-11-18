"""Command-line interface: same core path as the web form, no browser.

    python3 -m src.cli "I am a Year 2 student interested in data science."
    python3 -m src.cli --profile P2
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .corpus import DATA_DIR, get_corpus
from .fixtures import annotate
from .planner import plan

STATUS_MARK = {
    "eligible": "[ok]     ",
    "open": "[open]   ",
    "blocked": "[blocked]",
    "restricted": "[restricted]",
    "not_offered": "[not offered]",
    "needs_verification": "[verify]",
    "excluded": "[excluded]",
    "completed": "[done]   ",
    "deferred": "[deferred]",
    "closed": "[closed] ",
    "ineligible": "[ineligible]",
    "unverifiable": "[login]  ",
    "snapshot_verify_manually": "[snapshot]",
    "info_only": "[info]   ",
    "scheme": "[scheme] ",
    "quarantined": "[quarantined]",
}


def _profiles() -> dict[str, dict]:
    data = json.loads((DATA_DIR / "example_profiles.json").read_text(encoding="utf-8"))
    return {p["id"]: p for p in data["profiles"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", help="the student's question")
    parser.add_argument("--profile", default="P1", help="saved profile id (P1-P4)")
    args = parser.parse_args()

    saved = _profiles()[args.profile]
    query = args.query or saved["query"]
    result = annotate(plan(saved["profile"], query, get_corpus()))

    print(f"Q: {query}\n")
    print(f"status: {result['status']}  |  mode: {result['mode']}  |  as of {result['as_of']}")
    print(f"\n{result['summary']}\n")
    for notice in result["notices"]:
        print(f"! {notice}")
    for refusal in result["refused_actions"]:
        print(f"x refused: {refusal['action']} -> {refusal['manual_route']}")

    if result["courses"]:
        print("\nRECOMMENDED COURSES")
        for item in result["courses"]:
            cite = item["citations"][0]
            where = cite.get("local_url") or cite["url"]
            print(f"  {STATUS_MARK.get(item['status'], '')} {item['code']} {item['title']}")
            print(f"             {item['reasons'][0]['text']}")
            print(f"             source {cite['url']} (as of {cite['as_of']}) -> {where}")

    if result["opportunities"]:
        print("\nVERIFIED OPEN LEADS")
        for item in result["opportunities"]:
            window = item["window"]
            cite = item["citations"][0]
            where = cite.get("local_url") or cite["url"]
            print(f"  {STATUS_MARK.get(item['status'], '')} {item['title']} - {item['host']}")
            print(f"             window {window['start']} -> {window['end']} | {item['eligibility']}")
            print(f"             source {cite['url']} (as of {item['as_of']}) -> {where}")

    checked = result.get("checked_courses", [])
    if checked:
        print("\nCHECKED AND NOT RECOMMENDED")
        for item in checked:
            print(f"  {STATUS_MARK.get(item['status'], '')} {item['code']} {item['title']}: {item['reasons'][0]['text']}")

    unconfirmed = result.get("checked_opportunities", [])
    if unconfirmed:
        print("\nLEADS THAT CANNOT BE CONFIRMED")
        for item in unconfirmed:
            print(f"  {STATUS_MARK.get(item['status'], '')} {item['title']}: {item['reasons'][0]['text']}")

    print("\nNEXT STEPS")
    for step in result["next_steps"]:
        print(f"  - {step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
