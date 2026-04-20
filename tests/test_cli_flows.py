import argparse
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repo_autowork import cli
from repo_autowork.config import build_config
from repo_autowork.models import ProjectRecord, State


class CliFlowTests(unittest.TestCase):
    def test_main_run_dry_run_routes_through_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            controller_root = Path(tmp_dir) / "controller"
            repos_root = Path(tmp_dir) / "managed"
            controller_root.mkdir(parents=True)
            repos_root.mkdir(parents=True)

            repo_one = repos_root / "alpha"
            repo_two = repos_root / "beta"
            for repo_dir in (repo_one, repo_two):
                repo_dir.mkdir(parents=True)
                (repo_dir / ".git").mkdir()

            config = build_config(controller_root, repos_root=str(repos_root))
            projects = [
                ProjectRecord(slug="alpha", name="alpha", repo_path=str(repo_one)),
                ProjectRecord(slug="beta", name="beta", repo_path=str(repo_two), telegram_topic_id=77),
            ]

            stdout = io.StringIO()
            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "repo_autowork.cli.load_state", return_value=State()
            ), patch("repo_autowork.cli.sync_projects", return_value=projects) as sync_mock, patch(
                "repo_autowork.cli.safe_sync_crontab"
            ) as crontab_mock, patch("sys.argv", ["repo-autowork", "run", "--repos-root", str(repos_root), "--dry-run"]), patch(
                "sys.stdout", stdout
            ):
                exit_code = cli.main()

            self.assertEqual(exit_code, 0)
            sync_mock.assert_called_once()
            self.assertTrue(sync_mock.call_args.kwargs["dry_run"])
            crontab_mock.assert_called_once()
            rendered = stdout.getvalue()
            self.assertIn("Synced 2 repositories.", rendered)
            self.assertIn(f"- alpha | {repo_one} | topic=pending", rendered)
            self.assertIn(f"- beta | {repo_two} | topic=77", rendered)

    def test_project_run_loads_project_env_before_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "controller"
            repo_dir = root.parent / "managed-repo"
            root.mkdir(parents=True)
            repo_dir.mkdir(parents=True)
            (repo_dir / ".autowork").mkdir(parents=True)
            (repo_dir / ".autowork" / "project.env").write_text(
                "AUTOWORK_PROJECT_SLUG=managed-repo\nTG_TOPIC_ID=42\n",
                encoding="utf-8",
            )

            config = build_config(root, repos_root=str(root.parent))
            project = ProjectRecord(
                slug="managed-repo",
                name="managed-repo",
                repo_path=str(repo_dir),
                tg_folder=str(root / "tg" / "managed-repo"),
            )
            state = State(projects=[project])
            args = argparse.Namespace(repo=str(repo_dir), repos_root=str(root.parent), dry_run=True)

            original_slug = os.environ.get("AUTOWORK_PROJECT_SLUG")
            original_topic = os.environ.get("TG_TOPIC_ID")
            try:
                os.environ["AUTOWORK_PROJECT_SLUG"] = "stale-value"
                os.environ["TG_TOPIC_ID"] = "stale-topic"

                def fake_project_run_once(_, passed_project, dry_run=False):
                    self.assertTrue(dry_run)
                    self.assertEqual(passed_project.repo_path, str(repo_dir))
                    self.assertEqual(os.environ["AUTOWORK_PROJECT_SLUG"], "managed-repo")
                    self.assertEqual(os.environ["TG_TOPIC_ID"], "42")
                    return cli.subprocess.CompletedProcess(args=[], returncode=0, stdout="prompt", stderr="")

                with patch("repo_autowork.cli.build_config", return_value=config), patch(
                    "repo_autowork.cli.load_state", return_value=state
                ), patch("repo_autowork.cli.sync_projects"), patch(
                    "repo_autowork.cli.project_run_once", side_effect=fake_project_run_once
                ), patch("repo_autowork.cli.save_state"):
                    result = cli.cmd_project_run(args)

                self.assertEqual(result, 0)
            finally:
                if original_slug is None:
                    os.environ.pop("AUTOWORK_PROJECT_SLUG", None)
                else:
                    os.environ["AUTOWORK_PROJECT_SLUG"] = original_slug
                if original_topic is None:
                    os.environ.pop("TG_TOPIC_ID", None)
                else:
                    os.environ["TG_TOPIC_ID"] = original_topic

    def test_main_project_run_dry_run_prints_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "controller"
            repo_dir = root.parent / "managed-repo"
            root.mkdir(parents=True)
            repo_dir.mkdir(parents=True)
            (repo_dir / ".autowork").mkdir(parents=True)
            (repo_dir / ".autowork" / "project.env").write_text(
                "AUTOWORK_PROJECT_SLUG=managed-repo\nTG_TOPIC_ID=42\n",
                encoding="utf-8",
            )

            config = build_config(root, repos_root=str(root.parent))
            project = ProjectRecord(
                slug="managed-repo",
                name="managed-repo",
                repo_path=str(repo_dir),
                tg_folder=str(root / "tg" / "managed-repo"),
            )
            state = State(projects=[project])
            stdout = io.StringIO()

            def fake_project_run_once(_, passed_project, dry_run=False):
                self.assertTrue(dry_run)
                self.assertEqual(passed_project.repo_path, str(repo_dir))
                self.assertEqual(os.environ["AUTOWORK_PROJECT_SLUG"], "managed-repo")
                self.assertEqual(os.environ["TG_TOPIC_ID"], "42")
                return cli.subprocess.CompletedProcess(args=[], returncode=0, stdout="prompt body", stderr="")

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "repo_autowork.cli.load_state", return_value=state
            ), patch("repo_autowork.cli.sync_projects"), patch(
                "repo_autowork.cli.project_run_once", side_effect=fake_project_run_once
            ), patch("repo_autowork.cli.save_state") as save_mock, patch(
                "sys.argv", ["repo-autowork", "project-run", "--repo", str(repo_dir), "--repos-root", str(root.parent), "--dry-run"]
            ), patch("sys.stdout", stdout):
                exit_code = cli.main()

            self.assertEqual(exit_code, 0)
            save_mock.assert_called_once()
            self.assertIn("prompt body", stdout.getvalue())

    def test_telegram_sync_loads_project_env_before_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "controller"
            repo_dir = root.parent / "managed-repo"
            root.mkdir(parents=True)
            repo_dir.mkdir(parents=True)
            (repo_dir / ".autowork").mkdir(parents=True)
            (repo_dir / ".autowork" / "project.env").write_text(
                "AUTOWORK_PROJECT_SLUG=managed-repo\nTG_TOPIC_ID=42\n",
                encoding="utf-8",
            )

            config = build_config(root, repos_root=str(root.parent))
            project = ProjectRecord(
                slug="managed-repo",
                name="managed-repo",
                repo_path=str(repo_dir),
                telegram_topic_id=42,
                tg_folder=str(root / "tg" / "managed-repo"),
            )
            state = State(projects=[project])
            args = argparse.Namespace(repos_root=str(root.parent), timeout=0, dry_run=True)
            updates = [
                {
                    "update_id": 100,
                    "message": {
                        "message_id": 5,
                        "message_thread_id": 42,
                        "text": "Handle this task",
                        "chat": {"id": "12345"},
                        "from": {"is_bot": False},
                    },
                }
            ]

            original_slug = os.environ.get("AUTOWORK_PROJECT_SLUG")
            original_topic = os.environ.get("TG_TOPIC_ID")
            try:
                os.environ["AUTOWORK_PROJECT_SLUG"] = "stale-value"
                os.environ["TG_TOPIC_ID"] = "stale-topic"

                def fake_dispatch(_, passed_project, text, dry_run=False):
                    self.assertTrue(dry_run)
                    self.assertEqual(passed_project.repo_path, str(repo_dir))
                    self.assertEqual(text, "Handle this task")
                    self.assertEqual(os.environ["AUTOWORK_PROJECT_SLUG"], "managed-repo")
                    self.assertEqual(os.environ["TG_TOPIC_ID"], "42")
                    return cli.subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")

                with patch("repo_autowork.cli.build_config", return_value=config), patch(
                    "repo_autowork.cli.load_state", return_value=state
                ), patch("repo_autowork.cli.sync_projects"), patch(
                    "repo_autowork.cli.get_updates", return_value=updates
                ), patch("repo_autowork.cli.write_telegram_mirror", return_value=repo_dir / "inbox" / "telegram" / "update-100.json"), patch(
                    "repo_autowork.cli._dispatch_telegram_message", side_effect=fake_dispatch
                ), patch("repo_autowork.cli.save_state"):
                    result = cli.cmd_telegram_sync(args)

                self.assertEqual(result, 0)
                self.assertEqual(state.last_telegram_update_id, 100)
            finally:
                if original_slug is None:
                    os.environ.pop("AUTOWORK_PROJECT_SLUG", None)
                else:
                    os.environ["AUTOWORK_PROJECT_SLUG"] = original_slug
                if original_topic is None:
                    os.environ.pop("TG_TOPIC_ID", None)
                else:
                    os.environ["TG_TOPIC_ID"] = original_topic


if __name__ == "__main__":
    unittest.main()
