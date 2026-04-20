# TODO

## Done

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

## Next

- Decide whether `AUTOWORK_INSTRUCTIONS.md` should be a tracked controller policy file or a generated local artifact, then codify that in docs and gitignore if the current tracked-policy direction changes.
- Refresh `data/state.json` and generated child `autowork.sh` wrappers with a real controller run so live managed repos inherit the persisted cron minutes and current wrapper contract.
- Revisit cron allocation for larger portfolios: keep persisted minutes stable, but prefer nearby free slots for newly discovered repositories instead of drifting to arbitrary gaps.
- Add `telegram-sync --dry-run` CLI coverage for ignored updates, topic routing, and status output so message dispatch regressions surface before live bot runs.
- Extract and document a single per-project env hydration contract that all entrypoints share, keeping wrappers, scheduled runs, and Telegram dispatches behaviorally aligned.
