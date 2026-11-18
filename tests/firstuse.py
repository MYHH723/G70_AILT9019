"""First-use check on a clean clone.

The hand-off criterion is "a marker can clone the repository and reach a cited
result without editing code". This script tests the mechanical half of that:
the documented commands exist, the code imports nothing outside the standard
library, the CLI produces a citation, the interface answers over HTTP, the
export works, and the evaluation gate passes.

    python3 -m tests.firstuse --clone https://github.com/MYHH723/G70_AILT9019.git
    python3 -m tests.firstuse            # checks the working tree instead

Writes ``docs/firstuse_<date>.md`` and exits non-zero on any failure, so the
record cannot be produced from a broken tree.

The half it cannot test is whether a person finds the interface understandable.
That is what ``tests/walkthrough.py`` records.
"""

from __future__ import annotations

import argparse
import ast
import datetime as _dt
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
QUERY = "I am a Year 2 student interested in data science. What should I study next?"


def _python() -> str:
    return sys.executable


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": ok, "detail": detail}


def _stdlib_modules() -> set[str] | None:
    names = getattr(sys, "stdlib_module_names", None)
    return set(names) if names else None


def check_imports(root: Path) -> dict:
    stdlib = _stdlib_modules()
    local = {"src", "tests"}
    third_party: list[str] = []
    scanned = 0
    for path in sorted(list((root / "src").glob("*.py")) + list((root / "tests").glob("*.py"))):
        scanned += 1
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]] if node.level == 0 else []
            else:
                continue
            for name in names:
                if not name or name in local:
                    continue
                if stdlib is None:
                    continue
                if name not in stdlib and name not in third_party:
                    third_party.append(name)
    if stdlib is None:
        return _check("no third-party imports", True, f"{scanned} files scanned; runtime cannot list stdlib, check skipped")
    return _check(
        "no third-party imports",
        not third_party,
        f"{scanned} files scanned, imports outside the standard library: {third_party or 'none'}",
    )


def check_readme(root: Path) -> dict:
    readme = root / "README.md"
    if not readme.exists():
        return _check("README documents the run steps", False, "README.md missing")
    text = readme.read_text(encoding="utf-8")
    needed = ["./run.sh", "python3 -m src.cli", "python3 -m tests.run_tests"]
    missing = [n for n in needed if n not in text]
    return _check(
        "README documents the run steps",
        not missing,
        "all three commands documented" if not missing else f"missing: {missing}",
    )


def check_cli(root: Path) -> dict:
    proc = subprocess.run(
        [_python(), "-m", "src.cli", QUERY], cwd=root, capture_output=True, text=True, timeout=120
    )
    out = proc.stdout
    ok = proc.returncode == 0 and "source https://" in out and "as of" in out
    detail = (
        f"exit {proc.returncode}; citation present: {'source https://' in out}; "
        f"as-of present: {'as of' in out}"
    )
    if not ok:
        detail += f"; stderr: {proc.stderr.strip()[:200]}"
    return _check("CLI returns a cited plan", ok, detail)


def check_server(root: Path) -> dict:
    port = _free_port()
    env = {**os.environ, "PATHFINDER_PORT": str(port), "PATHFINDER_HOST": "127.0.0.1"}
    proc = subprocess.Popen(
        [_python(), "-m", "src.server"], cwd=root, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 20
        health = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"{base}/api/health", timeout=2) as response:
                    health = json.loads(response.read())
                break
            except (urllib.error.URLError, OSError):
                time.sleep(0.25)
        if health is None:
            return _check("interface answers over HTTP", False, "server did not become ready in 20s")

        payload = json.dumps(
            {
                "profile": {
                    "programme": "BEng(CS) 2023-24 intake",
                    "cohort": "2023-24",
                    "year": 2,
                    "completed": ["COMP1117", "MATH1013"],
                    "interests": ["data science", "machine learning"],
                    "target_semester": "S1",
                    "workload_ceiling": 4,
                    "opportunity_types": ["research", "internship"],
                },
                "query": QUERY,
            }
        ).encode()
        request = urllib.request.Request(
            f"{base}/api/plan", data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            plan = json.loads(response.read())
        cited = [c for c in plan.get("courses", []) if (c.get("citations") or [{}])[0].get("url")]
        missing_route = [c["code"] for c in plan.get("courses", [])
                         if not (c.get("citations") or [{}])[0].get("local_url")]
        route_ok = False
        if cited:
            route = cited[0]["citations"][0]["local_url"]
            with urllib.request.urlopen(f"{base}{route}", timeout=20) as response:
                fixture_page = response.read().decode("utf-8")
            route_ok = response.status == 200 and "Synthetic fixture record" in fixture_page
        ok = response.status == 200 and bool(cited) and not missing_route and route_ok
        detail = (
            f"HTTP {response.status}, status={plan.get('status')}, {len(cited)} cited course(s); "
            f"dead citation links: {missing_route or 'none'}; fixture page resolves: {route_ok}"
        )

        export_request = urllib.request.Request(
            f"{base}/api/export", data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(export_request, timeout=20) as response:
            body = response.read().decode("utf-8")
        export_ok = "# HKU Pathfinder plan" in body and "Source: https://" in body

        with urllib.request.urlopen(f"{base}/", timeout=20) as response:
            page = response.read().decode("utf-8")
        page_ok = "HKU Pathfinder" in page and "Download this plan" in page
        return _check(
            "interface answers over HTTP",
            ok and export_ok and page_ok,
            detail + f"; export contains citations: {export_ok}; export button served: {page_ok}",
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def check_suite(root: Path) -> dict:
    proc = subprocess.run(
        [_python(), "-m", "tests.run_tests", "--gate"], cwd=root, capture_output=True, text=True, timeout=300
    )
    ok = proc.returncode == 0 and "12/12" in proc.stdout
    return _check("core gate passes from this tree", ok, proc.stdout.strip().splitlines()[0] if proc.stdout else "no output")


def run(root: Path, clone_url: str | None) -> dict:
    checks: list[dict] = []
    temp = None
    if clone_url:
        temp = tempfile.mkdtemp(prefix="pathfinder-firstuse-")
        target = Path(temp) / "clone"
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, str(target)],
            capture_output=True, text=True, timeout=300,
        )
        checks.append(
            _check("clean clone succeeds", proc.returncode == 0,
                   proc.stderr.strip()[:200] or f"cloned into {target}")
        )
        if proc.returncode != 0:
            shutil.rmtree(temp, ignore_errors=True)
            return {"date": _dt.date.today().isoformat(), "root": str(root), "checks": checks}
        root = target

    try:
        checks.append(check_readme(root))
        checks.append(check_imports(root))
        checks.append(check_cli(root))
        checks.append(check_server(root))
        checks.append(check_suite(root))
    finally:
        if temp:
            shutil.rmtree(temp, ignore_errors=True)

    return {
        "date": _dt.date.today().isoformat(),
        "root": str(root),
        "clone_url": clone_url,
        "checks": checks,
    }


def render(report: dict) -> str:
    passed = sum(1 for c in report["checks"] if c["ok"])
    total = len(report["checks"])
    lines = [
        "# First-use check",
        "",
        f"Run: {report['date']}  |  Source: {report.get('clone_url') or 'working tree'}  |  "
        f"Result: **{passed}/{total} checks passed**",
        "",
        "This is the mechanical half of the hand-off criterion: clone, run, get a cited result, no code "
        "edited. The human half is in `docs/walkthrough_<date>.md`.",
        "",
        "| Check | Result | Detail |",
        "|---|---|---|",
    ]
    for c in report["checks"]:
        lines.append(f"| {c['name']} | {'PASS' if c['ok'] else 'FAIL'} | {c['detail']} |")
    lines += [
        "",
        "What this does not prove: that a new user understands the interface, that the plan is useful to "
        "them, or that the corpus is complete. It proves the documented path runs from a clean clone with "
        "no installation step.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clone", default=None, help="clone this URL into a temp directory and test that copy")
    args = parser.parse_args()

    report = run(ROOT, args.clone)
    DOCS.mkdir(parents=True, exist_ok=True)
    stamp = report["date"]
    (DOCS / f"firstuse_{stamp}.md").write_text(render(report), encoding="utf-8")

    passed = sum(1 for c in report["checks"] if c["ok"])
    total = len(report["checks"])
    print(f"firstuse: {passed}/{total} checks passed")
    for c in report["checks"]:
        if not c["ok"]:
            print(f"  FAIL {c['name']}: {c['detail']}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
