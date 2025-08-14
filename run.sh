#!/bin/bash
set -euo pipefail

# Resolve the directory of this script, even when invoked as a Login Item
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Prefer project-local virtual environment
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  PY="$SCRIPT_DIR/.venv/bin/python"
elif [ -x "$SCRIPT_DIR/venv/bin/python" ]; then
  PY="$SCRIPT_DIR/venv/bin/python"
else
  # Fallback to system python3 (expects deps to be installed there)
  PY="$(command -v python3 || true)"
fi

if [ -z "${PY:-}" ]; then
  echo "Error: Could not find a Python interpreter. Create a venv or install python3."
  exit 1
fi

exec "$PY" "$SCRIPT_DIR/whisper-dictation.py" "$@"
