#!/usr/bin/env python3
"""Comment the generated PR URL back on the original automation issue."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


class IssueCommentError(RuntimeError):
    """Raised when the issue comment cannot be posted."""


def log(level: str, message: str, **fields: Any) -> None:
    """Emit structured logs."""
    payload = {"level": level, "message": message, **fields}
    stream = sys.stderr if level == "ERROR" else sys.stdout
    print(json.dumps(payload, sort_keys=True), file=stream)


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object from disk."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise IssueCommentError(f"Missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise IssueCommentError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise IssueCommentError(f"{path} must contain a JSON object.")
    return data


def run_gh(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a GitHub CLI command using the built-in token."""
    env = os.environ.copy()
    if not env.get("GH_TOKEN") and env.get("GITHUB_TOKEN"):
        env["GH_TOKEN"] = env["GITHUB_TOKEN"]
    result = subprocess.run(
        ["gh", *args],
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        raise IssueCommentError(
            f"gh {' '.join(args[:2])} failed with exit {result.returncode}: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    return result


def main() -> int:
    """Post the PR URL to the original GitHub Issue."""
    try:
        if not (os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")):
            raise IssueCommentError("Missing GH_TOKEN or GITHUB_TOKEN for GitHub CLI.")

        automation_repo = os.getenv("AUTOMATION_REPO", "").strip()
        if not automation_repo:
            raise IssueCommentError("Missing required environment variable: AUTOMATION_REPO")

        parsed_issue = read_json(Path("parsed_issue.json"))
        pr_result = read_json(Path("pr_result.json"))
        issue_number = str(parsed_issue.get("issue_number", "")).strip()
        pr_url = str(pr_result.get("pr_url", "")).strip()
        if not issue_number.isdigit():
            raise IssueCommentError(f"Invalid issue number: {issue_number!r}")
        if not pr_url.startswith("https://github.com/"):
            raise IssueCommentError(f"Invalid PR URL: {pr_url!r}")

        body = f"""AI-generated fix PR created:
{pr_url}

Please review before merging.
"""
        run_gh(["issue", "comment", issue_number, "--repo", automation_repo, "--body", body])
        log("INFO", "Commented PR URL on original issue", issue_number=issue_number, pr_url=pr_url)
        return 0
    except IssueCommentError as exc:
        log("ERROR", "Failed to comment PR URL on issue", error=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
