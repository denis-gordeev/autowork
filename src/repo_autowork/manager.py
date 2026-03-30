from __future__ import annotations

import json
import re
import shlex
import subprocess
from pathlib import Path

from .config import Config, read_json, write_json
from .forge import detect_fork, list_open_work_items, merge_upstream, repo_snapshot
from .models import ProjectRecord, State, content_hash, utc_now_iso
from .telegram import TelegramError, create_topic, send_message


CRON_BLOCK_START = "# repo-autowork managed block start"
CRON_BLOCK_END = "# repo-autowork managed block end"


PROJECT_AUTOWORK = """#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
CONTROLLER_ROOT="{controller_root}"
PYTHON_BIN="${{AUTOWORK_PYTHON_BIN:-{python_bin}}}"

cd "$CONTROLLER_ROOT"
PYTHONPATH="$CONTROLLER_ROOT/src" "$PYTHON_BIN" -m repo_autowork.cli project-run --repo "$REPO_DIR" "$@"
"""


def slugify(value: str) -> str:
    lowered = value.lower().strip()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    return lowered.strip("-") or "repo"


def load_state(config: Config) -> State:
    if not config.state_path.exists():
        return State()
    return State.from_dict(read_json(config.state_path))


def save_state(config: Config, state: State) -> None:
    state.updated_at = utc_now_iso()
    write_json(config.state_path, state.to_dict())


def current_projects(state: State) -> list[ProjectRecord]:
    return state.projects


def _project_by_repo_path(state: State, repo_dir: Path) -> ProjectRecord | None:
    repo_path = str(repo_dir.resolve())
    for project in state.projects:
        if str(Path(project.repo_path).resolve()) == repo_path:
            return project
    return None


def discover_repo_dirs(config: Config) -> list[Path]:
    if not config.repos_root.exists():
        return []
    discovered: list[Path] = []
    for child in sorted(config.repos_root.iterdir()):
        if not child.is_dir():
            continue
        if child.resolve() == config.project_root.resolve():
            continue
        if (child / ".git").is_dir():
            discovered.append(child)
    return discovered


def ensure_project_record(config: Config, state: State, repo_dir: Path) -> ProjectRecord:
    existing = _project_by_repo_path(state, repo_dir)
    snapshot = repo_snapshot(repo_dir)
    is_fork, upstream_url, upstream_branch = detect_fork(
        repo_dir,
        str(snapshot["origin_url"]),
        str(snapshot["forge_kind"]),
    )
    if existing is None:
        project = ProjectRecord(
            slug=slugify(repo_dir.name),
            name=repo_dir.name,
            repo_path=str(repo_dir.resolve()),
            origin_url=str(snapshot["origin_url"]),
            forge_kind=str(snapshot["forge_kind"]),
            default_branch=str(snapshot["default_branch"]),
            current_branch=str(snapshot["current_branch"]),
            is_fork=is_fork,
            upstream_url=upstream_url,
            upstream_default_branch=upstream_branch,
            daily_runs_target=config.autowork_default_daily_runs,
            tg_folder=str((config.tg_root / slugify(repo_dir.name)).resolve()),
        )
        state.projects.append(project)
        return project

    existing.origin_url = str(snapshot["origin_url"])
    existing.forge_kind = str(snapshot["forge_kind"])
    existing.default_branch = str(snapshot["default_branch"])
    existing.current_branch = str(snapshot["current_branch"])
    existing.is_fork = is_fork
    existing.upstream_url = upstream_url
    existing.upstream_default_branch = upstream_branch
    existing.updated_at = utc_now_iso()
    if not existing.tg_folder:
        existing.tg_folder = str((config.tg_root / existing.slug).resolve())
    return existing


def project_metadata_dir(project: ProjectRecord) -> Path:
    return Path(project.repo_path) / ".autowork"


def ensure_project_files(config: Config, project: ProjectRecord) -> None:
    repo_dir = Path(project.repo_path)
    repo_dir.mkdir(parents=True, exist_ok=True)
    autowork_path = repo_dir / "autowork.sh"
    autowork_path.write_text(
        PROJECT_AUTOWORK.format(
            controller_root=str(config.project_root.resolve()),
            python_bin=config.autowork_python_bin,
        ),
        encoding="utf-8",
    )
    autowork_path.chmod(0o755)

    metadata_dir = project_metadata_dir(project)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    (metadata_dir / "project.env").write_text(
        "\n".join(
            [
                f"AUTOWORK_CONTROLLER_ROOT={config.project_root.resolve()}",
                f"AUTOWORK_PROJECT_SLUG={project.slug}",
                f"TG_TOPIC_ID={project.telegram_topic_id or ''}",
                f"AUTOWORK_TG_DIR={project.tg_folder}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    tg_dir = Path(project.tg_folder)
    tg_dir.mkdir(parents=True, exist_ok=True)
    (tg_dir / "README.md").write_text(
        "\n".join(
            [
                f"# {project.name}",
                "",
                "Local Telegram mirror for this repository.",
                f"- Repo: {project.repo_path}",
                f"- Topic ID: {project.telegram_topic_id or 'pending'}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    write_json(
        tg_dir / "meta.json",
        {
            "name": project.name,
            "slug": project.slug,
            "repo_path": project.repo_path,
            "telegram_topic_id": project.telegram_topic_id,
            "origin_url": project.origin_url,
            "updated_at": utc_now_iso(),
        },
    )


def ensure_project_topic(config: Config, project: ProjectRecord, dry_run: bool = False) -> None:
    if project.telegram_topic_id is not None:
        return
    if not (config.telegram_bot_token and config.telegram_chat_id):
        if "Telegram is not configured." not in project.notes:
            project.notes.append("Telegram is not configured.")
        return
    if dry_run:
        if "Dry-run: Telegram topic creation skipped." not in project.notes:
            project.notes.append("Dry-run: Telegram topic creation skipped.")
        return
    try:
        project.telegram_topic_id = create_topic(config, project.name)
        if project.telegram_topic_id is not None:
            send_message(
                config,
                f"Project linked: {project.name}\nRepo: {project.repo_path}",
                project.telegram_topic_id,
            )
    except TelegramError as exc:
        project.notes.append(f"Telegram setup failed: {exc}")


def sync_projects(config: Config, state: State, dry_run: bool = False) -> list[ProjectRecord]:
    active_paths = {str(path.resolve()) for path in discover_repo_dirs(config)}
    retained: list[ProjectRecord] = []
    known = {str(Path(project.repo_path).resolve()): project for project in state.projects}
    for repo_dir_str in sorted(active_paths):
        repo_dir = Path(repo_dir_str)
        project = known.get(repo_dir_str) or ensure_project_record(config, state, repo_dir)
        if project not in state.projects:
            state.projects.append(project)
        project = ensure_project_record(config, state, repo_dir)
        ensure_project_topic(config, project, dry_run=dry_run)
        ensure_project_files(config, project)
        retained.append(project)
    state.projects = retained
    save_state(config, state)
    return retained


def read_optional_file(path: Path, limit: int = 12000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return text[:limit]


def collect_todos(repo_dir: Path) -> list[str]:
    items: list[str] = []
    for candidate in [repo_dir / "TODO.md", repo_dir / "README.md"]:
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            lower = stripped.lower()
            if "todo" in lower or stripped.startswith("- [ ]") or stripped.startswith("* [ ]"):
                items.append(stripped)
            if len(items) >= 20:
                return items
    return items


def project_prompt(project: ProjectRecord, repo_dir: Path, work_items: dict[str, list[str]], upstream_note: str) -> str:
    instructions = read_optional_file(repo_dir / "AUTOWORK_INSTRUCTIONS.md")
    todo_items = collect_todos(repo_dir)
    prompt_lines = [
        f"Automation round for repository `{project.name}`.",
        "Priority order:",
        "1. AUTOWORK_INSTRUCTIONS.md, if it exists.",
        "2. Open issues and open PRs/MRs.",
        "3. TODO items from README.md and TODO.md.",
        "Work directly in this repository.",
        "Run relevant checks after making changes.",
        "If the repository is ready for it, commit and push the result.",
        f"Current branch: {project.current_branch}",
        f"Default branch: {project.default_branch}",
        f"Origin: {project.origin_url or 'missing'}",
    ]
    if project.is_fork:
        prompt_lines.append(f"Fork status: yes. {upstream_note}")
    if instructions:
        prompt_lines.extend(["", "AUTOWORK_INSTRUCTIONS.md:", instructions])
    if work_items["issues"]:
        prompt_lines.extend(["", "Open issues:"])
        prompt_lines.extend(f"- {item}" for item in work_items["issues"])
    if work_items["reviews"]:
        prompt_lines.extend(["", "Open PRs/MRs:"])
        prompt_lines.extend(f"- {item}" for item in work_items["reviews"])
    if todo_items:
        prompt_lines.extend(["", "TODOs from local docs:"])
        prompt_lines.extend(f"- {item}" for item in todo_items)
    if work_items["notes"]:
        prompt_lines.extend(["", "Forge lookup notes:"])
        prompt_lines.extend(f"- {item}" for item in work_items["notes"])
    if not instructions and not work_items["issues"] and not work_items["reviews"] and not todo_items:
        prompt_lines.extend(
            [
                "",
                "No explicit work queue was found. Inspect the repository, identify the highest-value next task, implement it, and update docs if needed.",
            ]
        )
    return "\n".join(prompt_lines)


def run_base_command(config: Config, repo_dir: Path, prompt: str) -> subprocess.CompletedProcess:
    command = shlex.split(config.autowork_base_command)
    if not command:
        raise RuntimeError("AUTOWORK_BASE_COMMAND is empty.")
    return subprocess.run(
        [*command, prompt],
        cwd=repo_dir,
        text=True,
        capture_output=True,
    )


def send_project_update(config: Config, project: ProjectRecord, text: str, dry_run: bool = False) -> None:
    if project.telegram_topic_id is None:
        return
    message_hash = content_hash(text)
    if project.last_telegram_report_hash == message_hash:
        return
    if dry_run:
        return
    try:
        send_message(config, text, project.telegram_topic_id)
        project.last_telegram_report_hash = message_hash
    except TelegramError as exc:
        project.notes.append(f"Telegram update failed: {exc}")


def review_summary(config: Config, state: State) -> str:
    lines = [
        f"Controller repo: {config.project_root}",
        f"Managed repos root: {config.repos_root}",
        f"Telegram mirror root: {config.tg_root}",
        f"Managed repositories: {len(state.projects)}",
    ]
    for project in state.projects:
        lines.append(
            f"- {project.name} | branch={project.current_branch} | runs/day={project.daily_runs_target} | fork={'yes' if project.is_fork else 'no'} | topic={project.telegram_topic_id or 'pending'}"
        )
    return "\n".join(lines)


def cron_hours_for_runs(daily_runs_target: int) -> list[int]:
    runs = max(1, daily_runs_target)
    slots = list(range(10, 21))
    if runs >= len(slots):
        return slots
    indices = [round(i * (len(slots) - 1) / max(1, runs - 1)) for i in range(runs)]
    ordered: list[int] = []
    for idx in indices:
        hour = slots[idx]
        if hour not in ordered:
            ordered.append(hour)
    for hour in slots:
        if len(ordered) >= runs:
            break
        if hour not in ordered:
            ordered.append(hour)
    return sorted(ordered)


def render_crontab(config: Config, state: State) -> str:
    lines = [CRON_BLOCK_START]
    controller_log = config.project_root / "autowork.log"
    for hour in config.autowork_portfolio_hours:
        lines.append(f"0 {hour} * * * cd {config.project_root} && ./autowork.sh >> {controller_log} 2>&1")
    for project in state.projects:
        repo_dir = Path(project.repo_path)
        log_path = repo_dir / "autowork.log"
        for hour in cron_hours_for_runs(project.daily_runs_target):
            lines.append(f"0 {hour} * * * cd {repo_dir} && ./autowork.sh >> {log_path} 2>&1")
    lines.append(CRON_BLOCK_END)
    return "\n".join(lines)


def write_telegram_mirror(project: ProjectRecord, update: dict) -> Path:
    tg_dir = Path(project.tg_folder)
    tg_dir.mkdir(parents=True, exist_ok=True)
    inbox_dir = Path(project.repo_path) / "inbox" / "telegram"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    message = update["message"]
    payload = {
        "project": project.name,
        "update_id": update["update_id"],
        "message_id": message.get("message_id"),
        "thread_id": message.get("message_thread_id"),
        "from": {
            "id": message.get("from", {}).get("id"),
            "username": message.get("from", {}).get("username"),
            "first_name": message.get("from", {}).get("first_name"),
            "last_name": message.get("from", {}).get("last_name"),
        },
        "date": message.get("date"),
        "text": message.get("text") or message.get("caption") or "",
    }
    for base in [tg_dir, inbox_dir]:
        journal = base / "messages.jsonl"
        with journal.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        write_json(base / f"update-{update['update_id']}.json", payload)
    return inbox_dir / f"update-{update['update_id']}.json"


def project_run_once(config: Config, project: ProjectRecord, dry_run: bool = False) -> subprocess.CompletedProcess:
    repo_dir = Path(project.repo_path)
    upstream_note = "Upstream merge not needed."
    if project.is_fork and project.upstream_url and project.upstream_default_branch:
        upstream_note = merge_upstream(repo_dir, project.upstream_default_branch, dry_run=dry_run)
    work_items = list_open_work_items(repo_dir, project.forge_kind)
    prompt = project_prompt(project, repo_dir, work_items, upstream_note)
    if dry_run:
        return subprocess.CompletedProcess(
            args=shlex.split(config.autowork_base_command),
            returncode=0,
            stdout=prompt,
            stderr="",
        )
    return run_base_command(config, repo_dir, prompt)
