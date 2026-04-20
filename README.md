# Repo Autowork

Local-first orchestrator for a folder of git repositories.

The controller scans a real directory with existing repositories. Each repository gets its own `autowork.sh`, cron schedule, Telegram topic, and local `tg/<repo>/` mirror folder.

Each automation round looks at:

1. `AUTOWORK_INSTRUCTIONS.md` first
2. then open issues and PRs/MRs
3. then TODO items from `README.md` and `TODO.md`
4. if the repository is a fork, the controller tries to merge upstream changes before dispatching work to the base command

Each child repository is also expected to keep a living task list:

- reuse `TODO.md` when it exists
- otherwise reuse a TODO section in `README.md`
- if neither exists, the agent should create `TODO.md`
- after each round, the agent should update completed items and next actions

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
AUTOWORK_INCLUDE_CONTROLLER=0
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
- `AUTOWORK_INCLUDE_CONTROLLER=1` opts the controller repo itself into the managed project set.
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
pytest -q
```

## Progress Tracker

### Completed

- Added `AUTOWORK_INCLUDE_CONTROLLER` so the controller repo can opt into self-management explicitly instead of relying on implicit discovery.
- Switched generated per-repo wrappers to call `project-run --repo <repo>` from the controller root, which prevents child repositories from accidentally re-running the full portfolio loop.
- Kept the controller root `./autowork.sh` on the original portfolio flow (`telegram-sync`, `run`, `review`) while child wrappers use `project-run`, so controller cron jobs and manual child runs both stay valid.
- Normalized runtime execution by prepending common macOS shell paths and resolving `codex` through `PATH` plus known Homebrew locations.
- Staggered managed project cron entries across the hour and skipped the extra controller-wide cron line when the controller is already a managed repository.
- Added regression coverage for cron staggering, controller discovery, runtime bootstrap, and generated wrapper contents.
- Added a regression check that protects the controller root wrapper from collapsing into child-only `project-run` behavior.
- Added pytest bootstrap wiring so `pytest -q` works without a manual `PYTHONPATH=src` export.
- Persisted a per-project `cron_minute` in controller state so existing repositories keep their assigned minute even when discovery order or portfolio size changes.
- `project-run` now loads `.autowork/project.env` automatically before dispatching the base command, so wrapper metadata is available to custom hooks and prompts.
- Added regression coverage for persisted cron minutes and for the `project-run` CLI path that hydrates per-repository env before execution.
- Restored the controller root `autowork.sh` contract so the controller repository still executes `telegram-sync -> run -> review` instead of collapsing into a child-style `project-run`.
- Added CLI-level dry-run coverage for both `run` and `project-run`, so parser wiring and user-facing console output are exercised instead of only helper-level call sites.
- Telegram-triggered repository dispatches now load `.autowork/project.env` before invoking the base command, so inbound topic tasks see the same per-project metadata as scheduled `project-run` executions.
- Added regression coverage that guards Telegram-triggered env loading and the `main()` entrypoint flow for dry-run CLI commands.

### Next Iterations

- Resolve whether controller-level `AUTOWORK_INSTRUCTIONS.md` is meant to be committed policy or ignored local guidance, and document that decision.
- Refresh persisted state and generated wrappers so older `state.json` entries and child repos pick up the new `cron_minute` + wrapper contract on the next real controller run.
- Add collision-aware cron rebalancing for large portfolios so newly discovered projects prefer free minutes near the ideal slot without starving late additions.
- Add CLI coverage for `telegram-sync --dry-run`, including ignored updates, topic matching, and status output, so inbound message handling has the same regression depth as scheduled runs.
- Add an explicit helper contract around per-project env hydration so future entrypoints reuse one path and tests can verify the same metadata is visible across wrappers, scheduled runs, and Telegram dispatches.

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
The prompt also tells the agent to create or refresh a persistent TODO for that repository on every round.

## Living Task List

The controller repository now keeps its own persistent task list in [TODO.md](TODO.md).
Update it alongside code changes so completed work and next iterations stay synchronized.

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
