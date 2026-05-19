#!/usr/bin/env python3
"""Parse GitHub Issue details for the automation pipeline.

The GitHub Actions workflow passes issue data through environment variables.
This script extracts a validated GitHub repository URL and bug description,
prints structured logs, and writes parsed_issue.json for the downstream Claude,
git, PR, and issue-comment steps.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse


GITHUB_HOST = "github.com"
GITHUB_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
GITHUB_REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class IssueParseError(ValueError):
    """Raised when the GitHub Issue body does not contain required fields."""


@dataclass(frozen=True)
class IssueContext:
    """Normalized issue data used by the automation pipeline."""

    issue_number: str
    issue_title: str
    issue_url: str
    issue_author: str
    repo_url: str
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


def extract_repo_url(issue_body: str) -> str:
    """Extract the full GitHub repository URL from 'Repo URL:'."""
    pattern = re.compile(
        r"(?ims)^\s*repo\s+url\s*:\s*(?P<repo_url>.*?)(?=^\s*[A-Za-z][A-Za-z0-9 ]*\s*:\s*$|\Z)"
    )
    match = pattern.search(issue_body)
    if not match:
        raise IssueParseError(
            "Issue body must include 'Repo URL: https://github.com/<owner>/<repo>'."
        )

    repo_url = match.group("repo_url").strip()
    if not repo_url:
        raise IssueParseError("Repo URL cannot be empty.")
    if len(repo_url.split()) != 1:
        raise IssueParseError("Repo URL must contain exactly one URL and no extra text.")
    return repo_url


def validate_and_parse_repo_url(repo_url: str) -> tuple[str, str]:
    """Validate and split https://github.com/<owner>/<repo>.

    This intentionally rejects SSH syntax, local paths, query strings, fragments,
    non-GitHub hosts, missing owner/repo segments, and .git suffixes in the issue.
    """
    parsed = urlparse(repo_url)
    if parsed.scheme != "https":
        raise IssueParseError("Repo URL must use https://.")
    if parsed.netloc.lower() != GITHUB_HOST:
        raise IssueParseError("Repo URL host must be github.com.")
    if parsed.params or parsed.query or parsed.fragment:
        raise IssueParseError("Repo URL must not include params, query strings, or fragments.")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        raise IssueParseError("Repo URL must have exactly two path parts: <owner>/<repo>.")

    owner, repo = parts
    if parsed.path != f"/{owner}/{repo}":
        raise IssueParseError("Repo URL must not include extra slashes or trailing slash.")
    if not GITHUB_OWNER_PATTERN.fullmatch(owner):
        raise IssueParseError(f"Invalid GitHub owner in Repo URL: {owner!r}.")
    if repo.endswith(".git"):
        raise IssueParseError("Repo URL must not include a .git suffix.")
    if not GITHUB_REPO_PATTERN.fullmatch(repo):
        raise IssueParseError(f"Invalid GitHub repo name in Repo URL: {repo!r}.")
    return owner, repo


def extract_section(issue_body: str, section_name: str) -> str:
    """Extract a Markdown-style section until the next '<Heading>:' line."""
    pattern = re.compile(
        rf"(?ims)^\s*{re.escape(section_name)}\s*:\s*(?P<value>.*?)(?=^\s*[A-Za-z][A-Za-z0-9 ]*\s*:\s*$|\Z)"
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
    repo_url = extract_repo_url(issue_body)
    repo_owner, repo_name = validate_and_parse_repo_url(repo_url)

    return IssueContext(
        issue_number=get_optional_env("ISSUE_NUMBER", "unknown"),
        issue_title=get_required_env("ISSUE_TITLE"),
        issue_url=get_optional_env("ISSUE_URL", "unknown"),
        issue_author=get_optional_env("ISSUE_AUTHOR", "unknown"),
        repo_url=repo_url,
        repo_owner=repo_owner,
        repo_name=repo_name,
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
        repo_url=issue_context.repo_url,
        repo_owner=issue_context.repo_owner,
        repo_name=issue_context.repo_name,
        bug_description=issue_context.bug_description,
    )
    log_info(
        "Parsed repository URL",
        repo_url=issue_context.repo_url,
        extracted_owner=issue_context.repo_owner,
        extracted_repo=issue_context.repo_name,
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
