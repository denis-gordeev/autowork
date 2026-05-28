import argparse
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repo_autowork import cli
from repo_autowork.config import build_config
from repo_autowork.models import ProjectDispatchOutcome, ProjectRecord, State, TelegramSyncSummary


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

    def test_dispatch_telegram_message_supports_shell_prompt_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "controller"
            repo_dir = root.parent / "managed-repo"
            root.mkdir(parents=True)
            repo_dir.mkdir(parents=True)

            original_base = os.environ.get("AUTOWORK_BASE_COMMAND")
            original_model = os.environ.get("MODEL")
            try:
                os.environ["AUTOWORK_BASE_COMMAND"] = 'python3 -c "import os,sys;print(os.environ[\'MODEL\']);print(sys.argv[1])" "$PROMPT"'
                os.environ["MODEL"] = "fhgenie/glm-5.1"
                config = build_config(root, repos_root=str(root.parent))
                project = ProjectRecord(
                    slug="managed-repo",
                    name="managed-repo",
                    repo_path=str(repo_dir),
                    telegram_topic_id=42,
                    tg_folder=str(root / "tg" / "managed-repo"),
                )

                result = cli._dispatch_telegram_message(config, project, "Handle this task")

                self.assertEqual(result.returncode, 0)
                rendered = result.stdout.strip().splitlines()
                self.assertEqual(rendered[0], "fhgenie/glm-5.1")
                self.assertIn("Incoming Telegram message for `managed-repo`.", rendered)
                self.assertEqual(rendered[-1], "Handle this task")
            finally:
                if original_base is None:
                    os.environ.pop("AUTOWORK_BASE_COMMAND", None)
                else:
                    os.environ["AUTOWORK_BASE_COMMAND"] = original_base
                if original_model is None:
                    os.environ.pop("MODEL", None)
                else:
                    os.environ["MODEL"] = original_model

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

    def test_main_telegram_sync_dry_run_reports_routing_and_ignored_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "controller"
            repo_one = root.parent / "managed-repo"
            repo_two = root.parent / "second-repo"
            root.mkdir(parents=True)
            repo_one.mkdir(parents=True)
            repo_two.mkdir(parents=True)
            for repo_dir, topic_id in ((repo_one, 42), (repo_two, 77)):
                (repo_dir / ".autowork").mkdir(parents=True)
                (repo_dir / ".autowork" / "project.env").write_text(
                    f"AUTOWORK_PROJECT_SLUG={repo_dir.name}\nTG_TOPIC_ID={topic_id}\n",
                    encoding="utf-8",
                )

            config = build_config(root, repos_root=str(root.parent))
            project_one = ProjectRecord(
                slug="managed-repo",
                name="managed-repo",
                repo_path=str(repo_one),
                telegram_topic_id=42,
                tg_folder=str(root / "tg" / "managed-repo"),
            )
            project_two = ProjectRecord(
                slug="second-repo",
                name="second-repo",
                repo_path=str(repo_two),
                telegram_topic_id=77,
                tg_folder=str(root / "tg" / "second-repo"),
            )
            state = State(projects=[project_one, project_two], last_telegram_update_id=99)
            updates = [
                {"update_id": 100},
                {
                    "update_id": 101,
                    "message": {
                        "message_id": 1,
                        "chat": {"id": "wrong-chat"},
                        "from": {"is_bot": False},
                        "message_thread_id": 42,
                        "text": "Wrong chat",
                    },
                },
                {
                    "update_id": 102,
                    "message": {
                        "message_id": 2,
                        "chat": {"id": config.telegram_chat_id},
                        "from": {"is_bot": True},
                        "message_thread_id": 42,
                        "text": "Bot message",
                    },
                },
                {
                    "update_id": 103,
                    "message": {
                        "message_id": 3,
                        "chat": {"id": config.telegram_chat_id},
                        "from": {"is_bot": False},
                        "text": "No thread",
                    },
                },
                {
                    "update_id": 104,
                    "message": {
                        "message_id": 4,
                        "chat": {"id": config.telegram_chat_id},
                        "from": {"is_bot": False},
                        "message_thread_id": 999,
                        "text": "Unknown topic",
                    },
                },
                {
                    "update_id": 105,
                    "message": {
                        "message_id": 5,
                        "chat": {"id": config.telegram_chat_id},
                        "from": {"is_bot": False},
                        "message_thread_id": 77,
                        "text": "Ship this",
                    },
                },
            ]

            stdout = io.StringIO()

            def fake_dispatch(_, passed_project, text, dry_run=False):
                self.assertTrue(dry_run)
                self.assertEqual(passed_project.repo_path, str(repo_two))
                self.assertEqual(text, "Ship this")
                self.assertEqual(os.environ["AUTOWORK_PROJECT_SLUG"], "second-repo")
                self.assertEqual(os.environ["TG_TOPIC_ID"], "77")
                return cli.subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "repo_autowork.cli.load_state", return_value=state
            ), patch("repo_autowork.cli.sync_projects"), patch(
                "repo_autowork.cli.get_updates", return_value=updates
            ), patch("repo_autowork.cli.write_telegram_mirror", return_value=repo_two / "inbox" / "telegram" / "update-105.json"), patch(
                "repo_autowork.cli._dispatch_telegram_message", side_effect=fake_dispatch
            ) as dispatch_mock, patch("repo_autowork.cli.save_state") as save_mock, patch(
                "sys.argv", ["repo-autowork", "telegram-sync", "--repos-root", str(root.parent), "--dry-run"]
            ), patch("sys.stdout", stdout):
                exit_code = cli.main()

            self.assertEqual(exit_code, 0)
            self.assertEqual(state.last_telegram_update_id, 105)
            dispatch_mock.assert_called_once()
            self.assertGreaterEqual(save_mock.call_count, 1)
            rendered = stdout.getvalue()
            self.assertIn("Syncing Telegram updates for 2 managed repositories starting from offset 100...", rendered)
            self.assertIn("Fetched 6 Telegram update(s).", rendered)
            self.assertIn("Dispatched Telegram update 105 to second-repo", rendered)
            self.assertIn("Handled 1 Telegram update(s).", rendered)
            self.assertIn(
                "Ignored 5 Telegram update(s): bot_sender=1, missing_thread=1, non_message=1, other_chat=1, unknown_topic=1.",
                rendered,
            )

    def test_main_doctor_reports_wrapper_drift_and_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            controller_root = Path(tmp_dir) / "controller"
            repos_root = Path(tmp_dir) / "managed"
            controller_root.mkdir(parents=True)
            repos_root.mkdir(parents=True)
            repo_dir = repos_root / "alpha"
            repo_dir.mkdir(parents=True)
            (repo_dir / ".git").mkdir()
            (controller_root / "autowork.sh").write_text("# drifted\n", encoding="utf-8")
            (repo_dir / "autowork.sh").write_text("# drifted child\n", encoding="utf-8")

            config = build_config(controller_root, repos_root=str(repos_root))
            stdout = io.StringIO()

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "sys.argv", ["repo-autowork", "doctor", "--repos-root", str(repos_root)]
            ), patch("sys.stdout", stdout):
                exit_code = cli.main()

            self.assertEqual(exit_code, 1)
            rendered = stdout.getvalue()
            self.assertIn("MISSING: Controller wrapper contract", rendered)
            self.assertIn("MISSING: Managed wrapper contracts", rendered)
            self.assertIn(str(controller_root / "autowork.sh"), rendered)
            self.assertIn(str(repo_dir / "autowork.sh"), rendered)
            self.assertIn("Remediation:", rendered)

    def test_main_doctor_succeeds_when_wrappers_match_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            controller_root = Path(tmp_dir) / "controller"
            repos_root = Path(tmp_dir) / "managed"
            controller_root.mkdir(parents=True)
            repos_root.mkdir(parents=True)
            repo_dir = repos_root / "alpha"
            repo_dir.mkdir(parents=True)
            (repo_dir / ".git").mkdir()

            config = build_config(controller_root, repos_root=str(repos_root))
            (controller_root / "autowork.sh").write_text(cli.render_root_autowork(config), encoding="utf-8")
            (repo_dir / "autowork.sh").write_text(cli.render_project_autowork(config), encoding="utf-8")
            stdout = io.StringIO()

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "sys.argv", ["repo-autowork", "doctor", "--repos-root", str(repos_root)]
            ), patch("sys.stdout", stdout):
                exit_code = cli.main()

            self.assertEqual(exit_code, 0)
            rendered = stdout.getvalue()
            self.assertIn("OK: Controller wrapper contract", rendered)
            self.assertIn("OK: Managed wrapper contracts", rendered)

    def test_main_review_reports_wrapper_contract_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            controller_root = Path(tmp_dir) / "controller"
            repos_root = Path(tmp_dir) / "managed"
            controller_root.mkdir(parents=True)
            repos_root.mkdir(parents=True)
            repo_dir = repos_root / "alpha"
            repo_dir.mkdir(parents=True)
            (repo_dir / ".git").mkdir()

            config = build_config(controller_root, repos_root=str(repos_root))
            (controller_root / "autowork.sh").write_text(cli.render_root_autowork(config), encoding="utf-8")
            (repo_dir / "autowork.sh").write_text("# drifted child\n", encoding="utf-8")
            state = State(
                projects=[
                    ProjectRecord(
                        slug="alpha",
                        name="alpha",
                        repo_path=str(repo_dir),
                        current_branch="main",
                        default_branch="main",
                    )
                ]
            )
            stdout = io.StringIO()

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "repo_autowork.cli.load_state", return_value=state
            ), patch("repo_autowork.cli.sync_projects"), patch(
                "sys.argv", ["repo-autowork", "review", "--repos-root", str(repos_root), "--dry-run"]
            ), patch("sys.stdout", stdout):
                exit_code = cli.main()

            self.assertEqual(exit_code, 0)
            rendered = stdout.getvalue()
            self.assertIn("Wrapper contracts: controller=ok", rendered)
            self.assertIn("managed=drifted", rendered)
            self.assertIn(str(repo_dir / "autowork.sh"), rendered)
            self.assertIn("Remediation:", rendered)

    def test_telegram_sync_returns_error_on_api_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "controller"
            root.mkdir(parents=True)

            config = build_config(root, repos_root=str(root.parent))
            state = State()
            args = argparse.Namespace(repos_root=str(root.parent), timeout=0, dry_run=True)

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "repo_autowork.cli.load_state", return_value=state
            ), patch("repo_autowork.cli.sync_projects"), patch(
                "repo_autowork.cli.get_updates", side_effect=cli.TelegramError("API error 403: Forbidden")
            ):
                exit_code = cli.cmd_telegram_sync(args)

            self.assertEqual(exit_code, 1)

    def test_telegram_sync_persists_summary(self) -> None:
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
            state = State(projects=[project], last_telegram_update_id=99)
            args = argparse.Namespace(repos_root=str(root.parent), timeout=0, dry_run=True)
            updates = [
                {
                    "update_id": 100,
                    "message": {
                        "message_id": 1,
                        "chat": {"id": config.telegram_chat_id},
                        "from": {"is_bot": False},
                        "message_thread_id": 42,
                        "text": "Do something",
                    },
                },
                {"update_id": 101},
            ]

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "repo_autowork.cli.load_state", return_value=state
            ), patch("repo_autowork.cli.sync_projects"), patch(
                "repo_autowork.cli.get_updates", return_value=updates
            ), patch("repo_autowork.cli.write_telegram_mirror", return_value=repo_dir / "inbox" / "telegram" / "update-100.json"), patch(
                "repo_autowork.cli._dispatch_telegram_message",
                return_value=cli.subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr=""),
            ), patch("repo_autowork.cli.save_state") as save_mock:
                result = cli.cmd_telegram_sync(args)

            self.assertEqual(result, 0)
            self.assertIsNotNone(state.last_telegram_sync)
            self.assertEqual(state.last_telegram_sync.handled, 1)
            self.assertEqual(state.last_telegram_sync.ignored.get("non_message", 0), 1)
            self.assertTrue(state.last_telegram_sync.timestamp)

    def test_review_json_outputs_machine_readable_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            controller_root = Path(tmp_dir) / "controller"
            repos_root = Path(tmp_dir) / "managed"
            controller_root.mkdir(parents=True)
            repos_root.mkdir(parents=True)
            repo_dir = repos_root / "alpha"
            repo_dir.mkdir(parents=True)
            (repo_dir / ".git").mkdir()

            config = build_config(controller_root, repos_root=str(repos_root))
            (controller_root / "autowork.sh").write_text(cli.render_root_autowork(config), encoding="utf-8")
            (repo_dir / "autowork.sh").write_text(cli.render_project_autowork(config), encoding="utf-8")
            state = State(
                projects=[
                    ProjectRecord(
                        slug="alpha",
                        name="alpha",
                        repo_path=str(repo_dir),
                        current_branch="main",
                        default_branch="main",
                    )
                ]
            )
            stdout = io.StringIO()

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "repo_autowork.cli.load_state", return_value=state
            ), patch("repo_autowork.cli.sync_projects"), patch(
                "sys.argv", ["repo-autowork", "review", "--repos-root", str(repos_root), "--dry-run", "--json"]
            ), patch("sys.stdout", stdout):
                exit_code = cli.main()

            self.assertEqual(exit_code, 0)
            data = json.loads(stdout.getvalue())
            self.assertEqual(data["managed_count"], 1)
            self.assertEqual(data["projects"][0]["name"], "alpha")
            self.assertEqual(data["wrapper_contracts"]["controller"], "ok")
            self.assertIsNone(data["last_telegram_sync"])

    def test_doctor_includes_runtime_env_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            controller_root = Path(tmp_dir) / "controller"
            repos_root = Path(tmp_dir) / "managed"
            controller_root.mkdir(parents=True)
            repos_root.mkdir(parents=True)

            config = build_config(controller_root, repos_root=str(repos_root))
            stdout = io.StringIO()

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "sys.argv", ["repo-autowork", "doctor", "--repos-root", str(repos_root)]
            ), patch("sys.stdout", stdout):
                cli.main()

            rendered = stdout.getvalue()
            self.assertIn("Project runtime env keys", rendered)
            self.assertIn("AUTOWORK_CONTROLLER_ROOT", rendered)
            self.assertIn("AUTOWORK_PROJECT_SLUG", rendered)

    def test_doctor_format_json_outputs_machine_readable_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            controller_root = Path(tmp_dir) / "controller"
            repos_root = Path(tmp_dir) / "managed"
            controller_root.mkdir(parents=True)
            repos_root.mkdir(parents=True)
            repo_dir = repos_root / "alpha"
            repo_dir.mkdir(parents=True)
            (repo_dir / ".git").mkdir()

            config = build_config(controller_root, repos_root=str(repos_root))
            (controller_root / "autowork.sh").write_text(cli.render_root_autowork(config), encoding="utf-8")
            (repo_dir / "autowork.sh").write_text(cli.render_project_autowork(config), encoding="utf-8")
            stdout = io.StringIO()

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "sys.argv", ["repo-autowork", "doctor", "--repos-root", str(repos_root), "--format", "json"]
            ), patch("sys.stdout", stdout):
                exit_code = cli.main()

            self.assertEqual(exit_code, 0)
            data = json.loads(stdout.getvalue())
            self.assertIsInstance(data["checks"], list)
            self.assertTrue(any(c["label"] == "Managed repos root" for c in data["checks"]))
            self.assertTrue(any(c["label"] == "Controller wrapper contract" for c in data["checks"]))
            self.assertEqual(data["wrapper_contracts"]["controller"], "ok")
            self.assertEqual(data["wrapper_contracts"]["managed"], "ok")
            self.assertEqual(data["wrapper_contracts"]["drifted_paths"], [])

    def test_doctor_format_json_reports_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            controller_root = Path(tmp_dir) / "controller"
            repos_root = Path(tmp_dir) / "managed"
            controller_root.mkdir(parents=True)
            repos_root.mkdir(parents=True)
            repo_dir = repos_root / "alpha"
            repo_dir.mkdir(parents=True)
            (repo_dir / ".git").mkdir()
            (controller_root / "autowork.sh").write_text("# drifted\n", encoding="utf-8")
            (repo_dir / "autowork.sh").write_text("# drifted child\n", encoding="utf-8")

            config = build_config(controller_root, repos_root=str(repos_root))
            stdout = io.StringIO()

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "sys.argv", ["repo-autowork", "doctor", "--repos-root", str(repos_root), "--format", "json"]
            ), patch("sys.stdout", stdout):
                exit_code = cli.main()

            self.assertEqual(exit_code, 1)
            data = json.loads(stdout.getvalue())
            self.assertEqual(data["wrapper_contracts"]["controller"], "drifted")
            self.assertEqual(data["wrapper_contracts"]["managed"], "drifted")
            self.assertIn(str(repo_dir / "autowork.sh"), data["wrapper_contracts"]["drifted_paths"])

    def test_telegram_sync_handles_base_command_failure(self) -> None:
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
            state = State(projects=[project], last_telegram_update_id=99)
            args = argparse.Namespace(repos_root=str(root.parent), timeout=0, dry_run=False)
            updates = [
                {
                    "update_id": 100,
                    "message": {
                        "message_id": 1,
                        "chat": {"id": config.telegram_chat_id},
                        "from": {"is_bot": False},
                        "message_thread_id": 42,
                        "text": "Do something",
                    },
                },
            ]

            failed_result = cli.subprocess.CompletedProcess(
                args=[], returncode=1, stdout="error output", stderr="command failed"
            )

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "repo_autowork.cli.load_state", return_value=state
            ), patch("repo_autowork.cli.sync_projects"), patch(
                "repo_autowork.cli.get_updates", return_value=updates
            ), patch("repo_autowork.cli.write_telegram_mirror", return_value=repo_dir / "inbox" / "telegram" / "update-100.json"), patch(
                "repo_autowork.cli._dispatch_telegram_message", return_value=failed_result
            ), patch("repo_autowork.cli.send_message") as send_mock, patch("repo_autowork.cli.save_state"):
                result = cli.cmd_telegram_sync(args)

            self.assertEqual(result, 0)
            send_mock.assert_called_once()
            status_text = send_mock.call_args[0][1]
            self.assertIn("Status: failed", status_text)
            self.assertIn("command failed", status_text)

    def test_telegram_sync_handles_send_message_failure_gracefully(self) -> None:
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
            state = State(projects=[project], last_telegram_update_id=99)
            args = argparse.Namespace(repos_root=str(root.parent), timeout=0, dry_run=False)
            updates = [
                {
                    "update_id": 100,
                    "message": {
                        "message_id": 1,
                        "chat": {"id": config.telegram_chat_id},
                        "from": {"is_bot": False},
                        "message_thread_id": 42,
                        "text": "Do something",
                    },
                },
            ]

            success_result = cli.subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "repo_autowork.cli.load_state", return_value=state
            ), patch("repo_autowork.cli.sync_projects"), patch(
                "repo_autowork.cli.get_updates", return_value=updates
            ), patch("repo_autowork.cli.write_telegram_mirror", return_value=repo_dir / "inbox" / "telegram" / "update-100.json"), patch(
                "repo_autowork.cli._dispatch_telegram_message", return_value=success_result
            ), patch(
                "repo_autowork.cli.send_message", side_effect=cli.TelegramError("send failed")
            ), patch("repo_autowork.cli.save_state"):
                result = cli.cmd_telegram_sync(args)

            self.assertEqual(result, 0)

    def test_telegram_sync_records_per_project_dispatch_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "controller"
            repo_one = root.parent / "repo-alpha"
            repo_two = root.parent / "repo-beta"
            root.mkdir(parents=True)
            repo_one.mkdir(parents=True)
            repo_two.mkdir(parents=True)
            for repo_dir, slug, topic_id in ((repo_one, "repo-alpha", 42), (repo_two, "repo-beta", 77)):
                (repo_dir / ".autowork").mkdir(parents=True)
                (repo_dir / ".autowork" / "project.env").write_text(
                    f"AUTOWORK_PROJECT_SLUG={slug}\nTG_TOPIC_ID={topic_id}\n",
                    encoding="utf-8",
                )

            config = build_config(root, repos_root=str(root.parent))
            project_alpha = ProjectRecord(
                slug="repo-alpha",
                name="repo-alpha",
                repo_path=str(repo_one),
                telegram_topic_id=42,
                tg_folder=str(root / "tg" / "repo-alpha"),
            )
            project_beta = ProjectRecord(
                slug="repo-beta",
                name="repo-beta",
                repo_path=str(repo_two),
                telegram_topic_id=77,
                tg_folder=str(root / "tg" / "repo-beta"),
            )
            state = State(projects=[project_alpha, project_beta], last_telegram_update_id=99)
            args = argparse.Namespace(repos_root=str(root.parent), timeout=0, dry_run=True)
            updates = [
                {
                    "update_id": 100,
                    "message": {
                        "message_id": 1,
                        "chat": {"id": config.telegram_chat_id},
                        "from": {"is_bot": False},
                        "message_thread_id": 42,
                        "text": "Task for alpha",
                    },
                },
                {
                    "update_id": 101,
                    "message": {
                        "message_id": 2,
                        "chat": {"id": config.telegram_chat_id},
                        "from": {"is_bot": False},
                        "message_thread_id": 77,
                        "text": "Task for beta",
                    },
                },
            ]

            success_result = cli.subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
            failed_result = cli.subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="command failed")

            dispatch_results = {"repo-alpha": success_result, "repo-beta": failed_result}

            def fake_dispatch(_, passed_project, text, dry_run=False):
                return dispatch_results[passed_project.slug]

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "repo_autowork.cli.load_state", return_value=state
            ), patch("repo_autowork.cli.sync_projects"), patch(
                "repo_autowork.cli.get_updates", return_value=updates
            ), patch("repo_autowork.cli.write_telegram_mirror", return_value=repo_one / "inbox" / "telegram" / "update-100.json"), patch(
                "repo_autowork.cli._dispatch_telegram_message", side_effect=fake_dispatch
            ), patch("repo_autowork.cli.save_state"):
                result = cli.cmd_telegram_sync(args)

            self.assertEqual(result, 0)
            self.assertIsNotNone(state.last_telegram_sync)
            outcomes = state.last_telegram_sync.dispatch_outcomes
            self.assertEqual(len(outcomes), 2)

            alpha_outcome = next(o for o in outcomes if o.project_slug == "repo-alpha")
            self.assertTrue(alpha_outcome.success)
            self.assertEqual(alpha_outcome.update_id, 100)

            beta_outcome = next(o for o in outcomes if o.project_slug == "repo-beta")
            self.assertFalse(beta_outcome.success)
            self.assertEqual(beta_outcome.update_id, 101)
            self.assertIn("command failed", beta_outcome.detail)

    def test_review_json_includes_dispatch_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            controller_root = Path(tmp_dir) / "controller"
            repos_root = Path(tmp_dir) / "managed"
            controller_root.mkdir(parents=True)
            repos_root.mkdir(parents=True)
            repo_dir = repos_root / "alpha"
            repo_dir.mkdir(parents=True)
            (repo_dir / ".git").mkdir()

            config = build_config(controller_root, repos_root=str(repos_root))
            (controller_root / "autowork.sh").write_text(cli.render_root_autowork(config), encoding="utf-8")
            (repo_dir / "autowork.sh").write_text(cli.render_project_autowork(config), encoding="utf-8")
            sync_summary = cli.TelegramSyncSummary(
                handled=2,
                ignored={},
                dispatch_outcomes=[
                    ProjectDispatchOutcome(project_slug="alpha", update_id=100, success=True),
                    ProjectDispatchOutcome(project_slug="alpha", update_id=101, success=False, detail="timeout"),
                ],
                timestamp="2026-05-27T12:00:00+00:00",
            )
            state = State(
                projects=[
                    ProjectRecord(
                        slug="alpha",
                        name="alpha",
                        repo_path=str(repo_dir),
                        current_branch="main",
                        default_branch="main",
                    )
                ],
                last_telegram_sync=sync_summary,
            )
            stdout = io.StringIO()

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "repo_autowork.cli.load_state", return_value=state
            ), patch("repo_autowork.cli.sync_projects"), patch(
                "sys.argv", ["repo-autowork", "review", "--repos-root", str(repos_root), "--dry-run", "--json"]
            ), patch("sys.stdout", stdout):
                exit_code = cli.main()

            self.assertEqual(exit_code, 0)
            data = json.loads(stdout.getvalue())
            self.assertIsNotNone(data["last_telegram_sync"])
            self.assertEqual(len(data["last_telegram_sync"]["dispatch_outcomes"]), 2)
            self.assertTrue(data["last_telegram_sync"]["dispatch_outcomes"][0]["success"])
            self.assertFalse(data["last_telegram_sync"]["dispatch_outcomes"][1]["success"])
            self.assertEqual(data["last_telegram_sync"]["dispatch_outcomes"][1]["detail"], "timeout")
            self.assertEqual(len(data["dispatch_outcomes"]), 2)


    def test_doctor_self_heal_regenerates_drifted_wrappers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            controller_root = Path(tmp_dir) / "controller"
            repos_root = Path(tmp_dir) / "managed"
            controller_root.mkdir(parents=True)
            repos_root.mkdir(parents=True)
            repo_dir = repos_root / "alpha"
            repo_dir.mkdir(parents=True)
            (repo_dir / ".git").mkdir()
            (controller_root / "autowork.sh").write_text("# drifted\n", encoding="utf-8")
            (repo_dir / "autowork.sh").write_text("# drifted child\n", encoding="utf-8")

            config = build_config(controller_root, repos_root=str(repos_root))
            stdout = io.StringIO()

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "sys.argv", ["repo-autowork", "doctor", "--repos-root", str(repos_root), "--self-heal"]
            ), patch("sys.stdout", stdout):
                exit_code = cli.main()

            self.assertEqual(exit_code, 0)
            rendered = stdout.getvalue()
            self.assertIn("healed", rendered.lower())
            self.assertEqual(
                (controller_root / "autowork.sh").read_text(encoding="utf-8"),
                cli.render_root_autowork(config),
            )
            self.assertEqual(
                (repo_dir / "autowork.sh").read_text(encoding="utf-8"),
                cli.render_project_autowork(config),
            )

    def test_doctor_self_heal_json_reports_healed_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            controller_root = Path(tmp_dir) / "controller"
            repos_root = Path(tmp_dir) / "managed"
            controller_root.mkdir(parents=True)
            repos_root.mkdir(parents=True)
            repo_dir = repos_root / "alpha"
            repo_dir.mkdir(parents=True)
            (repo_dir / ".git").mkdir()
            (controller_root / "autowork.sh").write_text("# drifted\n", encoding="utf-8")
            (repo_dir / "autowork.sh").write_text("# drifted child\n", encoding="utf-8")

            config = build_config(controller_root, repos_root=str(repos_root))
            stdout = io.StringIO()

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "sys.argv", ["repo-autowork", "doctor", "--repos-root", str(repos_root), "--format", "json", "--self-heal"]
            ), patch("sys.stdout", stdout):
                exit_code = cli.main()

            self.assertEqual(exit_code, 0)
            data = json.loads(stdout.getvalue())
            self.assertTrue(data["wrapper_contracts"]["controller_healed"])
            self.assertTrue(len(data["wrapper_contracts"]["healed_paths"]) > 0)

    def test_state_sync_history_keeps_recent_rounds(self) -> None:
        state = State()
        for i in range(12):
            summary = TelegramSyncSummary(handled=i, timestamp=f"2026-05-27T{i:02d}:00:00+00:00")
            state.append_sync_history(summary)
        self.assertEqual(len(state.telegram_sync_history), 10)
        self.assertEqual(state.telegram_sync_history[0].handled, 2)
        self.assertEqual(state.telegram_sync_history[-1].handled, 11)

    def test_review_json_includes_sync_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            controller_root = Path(tmp_dir) / "controller"
            repos_root = Path(tmp_dir) / "managed"
            controller_root.mkdir(parents=True)
            repos_root.mkdir(parents=True)
            repo_dir = repos_root / "alpha"
            repo_dir.mkdir(parents=True)
            (repo_dir / ".git").mkdir()

            config = build_config(controller_root, repos_root=str(repos_root))
            (controller_root / "autowork.sh").write_text(cli.render_root_autowork(config), encoding="utf-8")
            (repo_dir / "autowork.sh").write_text(cli.render_project_autowork(config), encoding="utf-8")
            sync_summary = TelegramSyncSummary(
                handled=1,
                ignored={},
                dispatch_outcomes=[],
                timestamp="2026-05-27T12:00:00+00:00",
            )
            state = State(
                projects=[
                    ProjectRecord(
                        slug="alpha",
                        name="alpha",
                        repo_path=str(repo_dir),
                        current_branch="main",
                        default_branch="main",
                    )
                ],
                last_telegram_sync=sync_summary,
                telegram_sync_history=[sync_summary],
            )
            stdout = io.StringIO()

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "repo_autowork.cli.load_state", return_value=state
            ), patch("repo_autowork.cli.sync_projects"), patch(
                "sys.argv", ["repo-autowork", "review", "--repos-root", str(repos_root), "--dry-run", "--json"]
            ), patch("sys.stdout", stdout):
                exit_code = cli.main()

            self.assertEqual(exit_code, 0)
            data = json.loads(stdout.getvalue())
            self.assertEqual(len(data["telegram_sync_history"]), 1)
            self.assertEqual(data["telegram_sync_history"][0]["handled"], 1)

    def test_review_text_includes_sync_history_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            controller_root = Path(tmp_dir) / "controller"
            repos_root = Path(tmp_dir) / "managed"
            controller_root.mkdir(parents=True)
            repos_root.mkdir(parents=True)
            repo_dir = repos_root / "alpha"
            repo_dir.mkdir(parents=True)
            (repo_dir / ".git").mkdir()

            config = build_config(controller_root, repos_root=str(repos_root))
            (controller_root / "autowork.sh").write_text(cli.render_root_autowork(config), encoding="utf-8")
            (repo_dir / "autowork.sh").write_text(cli.render_project_autowork(config), encoding="utf-8")
            sync_summary = TelegramSyncSummary(
                handled=2,
                ignored={},
                dispatch_outcomes=[
                    ProjectDispatchOutcome(project_slug="alpha", update_id=100, success=True),
                    ProjectDispatchOutcome(project_slug="alpha", update_id=101, success=False, detail="timeout"),
                ],
                timestamp="2026-05-27T12:00:00+00:00",
            )
            state = State(
                projects=[
                    ProjectRecord(
                        slug="alpha",
                        name="alpha",
                        repo_path=str(repo_dir),
                        current_branch="main",
                        default_branch="main",
                    )
                ],
                last_telegram_sync=sync_summary,
                telegram_sync_history=[sync_summary],
            )
            stdout = io.StringIO()

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "repo_autowork.cli.load_state", return_value=state
            ), patch("repo_autowork.cli.sync_projects"), patch(
                "sys.argv", ["repo-autowork", "review", "--repos-root", str(repos_root), "--dry-run"]
            ), patch("sys.stdout", stdout):
                exit_code = cli.main()

            self.assertEqual(exit_code, 0)
            rendered = stdout.getvalue()
            self.assertIn("Sync history", rendered)
            self.assertIn("total_handled=2", rendered)
            self.assertIn("total_failed_dispatches=1", rendered)

    def test_review_self_heal_regenerates_drifted_wrappers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            controller_root = Path(tmp_dir) / "controller"
            repos_root = Path(tmp_dir) / "managed"
            controller_root.mkdir(parents=True)
            repos_root.mkdir(parents=True)
            repo_dir = repos_root / "alpha"
            repo_dir.mkdir(parents=True)
            (repo_dir / ".git").mkdir()
            (controller_root / "autowork.sh").write_text("# drifted\n", encoding="utf-8")
            (repo_dir / "autowork.sh").write_text("# drifted child\n", encoding="utf-8")

            config = build_config(controller_root, repos_root=str(repos_root))
            state = State(
                projects=[
                    ProjectRecord(
                        slug="alpha",
                        name="alpha",
                        repo_path=str(repo_dir),
                        current_branch="main",
                        default_branch="main",
                    )
                ]
            )
            stdout = io.StringIO()

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "repo_autowork.cli.load_state", return_value=state
            ), patch("repo_autowork.cli.sync_projects"), patch(
                "sys.argv", ["repo-autowork", "review", "--repos-root", str(repos_root), "--dry-run", "--self-heal"]
            ), patch("sys.stdout", stdout):
                exit_code = cli.main()

            self.assertEqual(exit_code, 0)
            rendered = stdout.getvalue()
            self.assertIn("healed", rendered.lower())
            self.assertEqual(
                (controller_root / "autowork.sh").read_text(encoding="utf-8"),
                cli.render_root_autowork(config),
            )
            self.assertEqual(
                (repo_dir / "autowork.sh").read_text(encoding="utf-8"),
                cli.render_project_autowork(config),
            )

    def test_review_self_heal_json_reports_healed_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            controller_root = Path(tmp_dir) / "controller"
            repos_root = Path(tmp_dir) / "managed"
            controller_root.mkdir(parents=True)
            repos_root.mkdir(parents=True)
            repo_dir = repos_root / "alpha"
            repo_dir.mkdir(parents=True)
            (repo_dir / ".git").mkdir()
            (controller_root / "autowork.sh").write_text("# drifted\n", encoding="utf-8")
            (repo_dir / "autowork.sh").write_text("# drifted child\n", encoding="utf-8")

            config = build_config(controller_root, repos_root=str(repos_root))
            state = State(
                projects=[
                    ProjectRecord(
                        slug="alpha",
                        name="alpha",
                        repo_path=str(repo_dir),
                        current_branch="main",
                        default_branch="main",
                    )
                ]
            )
            stdout = io.StringIO()

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "repo_autowork.cli.load_state", return_value=state
            ), patch("repo_autowork.cli.sync_projects"), patch(
                "sys.argv", ["repo-autowork", "review", "--repos-root", str(repos_root), "--dry-run", "--json", "--self-heal"]
            ), patch("sys.stdout", stdout):
                exit_code = cli.main()

            self.assertEqual(exit_code, 0)
            data = json.loads(stdout.getvalue())
            self.assertTrue(data["wrapper_contracts"]["controller_healed"])
            self.assertTrue(len(data["wrapper_contracts"]["healed_paths"]) > 0)

    def test_telegram_sync_json_outputs_machine_readable_data(self) -> None:
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
            state = State(projects=[project], last_telegram_update_id=99)
            args = argparse.Namespace(repos_root=str(root.parent), timeout=0, dry_run=True, json=True)
            updates = [
                {
                    "update_id": 100,
                    "message": {
                        "message_id": 1,
                        "chat": {"id": config.telegram_chat_id},
                        "from": {"is_bot": False},
                        "message_thread_id": 42,
                        "text": "Do something",
                    },
                },
                {"update_id": 101},
            ]

            stdout = io.StringIO()

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "repo_autowork.cli.load_state", return_value=state
            ), patch("repo_autowork.cli.sync_projects"), patch(
                "repo_autowork.cli.get_updates", return_value=updates
            ), patch("repo_autowork.cli.write_telegram_mirror", return_value=repo_dir / "inbox" / "telegram" / "update-100.json"), patch(
                "repo_autowork.cli._dispatch_telegram_message",
                return_value=cli.subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr=""),
            ), patch("repo_autowork.cli.save_state"), patch("sys.stdout", stdout):
                result = cli.cmd_telegram_sync(args)

            self.assertEqual(result, 0)
            data = json.loads(stdout.getvalue())
            self.assertEqual(data["handled"], 1)
            self.assertEqual(data["ignored"].get("non_message", 0), 1)
            self.assertEqual(len(data["dispatch_outcomes"]), 1)
            self.assertTrue(data["dispatch_outcomes"][0]["success"])
            self.assertEqual(data["last_update_id"], 101)

    def test_history_subcommand_outputs_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "controller"
            root.mkdir(parents=True)

            config = build_config(root, repos_root=str(root.parent))
            sync_summary = TelegramSyncSummary(
                handled=2,
                ignored={},
                dispatch_outcomes=[
                    ProjectDispatchOutcome(project_slug="alpha", update_id=100, success=True),
                    ProjectDispatchOutcome(project_slug="beta", update_id=101, success=False, detail="timeout"),
                ],
                timestamp="2026-05-27T12:00:00+00:00",
            )
            state = State(telegram_sync_history=[sync_summary])
            stdout = io.StringIO()

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "repo_autowork.cli.load_state", return_value=state
            ), patch("sys.argv", ["repo-autowork", "history", "--repos-root", str(root.parent)]), patch("sys.stdout", stdout):
                exit_code = cli.main()

            self.assertEqual(exit_code, 0)
            rendered = stdout.getvalue()
            self.assertIn("Dispatch history", rendered)
            self.assertIn("1 round(s)", rendered)
            self.assertIn("alpha#100: success", rendered)
            self.assertIn("beta#101: failed", rendered)

    def test_history_subcommand_filters_by_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "controller"
            root.mkdir(parents=True)

            config = build_config(root, repos_root=str(root.parent))
            sync_summary = TelegramSyncSummary(
                handled=2,
                ignored={},
                dispatch_outcomes=[
                    ProjectDispatchOutcome(project_slug="alpha", update_id=100, success=True),
                    ProjectDispatchOutcome(project_slug="beta", update_id=101, success=False, detail="timeout"),
                ],
                timestamp="2026-05-27T12:00:00+00:00",
            )
            state = State(telegram_sync_history=[sync_summary])
            stdout = io.StringIO()

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "repo_autowork.cli.load_state", return_value=state
            ), patch("sys.argv", ["repo-autowork", "history", "--repos-root", str(root.parent), "--project", "alpha"]), patch("sys.stdout", stdout):
                exit_code = cli.main()

            self.assertEqual(exit_code, 0)
            rendered = stdout.getvalue()
            self.assertIn("filtered to alpha", rendered)
            self.assertIn("alpha#100: success", rendered)
            self.assertNotIn("beta", rendered)

    def test_history_subcommand_outputs_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "controller"
            root.mkdir(parents=True)

            config = build_config(root, repos_root=str(root.parent))
            sync_summary = TelegramSyncSummary(
                handled=1,
                ignored={},
                dispatch_outcomes=[
                    ProjectDispatchOutcome(project_slug="alpha", update_id=100, success=True),
                ],
                timestamp="2026-05-27T12:00:00+00:00",
            )
            state = State(telegram_sync_history=[sync_summary])
            stdout = io.StringIO()

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "repo_autowork.cli.load_state", return_value=state
            ), patch("sys.argv", ["repo-autowork", "history", "--repos-root", str(root.parent), "--json"]), patch("sys.stdout", stdout):
                exit_code = cli.main()

            self.assertEqual(exit_code, 0)
            data = json.loads(stdout.getvalue())
            self.assertEqual(data["total_rounds"], 1)
            self.assertIsNone(data["project_filter"])
            self.assertEqual(len(data["rounds"]), 1)
            self.assertEqual(data["rounds"][0]["outcomes"][0]["project_slug"], "alpha")

    def test_history_shows_empty_message_when_no_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "controller"
            root.mkdir(parents=True)

            config = build_config(root, repos_root=str(root.parent))
            state = State()
            stdout = io.StringIO()

            with patch("repo_autowork.cli.build_config", return_value=config), patch(
                "repo_autowork.cli.load_state", return_value=state
            ), patch("sys.argv", ["repo-autowork", "history", "--repos-root", str(root.parent)]), patch("sys.stdout", stdout):
                exit_code = cli.main()

            self.assertEqual(exit_code, 0)
            rendered = stdout.getvalue()
            self.assertIn("No sync history recorded yet", rendered)


if __name__ == "__main__":
    unittest.main()
