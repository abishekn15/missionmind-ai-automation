#!/usr/bin/env python3
"""Parse GitHub Issue details for Phase 1 automation.

The GitHub Actions workflow passes issue data through environment variables.
This script extracts the target repository name and bug description, validates
required fields, and prints structured logs for downstream automation phases.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass


class IssueParseError(ValueError):
    """Raised when the GitHub Issue body does not contain required fields."""


@dataclass(frozen=True)
class IssueContext:
    """Normalized issue data used by the automation pipeline."""

    issue_number: str
    issue_title: str
    issue_url: str
    issue_author: str
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
        repo_name=extract_repo_name(issue_body),
        bug_description=extract_section(issue_body, "Bug Description"),
    )


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
        repo_name=issue_context.repo_name,
        bug_description=issue_context.bug_description,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
