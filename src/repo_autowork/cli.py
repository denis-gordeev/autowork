from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from collections import Counter
from pathlib import Path

from .config import build_config, hydrate_project_runtime_env
from .manager import (
    CRON_BLOCK_END,
    CRON_BLOCK_START,
    current_projects,
    load_state,
    project_run_once,
    render_crontab,
    review_summary,
    save_state,
    sync_projects,
    write_telegram_mirror,
)
from .telegram import TelegramError, get_updates, send_message


def current_crontab() -> str:
    try:
        result = subprocess.run(["crontab", "-l"], text=True, capture_output=True)
    except (FileNotFoundError, PermissionError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.rstrip()


def merge_crontab(existing: str, managed_block: str) -> str:
    lines = existing.splitlines() if existing else []
    kept: list[str] = []
    inside_block = False
    for line in lines:
        stripped = line.strip()
        if stripped == CRON_BLOCK_START:
            inside_block = True
            continue
        if stripped == CRON_BLOCK_END:
            inside_block = False
            continue
        if not inside_block:
            kept.append(line)
    if kept and kept[-1] != "":
        kept.append("")
    kept.extend(managed_block.splitlines())
    return "\n".join(kept).strip() + "\n"


def sync_crontab(config, state) -> None:
    merged = merge_crontab(current_crontab(), render_crontab(config, state))
    subprocess.run(["crontab", "-"], input=merged, text=True, check=True)


def safe_sync_crontab(config, state) -> None:
    try:
        sync_crontab(config, state)
    except (subprocess.CalledProcessError, FileNotFoundError, PermissionError) as exc:
        print(f"Warning: failed to sync crontab: {exc}", file=sys.stderr)


def doctor_summary(config) -> str:
    checks = [
        ("Managed repos root", config.repos_root.exists(), str(config.repos_root)),
        ("Telegram bot token", bool(config.telegram_bot_token), "set" if config.telegram_bot_token else "missing"),
        ("Telegram chat id", bool(config.telegram_chat_id), config.telegram_chat_id or "missing"),
        ("Base command", bool(config.autowork_base_command), config.autowork_base_command),
        ("GitHub owner", bool(config.github_owner), config.github_owner or "missing"),
    ]
    lines = []
    for label, ok, detail in checks:
        lines.append(f"{'OK' if ok else 'MISSING'}: {label} ({detail})")
    return "\n".join(lines)


def cmd_run(args: argparse.Namespace) -> int:
    config = build_config(Path.cwd(), repos_root=args.repos_root)
    state = load_state(config)
    projects = sync_projects(config, state, dry_run=args.dry_run)
    safe_sync_crontab(config, state)
    print(f"Synced {len(projects)} repositories.")
    for project in projects:
        print(f"- {project.name} | {project.repo_path} | topic={project.telegram_topic_id or 'pending'}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    config = build_config(Path.cwd(), repos_root=args.repos_root)
    state = load_state(config)
    sync_projects(config, state, dry_run=args.dry_run)
    print(review_summary(config, state))
    return 0


def cmd_sync_crontab(args: argparse.Namespace) -> int:
    config = build_config(Path.cwd(), repos_root=args.repos_root)
    state = load_state(config)
    sync_projects(config, state, dry_run=args.dry_run)
    try:
        sync_crontab(config, state)
    except (subprocess.CalledProcessError, FileNotFoundError, PermissionError) as exc:
        print(f"Failed to sync crontab: {exc}", file=sys.stderr)
        return 1
    print(render_crontab(config, state))
    return 0


def _find_project(state, repo_path: Path):
    resolved = str(repo_path.resolve())
    for project in current_projects(state):
        if str(Path(project.repo_path).resolve()) == resolved:
            return project
    return None


def _load_project_env(project) -> None:
    hydrate_project_runtime_env(Path(project.repo_path))


def cmd_project_run(args: argparse.Namespace) -> int:
    config = build_config(Path.cwd(), repos_root=args.repos_root)
    state = load_state(config)
    sync_projects(config, state, dry_run=args.dry_run)
    project = _find_project(state, Path(args.repo))
    if project is None:
        print(f"Repository is not managed: {args.repo}", file=sys.stderr)
        return 1
    _load_project_env(project)
    result = project_run_once(config, project, dry_run=args.dry_run)
    save_state(config, state)
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    return result.returncode


def _message_text(payload: dict) -> str:
    text = payload.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    caption = payload.get("caption")
    if isinstance(caption, str) and caption.strip():
        return caption.strip()
    return ""


def _dispatch_telegram_message(config, project, text: str, dry_run: bool = False) -> subprocess.CompletedProcess:
    prompt = "\n".join(
        [
            f"Incoming Telegram message for `{project.name}`.",
            "Treat this as a concrete task for the repository.",
            "If code or docs need changes, make them.",
            "If the request is operational, update the relevant artifacts.",
            "",
            text,
        ]
    )
    if dry_run:
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=prompt, stderr="")
    return subprocess.run(
        [*shlex.split(config.autowork_base_command), prompt],
        cwd=project.repo_path,
        text=True,
        capture_output=True,
    )


def _format_ignored_updates(ignored_updates: Counter[str]) -> str:
    total = sum(ignored_updates.values())
    if total == 0:
        return "Ignored 0 Telegram update(s)."
    breakdown = ", ".join(f"{reason}={ignored_updates[reason]}" for reason in sorted(ignored_updates))
    return f"Ignored {total} Telegram update(s): {breakdown}."


def cmd_telegram_sync(args: argparse.Namespace) -> int:
    config = build_config(Path.cwd(), repos_root=args.repos_root)
    state = load_state(config)
    sync_projects(config, state, dry_run=args.dry_run)
    offset = state.last_telegram_update_id + 1 if state.last_telegram_update_id else None
    print(
        f"Syncing Telegram updates for {len(state.projects)} managed repositories"
        + (f" starting from offset {offset}" if offset is not None else " from the current head")
        + "...",
        flush=True,
    )
    try:
        updates = get_updates(config, offset=offset, timeout=args.timeout)
    except TelegramError as exc:
        print(f"Telegram sync failed: {exc}", file=sys.stderr)
        return 1
    print(f"Fetched {len(updates)} Telegram update(s).", flush=True)
    handled = 0
    ignored_updates: Counter[str] = Counter()
    for update in updates:
        state.last_telegram_update_id = max(state.last_telegram_update_id, int(update.get("update_id", 0)))
        message = update.get("message")
        if not isinstance(message, dict):
            ignored_updates["non_message"] += 1
            continue
        if str(message.get("chat", {}).get("id")) != str(config.telegram_chat_id):
            ignored_updates["other_chat"] += 1
            continue
        if message.get("from", {}).get("is_bot"):
            ignored_updates["bot_sender"] += 1
            continue
        thread_id = message.get("message_thread_id")
        if thread_id is None:
            ignored_updates["missing_thread"] += 1
            continue
        text = _message_text(message)
        if not text:
            ignored_updates["empty_text"] += 1
            continue
        project = next((item for item in state.projects if item.telegram_topic_id == int(thread_id)), None)
        if project is None:
            ignored_updates["unknown_topic"] += 1
            continue
        inbox_path = write_telegram_mirror(project, update)
        _load_project_env(project)
        result = _dispatch_telegram_message(config, project, text, dry_run=args.dry_run)
        handled += 1
        print(f"Dispatched Telegram update {update['update_id']} to {project.name}")
        if not args.dry_run:
            status_lines = [
                f"Queued for {project.name}",
                f"Inbox record: {inbox_path}",
                "Status: success" if result.returncode == 0 else "Status: failed",
            ]
            tail = (result.stderr or result.stdout or "").strip()
            if tail:
                status_lines.append(tail[:1200])
            try:
                send_message(config, "\n".join(status_lines), project.telegram_topic_id)
            except TelegramError:
                pass
    save_state(config, state)
    print(f"Handled {handled} Telegram update(s).")
    print(_format_ignored_updates(ignored_updates))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    config = build_config(Path.cwd(), repos_root=args.repos_root)
    print(doctor_summary(config))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage autowork automation across local git repositories.")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Discover repositories, provision wrappers, and refresh cron.")
    run_parser.add_argument("--repos-root", default=None, help="Directory that contains managed repositories.")
    run_parser.add_argument("--dry-run", action="store_true", help="Do not create Telegram topics.")
    run_parser.set_defaults(func=cmd_run)

    review_parser = sub.add_parser("review", help="Print a summary of managed repositories.")
    review_parser.add_argument("--repos-root", default=None, help="Directory that contains managed repositories.")
    review_parser.add_argument("--dry-run", action="store_true", help="Avoid external side effects.")
    review_parser.set_defaults(func=cmd_review)

    cron_parser = sub.add_parser("sync-crontab", help="Install or refresh cron jobs for all managed repositories.")
    cron_parser.add_argument("--repos-root", default=None, help="Directory that contains managed repositories.")
    cron_parser.add_argument("--dry-run", action="store_true", help="Avoid Telegram topic creation while syncing.")
    cron_parser.set_defaults(func=cmd_sync_crontab)

    project_parser = sub.add_parser("project-run", help="Execute one automation round for a specific repository.")
    project_parser.add_argument("--repo", required=True, help="Absolute or relative path to the repository.")
    project_parser.add_argument("--repos-root", default=None, help="Directory that contains managed repositories.")
    project_parser.add_argument("--dry-run", action="store_true", help="Print the generated prompt instead of executing the base command.")
    project_parser.set_defaults(func=cmd_project_run)

    telegram_parser = sub.add_parser("telegram-sync", help="Pull Telegram topic messages and dispatch them to project chats.")
    telegram_parser.add_argument("--repos-root", default=None, help="Directory that contains managed repositories.")
    telegram_parser.add_argument("--timeout", type=int, default=0, help="Telegram long-poll timeout in seconds.")
    telegram_parser.add_argument("--dry-run", action="store_true", help="Do not send confirmation messages back to Telegram.")
    telegram_parser.set_defaults(func=cmd_telegram_sync)

    doctor_parser = sub.add_parser("doctor", help="Validate environment and toolchain configuration.")
    doctor_parser.add_argument("--repos-root", default=None, help="Directory that contains managed repositories.")
    doctor_parser.set_defaults(func=cmd_doctor)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
