# TODO

## Done

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

## Next

- Refresh `data/state.json` and generated child `autowork.sh` wrappers with a real controller run so live managed repos inherit the persisted cron minutes and current wrapper contract.
- Revisit cron allocation for larger portfolios: keep persisted minutes stable, but prefer nearby free slots for newly discovered repositories instead of drifting to arbitrary gaps.
- Consider adding `--self-heal` flag to `doctor` so it can regenerate drifted wrappers in addition to auditing them.
- Consider surfacing per-project dispatch outcome history across multiple sync rounds rather than only the latest summary.
