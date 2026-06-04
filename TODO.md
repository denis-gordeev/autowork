# TODO

## Done

- `sync_projects(..., dry_run=True)` is now read-only on disk, so review-style dry runs skip wrapper generation, `.autowork/project.env` writes, root wrapper regeneration, and `state.json` persistence.
- `project-run --format json` now outputs a machine-readable JSON payload with project metadata (slug, name, repo_path, branch, fork, topic), the generated prompt, dry-run flag, and dispatch result (returncode, stdout, stderr), matching the `review --json` and `run --format json` pattern for automated workflows.
- `project_run_once` now returns a `ProjectRunResult` dataclass that carries the prompt alongside the dispatch result, so `project-run --format json` can expose the generated prompt without rebuilding it separately.
- Regression coverage now guards `project-run --format json` for both successful and failed dispatches, verifying project metadata, prompt content, dry-run flag, and error details in the JSON payload.
- Restored the live controller-root `autowork.sh` to the documented portfolio-wide `telegram-sync -> run -> review` flow.

- `project-run --self-heal` now regenerates drifted controller and managed wrappers before running the project, matching the `doctor --self-heal`, `review --self-heal`, `run --self-heal`, and `telegram-sync --self-heal` behavior so wrapper drift can be fixed from the single-project surface as well.
- `project-run --format json --self-heal` reports `wrapper_contracts` with `controller_healed`, `healed_paths`, `per_project_healed`, and `per_project_drifted` in the machine-readable payload, so automated tooling can detect healing from the project-run surface.
- Regression coverage now guards `project-run --self-heal` (text and JSON) including per-project healing mappings.
- Restored the live controller-root `autowork.sh` to the documented portfolio-wide `telegram-sync -> run -> review` flow.

- Per-project granular healing is now available in `wrapper_contract_status` and all JSON output surfaces: `telegram-sync --self-heal --json`, `review --json`, `doctor --format json --self-heal`, and `run --format json --self-heal` now include `per_project_healed` and `per_project_drifted` mappings that associate each healed or drifted wrapper path with its project slug, resolving the remaining open TODO about per-project healing visibility.
- `wrapper_contract_status` now accepts an optional `state` parameter so discovered repo directories can be resolved to their project slug for per-project healing/drift tracking.
- Restored the live controller-root `autowork.sh` to the documented portfolio-wide `telegram-sync -> run -> review` flow.
- Regression coverage now guards per-project healing mappings in `telegram-sync --self-heal --json`, `review --json`, `doctor --format json --self-heal`, and `run --format json --self-heal`.
- `run --self-heal` now regenerates drifted controller and managed wrappers before syncing projects, matching the `doctor --self-heal` and `review --self-heal` behavior so wrapper drift can be fixed from the run command as well.
- `run --format json --self-heal` reports `controller_healed` and `healed_paths` in the machine-readable payload, so automated tooling can detect healing from the run surface.
- `telegram-sync --json --self-heal` now includes `controller_healed`, `drifted_paths`, and `healed_paths` in the `wrapper_contracts` payload, so per-project wrapper healing details are visible in machine-readable output.
- `history --until` now filters rounds to those at or before a given ISO timestamp, complementing `--since` for range queries.
- `history --json` now includes `until` in the machine-readable payload for query transparency.
- Regression coverage now guards `run --self-heal` (text and JSON), `telegram-sync --json --self-heal` per-project healing details, and `history --until` / `--since` + `--until` range filtering.
- Restored the live controller-root `autowork.sh` to the documented portfolio-wide `telegram-sync -> run -> review` flow.

- `review` now reports wrapper-contract health for both the tracked controller `autowork.sh` and discovered child wrappers, so unattended cron summaries expose wrapper drift without a separate `doctor` pass.
- Per-repo `autowork.sh` now routes into controller-side `project-run` instead of invoking the full portfolio loop from inside child repositories.
- The controller root `autowork.sh` keeps the portfolio-wide `telegram-sync -> run -> review` flow, so controller cron jobs still work while child wrappers stay repo-scoped.
- Runtime bootstrap now normalizes `PATH`, resolves the `codex` binary more defensively, and exposes `AUTOWORK_INCLUDE_CONTROLLER` so the controller repo can manage itself explicitly.
- Managed cron entries are staggered across the hour, and the controller avoids creating a duplicate portfolio-level cron line when it is already part of the managed project set.
- Regression tests cover cron staggering, optional controller discovery, generated wrapper contents, and runtime command resolution.
- Regression tests also guard the controller root wrapper contract so future refactors do not break the portfolio entrypoint.
- Pytest now works out of the box without requiring a manual `PYTHONPATH=src` prefix.
- Project records now persist `cron_minute`, so existing repositories keep stable launch minutes when discovery order changes.
- `project-run` now hydrates `.autowork/project.env` before dispatch, making wrapper metadata available to downstream commands and hooks.
- CLI regressions now cover persisted cron minutes and the `project-run` env-loading path.
- The controller root `autowork.sh` once again keeps the portfolio-wide `telegram-sync -> run -> review` flow instead of degrading into a child wrapper.
- CLI dry-run coverage now exercises the `main()` entrypoint for both `run` and `project-run`, so parser wiring and console output are covered in addition to helper-level behavior.
- Telegram-triggered dispatch now hydrates `.autowork/project.env` before invoking the base command, matching the scheduled `project-run` environment contract.
- Regression coverage now guards Telegram-triggered env loading as well as the dry-run CLI entrypoint flow.
- The tracked controller-root `autowork.sh` now once again preserves the portfolio-wide `telegram-sync -> run -> review` sequence instead of drifting into a child-only `project-run` wrapper.
- `telegram-sync` now emits a handled/ignored summary with ignored-reason breakdowns, making dry-run output easier to audit during manual checks and CI coverage.
- CLI regressions now cover `telegram-sync --dry-run`, including ignored updates, topic routing, env hydration for the selected project, and status output from the `main()` entrypoint.
- Shared helpers now define the `.autowork/project.env` path and hydration behavior in one place, so scheduled runs and Telegram-triggered dispatch use the same override-loading contract.
- Regression coverage now checks the shared project-runtime env helper directly, and the tracked controller `autowork.sh` has been restored to the documented portfolio-wide flow.
- `doctor` now audits wrapper drift for both the tracked controller-root `autowork.sh` and discovered child wrappers, and returns a failing exit code when the generated contract no longer matches live files.
- The live controller-root `autowork.sh` has been restored to the documented `telegram-sync -> run -> review` portfolio flow, so the repository no longer silently ships a child-only wrapper regression.
- `AUTOWORK_INSTRUCTIONS.md` is now documented as a tracked policy file committed to the repository (not generated, not gitignored), resolving the open decision about its lifecycle.
- `review` and `doctor` now emit remediation hints when wrapper drift is detected, so operators see the next safe command instead of only the drifted paths.
- Telegram sync summary is now persisted in `State.last_telegram_sync` with handled/ignored counters and a timestamp, so unattended cron runs expose bot health without needing raw stdout logs.
- `review` now surfaces the last Telegram sync summary in its output and in the `--json` machine-readable payload.
- Added regression coverage for Telegram failure paths: `telegram-sync` returns exit code 1 when `get_updates` raises `TelegramError`.
- `doctor` now lists the guaranteed project-runtime env keys (`AUTOWORK_CONTROLLER_ROOT`, `AUTOWORK_PROJECT_SLUG`, `TG_TOPIC_ID`, `AUTOWORK_TG_DIR`) so downstream tools can see which metadata is available at dispatch time.
- `review --json` outputs a machine-readable JSON payload with wrapper contract status, project list, and Telegram sync summary, so dashboards can consume review data without parsing text.
- `doctor --format json` outputs machine-readable JSON with per-check status and wrapper contract details, mirroring the `review --json` pattern for automated health monitoring.
- Regression coverage now guards `doctor --format json` for both healthy and drifted states.
- Added regression coverage for Telegram downstream dispatch failures: when the base command returns non-zero, `telegram-sync` still reports the failed status back to the Telegram topic and completes the sync round without crashing.
- Added regression coverage for Telegram `send_message` failure during dispatch confirmation, verifying that the sync loop absorbs the error and continues.
- Restored the live controller-root `autowork.sh` to the documented portfolio-wide `telegram-sync -> run -> review` flow so wrapper-contract audits pass.
- Per-project Telegram dispatch outcomes are now persisted in `TelegramSyncSummary.dispatch_outcomes` as `ProjectDispatchOutcome` records (slug, update_id, success, detail), so individual repo failures are visible in the review surface and `review --json` payload.
- `review` and `review --json` now list succeeded and failed dispatches from the last Telegram sync, making per-project dispatch health visible without raw stdout logs.
- The controller root wrapper is now self-healing: `sync_projects` (called by `run`) calls `ensure_root_wrapper` to regenerate the root `autowork.sh` when it has drifted from the generated contract, preventing the recurring drift regression.
- The live controller-root `autowork.sh` has been restored to the documented portfolio-wide `telegram-sync -> run -> review` flow.
- `doctor --self-heal` now regenerates drifted controller and managed wrappers in addition to auditing them, so operators can fix drift in a single command without running the full `run` cycle.
- `doctor --format json --self-heal` reports `controller_healed` and `healed_paths` so automated tooling can detect when self-healing occurred.
- Telegram sync history is now persisted in `State.telegram_sync_history` (capped at 10 rounds), so dispatch outcome trends are visible across multiple sync rounds rather than only the latest summary.
- `review` and `review --json` now include a sync history summary showing total handled updates and failed dispatches across recent rounds.
- Collision-aware cron minute assignment now prefers the nearest free slot to the ideal minute for newly discovered projects, preventing arbitrary minute gaps in large portfolios.
- Restored the live controller-root `autowork.sh` to the documented portfolio-wide `telegram-sync -> run -> review` flow (again).
- `review --self-heal` now regenerates drifted controller and managed wrappers, matching the `doctor --self-heal` behavior so wrapper drift can be fixed from either command.
- `review --json --self-heal` reports `controller_healed` and `healed_paths` in the machine-readable payload, so automated tooling can detect healing from the review surface as well.
- `telegram-sync --json` now outputs a machine-readable JSON payload with handled/ignored counts, dispatch outcomes, last update ID, and timestamp, so automated monitoring can consume sync round data without parsing text.
- Added a `history` CLI subcommand that exposes per-project dispatch outcome trends across recent Telegram sync rounds, with optional `--project` slug filtering and `--json` output.
- Regression coverage now guards `review --self-heal` (both text and JSON), `telegram-sync --json`, and the `history` subcommand (text, JSON, project filter, empty state).
- `telegram-sync --self-heal` now regenerates drifted controller and managed wrappers before processing updates, matching the `doctor --self-heal` and `review --self-heal` behavior so wrapper drift can be fixed from the sync command as well.
- `telegram-sync --json --self-heal` reports `wrapper_contracts` in the machine-readable payload, so automated monitoring can confirm wrapper health after a self-healing sync round.
- `history --limit` now restricts the number of sync rounds shown, and `history --since` filters rounds to those at or after a given ISO timestamp, enabling finer-grained trend queries.
- `history --json` now includes `limit` and `since` fields in the machine-readable payload for query transparency.
- `run --format json` now outputs a machine-readable JSON payload with synced project count and per-project details, matching the `review --json` and `doctor --format json` pattern for automated workflows.
- Regression coverage now guards `telegram-sync --self-heal` (wrapper regeneration and JSON output), `history --limit` / `--since`, and `run --format json`.

- Fixed the recurring controller-wrapper drift bug: `sync_projects` now calls `ensure_root_wrapper` after all `ensure_project_files` calls, so the controller root `autowork.sh` is not silently overwritten with the child-only `project-run` wrapper when `AUTOWORK_INCLUDE_CONTROLLER=1`.
- Removed the redundant second `ensure_project_record` call in `sync_projects` that caused duplicate snapshot reads for every discovered project.
- Normalized `wrapper_contracts` JSON fields across all self-heal surfaces: `run --format json --self-heal` and `project-run --format json --self-heal` now include `drifted_paths` and `per_project_drifted`, matching the `review --json`, `doctor --format json --self-heal`, and `telegram-sync --json --self-heal` payloads.
- Added regression coverage that verifies the controller wrapper stays intact after `sync_projects` runs with `AUTOWORK_INCLUDE_CONTROLLER=1`.
- Restored the live controller-root `autowork.sh` to the documented portfolio-wide `telegram-sync -> run -> review` flow.

## Next

- Extend the same read-only dry-run behavior to `project-run` and `telegram-sync` if we want every CLI surface to avoid disk writes in dry-run mode.
- Refresh `data/state.json` and generated child `autowork.sh` wrappers with a real controller run so live managed repos inherit the persisted cron minutes and current wrapper contract.
- Resolve GitHub authentication (`gh auth login`) so the controller can discover open issues and PRs for managed repositories.
