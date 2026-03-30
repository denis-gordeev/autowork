from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class ForgeError(RuntimeError):
    pass


def _run(command: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
    )


def _git(repo_dir: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return _run(["git", *args], cwd=repo_dir, check=check)


def _remote_name(url: str) -> tuple[str, str]:
    cleaned = url.strip()
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    if cleaned.startswith("git@"):
        host_and_path = cleaned.split(":", 1)
        if len(host_and_path) != 2:
            return "unknown", ""
        host = host_and_path[0][4:]
        return host, host_and_path[1]
    if "://" in cleaned:
        without_scheme = cleaned.split("://", 1)[1]
        parts = without_scheme.split("/", 1)
        if len(parts) != 2:
            return "unknown", ""
        return parts[0], parts[1]
    return "unknown", cleaned


def gh_available() -> bool:
    return shutil.which("gh") is not None


def glab_available() -> bool:
    return shutil.which("glab") is not None


def get_origin_url(repo_dir: Path) -> str:
    result = _git(repo_dir, "remote", "get-url", "origin", check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def get_current_branch(repo_dir: Path) -> str:
    result = _git(repo_dir, "branch", "--show-current", check=False)
    return result.stdout.strip() or "HEAD"


def get_default_branch(repo_dir: Path, remote_name: str = "origin") -> str:
    symbolic = _git(repo_dir, "symbolic-ref", f"refs/remotes/{remote_name}/HEAD", check=False)
    if symbolic.returncode == 0:
        target = symbolic.stdout.strip()
        if "/" in target:
            return target.rsplit("/", 1)[-1]
    return "main"


def repo_snapshot(repo_dir: Path) -> dict[str, str | bool]:
    origin_url = get_origin_url(repo_dir)
    host, _ = _remote_name(origin_url)
    return {
        "origin_url": origin_url,
        "forge_kind": "github" if host == "github.com" else "gitlab" if host == "gitlab.com" else host or "unknown",
        "current_branch": get_current_branch(repo_dir),
        "default_branch": get_default_branch(repo_dir),
    }


def list_open_work_items(repo_dir: Path, forge_kind: str) -> dict[str, list[str]]:
    items = {"issues": [], "reviews": [], "notes": []}
    if forge_kind == "github" and gh_available():
        issues = _run(
            ["gh", "issue", "list", "--limit", "10", "--state", "open", "--json", "number,title,url"],
            cwd=repo_dir,
            check=False,
        )
        if issues.returncode == 0 and issues.stdout.strip():
            for item in json.loads(issues.stdout):
                items["issues"].append(f"#{item['number']} {item['title']} ({item['url']})")
        elif issues.stderr.strip():
            items["notes"].append(f"GitHub issues unavailable: {issues.stderr.strip()}")

        prs = _run(
            ["gh", "pr", "list", "--limit", "10", "--state", "open", "--json", "number,title,url,isDraft"],
            cwd=repo_dir,
            check=False,
        )
        if prs.returncode == 0 and prs.stdout.strip():
            for item in json.loads(prs.stdout):
                draft = " draft" if item.get("isDraft") else ""
                items["reviews"].append(f"PR #{item['number']}{draft} {item['title']} ({item['url']})")
        elif prs.stderr.strip():
            items["notes"].append(f"GitHub PRs unavailable: {prs.stderr.strip()}")
    elif forge_kind == "gitlab" and glab_available():
        issues = _run(["glab", "issue", "list"], cwd=repo_dir, check=False)
        if issues.returncode == 0:
            items["issues"] = [line.strip() for line in issues.stdout.splitlines()[:10] if line.strip()]
        elif issues.stderr.strip():
            items["notes"].append(f"GitLab issues unavailable: {issues.stderr.strip()}")

        mrs = _run(["glab", "mr", "list"], cwd=repo_dir, check=False)
        if mrs.returncode == 0:
            items["reviews"] = [line.strip() for line in mrs.stdout.splitlines()[:10] if line.strip()]
        elif mrs.stderr.strip():
            items["notes"].append(f"GitLab merge requests unavailable: {mrs.stderr.strip()}")
    return items


def detect_fork(repo_dir: Path, origin_url: str, forge_kind: str) -> tuple[bool, str, str]:
    upstream_url = ""
    upstream_branch = ""
    existing_upstream = _git(repo_dir, "remote", "get-url", "upstream", check=False)
    if existing_upstream.returncode == 0:
        upstream_url = existing_upstream.stdout.strip()
        upstream_branch = get_default_branch(repo_dir, "upstream")
        return True, upstream_url, upstream_branch

    if forge_kind == "github" and gh_available() and origin_url:
        result = _run(
            ["gh", "repo", "view", "--json", "isFork,parent,defaultBranchRef"],
            cwd=repo_dir,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            payload = json.loads(result.stdout)
            if payload.get("isFork") and payload.get("parent"):
                owner = payload["parent"]["owner"]["login"]
                name = payload["parent"]["name"]
                upstream_url = f"git@github.com:{owner}/{name}.git"
                default_branch = payload.get("parent", {}).get("defaultBranchRef", {}) or payload.get("defaultBranchRef", {})
                upstream_branch = default_branch.get("name") or "main"
                return True, upstream_url, upstream_branch
    return False, "", ""


def ensure_upstream_remote(repo_dir: Path, upstream_url: str) -> None:
    remotes = _git(repo_dir, "remote", check=True).stdout.splitlines()
    if "upstream" not in remotes:
        _git(repo_dir, "remote", "add", "upstream", upstream_url, check=True)


def merge_upstream(repo_dir: Path, upstream_branch: str, dry_run: bool = False) -> str:
    status = _git(repo_dir, "status", "--short", check=True).stdout.strip()
    if status:
        return "Skipped upstream merge because the worktree is dirty."
    if dry_run:
        return f"Dry-run: would merge upstream/{upstream_branch}."
    fetch = _git(repo_dir, "fetch", "upstream", check=False)
    if fetch.returncode != 0:
        return f"Upstream fetch failed: {(fetch.stderr or fetch.stdout).strip()}"
    merge = _git(repo_dir, "merge", "--no-edit", f"upstream/{upstream_branch}", check=False)
    if merge.returncode != 0:
        return f"Upstream merge failed: {(merge.stderr or merge.stdout).strip()}"
    return f"Merged upstream/{upstream_branch}."
