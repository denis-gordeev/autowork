# Repo Autowork

Local-first orchestrator for a folder of git repositories.

It is based on the `my-summer-startup` mechanics, but the domain model is different:

1. There are no generated startups.
2. The controller scans a real directory with existing repositories.
3. Each repository gets its own `autowork.sh`, cron schedule, Telegram topic, and local `tg/<repo>/` mirror folder.
4. Each automation round looks at:
   - `AUTOWORK_INSTRUCTIONS.md` first
   - then open issues and PRs/MRs
   - then TODO items from `README.md` and `TODO.md`
5. If the repository is a fork, the controller tries to merge upstream changes before dispatching work to the base command.

## Default Layout

- controller repo: this repository
- managed repos root: `AUTOWORK_REPOS_ROOT`
- default managed repos root: `/Users/denis/programming/autowork`
- local Telegram mirror root: `AUTOWORK_TG_ROOT`
- per-repo wrapper: `<repo>/autowork.sh`
- per-repo mirror: `<AUTOWORK_TG_ROOT>/<repo-slug>/`

## Environment

Copy `.env.example` to `.env` and fill the required values.

```bash
AUTOWORK_REPOS_ROOT=/Users/denis/programming/autowork
AUTOWORK_TG_ROOT=/Users/denis/programming/autowork/repo-autowork/tg
AUTOWORK_BASE_COMMAND=codex exec --yolo
AUTOWORK_DEFAULT_DAILY_RUNS=2
AUTOWORK_PORTFOLIO_HOURS=10,20
AUTOWORK_PYTHON_BIN=python3
GITHUB_OWNER=
GITHUB_VISIBILITY=private
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Notes:

- `AUTOWORK_BASE_COMMAND` defaults to `codex exec --yolo`, but any compatible CLI command can be used.
- `AUTOWORK_REPOS_ROOT` is the folder that contains the repositories to manage.
- `AUTOWORK_TG_ROOT` is a local filesystem mirror for project Telegram threads.
- The Telegram bot should be an admin in a forum-enabled group if you want one topic per repository.

## Commands

```bash
PYTHONPATH=src python3 -m repo_autowork.cli doctor
PYTHONPATH=src python3 -m repo_autowork.cli run --dry-run
PYTHONPATH=src python3 -m repo_autowork.cli review
PYTHONPATH=src python3 -m repo_autowork.cli sync-crontab
PYTHONPATH=src python3 -m repo_autowork.cli project-run --repo /Users/denis/programming/autowork/mcp-russia --dry-run
PYTHONPATH=src python3 -m repo_autowork.cli telegram-sync
./autowork.sh --dry-run
```

## What `run` Does

For every git repository directly inside `AUTOWORK_REPOS_ROOT`, the controller:

- discovers the repo and stores it in `data/state.json`
- creates or refreshes `<repo>/autowork.sh`
- creates `.autowork/project.env` inside the repo
- creates the local Telegram mirror folder under `AUTOWORK_TG_ROOT`
- creates a Telegram topic when Telegram is configured
- refreshes the managed cron block

## What `project-run` Does

One repository round builds a prompt in this order:

1. `AUTOWORK_INSTRUCTIONS.md`
2. open issues
3. open PRs or merge requests
4. TODOs from `README.md` and `TODO.md`

Then it dispatches the prompt to `AUTOWORK_BASE_COMMAND`.

If the repo is a fork and an upstream remote or forge parent can be resolved, the controller tries to merge upstream first.

## Telegram Flow

- one forum topic per repository
- inbound Telegram messages are matched by `message_thread_id`
- messages are mirrored to both:
  - `<repo>/inbox/telegram/`
  - `<AUTOWORK_TG_ROOT>/<repo-slug>/`
- each message is also forwarded to the base command in that repository

## Cron

- the controller repo gets runs at the hours in `AUTOWORK_PORTFOLIO_HOURS`
- each managed repo gets `AUTOWORK_DEFAULT_DAILY_RUNS` launches per day by default
- the project only rewrites its own managed block in `crontab`

## GitHub Repo For This Controller

The codebase is ready to be pushed to a fresh GitHub repository.
Remote creation requires valid GitHub authentication, for example via `gh auth login`.
