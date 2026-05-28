from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path

from .config import Config, project_runtime_env_path, read_json, write_json
from .forge import detect_fork, list_open_work_items, merge_upstream, repo_snapshot
from .models import ProjectRecord, ProjectDispatchOutcome, State, content_hash, utc_now_iso
from .telegram import TelegramError, create_topic, send_message


CRON_BLOCK_START = "# repo-autowork managed block start"
CRON_BLOCK_END = "# repo-autowork managed block end"

ROOT_AUTOWORK = """#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${{PATH:-}}"
CONTROLLER_ROOT="${{AUTOWORK_CONTROLLER_ROOT:-{controller_root}}}"
PYTHON_BIN="${{AUTOWORK_PYTHON_BIN:-{python_bin}}}"

cd "$CONTROLLER_ROOT"
if [ "$REPO_DIR" = "$CONTROLLER_ROOT" ]; then
  PYTHONPATH="$CONTROLLER_ROOT/src" "$PYTHON_BIN" -m repo_autowork.cli telegram-sync "$@"
  PYTHONPATH="$CONTROLLER_ROOT/src" "$PYTHON_BIN" -m repo_autowork.cli run "$@"
  PYTHONPATH="$CONTROLLER_ROOT/src" "$PYTHON_BIN" -m repo_autowork.cli review "$@"
else
  PYTHONPATH="$CONTROLLER_ROOT/src" "$PYTHON_BIN" -m repo_autowork.cli project-run --repo "$REPO_DIR" "$@"
fi
"""


PROJECT_AUTOWORK = """#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${{PATH:-}}"
CONTROLLER_ROOT="${{AUTOWORK_CONTROLLER_ROOT:-{controller_root}}}"
PYTHON_BIN="${{AUTOWORK_PYTHON_BIN:-{python_bin}}}"

cd "$CONTROLLER_ROOT"
PYTHONPATH="$CONTROLLER_ROOT/src" "$PYTHON_BIN" -m repo_autowork.cli project-run --repo "$REPO_DIR" "$@"
"""


def render_root_autowork(config: Config) -> str:
    return ROOT_AUTOWORK.format(
        controller_root=str(config.project_root.resolve()),
        python_bin=config.autowork_python_bin,
    )


def render_project_autowork(config: Config) -> str:
    return PROJECT_AUTOWORK.format(
        controller_root=str(config.project_root.resolve()),
        python_bin=config.autowork_python_bin,
    )


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
    if config.autowork_include_controller and (config.project_root / ".git").is_dir():
        discovered.append(config.project_root.resolve())
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


def assign_project_cron_minutes(projects: list[ProjectRecord]) -> None:
    if not projects:
        return
    used_minutes = {project.cron_minute for project in projects if project.cron_minute is not None}
    total_projects = len(projects)
    for project_index, project in enumerate(projects):
        if project.cron_minute is not None:
            continue
        ideal_minute = cron_minute_for_project(project_index, total_projects)
        candidate_minutes = sorted(range(1, 60), key=lambda minute: (abs(minute - ideal_minute), minute))
        assigned = next((minute for minute in candidate_minutes if minute not in used_minutes), None)
        if assigned is None:
            assigned = ideal_minute
        project.cron_minute = assigned
        used_minutes.add(assigned)


def project_metadata_dir(project: ProjectRecord) -> Path:
    return Path(project.repo_path) / ".autowork"


def render_project_runtime_env(config: Config, project: ProjectRecord) -> str:
    return (
        "\n".join(
            [
                f"AUTOWORK_CONTROLLER_ROOT={config.project_root.resolve()}",
                f"AUTOWORK_PROJECT_SLUG={project.slug}",
                f"TG_TOPIC_ID={project.telegram_topic_id or ''}",
                f"AUTOWORK_TG_DIR={project.tg_folder}",
            ]
        )
        + "\n"
    )


def ensure_root_wrapper(config: Config) -> bool:
    root_wrapper_path = config.project_root / "autowork.sh"
    expected = render_root_autowork(config)
    if root_wrapper_path.exists() and root_wrapper_path.read_text(encoding="utf-8") == expected:
        return False
    root_wrapper_path.write_text(expected, encoding="utf-8")
    root_wrapper_path.chmod(0o755)
    return True


def ensure_project_files(config: Config, project: ProjectRecord) -> None:
    repo_dir = Path(project.repo_path)
    repo_dir.mkdir(parents=True, exist_ok=True)
    autowork_path = repo_dir / "autowork.sh"
    autowork_path.write_text(render_project_autowork(config), encoding="utf-8")
    autowork_path.chmod(0o755)

    metadata_dir = project_metadata_dir(project)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    project_runtime_env_path(Path(project.repo_path)).write_text(
        render_project_runtime_env(config, project),
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


def wrapper_contract_status(config: Config, self_heal: bool = False) -> dict[str, object]:
    root_wrapper_path = config.project_root / "autowork.sh"
    root_wrapper_expected = render_root_autowork(config)
    root_wrapper_ok = root_wrapper_path.exists() and root_wrapper_path.read_text(encoding="utf-8") == root_wrapper_expected
    root_healed = False
    if not root_wrapper_ok and self_heal:
        root_wrapper_path.write_text(root_wrapper_expected, encoding="utf-8")
        root_wrapper_path.chmod(0o755)
        root_wrapper_ok = True
        root_healed = True

    expected_project_wrapper = render_project_autowork(config)
    discovered_repos = [repo_dir for repo_dir in discover_repo_dirs(config) if repo_dir.resolve() != config.project_root.resolve()]
    drifted_project_wrappers: list[str] = []
    healed_project_wrappers: list[str] = []
    for repo_dir in discovered_repos:
        wrapper_path = repo_dir / "autowork.sh"
        if not wrapper_path.exists():
            if self_heal:
                wrapper_path.write_text(expected_project_wrapper, encoding="utf-8")
                wrapper_path.chmod(0o755)
                healed_project_wrappers.append(str(wrapper_path))
            else:
                drifted_project_wrappers.append(str(wrapper_path))
            continue
        if wrapper_path.read_text(encoding="utf-8") != expected_project_wrapper:
            if self_heal:
                wrapper_path.write_text(expected_project_wrapper, encoding="utf-8")
                wrapper_path.chmod(0o755)
                healed_project_wrappers.append(str(wrapper_path))
            else:
                drifted_project_wrappers.append(str(wrapper_path))

    if drifted_project_wrappers:
        preview = ", ".join(drifted_project_wrappers[:3])
        if len(drifted_project_wrappers) > 3:
            preview += f", +{len(drifted_project_wrappers) - 3} more"
        managed_detail = preview
    elif healed_project_wrappers:
        preview = ", ".join(healed_project_wrappers[:3])
        if len(healed_project_wrappers) > 3:
            preview += f", +{len(healed_project_wrappers) - 3} more"
        managed_detail = f"healed {preview}"
    else:
        managed_detail = f"{len(discovered_repos)} managed wrapper(s) match the generated contract"

    return {
        "root_ok": root_wrapper_ok,
        "root_path": str(root_wrapper_path),
        "root_healed": root_healed,
        "managed_ok": not drifted_project_wrappers,
        "managed_detail": managed_detail,
        "drifted_project_wrappers": drifted_project_wrappers,
        "healed_project_wrappers": healed_project_wrappers,
        "managed_repo_count": len(discovered_repos),
    }


def sync_projects(config: Config, state: State, dry_run: bool = False) -> list[ProjectRecord]:
    ensure_root_wrapper(config)
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
    assign_project_cron_minutes(state.projects)
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
        "Maintain a living task list for the repository.",
        "If TODO.md does not exist and README.md has no TODO section, create TODO.md.",
        "After each round, update TODO.md or the README TODO section with completed items and next actions.",
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
                "No explicit work queue was found. Inspect the repository, identify the highest-value next task, implement it, create a TODO if needed, and update docs.",
            ]
        )
    return "\n".join(prompt_lines)


def run_base_command(config: Config, repo_dir: Path, prompt: str) -> subprocess.CompletedProcess:
    if "$PROMPT" in config.autowork_base_command:
        env = dict(os.environ)
        env["PROMPT"] = prompt
        try:
            return subprocess.run(
                config.autowork_base_command,
                cwd=repo_dir,
                text=True,
                capture_output=True,
                shell=True,
                executable="/bin/zsh",
                env=env,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Failed to execute base command `{config.autowork_base_command}` from {repo_dir}: missing `/bin/zsh`."
            ) from exc
    command = shlex.split(config.autowork_base_command)
    if not command:
        raise RuntimeError("AUTOWORK_BASE_COMMAND is empty.")
    try:
        return subprocess.run(
            [*command, prompt],
            cwd=repo_dir,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Failed to execute base command `{config.autowork_base_command}` from {repo_dir}: missing `{command[0]}`."
        ) from exc


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


def review_summary(config: Config, state: State, self_heal: bool = False) -> str:
    wrapper_status = wrapper_contract_status(config, self_heal=self_heal)
    lines = [
        f"Controller repo: {config.project_root}",
        f"Managed repos root: {config.repos_root}",
        f"Telegram mirror root: {config.tg_root}",
        f"Managed repositories: {len(state.projects)}",
        (
            "Wrapper contracts: "
            f"controller={'ok' if wrapper_status['root_ok'] else 'drifted'}"
            f" ({wrapper_status['root_path']})"
            ", "
            f"managed={'ok' if wrapper_status['managed_ok'] else 'drifted'}"
            f" ({wrapper_status['managed_detail']})"
        ),
    ]
    if not wrapper_status["root_ok"]:
        lines.append(f"  Remediation: run `PYTHONPATH=src python3 -m repo_autowork.cli run` to regenerate the controller wrapper, or restore {wrapper_status['root_path']} from git.")
    if not wrapper_status["managed_ok"]:
        lines.append("  Remediation: run `PYTHONPATH=src python3 -m repo_autowork.cli run` to regenerate drifted managed wrappers.")
    if wrapper_status.get("root_healed"):
        lines.append(f"  Self-healed controller wrapper: {wrapper_status['root_path']}")
    if wrapper_status.get("healed_project_wrappers"):
        preview = ", ".join(wrapper_status["healed_project_wrappers"][:3])
        if len(wrapper_status["healed_project_wrappers"]) > 3:
            preview += f", +{len(wrapper_status['healed_project_wrappers']) - 3} more"
        lines.append(f"  Self-healed managed wrappers: {preview}")
    for project in state.projects:
        lines.append(
            f"- {project.name} | branch={project.current_branch} | runs/day={project.daily_runs_target} | fork={'yes' if project.is_fork else 'no'} | topic={project.telegram_topic_id or 'pending'}"
        )
    if state.last_telegram_sync:
        sync = state.last_telegram_sync
        ignored_breakdown = ", ".join(f"{k}={v}" for k, v in sorted(sync.ignored.items())) if sync.ignored else "none"
        lines.append(
            f"Last Telegram sync: handled={sync.handled}, ignored=[{ignored_breakdown}], at={sync.timestamp or 'unknown'}"
        )
        failed_outcomes = [o for o in sync.dispatch_outcomes if not o.success]
        if failed_outcomes:
            lines.append(
                f"Failed dispatches: {', '.join(f'{o.project_slug}#{o.update_id}' for o in failed_outcomes)}"
            )
        succeeded_outcomes = [o for o in sync.dispatch_outcomes if o.success]
        if succeeded_outcomes:
            lines.append(
                f"Succeeded dispatches: {', '.join(f'{o.project_slug}#{o.update_id}' for o in succeeded_outcomes)}"
            )
    else:
        lines.append("Last Telegram sync: none recorded")
    if state.telegram_sync_history:
        total_syncs = len(state.telegram_sync_history)
        total_handled = sum(s.handled for s in state.telegram_sync_history)
        total_failed = sum(1 for s in state.telegram_sync_history for o in s.dispatch_outcomes if not o.success)
        lines.append(
            f"Sync history (last {total_syncs} round(s)): total_handled={total_handled}, total_failed_dispatches={total_failed}"
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


def cron_minute_for_project(project_index: int, total_projects: int) -> int:
    if total_projects <= 1:
        return 5
    # Spread project runs across the hour while leaving minute 0 for controller jobs.
    return max(1, min(59, round((project_index + 1) * 59 / total_projects)))


def render_crontab(config: Config, state: State) -> str:
    lines = [CRON_BLOCK_START]
    controller_log = config.project_root / "autowork.log"
    controller_is_managed = any(Path(project.repo_path).resolve() == config.project_root.resolve() for project in state.projects)
    if not controller_is_managed:
        for hour in config.autowork_portfolio_hours:
            lines.append(f"0 {hour} * * * cd {config.project_root} && ./autowork.sh >> {controller_log} 2>&1")
    total_projects = len(state.projects)
    for project_index, project in enumerate(state.projects):
        repo_dir = Path(project.repo_path)
        log_path = repo_dir / "autowork.log"
        minute = project.cron_minute if project.cron_minute is not None else cron_minute_for_project(project_index, total_projects)
        for hour in cron_hours_for_runs(project.daily_runs_target):
            lines.append(f"{minute} {hour} * * * cd {repo_dir} && ./autowork.sh >> {log_path} 2>&1")
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
