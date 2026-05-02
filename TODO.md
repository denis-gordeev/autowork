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
- The tracked controller-root `autowork.sh` now once again preserves the portfolio-wide `telegram-sync -> run -> review` sequence instead of drifting into a child-only `project-run` wrapper.
- `telegram-sync` now emits a handled/ignored summary with ignored-reason breakdowns, making dry-run output easier to audit during manual checks and CI coverage.
- CLI regressions now cover `telegram-sync --dry-run`, including ignored updates, topic routing, env hydration for the selected project, and status output from the `main()` entrypoint.
- Shared helpers now define the `.autowork/project.env` path and hydration behavior in one place, so scheduled runs and Telegram-triggered dispatch use the same override-loading contract.
- Regression coverage now checks the shared project-runtime env helper directly, and the tracked controller `autowork.sh` has been restored to the documented portfolio-wide flow.
- `doctor` now audits wrapper drift for both the tracked controller-root `autowork.sh` and discovered child wrappers, and returns a failing exit code when the generated contract no longer matches live files.
- The live controller-root `autowork.sh` has been restored to the documented `telegram-sync -> run -> review` portfolio flow, so the repository no longer silently ships a child-only wrapper regression.

## Next

- Decide whether `AUTOWORK_INSTRUCTIONS.md` should be a tracked controller policy file or a generated local artifact, then codify that in docs and gitignore if the current tracked-policy direction changes.
- Refresh `data/state.json` and generated child `autowork.sh` wrappers with a real controller run so live managed repos inherit the persisted cron minutes and current wrapper contract.
- Revisit cron allocation for larger portfolios: keep persisted minutes stable, but prefer nearby free slots for newly discovered repositories instead of drifting to arbitrary gaps.
- Persist Telegram sync handled/ignored counters somewhere reviewable, so unattended cron runs expose bot health without needing raw stdout logs.
- Add explicit regression coverage for Telegram failure paths, especially `get_updates` API errors and downstream dispatch failures, so status reporting stays trustworthy when integrations misbehave.
- Expose the shared project-runtime env keys in operator-facing docs or diagnostics, so downstream commands know which metadata is guaranteed at dispatch time.
- Surface wrapper-drift results in `review` output or a persisted journal, so operators can see contract health after cron runs without manually invoking `doctor`.
- Decide whether the controller root wrapper should remain git-tracked-only or whether `run` should be allowed to regenerate it as part of self-healing drift remediation.
