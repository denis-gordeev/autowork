import os
import tempfile
import unittest
from pathlib import Path

from repo_autowork.config import (
    build_config,
    ensure_runtime_path,
    hydrate_project_runtime_env,
    load_env_file,
    project_runtime_env_path,
    resolve_base_command,
)
from repo_autowork.manager import (
    discover_repo_dirs,
    ensure_project_files,
    render_project_autowork,
    render_root_autowork,
)
from repo_autowork.models import ProjectRecord


class RuntimeConfigTests(unittest.TestCase):
    def test_ensure_runtime_path_prepends_common_binary_dirs(self) -> None:
        original_path = os.environ.get("PATH")
        try:
            os.environ["PATH"] = "/usr/bin:/bin"
            runtime_path = ensure_runtime_path()

            self.assertTrue(runtime_path.startswith("/opt/homebrew/bin:/usr/local/bin:"))
            self.assertEqual(os.environ["PATH"], runtime_path)
        finally:
            if original_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = original_path

    def test_resolve_base_command_uses_known_codex_location(self) -> None:
        original_path = os.environ.get("PATH")
        try:
            os.environ["PATH"] = "/usr/bin:/bin"
            resolved = resolve_base_command("codex exec --yolo")

            self.assertEqual(resolved, "/opt/homebrew/bin/codex exec --yolo")
        finally:
            if original_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = original_path

    def test_generated_project_wrapper_sets_runtime_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config = build_config(root)
            project_root = root / "example"
            project = ProjectRecord(
                slug="example",
                name="example",
                repo_path=str(project_root),
                tg_folder=str(root / "tg" / "example"),
            )

            ensure_project_files(config, project)
            wrapper = (project_root / "autowork.sh").read_text(encoding="utf-8")

            self.assertIn('PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"', wrapper)
            self.assertIn('CONTROLLER_ROOT="${AUTOWORK_CONTROLLER_ROOT:-', wrapper)

    def test_controller_repo_is_optional_in_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / ".git").mkdir()

            original_include = os.environ.get("AUTOWORK_INCLUDE_CONTROLLER")
            try:
                os.environ["AUTOWORK_INCLUDE_CONTROLLER"] = "1"
                config = build_config(root, repos_root=str(root.parent))
                discovered = discover_repo_dirs(config)

                self.assertIn(root.resolve(), discovered)
            finally:
                if original_include is None:
                    os.environ.pop("AUTOWORK_INCLUDE_CONTROLLER", None)
                else:
                    os.environ["AUTOWORK_INCLUDE_CONTROLLER"] = original_include

    def test_load_env_file_can_override_existing_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = Path(tmp_dir) / "project.env"
            env_path.write_text("AUTOWORK_PROJECT_SLUG=fresh-value\n", encoding="utf-8")
            original_slug = os.environ.get("AUTOWORK_PROJECT_SLUG")
            try:
                os.environ["AUTOWORK_PROJECT_SLUG"] = "stale-value"
                load_env_file(env_path, override=True)

                self.assertEqual(os.environ["AUTOWORK_PROJECT_SLUG"], "fresh-value")
            finally:
                if original_slug is None:
                    os.environ.pop("AUTOWORK_PROJECT_SLUG", None)
                else:
                    os.environ["AUTOWORK_PROJECT_SLUG"] = original_slug

    def test_hydrate_project_runtime_env_uses_shared_project_env_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            env_path = project_runtime_env_path(repo_root)
            env_path.parent.mkdir(parents=True, exist_ok=True)
            env_path.write_text(
                "AUTOWORK_PROJECT_SLUG=fresh-value\nTG_TOPIC_ID=42\n",
                encoding="utf-8",
            )
            original_slug = os.environ.get("AUTOWORK_PROJECT_SLUG")
            original_topic = os.environ.get("TG_TOPIC_ID")
            try:
                os.environ["AUTOWORK_PROJECT_SLUG"] = "stale-value"
                os.environ["TG_TOPIC_ID"] = "stale-topic"

                returned_path = hydrate_project_runtime_env(repo_root)

                self.assertEqual(returned_path, env_path)
                self.assertEqual(os.environ["AUTOWORK_PROJECT_SLUG"], "fresh-value")
                self.assertEqual(os.environ["TG_TOPIC_ID"], "42")
            finally:
                if original_slug is None:
                    os.environ.pop("AUTOWORK_PROJECT_SLUG", None)
                else:
                    os.environ["AUTOWORK_PROJECT_SLUG"] = original_slug
                if original_topic is None:
                    os.environ.pop("TG_TOPIC_ID", None)
                else:
                    os.environ["TG_TOPIC_ID"] = original_topic

    def test_root_wrapper_keeps_portfolio_flow_for_controller_root(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        config = build_config(repo_root)
        root_wrapper = (repo_root / "autowork.sh").read_text(encoding="utf-8")

        self.assertEqual(root_wrapper, render_root_autowork(config))
        self.assertIn('if [ "$REPO_DIR" = "$CONTROLLER_ROOT" ]; then', root_wrapper)
        self.assertIn('telegram-sync "$@"', root_wrapper)
        self.assertIn('run "$@"', root_wrapper)
        self.assertIn('review "$@"', root_wrapper)
        self.assertIn('project-run --repo "$REPO_DIR" "$@"', root_wrapper)

    def test_rendered_project_wrapper_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config = build_config(root)

            wrapper = render_project_autowork(config)

            self.assertIn('repo_autowork.cli project-run --repo "$REPO_DIR" "$@"', wrapper)
            self.assertNotIn('telegram-sync "$@"', wrapper)


if __name__ == "__main__":
    unittest.main()
