from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from collections import Counter
from pathlib import Path

from .config import build_config, hydrate_project_runtime_env, project_runtime_env_path, write_json
from .manager import (
    CRON_BLOCK_END,
    CRON_BLOCK_START,
    current_projects,
    discover_repo_dirs,
    load_state,
    project_run_once,
    render_project_autowork,
    render_root_autowork,
    render_crontab,
    review_summary,
    wrapper_contract_status,
    save_state,
    sync_projects,
    write_telegram_mirror,
)
from .models import ProjectDispatchOutcome, ProjectRunResult, TelegramSyncSummary, utc_now_iso
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


def doctor_checks(config, self_heal: bool = False, state: State | None = None) -> list[tuple[str, bool, str]]:
    wrapper_status = wrapper_contract_status(config, self_heal=self_heal, state=state)
    guaranteed_env_keys = "AUTOWORK_CONTROLLER_ROOT, AUTOWORK_PROJECT_SLUG, TG_TOPIC_ID, AUTOWORK_TG_DIR"
    root_label = "Controller wrapper contract (healed)" if wrapper_status.get("root_healed") else "Controller wrapper contract"
    managed_label = "Managed wrapper contracts (healed)" if wrapper_status.get("healed_project_wrappers") else "Managed wrapper contracts"

    return [
        ("Managed repos root", config.repos_root.exists(), str(config.repos_root)),
        ("Telegram bot token", bool(config.telegram_bot_token), "set" if config.telegram_bot_token else "missing"),
        ("Telegram chat id", bool(config.telegram_chat_id), config.telegram_chat_id or "missing"),
        ("Base command", bool(config.autowork_base_command), config.autowork_base_command),
        ("GitHub owner", bool(config.github_owner), config.github_owner or "missing"),
        ("Project runtime env keys", True, guaranteed_env_keys),
        (root_label, bool(wrapper_status["root_ok"]), str(wrapper_status["root_path"])),
        (managed_label, bool(wrapper_status["managed_ok"]), str(wrapper_status["managed_detail"])),
    ]


def doctor_summary(config, self_heal: bool = False, state: State | None = None) -> str:
    checks = doctor_checks(config, self_heal=self_heal, state=state)
    lines = []
    for label, ok, detail in checks:
        lines.append(f"{'OK' if ok else 'MISSING'}: {label} ({detail})")
    return "\n".join(lines)


def cmd_run(args: argparse.Namespace) -> int:
    config = build_config(Path.cwd(), repos_root=args.repos_root)
    state = load_state(config)
    self_heal = getattr(args, "self_heal", False)
    heal_status = None
    if self_heal:
        heal_status = wrapper_contract_status(config, self_heal=True, state=state)
    projects = sync_projects(config, state, dry_run=args.dry_run)
    safe_sync_crontab(config, state)
    if getattr(args, "format", None) == "json":
        run_data: dict = {
            "synced_count": len(projects),
            "projects": [
                {
                    "name": p.name,
                    "slug": p.slug,
                    "repo_path": p.repo_path,
                    "topic": p.telegram_topic_id or "pending",
                }
                for p in projects
            ],
        }
        if self_heal and heal_status is not None:
            run_data["wrapper_contracts"] = {
                "controller": "ok" if heal_status["root_ok"] else "drifted",
                "controller_healed": heal_status.get("root_healed", False),
                "managed": "ok" if heal_status["managed_ok"] else "drifted",
                "drifted_paths": heal_status.get("drifted_project_wrappers", []),
                "healed_paths": heal_status.get("healed_project_wrappers", []),
                "per_project_healed": heal_status.get("per_project_healed", {}),
                "per_project_drifted": heal_status.get("per_project_drifted", {}),
            }
        print(json.dumps(run_data, ensure_ascii=False, indent=2))
    else:
        print(f"Synced {len(projects)} repositories.")
        for project in projects:
            print(f"- {project.name} | {project.repo_path} | topic={project.telegram_topic_id or 'pending'}")
        if self_heal and heal_status is not None:
            if heal_status.get("root_healed"):
                print(f"  Self-healed controller wrapper: {heal_status['root_path']}")
            if heal_status.get("healed_project_wrappers"):
                preview = ", ".join(heal_status["healed_project_wrappers"][:3])
                if len(heal_status["healed_project_wrappers"]) > 3:
                    preview += f", +{len(heal_status['healed_project_wrappers']) - 3} more"
                print(f"  Self-healed managed wrappers: {preview}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    config = build_config(Path.cwd(), repos_root=args.repos_root)
    state = load_state(config)
    sync_projects(config, state, dry_run=args.dry_run)
    self_heal = getattr(args, "self_heal", False)
    if args.json:
        review_data = _review_data(config, state, self_heal=self_heal)
        print(json.dumps(review_data, ensure_ascii=False, indent=2))
    else:
        print(review_summary(config, state, self_heal=self_heal))
    return 0


def _review_data(config, state, self_heal: bool = False) -> dict:
    wrapper_status = wrapper_contract_status(config, self_heal=self_heal, state=state)
    return {
        "controller_root": str(config.project_root),
        "repos_root": str(config.repos_root),
        "tg_root": str(config.tg_root),
        "managed_count": len(state.projects),
        "wrapper_contracts": {
            "controller": "ok" if wrapper_status["root_ok"] else "drifted",
            "controller_healed": wrapper_status.get("root_healed", False),
            "managed": "ok" if wrapper_status["managed_ok"] else "drifted",
            "drifted_paths": wrapper_status["drifted_project_wrappers"],
            "healed_paths": wrapper_status.get("healed_project_wrappers", []),
            "per_project_healed": wrapper_status.get("per_project_healed", {}),
            "per_project_drifted": wrapper_status.get("per_project_drifted", {}),
        },
        "projects": [
            {
                "name": p.name,
                "slug": p.slug,
                "branch": p.current_branch,
                "daily_runs": p.daily_runs_target,
                "fork": p.is_fork,
                "topic": p.telegram_topic_id,
            }
            for p in state.projects
        ],
        "last_telegram_sync": state.last_telegram_sync.to_dict() if state.last_telegram_sync else None,
        "dispatch_outcomes": [o.to_dict() for o in state.last_telegram_sync.dispatch_outcomes] if state.last_telegram_sync else [],
        "telegram_sync_history": [s.to_dict() for s in state.telegram_sync_history],
    }


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
    self_heal = getattr(args, "self_heal", False)
    heal_status = None
    if self_heal:
        heal_status = wrapper_contract_status(config, self_heal=True, state=state)
    project = _find_project(state, Path(args.repo))
    if project is None:
        print(f"Repository is not managed: {args.repo}", file=sys.stderr)
        return 1
    _load_project_env(project)
    result = project_run_once(config, project, dry_run=args.dry_run)
    save_state(config, state)
    if getattr(args, "format", None) == "json":
        run_data = {
            "project": {
                "slug": project.slug,
                "name": project.name,
                "repo_path": project.repo_path,
                "branch": project.current_branch,
                "default_branch": project.default_branch,
                "fork": project.is_fork,
                "topic": project.telegram_topic_id,
            },
            "prompt": result.prompt,
            "dry_run": args.dry_run,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        if self_heal and heal_status is not None:
            run_data["wrapper_contracts"] = {
                "controller": "ok" if heal_status["root_ok"] else "drifted",
                "controller_healed": heal_status.get("root_healed", False),
                "managed": "ok" if heal_status["managed_ok"] else "drifted",
                "drifted_paths": heal_status.get("drifted_project_wrappers", []),
                "healed_paths": heal_status.get("healed_project_wrappers", []),
                "per_project_healed": heal_status.get("per_project_healed", {}),
                "per_project_drifted": heal_status.get("per_project_drifted", {}),
            }
        print(json.dumps(run_data, ensure_ascii=False, indent=2))
    else:
        if self_heal and heal_status is not None:
            if heal_status.get("root_healed"):
                print(f"Self-healed controller wrapper: {heal_status['root_path']}")
            if heal_status.get("healed_project_wrappers"):
                preview = ", ".join(heal_status["healed_project_wrappers"][:3])
                if len(heal_status["healed_project_wrappers"]) > 3:
                    preview += f", +{len(heal_status['healed_project_wrappers']) - 3} more"
                print(f"Self-healed managed wrappers: {preview}")
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
    if "$PROMPT" in config.autowork_base_command:
        env = dict(os.environ)
        env["PROMPT"] = prompt
        return subprocess.run(
            config.autowork_base_command,
            cwd=project.repo_path,
            text=True,
            capture_output=True,
            shell=True,
            executable="/bin/zsh",
            env=env,
        )
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
    self_heal = getattr(args, "self_heal", False)
    heal_status = None
    if self_heal:
        heal_status = wrapper_contract_status(config, self_heal=True, state=state)
    json_output = getattr(args, "json", False)
    offset = state.last_telegram_update_id + 1 if state.last_telegram_update_id else None
    if not json_output:
        print(
            f"Syncing Telegram updates for {len(state.projects)} managed repositories"
            + (f" starting from offset {offset}" if offset is not None else " from the current head")
            + "...",
            flush=True,
        )
    try:
        updates = get_updates(config, offset=offset, timeout=args.timeout)
    except TelegramError as exc:
        if json_output:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"Telegram sync failed: {exc}", file=sys.stderr)
        return 1
    if not json_output:
        print(f"Fetched {len(updates)} Telegram update(s).", flush=True)
    handled = 0
    ignored_updates: Counter[str] = Counter()
    dispatch_outcomes: list[ProjectDispatchOutcome] = []
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
        success = result.returncode == 0
        dispatch_outcomes.append(
            ProjectDispatchOutcome(
                project_slug=project.slug,
                update_id=int(update.get("update_id", 0)),
                success=success,
                detail="" if success else (result.stderr or result.stdout or "").strip()[:200],
            )
        )
        if not json_output:
            print(f"Dispatched Telegram update {update['update_id']} to {project.name}: {'success' if success else 'failed'}")
        if not args.dry_run:
            status_lines = [
                f"Queued for {project.name}",
                f"Inbox record: {inbox_path}",
                "Status: success" if success else "Status: failed",
            ]
            tail = (result.stderr or result.stdout or "").strip()
            if tail:
                status_lines.append(tail[:1200])
            try:
                send_message(config, "\n".join(status_lines), project.telegram_topic_id)
            except TelegramError:
                pass
    save_state(config, state)
    state.last_telegram_sync = TelegramSyncSummary(
        handled=handled,
        ignored=dict(ignored_updates),
        dispatch_outcomes=dispatch_outcomes,
        timestamp=utc_now_iso(),
    )
    state.append_sync_history(state.last_telegram_sync)
    save_state(config, state)
    sync_data = {
        "handled": handled,
        "ignored": dict(ignored_updates),
        "dispatch_outcomes": [o.to_dict() for o in dispatch_outcomes],
        "last_update_id": state.last_telegram_update_id,
        "timestamp": state.last_telegram_sync.timestamp,
    }
    if self_heal and heal_status is not None:
        sync_data["wrapper_contracts"] = {
            "controller": "ok" if heal_status["root_ok"] else "drifted",
            "controller_healed": heal_status.get("root_healed", False),
            "managed": "ok" if heal_status["managed_ok"] else "drifted",
            "drifted_paths": heal_status["drifted_project_wrappers"],
            "healed_paths": heal_status.get("healed_project_wrappers", []),
            "per_project_healed": heal_status.get("per_project_healed", {}),
            "per_project_drifted": heal_status.get("per_project_drifted", {}),
        }
    if getattr(args, "json", False):
        print(json.dumps(sync_data, ensure_ascii=False, indent=2))
    else:
        print(f"Handled {handled} Telegram update(s).")
        print(_format_ignored_updates(ignored_updates))
        failed_dispatches = [o for o in dispatch_outcomes if not o.success]
        if failed_dispatches:
            print(f"Failed dispatches: {', '.join(f'{o.project_slug}#{o.update_id}' for o in failed_dispatches)}")
    return 0


def _doctor_data(config, self_heal: bool = False, wrapper_status: dict | None = None) -> dict:
    if wrapper_status is None:
        wrapper_status = wrapper_contract_status(config, self_heal=self_heal)
    checks = doctor_checks(config, self_heal=self_heal)
    return {
        "checks": [
            {"label": label, "ok": ok, "detail": detail}
            for label, ok, detail in checks
        ],
        "wrapper_contracts": {
            "controller": "ok" if wrapper_status["root_ok"] else "drifted",
            "controller_path": wrapper_status["root_path"],
            "controller_healed": wrapper_status.get("root_healed", False),
            "managed": "ok" if wrapper_status["managed_ok"] else "drifted",
            "drifted_paths": wrapper_status["drifted_project_wrappers"],
            "healed_paths": wrapper_status.get("healed_project_wrappers", []),
            "per_project_healed": wrapper_status.get("per_project_healed", {}),
            "per_project_drifted": wrapper_status.get("per_project_drifted", {}),
        },
    }


def cmd_doctor(args: argparse.Namespace) -> int:
    config = build_config(Path.cwd(), repos_root=args.repos_root)
    self_heal = getattr(args, "self_heal", False)
    state = load_state(config)
    wrapper_status = wrapper_contract_status(config, self_heal=self_heal, state=state)
    checks = doctor_checks(config, self_heal=self_heal, state=state)
    if getattr(args, "format", None) == "json":
        print(json.dumps(_doctor_data(config, self_heal=self_heal, wrapper_status=wrapper_status), ensure_ascii=False, indent=2))
    else:
        summary_lines = [f"{'OK' if ok else 'MISSING'}: {label} ({detail})" for label, ok, detail in checks]
        if not wrapper_status["root_ok"]:
            summary_lines.append(f"  Remediation: run `PYTHONPATH=src python3 -m repo_autowork.cli run` to regenerate the controller wrapper, or restore {wrapper_status['root_path']} from git.")
        if not wrapper_status["managed_ok"]:
            summary_lines.append("  Remediation: run `PYTHONPATH=src python3 -m repo_autowork.cli run` to regenerate drifted managed wrappers.")
        if wrapper_status.get("root_healed"):
            summary_lines.append(f"  Self-healed controller wrapper: {wrapper_status['root_path']}")
        if wrapper_status.get("healed_project_wrappers"):
            paths = ", ".join(wrapper_status["healed_project_wrappers"][:3])
            if len(wrapper_status["healed_project_wrappers"]) > 3:
                paths += f", +{len(wrapper_status['healed_project_wrappers']) - 3} more"
            summary_lines.append(f"  Self-healed managed wrappers: {paths}")
        print("\n".join(summary_lines))
    blocking_labels = {
        "Managed repos root",
        "Controller wrapper contract",
        "Controller wrapper contract (healed)",
        "Managed wrapper contracts",
        "Managed wrapper contracts (healed)",
    }
    return 0 if all(ok for label, ok, _ in checks if label in blocking_labels) else 1


def cmd_history(args: argparse.Namespace) -> int:
    config = build_config(Path.cwd(), repos_root=args.repos_root)
    state = load_state(config)
    project_slug = getattr(args, "project", None)
    limit = getattr(args, "limit", None)
    since = getattr(args, "since", None)
    until = getattr(args, "until", None)
    history_data = _history_data(state, project_slug=project_slug, limit=limit, since=since, until=until)
    if getattr(args, "json", False):
        print(json.dumps(history_data, ensure_ascii=False, indent=2))
    else:
        print(_history_text(history_data))
    return 0


def _history_data(state, project_slug: str | None = None, limit: int | None = None, since: str | None = None, until: str | None = None) -> dict:
    rounds = []
    for sync in reversed(state.telegram_sync_history):
        if since and sync.timestamp and sync.timestamp < since:
            continue
        if until and sync.timestamp and sync.timestamp > until:
            continue
        outcomes = sync.dispatch_outcomes
        if project_slug:
            outcomes = [o for o in outcomes if o.project_slug == project_slug]
        rounds.append({
            "timestamp": sync.timestamp,
            "handled": sync.handled,
            "ignored": sync.ignored,
            "outcomes": [o.to_dict() for o in outcomes],
        })
        if limit is not None and len(rounds) >= limit:
            break
    rounds.reverse()
    return {
        "total_rounds": len(rounds),
        "project_filter": project_slug,
        "limit": limit,
        "since": since,
        "until": until,
        "rounds": rounds,
    }


def _history_text(data: dict) -> str:
    filter_note = f" filtered to {data['project_filter']}" if data["project_filter"] else ""
    lines = [f"Dispatch history ({data['total_rounds']} round(s)){filter_note}:"]
    for round_entry in data["rounds"]:
        ts = round_entry["timestamp"] or "unknown"
        handled = round_entry["handled"]
        outcomes = round_entry["outcomes"]
        lines.append(f"  {ts} | handled={handled}")
        for o in outcomes:
            status = "success" if o["success"] else f"failed ({o['detail']})"
            lines.append(f"    - {o['project_slug']}#{o['update_id']}: {status}")
    if not data["rounds"]:
        lines.append("  No sync history recorded yet.")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage autowork automation across local git repositories.")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Discover repositories, provision wrappers, and refresh cron.")
    run_parser.add_argument("--repos-root", default=None, help="Directory that contains managed repositories.")
    run_parser.add_argument("--dry-run", action="store_true", help="Do not create Telegram topics.")
    run_parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format (default: text).")
    run_parser.add_argument("--self-heal", action="store_true", help="Regenerate drifted wrappers before syncing projects.")
    run_parser.set_defaults(func=cmd_run)

    review_parser = sub.add_parser("review", help="Print a summary of managed repositories.")
    review_parser.add_argument("--repos-root", default=None, help="Directory that contains managed repositories.")
    review_parser.add_argument("--dry-run", action="store_true", help="Avoid external side effects.")
    review_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    review_parser.add_argument("--self-heal", action="store_true", help="Regenerate drifted wrappers instead of only auditing them.")
    review_parser.set_defaults(func=cmd_review)

    cron_parser = sub.add_parser("sync-crontab", help="Install or refresh cron jobs for all managed repositories.")
    cron_parser.add_argument("--repos-root", default=None, help="Directory that contains managed repositories.")
    cron_parser.add_argument("--dry-run", action="store_true", help="Avoid Telegram topic creation while syncing.")
    cron_parser.set_defaults(func=cmd_sync_crontab)

    project_parser = sub.add_parser("project-run", help="Execute one automation round for a specific repository.")
    project_parser.add_argument("--repo", required=True, help="Absolute or relative path to the repository.")
    project_parser.add_argument("--repos-root", default=None, help="Directory that contains managed repositories.")
    project_parser.add_argument("--dry-run", action="store_true", help="Print the generated prompt instead of executing the base command.")
    project_parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format (default: text).")
    project_parser.add_argument("--self-heal", action="store_true", help="Regenerate drifted wrappers before running the project.")
    project_parser.set_defaults(func=cmd_project_run)

    telegram_parser = sub.add_parser("telegram-sync", help="Pull Telegram topic messages and dispatch them to project chats.")
    telegram_parser.add_argument("--repos-root", default=None, help="Directory that contains managed repositories.")
    telegram_parser.add_argument("--timeout", type=int, default=0, help="Telegram long-poll timeout in seconds.")
    telegram_parser.add_argument("--dry-run", action="store_true", help="Do not send confirmation messages back to Telegram.")
    telegram_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    telegram_parser.add_argument("--self-heal", action="store_true", help="Regenerate drifted wrappers before processing updates.")
    telegram_parser.set_defaults(func=cmd_telegram_sync)

    doctor_parser = sub.add_parser("doctor", help="Validate environment and toolchain configuration.")
    doctor_parser.add_argument("--repos-root", default=None, help="Directory that contains managed repositories.")
    doctor_parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format (default: text).")
    doctor_parser.add_argument("--self-heal", action="store_true", help="Regenerate drifted wrappers instead of only auditing them.")
    doctor_parser.set_defaults(func=cmd_doctor)

    history_parser = sub.add_parser("history", help="Show Telegram dispatch outcome history across recent sync rounds.")
    history_parser.add_argument("--repos-root", default=None, help="Directory that contains managed repositories.")
    history_parser.add_argument("--project", default=None, help="Filter outcomes to a specific project slug.")
    history_parser.add_argument("--limit", type=int, default=None, help="Maximum number of sync rounds to show.")
    history_parser.add_argument("--since", default=None, help="Only show rounds at or after this ISO timestamp.")
    history_parser.add_argument("--until", default=None, help="Only show rounds at or before this ISO timestamp.")
    history_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    history_parser.set_defaults(func=cmd_history)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
