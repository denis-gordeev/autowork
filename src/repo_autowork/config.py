from __future__ import annotations

import json
import os
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

RUNTIME_PATH_ENTRIES = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
]


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
    autowork_include_controller: bool
    autowork_python_bin: str


def load_env_file(path: Path, override: bool = False) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if override or key not in os.environ:
            os.environ[key] = value


def load_dotenv(project_root: Path) -> None:
    env_path = project_root / ".env"
    if not env_path.exists():
        return
    load_env_file(env_path, override=False)


def project_runtime_env_path(repo_root: Path) -> Path:
    return repo_root / ".autowork" / "project.env"


def hydrate_project_runtime_env(repo_root: Path) -> Path:
    env_path = project_runtime_env_path(repo_root)
    load_env_file(env_path, override=True)
    return env_path


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


def _parse_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def ensure_runtime_path() -> str:
    current_entries = [entry for entry in os.environ.get("PATH", "").split(":") if entry]
    merged = [entry for entry in RUNTIME_PATH_ENTRIES if entry not in current_entries]
    merged.extend(current_entries)
    runtime_path = ":".join(merged)
    os.environ["PATH"] = runtime_path
    return runtime_path


def resolve_base_command(raw: str) -> str:
    parts = shlex.split(raw)
    if not parts:
        return raw
    resolved = shutil.which(parts[0])
    if not resolved and parts[0] == "codex":
        for candidate in ["/opt/homebrew/bin/codex", "/usr/local/bin/codex"]:
            if Path(candidate).exists():
                resolved = candidate
                break
    if not resolved:
        return raw
    parts[0] = resolved
    return shlex.join(parts)


def build_config(project_root: Path, repos_root: Optional[str] = None) -> Config:
    ensure_runtime_path()
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
        autowork_base_command=resolve_base_command(os.getenv("AUTOWORK_BASE_COMMAND", "codex exec --yolo")),
        autowork_default_daily_runs=_parse_int(os.getenv("AUTOWORK_DEFAULT_DAILY_RUNS", "2"), 2),
        autowork_portfolio_hours=_parse_hours(os.getenv("AUTOWORK_PORTFOLIO_HOURS", "10,20")),
        autowork_include_controller=_parse_bool(os.getenv("AUTOWORK_INCLUDE_CONTROLLER"), False),
        autowork_python_bin=os.getenv("AUTOWORK_PYTHON_BIN", "python3"),
    )


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
