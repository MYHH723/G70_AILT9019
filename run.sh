#!/usr/bin/env bash
# Launcher for the HKU Pathfinder pilot. Checks the interpreter, then starts
# the local interface. No dependencies to install.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python 3 was not found. Install Python 3.9 or newer, then re-run ./run.sh" >&2
  exit 1
fi

"$PY" - <<'EOF'
import sys
if sys.version_info < (3, 9):
    sys.exit("Python 3.9 or newer is required; found %s" % sys.version.split()[0])
EOF

echo "Starting HKU Pathfinder on http://127.0.0.1:8765"
echo "Mode: offline-fixture (no API key, no network). Press Ctrl+C to stop."
exec "$PY" -m src.server
