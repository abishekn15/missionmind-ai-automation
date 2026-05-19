#!/usr/bin/env python3
"""Create an AI fix branch, commit Claude changes, and push to GitHub.

All git operations are scoped to target-repo/. The script never pushes to main;
it always creates ai-fix-{issue-number}.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


class GitAutomationError(RuntimeError):
    """Raised when a git operation cannot be completed safely."""


def log(level: str, message: str, **fields: Any) -> None:
    """Emit structured GitHub Actions logs without leaking credentials."""
    payload = {"level": level, "message": message, **fields}
    stream = sys.stderr if level == "ERROR" else sys.stdout
    print(json.dumps(payload, sort_keys=True), file=stream)


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object from disk."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GitAutomationError(f"Missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise GitAutomationError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise GitAutomationError(f"{path} must contain a JSON object.")
    return data


def run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a git command with captured output and sanitized logging."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        raise GitAutomationError(
            f"git {' '.join(args[:2])} failed with exit {result.returncode}: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    return result


def validate_repo_name(value: str, field: str) -> None:
    """Accept standard GitHub owner/repo characters only."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise GitAutomationError(f"Invalid {field}: {value!r}")


def validate_modified_files(target_repo: Path, modified_files: list[str]) -> list[str]:
    """Ensure every committed path came from fix_result.json and stays in target-repo/."""
    if not modified_files:
        raise GitAutomationError("fix_result.json contains no modified files.")

    safe_files: list[str] = []
    root = target_repo.resolve()
    for filename in modified_files:
        path = (target_repo / filename).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise GitAutomationError(f"Refusing to commit path outside target-repo: {filename}") from exc
        if not path.is_file():
            raise GitAutomationError(f"Modified file is missing: {filename}")
        safe_files.append(filename)
    return safe_files


def write_git_result(path: Path, payload: dict[str, Any]) -> None:
    """Write branch metadata for the PR creation script."""
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    """Create, commit, and push ai-fix-{issue-number}."""
    try:
        token = os.getenv("GITHUB_TOKEN", "").strip()
        if not token:
            raise GitAutomationError("Missing required environment variable: GITHUB_TOKEN")

        parsed_issue = read_json(Path("parsed_issue.json"))
        fix_result = read_json(Path("fix_result.json"))
        target_repo = Path("target-repo")
        if not target_repo.is_dir():
            raise GitAutomationError("Missing target-repo/ directory.")

        repo_owner = str(parsed_issue.get("repo_owner", "")).strip()
        repo_name = str(parsed_issue.get("repo_name", "")).strip()
        issue_number = str(parsed_issue.get("issue_number", "")).strip()
        issue_title = str(parsed_issue.get("issue_title", "")).strip()
        validate_repo_name(repo_owner, "repo_owner")
        validate_repo_name(repo_name, "repo_name")
        if not re.fullmatch(r"\d+", issue_number):
            raise GitAutomationError(f"Invalid issue number: {issue_number!r}")
        if not issue_title:
            raise GitAutomationError("Issue title is required for the commit message.")

        modified_files = validate_modified_files(target_repo, list(fix_result.get("modified_files", [])))
        branch_name = f"ai-fix-{issue_number}"
        commit_message = f"AI Fix: {issue_title}"

        run_git(["config", "user.name", "github-actions[bot]"], cwd=target_repo)
        run_git(["config", "user.email", "github-actions[bot]@users.noreply.github.com"], cwd=target_repo)
        run_git(["checkout", "-B", branch_name], cwd=target_repo)

        for filename in modified_files:
            run_git(["add", "--", filename], cwd=target_repo)

        status = run_git(["status", "--porcelain"], cwd=target_repo).stdout.strip()
        if not status:
            raise GitAutomationError("No git changes detected after Claude fix.")

        run_git(["commit", "-m", commit_message], cwd=target_repo)

        # Use the built-in GITHUB_TOKEN exactly as requested. Note: GitHub scopes
        # this token to the workflow repository; cross-repo writes may be blocked
        # by GitHub even when both repos have the same owner.
        remote_url = f"https://x-access-token:{token}@github.com/{repo_owner}/{repo_name}.git"
        run_git(["remote", "set-url", "origin", remote_url], cwd=target_repo)
        run_git(["push", "origin", f"HEAD:{branch_name}"], cwd=target_repo)

        result = {
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "branch_name": branch_name,
            "commit_message": commit_message,
            "modified_files": modified_files,
        }
        write_git_result(Path("git_result.json"), result)
        log("INFO", "Branch pushed", repo=f"{repo_owner}/{repo_name}", branch=branch_name, modified_files=modified_files)
        return 0
    except GitAutomationError as exc:
        log("ERROR", "Git commit/push failed", error=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
