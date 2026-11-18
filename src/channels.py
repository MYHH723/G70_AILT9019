"""Real places to look for opportunities.

The pilot cannot ingest vacancy pages - permission is unconfirmed - so instead of
inventing listings it points at the places that actually publish them: the
university careers portals, the inter-university system, the research scheme
pages, and two commercial job boards.

Two rules keep this honest:

* a channel is a **doorway, not a vacancy**. Every entry says so, and none is
  ever presented as evidence that a position is open;
* only channels that tolerate an automated request are probed. The ones that
  block bots (JobsDB, LinkedIn, Cyberport) are offered as links with
  ``probe: false``, because reporting them as "unreachable" would be a lie about
  a site that is working fine for a human.

Standard library only, like the rest of the pilot.
"""

from __future__ import annotations

import json
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterable

from .livecheck import probe

DATA = Path(__file__).resolve().parent.parent / "data" / "channels.json"

KIND_LABEL = {
    "hku": "University sources",
    "research": "Research and innovation schemes",
    "commercial": "Commercial job boards",
}

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
CACHE_TTL = 600.0


def _load() -> dict[str, Any]:
    with open(DATA, encoding="utf-8") as handle:
        return json.load(handle)


def all_channels() -> list[dict[str, Any]]:
    return _load()["channels"]


def check(timeout: float = 8.0, use_cache: bool = True) -> dict[str, dict[str, Any]]:
    """Probe the channels that allow it, concurrently."""
    import time

    results: dict[str, dict[str, Any]] = {}
    pending: list[dict[str, Any]] = []
    for channel in all_channels():
        if not channel.get("probe"):
            continue
        cached = _CACHE.get(channel["url"])
        if use_cache and cached and (time.monotonic() - cached[0]) < CACHE_TTL:
            results[channel["id"]] = cached[1]
        else:
            pending.append(channel)

    # These are deliberate, named external hosts: the channel directory links to
    # JIJIS, HKSTP and the job boards, so the probe must be allowed to reach them
    # without widening the allowlist used for official HKU pages.
    extras = tuple({urllib.parse.urlsplit(c["url"]).hostname or "" for c in all_channels()})

    def one(channel: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        # No retry here, unlike the official pages: a portal that is slow to
        # answer is not a finding, and doubling the wait makes the button feel
        # broken. The status is reported as it came back.
        return channel["id"], probe(channel["url"], timeout=timeout, extra_hosts=extras)

    if pending:
        with ThreadPoolExecutor(max_workers=min(6, len(pending))) as pool:
            for channel_id, row in pool.map(one, pending):
                _CACHE[row["url"]] = (time.monotonic(), row)
                results[channel_id] = row
    return results


def attach(plan: dict[str, Any], live: bool = False, timeout: float = 8.0) -> dict[str, Any]:
    """Add the channel directory to a plan, with live status when asked."""
    checks = check(timeout=timeout) if live else {}
    rows: list[dict[str, Any]] = []
    for channel in all_channels():
        row = {
            "id": channel["id"],
            "kind": channel["kind"],
            "kind_label": KIND_LABEL.get(channel["kind"], channel["kind"]),
            "label": channel["label"],
            "url": channel["url"],
            "covers": channel["covers"],
            "login_required": channel["login_required"],
            "probe": channel["probe"],
            "note": channel["note"],
            "live": None,
        }
        if live:
            hit = checks.get(channel["id"])
            if hit:
                row["live"] = {
                    "status": hit.get("status"),
                    "http_status": hit.get("http_status"),
                    "checked_at": hit.get("checked_at"),
                    "detail": hit.get("detail"),
                }
            else:
                row["live"] = {"status": "not_checked", "detail": "this site blocks automated requests"}
        rows.append(row)

    plan["channels"] = rows
    plan["channels_note"] = (
        "These are doorways, not vacancies: none of them is evidence that a position is open. "
        "The pilot has no permission to ingest vacancy pages, so it points at the sources instead."
    )
    return plan


def markdown(rows: Iterable[dict[str, Any]]) -> str:
    lines = ["| Channel | What it covers | Access | Checked |", "|---|---|---|---|"]
    for row in rows:
        access = "HKU login required" if row["login_required"] else "open"
        live = row.get("live")
        if not live:
            checked = "-"
        elif live.get("status") == "not_checked":
            checked = "not checked (blocks bots)"
        else:
            checked = f"{live.get('status')} ({live.get('http_status') or '-'})"
        lines.append(f"| {row['label']} - {row['url']} | {row['covers']} | {access} | {checked} |")
    return "\n".join(lines)
