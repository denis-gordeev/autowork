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
PYTHONPATH=src python3 -m repo_autowork.cli run --format json
PYTHONPATH=src python3 -m repo_autowork.cli run --self-heal
PYTHONPATH=src python3 -m repo_autowork.cli review
PYTHONPATH=src python3 -m repo_autowork.cli sync-crontab
PYTHONPATH=src python3 -m repo_autowork.cli project-run --repo /Users/denis/programming/autowork/mcp-russia --dry-run
PYTHONPATH=src python3 -m repo_autowork.cli telegram-sync
PYTHONPATH=src python3 -m repo_autowork.cli telegram-sync --self-heal
PYTHONPATH=src python3 -m repo_autowork.cli history
PYTHONPATH=src python3 -m repo_autowork.cli history --project alpha --json
PYTHONPATH=src python3 -m repo_autowork.cli history --limit 5 --since "2026-05-27T10:00:00+00:00"
PYTHONPATH=src python3 -m repo_autowork.cli history --until "2026-05-28T10:00:00+00:00"
./autowork.sh --dry-run
pytest -q
```

## Progress Tracker

### Completed

- Surfaced wrapper-contract health directly in `review`, so unattended portfolio summaries now show whether the tracked controller wrapper or any managed child wrapper drifted from the generated contract without requiring a separate `doctor` run.
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
- Restored the tracked controller-root `autowork.sh` contract so the root wrapper again keeps the portfolio-wide `telegram-sync -> run -> review` flow instead of drifting into a child-only `project-run`.
- `telegram-sync` now prints an ignored-update breakdown after each sync, making dry-run output easier to audit when updates are skipped for chat, thread, sender, or payload reasons.
- Added CLI dry-run coverage for `telegram-sync`, including ignored updates, topic routing, env hydration for the routed project, and user-facing status output.
- Extracted a shared project-runtime env helper so `.autowork/project.env` path resolution and override-loading are defined in one place for wrappers, scheduled `project-run`, and Telegram-triggered dispatches.
- Added regression coverage for the shared project-runtime env helper and restored the tracked controller-root `autowork.sh` so the checked-in wrapper matches the documented portfolio contract again.
- Added a `doctor`-level wrapper drift audit that compares the tracked controller `autowork.sh` and discovered child wrappers against the generated contracts, and now exits non-zero when either side drifts.
- Restored the live controller-root `autowork.sh` to the documented portfolio-wide `telegram-sync -> run -> review` flow so the new audit passes on the checked-in repository state.
- Documented `AUTOWORK_INSTRUCTIONS.md` as a tracked policy file committed to the repository, resolving the open decision about its lifecycle.
- `review` and `doctor` now emit remediation hints when wrapper drift is detected, so operators see the next safe command instead of only the drifted paths.
- Telegram sync summary is now persisted in `State.last_telegram_sync` with handled/ignored counters and timestamp, so unattended cron runs expose bot health without raw stdout logs.
- `review` now surfaces the last Telegram sync summary in its output and in the `--json` machine-readable payload.
- Added regression coverage for Telegram failure paths: `telegram-sync` returns exit code 1 when `get_updates` raises `TelegramError`.
- `doctor` now lists the guaranteed project-runtime env keys so downstream tools know which metadata is available at dispatch time.
- `review --json` outputs machine-readable JSON with wrapper contract status, project list, and Telegram sync summary.
- `doctor --format json` outputs machine-readable JSON with per-check status and wrapper contract details, mirroring the `review --json` pattern for automated health monitoring.
- Added regression coverage for Telegram downstream dispatch failures: when the base command returns non-zero, `telegram-sync` reports the failed status back to the Telegram topic and completes the sync round.
- Restored the live controller-root `autowork.sh` to the documented portfolio-wide `telegram-sync -> run -> review` flow so wrapper-contract audits pass.
- Per-project Telegram dispatch outcomes are now persisted in `TelegramSyncSummary.dispatch_outcomes` as `ProjectDispatchOutcome` records, so individual repo failures are visible in the review surface and `review --json` payload.
- `review` now lists succeeded and failed dispatches from the last Telegram sync.
- The controller root wrapper is now self-healing: `sync_projects` (called by `run`) regenerates the root `autowork.sh` when it has drifted from the generated contract.
- `doctor --self-heal` now regenerates drifted controller and managed wrappers in addition to auditing them, so operators can fix drift in a single command without running the full `run` cycle.
- `doctor --format json --self-heal` reports `controller_healed` and `healed_paths` so automated tooling can detect when self-healing occurred.
- Telegram sync history is now persisted in `State.telegram_sync_history` (capped at 10 rounds), so dispatch outcome trends are visible across multiple sync rounds rather than only the latest summary.
- `review` and `review --json` now include a sync history summary showing total handled updates and failed dispatches across recent rounds.
- Collision-aware cron minute assignment now prefers the nearest free slot to the ideal minute for newly discovered projects, preventing arbitrary minute gaps in large portfolios.
- Restored the live controller-root `autowork.sh` to the documented portfolio-wide `telegram-sync -> run -> review` flow (again).
- `review --self-heal` now regenerates drifted controller and managed wrappers, matching `doctor --self-heal` so wrapper drift can be fixed from either command.
- `review --json --self-heal` reports `controller_healed` and `healed_paths` in the machine-readable payload.
- `telegram-sync --json` now outputs a machine-readable JSON payload with handled/ignored counts, dispatch outcomes, last update ID, and timestamp.
- Added a `history` CLI subcommand that exposes per-project dispatch outcome trends across recent Telegram sync rounds, with optional `--project` slug filtering and `--json` output.
- Regression coverage now guards `review --self-heal` (text and JSON), `telegram-sync --json`, and the `history` subcommand (text, JSON, project filter, empty state).
- `telegram-sync --self-heal` now regenerates drifted controller and managed wrappers before processing updates, matching the `doctor --self-heal` and `review --self-heal` behavior.
- `telegram-sync --json --self-heal` reports `wrapper_contracts` in the machine-readable payload, so automated monitoring can confirm wrapper health after a self-healing sync round.
- `history --limit` now restricts the number of sync rounds shown, and `history --since` filters rounds to those at or after a given ISO timestamp, enabling finer-grained trend queries.
- `run --format json` now outputs a machine-readable JSON payload with synced project count and per-project details, matching the `review --json` and `doctor --format json` pattern for automated workflows.
- Regression coverage now guards `telegram-sync --self-heal` (wrapper regeneration and JSON output), `history --limit` / `--since`, and `run --format json`.
- `run --self-heal` now regenerates drifted controller and managed wrappers before syncing projects, matching the `doctor --self-heal` and `review --self-heal` behavior.
- `run --format json --self-heal` reports `controller_healed` and `healed_paths` in the machine-readable payload.
- `telegram-sync --json --self-heal` now includes `controller_healed`, `drifted_paths`, and `healed_paths` in the `wrapper_contracts` payload for per-project wrapper healing visibility.
- `history --until` now filters rounds to those at or before a given ISO timestamp, complementing `--since` for range queries.
- `history --json` now includes `until` in the machine-readable payload for query transparency.
- Regression coverage now guards `run --self-heal` (text and JSON), `telegram-sync --json --self-heal` per-project healing details, and `history --until` / `--since` + `--until` range filtering.

### Next Iterations

- Refresh persisted state and generated wrappers so older `state.json` entries and child repos pick up the new `cron_minute` + wrapper contract on the next real controller run.
- Consider adding per-project granular healing in `telegram-sync --self-heal --json` that maps each healed path to its project slug.

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

Before dispatch, the controller hydrates `.autowork/project.env` through the shared runtime helper. Current guaranteed keys are:

- `AUTOWORK_CONTROLLER_ROOT`
- `AUTOWORK_PROJECT_SLUG`
- `TG_TOPIC_ID`
- `AUTOWORK_TG_DIR`

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
