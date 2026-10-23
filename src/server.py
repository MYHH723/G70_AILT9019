"""Local web interface for the HKU Pathfinder pilot.

Standard library only: no framework, no build step, no API key. Run with
``python3 -m src.server`` and open http://127.0.0.1:8765.
"""

from __future__ import annotations

import json
import mimetypes
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .corpus import DATA_DIR, get_corpus
from .planner import plan

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
FEEDBACK_FILE = DATA_DIR / "feedback.jsonl"
HOST, PORT = "127.0.0.1", 8765


def _read_json(handler) -> dict:
    length = int(handler.headers.get("Content-Length") or 0)
    if not length:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def _feedback_summary() -> dict:
    if not FEEDBACK_FILE.exists():
        return {"total": 0, "helpful": 0, "not_helpful": 0, "items": {}}
    rows = [json.loads(line) for line in FEEDBACK_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    per_item: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = per_item.setdefault(row["item_id"], {"helpful": 0, "not_helpful": 0})
        bucket["helpful" if row["rating"] == "helpful" else "not_helpful"] += 1
    return {
        "total": len(rows),
        "helpful": sum(1 for r in rows if r["rating"] == "helpful"),
        "not_helpful": sum(1 for r in rows if r["rating"] != "helpful"),
        "items": per_item,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "PathfinderPilot/0.1"

    def log_message(self, fmt, *args):  # keep the terminal readable during recording
        return

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    # -- routes -----------------------------------------------------------
    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/api/health":
            corpus = get_corpus()
            return self._json(200, {"status": "ok", "corpus": corpus.stats(), "mode": "offline-fixture"})
        if path == "/api/profiles":
            data = json.loads((DATA_DIR / "example_profiles.json").read_text(encoding="utf-8"))
            return self._json(200, data)
        if path == "/api/feedback/summary":
            return self._json(200, _feedback_summary())

        target = WEB_DIR / ("index.html" if path in {"/", ""} else path.lstrip("/"))
        if not target.exists() or not target.is_file():
            return self._json(404, {"error": "not found"})
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        return self._send(200, target.read_bytes(), ctype)

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        try:
            payload = _read_json(self)
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid JSON"})

        if path == "/api/plan":
            profile = payload.get("profile") or {}
            query = (payload.get("query") or "").strip()
            if not query:
                return self._json(400, {"error": "query is required"})
            return self._json(200, plan(profile, query, get_corpus()))

        if path == "/api/feedback":
            item_id = payload.get("item_id")
            rating = payload.get("rating")
            if rating not in {"helpful", "not_helpful"} or not item_id:
                return self._json(400, {"error": "item_id and rating are required"})
            row = {
                "item_id": item_id,
                "rating": rating,
                "comment": (payload.get("comment") or "")[:280],
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            # Anonymous and profile-free by construction: no session id, no input text.
            with open(FEEDBACK_FILE, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            return self._json(200, {"ok": True, "summary": _feedback_summary()})

        return self._json(404, {"error": "not found"})


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"HKU Pathfinder pilot running at http://{HOST}:{PORT}")
    print("Mode: offline-fixture (no API key, no network). Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
