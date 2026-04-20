import argparse
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repo_autowork import cli
from repo_autowork.config import build_config
from repo_autowork.models import ProjectRecord, State


class CliFlowTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
