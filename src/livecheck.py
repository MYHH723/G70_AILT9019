"""Live, read-only reachability probe for approved official pages.

This module closes the limitation recorded in README section 6: the pilot used
to take ``fetch_status`` from a staged field on each record, so the snapshot
fallback was tested end to end but the failure itself was never real. With this
probe the status comes from an actual HTTP request.

Guard rails, because a retrieval tool that can be pointed anywhere is a
security problem rather than a feature:

* only hosts on the approved list are contacted, and a redirect is revalidated
  against the same list before it is followed;
* the resolved address must be public - a hostname that resolves to a private,
  loopback, link-local or reserved address is refused, which blocks the usual
  server-side request forgery tricks;
* only the status line, the final URL, a byte count and the elapsed time are
  kept. Page content is read to a small cap and discarded, never stored, so the
  probe cannot become a scraping or redistribution channel.

Standard library only, like the rest of the pilot.
"""

from __future__ import annotations

import hashlib
import html
import ipaddress
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Iterable

# Exact hosts, plus one suffix rule for genuine HKU subdomains. A suffix match
# on "hku.hk" alone would also accept "hku.hk.example.com", so the leading dot
# is required by ``host_allowed``.
ALLOWED_HOSTS = {
    "hku.hk",
    "www.hku.hk",
    "www4.hku.hk",
    "tl.hku.hk",
    "www.cedars.hku.hk",
    "intraweb.hku.hk",
}
ALLOWED_SUFFIXES = (".hku.hk",)

# A redirect landing on one of these path fragments means the page is behind a
# sign-in wall; the record is unverifiable, not unreachable.
LOGIN_HINTS = ("login", "signin", "sign-in", "sso", "auth", "oidc", "shibboleth")

USER_AGENT = "HKUPathfinderPilot/1.0 (read-only reachability check)"
MAX_BYTES = 64 * 1024
MAX_REDIRECTS = 4


class BlockedTarget(RuntimeError):
    """The URL is outside the approved set, or resolves to a non-public address."""


def host_allowed(host: str, extra: Iterable[str] = ()) -> bool:
    """Whether this host may be contacted.

    ``extra`` exists so a caller can widen the list for a specific, deliberate
    purpose - the channel directory links to JIJIS and HKSTP - without loosening
    the default used for official HKU pages.
    """
    host = (host or "").lower().rstrip(".")
    if not host:
        return False
    if host in ALLOWED_HOSTS or host in {h.lower() for h in extra}:
        return True
    return any(host.endswith(suffix) for suffix in ALLOWED_SUFFIXES)


def _assert_public(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise BlockedTarget(f"DNS lookup failed for {host}") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise BlockedTarget(f"{host} resolves to a non-public address ({address})")


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only if the new target is still on the approved list."""

    def __init__(self, extra: Iterable[str] = ()):
        super().__init__()
        self.extra = tuple(extra)

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        host = urllib.parse.urlsplit(newurl).hostname or ""
        if not host_allowed(host, self.extra):
            raise BlockedTarget(f"redirect left the approved hosts: {newurl}")
        _assert_public(host)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _result(url: str, status: str, *, detail: str, http_status: int | None = None,
            final_url: str | None = None, elapsed_ms: int | None = None,
            size: int | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    row = {
        "url": url,
        "status": status,
        "http_status": http_status,
        "final_url": final_url or url,
        "elapsed_ms": elapsed_ms,
        "bytes_read": size,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "detail": detail,
    }
    if extra:
        row.update(extra)
    return row


def probe(url: str, timeout: float = 12.0, max_bytes: int = MAX_BYTES,
          extra_hosts: Iterable[str] = ()) -> dict[str, Any]:
    """Check one approved URL and classify it as ok / unreachable / login_required / blocked.

    ``blocked`` is a policy refusal, not a network failure: the URL was never
    requested. It is kept separate so a caller cannot mistake a blocked target
    for a page that happens to be down.
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        return _result(url, "blocked", detail=f"scheme '{parsed.scheme}' is not allowed")
    host = parsed.hostname or ""
    if not host_allowed(host, extra_hosts):
        return _result(url, "blocked", detail=f"host '{host}' is not on the approved list")
    try:
        _assert_public(host)
    except BlockedTarget as exc:
        return _result(url, "blocked", detail=str(exc))

    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.5",
                 "Accept-Encoding": "identity"},
        method="GET",
    )
    opener = urllib.request.build_opener(_GuardedRedirect(extra_hosts))
    started = time.monotonic()

    def elapsed() -> int:
        return int((time.monotonic() - started) * 1000)

    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(max_bytes)
            final_url = response.geturl()
            code = response.status
            path = urllib.parse.urlsplit(final_url).path.lower()
            if code in (401, 403) or any(hint in path for hint in LOGIN_HINTS):
                return _result(url, "login_required", http_status=code, final_url=final_url,
                               elapsed_ms=elapsed(), size=len(body),
                               detail="page redirects to, or requires, a sign-in")
            return _result(url, "ok", http_status=code, final_url=final_url,
                           elapsed_ms=elapsed(), size=len(body),
                           detail=f"HTTP {code}, {len(body)} bytes read and discarded")
    except urllib.error.HTTPError as exc:
        code = exc.code
        status = "login_required" if code in (401, 403) else "unreachable"
        return _result(url, status, http_status=code, elapsed_ms=elapsed(),
                       detail=f"HTTP {code} {exc.reason}")
    except BlockedTarget as exc:
        return _result(url, "blocked", elapsed_ms=elapsed(), detail=str(exc))
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return _result(url, "unreachable", elapsed_ms=elapsed(),
                       detail=f"{type(exc).__name__}: {reason}")


def probe_many(urls: Iterable[str], timeout: float = 12.0) -> list[dict[str, Any]]:
    """Probe each URL in turn. Sequential on purpose: a burst looks like abuse."""
    return [probe(url, timeout=timeout) for url in urls]


def reachability_map(results: Iterable[dict[str, Any]]) -> dict[str, str]:
    """Reduce probe results to the vocabulary the planner already understands.

    ``blocked`` is deliberately reported as ``unreachable``: from the student's
    point of view a page we are not allowed to read is a page we cannot verify,
    and the snapshot fallback is the correct response either way.
    """
    mapping: dict[str, str] = {}
    for row in results:
        status = row["status"]
        mapping[row["url"]] = "ok" if status == "ok" else (
            "login_required" if status == "login_required" else "unreachable"
        )
    return mapping


# ---------------------------------------------------------------------------
# Page reading
# ---------------------------------------------------------------------------
# The probe above answers "can I reach it?". This answers "what does it say?",
# which is what a live citation needs. The same guards apply, and the text is
# returned to the caller and never written to disk: the pilot cites the page,
# it does not redistribute it.

_BLOCK = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1>", re.S | re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_TAG = re.compile(r"<[^>]+>")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_SPACE = re.compile(r"\s+")

TEXT_CAP = 20_000
DOCUMENT_READ = 2_048


def _visible_text(body: str) -> str:
    text = _COMMENT.sub(" ", body)
    text = _BLOCK.sub(" ", text)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    return _SPACE.sub(" ", text).strip()


def fetch_page(url: str, timeout: float = 15.0, max_bytes: int = 400_000,
               text_cap: int = TEXT_CAP, extra_hosts: Iterable[str] = ()) -> dict[str, Any]:
    """Read one approved page and return what a citation needs, not the page.

    Returns the final URL, the HTTP status, the page title, a bounded plain-text
    rendering, a SHA-256 of that text (for drift detection), and the elapsed
    time. Documents such as PDFs are recorded by type and size only: the pilot
    does not parse or reproduce them.
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        return _result(url, "blocked", detail=f"scheme '{parsed.scheme}' is not allowed")
    host = parsed.hostname or ""
    if not host_allowed(host, extra_hosts):
        return _result(url, "blocked", detail=f"host '{host}' is not on the approved list")
    try:
        _assert_public(host)
    except BlockedTarget as exc:
        return _result(url, "blocked", detail=str(exc))

    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.5",
                 "Accept-Encoding": "identity"},
        method="GET",
    )
    opener = urllib.request.build_opener(_GuardedRedirect(extra_hosts))
    started = time.monotonic()

    def elapsed() -> int:
        return int((time.monotonic() - started) * 1000)

    try:
        with opener.open(request, timeout=timeout) as response:
            ctype = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            is_document = ctype not in {"text/html", "text/plain", "application/xhtml+xml", ""}
            body = response.read(DOCUMENT_READ if is_document else max_bytes)
            final_url = response.geturl()
            code = response.status
            path = urllib.parse.urlsplit(final_url).path.lower()
            if code in (401, 403) or any(hint in path for hint in LOGIN_HINTS):
                return _result(url, "login_required", http_status=code, final_url=final_url,
                               elapsed_ms=elapsed(), size=len(body),
                               detail="page redirects to, or requires, a sign-in")

            if is_document:
                name = urllib.parse.unquote(path.rsplit("/", 1)[-1]) or url
                return _result(url, "ok", http_status=code, final_url=final_url,
                               elapsed_ms=elapsed(), size=len(body),
                               detail=f"{ctype or 'binary'} document, {len(body)} bytes read and discarded",
                               extra={"kind": "document", "title": name, "content_type": ctype,
                                      "text": "", "text_sha256": ""})

            charset = "utf-8"
            match = re.search(r"charset=([\w-]+)", response.headers.get("Content-Type") or "", re.I)
            if match:
                charset = match.group(1)
            try:
                page = body.decode(charset, "replace")
            except LookupError:
                page = body.decode("utf-8", "replace")

            title_match = _TITLE.search(page)
            title = _visible_text(title_match.group(1)) if title_match else ""
            text = _visible_text(page)[:text_cap]
            return _result(url, "ok", http_status=code, final_url=final_url,
                           elapsed_ms=elapsed(), size=len(body),
                           detail=f"HTTP {code}, {len(text)} chars of text extracted",
                           extra={"kind": "page", "title": title, "content_type": ctype,
                                  "text": text,
                                  "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
    except urllib.error.HTTPError as exc:
        status = "login_required" if exc.code in (401, 403) else "unreachable"
        return _result(url, status, http_status=exc.code, elapsed_ms=elapsed(),
                       detail=f"HTTP {exc.code} {exc.reason}")
    except BlockedTarget as exc:
        return _result(url, "blocked", elapsed_ms=elapsed(), detail=str(exc))
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return _result(url, "unreachable", elapsed_ms=elapsed(),
                       detail=f"{type(exc).__name__}: {reason}")


def find_sentence(text: str, needle: str, width: int = 220) -> str:
    """The sentence around the first occurrence of ``needle``, or an empty string.

    Used to quote the one line that matters - for example the sentence saying a
    deadline is set by the faculty - instead of reproducing a whole page.
    """
    if not text or not needle:
        return ""
    index = text.lower().find(needle.lower())
    if index < 0:
        return ""
    start = max(text.rfind(". ", 0, index) + 2, index - width // 2, 0)
    end = text.find(". ", index)
    end = len(text) if end < 0 else end + 1
    return text[start:min(end, start + width * 2)].strip()
