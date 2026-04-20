import unittest
from pathlib import Path

from repo_autowork.config import Config
from repo_autowork.manager import assign_project_cron_minutes, cron_minute_for_project, render_crontab
from repo_autowork.models import ProjectRecord, State


def build_config() -> Config:
    root = Path("/tmp/repo-autowork")
    return Config(
        project_root=root,
        state_path=root / "data" / "state.json",
        repos_root=root.parent,
        tg_root=root / "tg",
        github_owner=None,
        github_visibility="private",
        telegram_bot_token=None,
        telegram_chat_id=None,
        autowork_base_command="codex exec --yolo",
        autowork_default_daily_runs=2,
        autowork_portfolio_hours=[10, 20],
        autowork_include_controller=False,
        autowork_python_bin="python3",
    )


def build_project(name: str) -> ProjectRecord:
    repo_dir = Path("/tmp") / name
    return ProjectRecord(
        slug=name,
        name=name,
        repo_path=str(repo_dir),
        daily_runs_target=2,
        tg_folder=str(repo_dir / "tg"),
    )


class CronRenderTests(unittest.TestCase):
    def test_cron_minutes_are_spread_across_projects(self) -> None:
        config = build_config()
        state = State(projects=[build_project(f"repo-{idx}") for idx in range(4)])

        crontab = render_crontab(config, state).splitlines()
        project_lines = [line for line in crontab if line and not line.startswith("#")][2:]
        minutes = sorted({int(line.split()[0]) for line in project_lines})

        self.assertEqual(minutes, [15, 30, 44, 59])

    def test_project_keeps_same_minute_for_each_daily_run(self) -> None:
        config = build_config()
        project = build_project("repo-1")
        state = State(projects=[project])

        crontab = render_crontab(config, state).splitlines()
        project_lines = [line for line in crontab if "/tmp/repo-1" in line]
        minutes = {int(line.split()[0]) for line in project_lines}
        hours = [int(line.split()[1]) for line in project_lines]

        self.assertEqual(minutes, {5})
        self.assertEqual(hours, [10, 20])

    def test_cron_minute_stays_in_valid_range(self) -> None:
        minutes = [cron_minute_for_project(idx, 20) for idx in range(20)]

        self.assertTrue(all(1 <= minute <= 59 for minute in minutes))
        self.assertEqual(minutes, sorted(minutes))

    def test_existing_project_minutes_are_preserved_when_new_repo_is_added(self) -> None:
        projects = [build_project("repo-1"), build_project("repo-2")]
        assign_project_cron_minutes(projects)
        original_minutes = {project.name: project.cron_minute for project in projects}

        projects.append(build_project("repo-3"))
        assign_project_cron_minutes(projects)

        self.assertEqual(projects[0].cron_minute, original_minutes["repo-1"])
        self.assertEqual(projects[1].cron_minute, original_minutes["repo-2"])
        self.assertIsNotNone(projects[2].cron_minute)
        self.assertEqual(len({project.cron_minute for project in projects}), 3)

    def test_controller_does_not_get_duplicate_schedule_when_managed(self) -> None:
        config = build_config()
        controller = ProjectRecord(
            slug="repo-autowork",
            name="repo-autowork",
            repo_path=str(config.project_root),
            daily_runs_target=4,
            tg_folder=str(config.project_root / "tg"),
        )
        state = State(projects=[controller])

        crontab = render_crontab(config, state).splitlines()
        project_lines = [line for line in crontab if str(config.project_root) in line]

        self.assertEqual(len(project_lines), 4)


if __name__ == "__main__":
    unittest.main()
