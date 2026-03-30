#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTROLLER_ROOT="/Users/denis/programming/autowork/ru-skill"
PYTHON_BIN="${AUTOWORK_PYTHON_BIN:-python3}"

cd "$ROOT_DIR"
PYTHONPATH="$CONTROLLER_ROOT/src" "$PYTHON_BIN" -m repo_autowork.cli project-run --repo "$ROOT_DIR" "$@"
