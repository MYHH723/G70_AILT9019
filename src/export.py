"""Markdown export of a plan.

A student who has just been handed a plan should be able to keep it. The export
carries the same three things the interface shows - the recommendation, the
reason, and the source with its as-of date - because an exported plan that drops
the citations is exactly the unverifiable artefact the pilot exists to avoid.

Plain text on purpose: no PDF engine, no dependency, and it pastes into an email
to a programme office.
"""

from __future__ import annotations

from typing import Any

STATUS_TEXT = {
    "eligible": "eligible",
    "blocked": "blocked",
    "restricted": "restricted",
    "not_offered": "not offered",
    "needs_verification": "needs verification",
    "excluded": "excluded",
    "completed": "already completed",
    "deferred": "deferred",
    "open": "open",
    "closed": "closed",
    "ineligible": "ineligible",
    "unverifiable": "cannot verify (login required)",
    "snapshot_verify_manually": "snapshot - verify manually",
    "info_only": "information page only",
    "scheme": "scheme information",
    "quarantined": "held for manual review",
}


def _cite(item: dict[str, Any], base_url: str = "") -> str:
    citations = item.get("citations") or []
    if not citations:
        return "no source"
    first = citations[0]
    if not first.get("url"):
        return "no source"
    recorded = f"{first['url']} (as of {first.get('as_of') or 'unknown'})"
    if first.get("local_url") and base_url:
        return f"{recorded} - fixture record: {base_url.rstrip('/')}{first['local_url']}"
    return recorded


def _official(item: dict[str, Any]) -> str:
    """The real official page for this item, if the plan checked one."""
    official = item.get("official")
    if not official:
        return ""
    return (
        f"- Official page: {official['label']} - {official['url']} "
        f"(live check: {official.get('status')} at {official.get('checked_at')})"
    )


def to_markdown(result: dict[str, Any], query: str = "", base_url: str = "") -> str:
    lines = [
        "# HKU Pathfinder plan",
        "",
        f"- As of: {result.get('as_of')}",
        f"- Mode: {result.get('mode')}",
        f"- Status: {result.get('status')}",
    ]
    if query:
        lines.append(f"- Question: {query}")
    lines += [
        "",
        "> Schedule-planning support, not personal course-selection advice. Prerequisites, eligibility and "
        "deadlines are quoted from the cited source; anything labelled 'agent reading' is the pilot's own "
        "interpretation. The decision remains with you and the official advisers named below.",
        "",
        "> Source links in this build point at synthetic fixture records. The recorded "
        "`fixtures.pathfinder.local` address is a reserved host and does not resolve; where a "
        "'fixture record' address is given, it is served by the app while the app is running.",
        "",
        "## Summary",
        "",
        result.get("summary", ""),
    ]

    if result.get("notices"):
        lines += ["", "### Notices", ""]
        lines += [f"- {n}" for n in result["notices"]]

    if result.get("refused_actions"):
        lines += ["", "### Not performed", ""]
        for item in result["refused_actions"]:
            lines.append(f"- **{item['action']}** - {item['reason']} Manual route: {item['manual_route']}")

    courses = result.get("courses") or []
    lines += ["", "## Recommended courses", ""]
    if not courses:
        lines.append("_No course passed the documented checks for this request._")
    for item in courses:
        lines.append("")
        lines.append(f"### {item['code']} - {item['title']}  \n_Status: {STATUS_TEXT.get(item['status'], item['status'])}_")
        for reason in item["reasons"]:
            lines.append(f"- ({reason.get('label', 'note')}) {reason['text']}")
        lines.append(f"- Source: {_cite(item, base_url)}")
        if _official(item):
            lines.append(_official(item))

    leads = result.get("opportunities") or []
    lines += ["", "## Opportunity leads (verified open)", ""]
    if not leads:
        lines.append("_No opportunity could be verified as currently open._")
    for item in leads:
        window = item.get("window") or {}
        lines.append("")
        lines.append(f"### {item['title']}  \n_Status: {STATUS_TEXT.get(item['status'], item['status'])}_")
        lines.append(f"- Host: {item.get('host') or 'not stated'}")
        lines.append(f"- Application window: {window.get('start') or 'not stated'} to {window.get('end') or 'not stated'}")
        if item.get("eligibility"):
            lines.append(f"- Eligibility: {item['eligibility']}")
        for reason in item["reasons"]:
            lines.append(f"- ({reason.get('label', 'note')}) {reason['text']}")
        lines.append(f"- Source: {_cite(item, base_url)}")
        if _official(item):
            lines.append(_official(item))

    live = result.get("live") or {}
    if live.get("sources"):
        lines += ["", "## Official pages checked", "",
                  f"Checked at {live.get('checked_at')}. Status and quotes below come from the page as it was "
                  "during this request; course-level facts in this plan still come from the pilot fixtures.", ""]
        for source in live["sources"]:
            line = f"- **{source['label']}** - {source['url']} - {source['status']}"
            if source.get("http_status"):
                line += f" (HTTP {source['http_status']})"
            line += f", checked {source.get('checked_at')}"
            lines.append(line)
            if source.get("quote"):
                lines.append(f"  - quoted: \"{source['quote']}\"")
            if source.get("note"):
                lines.append(f"  - (agent reading) {source['note']}")

    channels = result.get("channels") or []
    if channels:
        lines += ["", "## Where to look", "", result.get("channels_note", ""), ""]
        current_kind = None
        for channel in channels:
            if channel["kind_label"] != current_kind:
                current_kind = channel["kind_label"]
                lines += [f"### {current_kind}", ""]
            access = " - HKU login required" if channel["login_required"] else ""
            lines.append(f"- **{channel['label']}** - {channel['url']}{access}")
            lines.append(f"  - {channel['covers']}")
            lines.append(f"  - (agent reading) {channel['note']}")
        lines.append("")

    checked = result.get("checked_courses") or []
    if checked:
        lines += ["", "## Checked and not recommended", ""]
        for item in checked:
            reason = item["reasons"][0]["text"] if item["reasons"] else ""
            lines.append(f"- **{item['code']}** ({STATUS_TEXT.get(item['status'], item['status'])}) - {reason}")

    unconfirmed = result.get("checked_opportunities") or []
    if unconfirmed:
        lines += ["", "## Leads that cannot be confirmed", ""]
        for item in unconfirmed:
            reason = item["reasons"][0]["text"] if item["reasons"] else ""
            lines.append(f"- **{item['title']}** ({STATUS_TEXT.get(item['status'], item['status'])}) - {reason}")

    steps = result.get("next_steps") or []
    if steps:
        lines += ["", "## Next steps", ""]
        lines += [f"{i}. {s}" for i, s in enumerate(steps, 1)]

    lines += [
        "",
        "---",
        "",
        "Generated by the HKU Pathfinder pilot. The course and opportunity records in this build are "
        "synthetic fixtures, not official HKU pages; every recommendation above still points at the source "
        "it came from, so check that page before acting. Final authority rests with the programme office, "
        "AASO and CEDARS advisers.",
        "",
    ]
    return "\n".join(lines)
