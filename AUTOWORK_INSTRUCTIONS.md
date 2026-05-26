# Repo Autowork Instructions

This file is a **tracked policy document** committed to the repository. It is not generated and should not be gitignored. Changes to scheduling or run-frequency policy should be made here and committed.

- Keep managed repository cron entries staggered across the hour.
- Do not schedule all child repositories at the same minute unless explicitly requested.
- Preserve the current number of daily runs per project unless the task explicitly changes run frequency.
