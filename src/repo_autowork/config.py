from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Config:
    project_root: Path
    state_path: Path
    repos_root: Path
    tg_root: Path
    github_owner: Optional[str]
    github_visibility: str
    telegram_bot_token: Optional[str]
    telegram_chat_id: Optional[str]
    autowork_base_command: str
    autowork_default_daily_runs: int
    autowork_portfolio_hours: list[int]
    autowork_python_bin: str


def load_dotenv(project_root: Path) -> None:
    env_path = project_root / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _parse_int(value: str, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _parse_hours(raw: str) -> list[int]:
    hours: list[int] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            value = int(item)
        except ValueError:
            continue
        if 0 <= value <= 23 and value not in hours:
            hours.append(value)
    return hours or [10, 20]


def build_config(project_root: Path, repos_root: Optional[str] = None) -> Config:
    load_dotenv(project_root)
    state_dir = project_root / "data"
    state_dir.mkdir(parents=True, exist_ok=True)
    resolved_repos_root = Path(
        repos_root
        or os.getenv("AUTOWORK_REPOS_ROOT")
        or str(project_root.parent)
    ).expanduser()
    resolved_tg_root = Path(
        os.getenv("AUTOWORK_TG_ROOT") or str(project_root / "tg")
    ).expanduser()
    resolved_tg_root.mkdir(parents=True, exist_ok=True)
    return Config(
        project_root=project_root,
        state_path=state_dir / "state.json",
        repos_root=resolved_repos_root,
        tg_root=resolved_tg_root,
        github_owner=os.getenv("GITHUB_OWNER"),
        github_visibility=os.getenv("GITHUB_VISIBILITY", "private"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        autowork_base_command=os.getenv("AUTOWORK_BASE_COMMAND", "codex exec --yolo"),
        autowork_default_daily_runs=_parse_int(os.getenv("AUTOWORK_DEFAULT_DAILY_RUNS", "2"), 2),
        autowork_portfolio_hours=_parse_hours(os.getenv("AUTOWORK_PORTFOLIO_HOURS", "10,20")),
        autowork_python_bin=os.getenv("AUTOWORK_PYTHON_BIN", "python3"),
    )


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
