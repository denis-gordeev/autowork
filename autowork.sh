#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
CONTROLLER_ROOT="${AUTOWORK_CONTROLLER_ROOT:-/Users/denis/programming/autowork/repo-autowork}"
PYTHON_BIN="${AUTOWORK_PYTHON_BIN:-python3}"

cd "$CONTROLLER_ROOT"
if [ "$REPO_DIR" = "$CONTROLLER_ROOT" ]; then
  PYTHONPATH="$CONTROLLER_ROOT/src" "$PYTHON_BIN" -m repo_autowork.cli telegram-sync "$@"
  PYTHONPATH="$CONTROLLER_ROOT/src" "$PYTHON_BIN" -m repo_autowork.cli run "$@"
  PYTHONPATH="$CONTROLLER_ROOT/src" "$PYTHON_BIN" -m repo_autowork.cli review "$@"
else
  PYTHONPATH="$CONTROLLER_ROOT/src" "$PYTHON_BIN" -m repo_autowork.cli project-run --repo "$REPO_DIR" "$@"
fi
