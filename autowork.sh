#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PYTHONPATH=src python3 -m repo_autowork.cli telegram-sync "$@"
PYTHONPATH=src python3 -m repo_autowork.cli run "$@"
PYTHONPATH=src python3 -m repo_autowork.cli review "$@"
