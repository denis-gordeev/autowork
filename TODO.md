# TODO

## Done

- Per-repo `autowork.sh` now routes into controller-side `project-run` instead of invoking the full portfolio loop from inside child repositories.
- The controller root `autowork.sh` keeps the portfolio-wide `telegram-sync -> run -> review` flow, so controller cron jobs still work while child wrappers stay repo-scoped.
- Runtime bootstrap now normalizes `PATH`, resolves the `codex` binary more defensively, and exposes `AUTOWORK_INCLUDE_CONTROLLER` so the controller repo can manage itself explicitly.
- Managed cron entries are staggered across the hour, and the controller avoids creating a duplicate portfolio-level cron line when it is already part of the managed project set.
- Regression tests cover cron staggering, optional controller discovery, generated wrapper contents, and runtime command resolution.
- Regression tests also guard the controller root wrapper contract so future refactors do not break the portfolio entrypoint.
- Pytest now works out of the box without requiring a manual `PYTHONPATH=src` prefix.

## Next

- Persist a per-project cron minute in state so schedules stay stable when repository ordering changes.
- Load `.autowork/project.env` before invoking `project-run` so per-repository wrapper metadata is available to custom commands and hooks.
- Add CLI coverage for `project-run --dry-run` and for controller-included `run` flows to catch prompt/regression issues earlier.
- Decide whether `AUTOWORK_INSTRUCTIONS.md` should be a tracked controller policy file or a generated local artifact, then codify that in docs and gitignore if the current tracked-policy direction changes.
