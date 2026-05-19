#!/usr/bin/env python3
"""Parse GitHub Issue details for the automation pipeline.

The GitHub Actions workflow passes issue data through environment variables.
This script extracts the target repository name and bug description, validates
required fields, prints structured logs, and writes parsed_issue.json for the
downstream Claude, git, PR, and issue-comment steps.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


class IssueParseError(ValueError):
    """Raised when the GitHub Issue body does not contain required fields."""


@dataclass(frozen=True)
class IssueContext:
    """Normalized issue data used by the automation pipeline."""

    issue_number: str
    issue_title: str
    issue_url: str
    issue_author: str
    repo_owner: str
    repo_name: str
    bug_description: str


def get_required_env(name: str) -> str:
    """Read a required environment variable and fail with a clear message."""
    value = os.getenv(name, "").strip()
    if not value:
        raise IssueParseError(f"Missing required environment variable: {name}")
    return value


def get_optional_env(name: str, default: str = "") -> str:
    """Read an optional environment variable while keeping output predictable."""
    return os.getenv(name, default).strip()


def extract_repo_name(issue_body: str) -> str:
    """Extract the repository name from a line like 'Repo: HR-worker-api'."""
    match = re.search(r"(?im)^\s*repo\s*:\s*(?P<repo>[A-Za-z0-9_.-]+)\s*$", issue_body)
    if not match:
        raise IssueParseError("Issue body must include a 'Repo: <repository-name>' line.")
    return match.group("repo")


def extract_repo_owner(issue_body: str) -> str | None:
    """Extract optional owner/org from 'Owner: acme' or 'Org: acme' in the issue body."""
    match = re.search(
        r"(?im)^\s*(?:owner|org)\s*:\s*(?P<owner>[A-Za-z0-9_.-]+)\s*$",
        issue_body,
    )
    if not match:
        return None
    return match.group("owner")


def resolve_repo_owner(issue_body: str) -> str:
    """Prefer explicit Owner/Org in the body; otherwise use DEFAULT_REPO_OWNER env."""
    explicit = extract_repo_owner(issue_body)
    if explicit:
        return explicit
    default = get_optional_env("DEFAULT_REPO_OWNER")
    if not default:
        raise IssueParseError(
            "Set an 'Owner: <github-org-or-user>' line in the issue body, "
            "or pass DEFAULT_REPO_OWNER from the workflow (typically the automation repo owner)."
        )
    return default


def extract_section(issue_body: str, section_name: str) -> str:
    """Extract a Markdown-style section until the next '<Heading>:' line."""
    pattern = re.compile(
        rf"(?ims)^\s*{re.escape(section_name)}\s*:\s*(?P<value>.*?)(?=^\s*[A-Za-z][A-Za-z0-9 ]*\s*:|\Z)"
    )
    match = pattern.search(issue_body)
    if not match:
        raise IssueParseError(f"Issue body must include a '{section_name}:' section.")

    value = match.group("value").strip()
    if not value:
        raise IssueParseError(f"The '{section_name}:' section cannot be empty.")
    return value


def parse_issue_from_environment() -> IssueContext:
    """Build an IssueContext from GitHub Actions environment variables."""
    issue_body = get_required_env("ISSUE_BODY")

    return IssueContext(
        issue_number=get_optional_env("ISSUE_NUMBER", "unknown"),
        issue_title=get_required_env("ISSUE_TITLE"),
        issue_url=get_optional_env("ISSUE_URL", "unknown"),
        issue_author=get_optional_env("ISSUE_AUTHOR", "unknown"),
        repo_owner=resolve_repo_owner(issue_body),
        repo_name=extract_repo_name(issue_body),
        bug_description=extract_section(issue_body, "Bug Description"),
    )


def write_parsed_json(issue_context: IssueContext, output_path: Path) -> None:
    """Write machine-readable output for downstream workflow steps."""
    payload = asdict(issue_context)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def log_info(message: str, **fields: str) -> None:
    """Print a structured JSON log line for successful processing steps."""
    payload = {"level": "INFO", "message": message, **fields}
    print(json.dumps(payload, sort_keys=True))


def log_error(message: str, **fields: str) -> None:
    """Print a structured JSON log line for failures."""
    payload = {"level": "ERROR", "message": message, **fields}
    print(json.dumps(payload, sort_keys=True), file=sys.stderr)


def main() -> int:
    """Parse the issue payload and print structured logs for the workflow."""
    try:
        issue_context = parse_issue_from_environment()
    except IssueParseError as error:
        log_error("Failed to parse GitHub Issue", error=str(error))
        return 1

    parsed_data = asdict(issue_context)
    log_info("Parsed GitHub Issue successfully", **parsed_data)
    log_info(
        "Automation input summary",
        repo_owner=issue_context.repo_owner,
        repo_name=issue_context.repo_name,
        bug_description=issue_context.bug_description,
    )

    json_path_raw = os.getenv("PARSED_ISSUE_JSON_PATH", "").strip()
    output_path = Path(json_path_raw or "parsed_issue.json")
    try:
        write_parsed_json(issue_context, output_path)
    except OSError as error:
        log_error("Failed to write parsed issue JSON", path=str(output_path), error=str(error))
        return 1
    log_info("Wrote parsed issue JSON", path=str(output_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
