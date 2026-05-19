#!/usr/bin/env python3
"""Use Claude to generate a safe Python bug fix inside target-repo/.

This script is intentionally narrow for the first production version:
- reads issue context from parsed_issue.json
- scans Python files under target-repo/
- asks Claude to fix one affected Python file
- validates the returned code with ast.parse()
- writes fix_result.json for the git/PR steps

The script never executes code from the issue body or the target repository.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
# Haiku is the cheapest Claude 3 tier; suitable for small targeted fixes.
DEFAULT_MODEL = "claude-3-haiku-20240307"
MAX_FILE_BYTES = 80_000
MAX_TOTAL_PROMPT_CHARS = 140_000
SUPPORTED_BUG_KEYWORDS = (
    "division",
    "divide",
    "denominator",
    "zero",
    "zerodivision",
    "validation",
    "empty",
    "missing",
    "http",
    "status",
    "500",
    "400",
)


class AutomationError(RuntimeError):
    """Raised when the automation cannot continue safely."""


@dataclass(frozen=True)
class PythonFile:
    """A Python file discovered under target-repo/."""

    path: Path
    relative_path: str
    content: str


def log(level: str, message: str, **fields: Any) -> None:
    """Emit structured logs that are easy to search in GitHub Actions."""
    payload = {"level": level, "message": message, **fields}
    stream = sys.stderr if level == "ERROR" else sys.stdout
    print(json.dumps(payload, sort_keys=True), file=stream)


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object from disk with clear error messages."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AutomationError(f"Missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AutomationError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise AutomationError(f"{path} must contain a JSON object.")
    return data


def validate_repo_name(repo_name: str) -> None:
    """Protect clone/push paths from malformed repository names."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", repo_name):
        raise AutomationError(f"Invalid repository name: {repo_name!r}")


def ensure_supported_bug(issue_title: str, bug_description: str) -> None:
    """Fail early for bug categories this first automation version does not target."""
    haystack = f"{issue_title}\n{bug_description}".lower()
    if not any(keyword in haystack for keyword in SUPPORTED_BUG_KEYWORDS):
        raise AutomationError(
            "Unsupported bug type. Supported examples: division by zero, "
            "missing validation, and wrong HTTP status code."
        )


def safe_relative_path(path: Path, root: Path) -> str:
    """Return a POSIX relative path after ensuring the file is inside target-repo/."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise AutomationError(f"Refusing to read path outside target-repo: {path}") from exc


def discover_python_files(target_repo: Path) -> list[PythonFile]:
    """Read Python files under target-repo/, skipping git metadata and large files."""
    if not target_repo.is_dir():
        raise AutomationError(f"Missing target repository directory: {target_repo}")

    files: list[PythonFile] = []
    for path in sorted(target_repo.rglob("*.py")):
        if ".git" in path.parts:
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            log("INFO", "Skipping large Python file", file=str(path), max_bytes=MAX_FILE_BYTES)
            continue
        relative_path = safe_relative_path(path, target_repo)
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            log("INFO", "Skipping non-UTF-8 Python file", file=relative_path)
            continue
        files.append(PythonFile(path=path, relative_path=relative_path, content=content))

    if not files:
        raise AutomationError("No Python files found under target-repo/.")
    return files


def rank_candidate_files(files: list[PythonFile], issue_title: str, bug_description: str) -> list[PythonFile]:
    """Prefer files whose names/content look related to the issue."""
    haystack = f"{issue_title}\n{bug_description}".lower()

    def score(item: PythonFile) -> tuple[int, str]:
        text = f"{item.relative_path}\n{item.content}".lower()
        value = 0
        if "division" in haystack or "denominator" in haystack or "zerodivision" in haystack:
            value += 5 if any(token in text for token in ("divide", "division", "denominator", "/")) else 0
        if "validation" in haystack or "empty" in haystack:
            value += 3 if any(token in text for token in ("validate", "empty", "none", "request")) else 0
        if "status" in haystack or "500" in haystack or "http" in haystack:
            value += 3 if any(token in text for token in ("status", "response", "http", "flask", "fastapi")) else 0
        return (-value, item.relative_path)

    return sorted(files, key=score)


def build_repository_context(files: list[PythonFile]) -> str:
    """Build bounded Python source context for Claude."""
    blocks: list[str] = []
    total = 0
    for item in files:
        block = f"FILE: {item.relative_path}\n```python\n{item.content}\n```\n"
        if total + len(block) > MAX_TOTAL_PROMPT_CHARS:
            log("INFO", "Prompt context limit reached", included_files=len(blocks))
            break
        blocks.append(block)
        total += len(block)
    return "\n".join(blocks)


def build_prompt(issue: dict[str, Any], candidate: PythonFile, repository_context: str) -> str:
    """Create a strict prompt that asks Claude for one full corrected file."""
    return f"""You are fixing a Python bug in a GitHub repository.

Safety rules:
- Modify only the candidate file named below.
- Return ONLY the complete corrected Python code for that candidate file.
- Do not include Markdown fences, prose, diffs, explanations, shell commands, or JSON.
- If the candidate file is not the affected file, return exactly: NO_CHANGE
- Preserve the existing style and public API unless a small validation fix is required.
- Supported bug classes: division by zero, missing validation, wrong HTTP status code.

Issue title:
{issue["issue_title"]}

Bug description:
{issue["bug_description"]}

Target repository:
{issue["repo_owner"]}/{issue["repo_name"]}

Candidate file to fix:
{candidate.relative_path}

Repository Python context:
{repository_context}
"""


def call_claude(prompt: str, api_key: str, model: str) -> tuple[int, str]:
    """Call Anthropic Messages API using stdlib urllib."""
    body = {
        "model": model,
        "max_tokens": 4096,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }
    request = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
            "x-api-key": api_key,
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=90) as response:
        raw = response.read().decode("utf-8")
        payload = json.loads(raw)
        content = payload.get("content", [])
        text_parts = [part.get("text", "") for part in content if part.get("type") == "text"]
        return response.status, "\n".join(text_parts).strip()


def call_claude_with_retry(prompt: str, api_key: str, model: str, attempts: int = 3) -> str:
    """Retry transient Anthropic/API failures with exponential backoff."""
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            status, text = call_claude(prompt, api_key, model)
            log("INFO", "Claude response received", status=status, attempt=attempt)
            return text
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            last_error = f"HTTP {exc.code}: {error_body[:500]}"
            log("ERROR", "Claude HTTP error", status=exc.code, attempt=attempt)
            if exc.code not in {408, 409, 429, 500, 502, 503, 504}:
                break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            log("ERROR", "Claude transient error", attempt=attempt, error=last_error)

        if attempt < attempts:
            time.sleep(2**attempt)

    raise AutomationError(f"Claude request failed after {attempts} attempts: {last_error}")


def normalize_claude_code(response_text: str) -> str | None:
    """Normalize Claude output while rejecting explanations and malformed responses."""
    text = response_text.strip()
    if not text:
        return None
    if text == "NO_CHANGE":
        return None
    if text.startswith("```"):
        raise AutomationError("Claude returned Markdown fences instead of raw code.")
    if "```" in text:
        raise AutomationError("Claude response contains Markdown fences.")
    return text


def validate_python_code(code: str, relative_path: str) -> None:
    """Ensure Claude returned syntactically valid Python."""
    try:
        ast.parse(code, filename=relative_path)
    except SyntaxError as exc:
        raise AutomationError(f"Claude returned malformed Python for {relative_path}: {exc}") from exc


def write_fix_result(path: Path, modified_file: str, issue: dict[str, Any]) -> None:
    """Persist modified-file metadata for commit and PR scripts."""
    payload = {
        "repo_owner": issue["repo_owner"],
        "repo_name": issue["repo_name"],
        "issue_number": issue["issue_number"],
        "issue_title": issue["issue_title"],
        "modified_files": [modified_file],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    """Generate and apply one safe Claude fix."""
    try:
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise AutomationError("Missing required environment variable: ANTHROPIC_API_KEY")

        issue = read_json(Path("parsed_issue.json"))
        for key in ("repo_owner", "repo_name", "issue_number", "issue_title", "bug_description"):
            if not str(issue.get(key, "")).strip():
                raise AutomationError(f"parsed_issue.json missing required field: {key}")

        validate_repo_name(str(issue["repo_name"]))
        ensure_supported_bug(str(issue["issue_title"]), str(issue["bug_description"]))

        target_repo = Path("target-repo")
        python_files = discover_python_files(target_repo)
        ranked_files = rank_candidate_files(python_files, str(issue["issue_title"]), str(issue["bug_description"]))
        repository_context = build_repository_context(python_files)
        model = os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL

        for candidate in ranked_files:
            log("INFO", "Requesting Claude fix for candidate file", file=candidate.relative_path, model=model)
            prompt = build_prompt(issue, candidate, repository_context)
            response = call_claude_with_retry(prompt, api_key, model)
            corrected_code = normalize_claude_code(response)
            if corrected_code is None:
                log("INFO", "Claude reported no change for candidate", file=candidate.relative_path)
                continue
            if corrected_code.strip() == candidate.content.strip():
                log("INFO", "Claude returned unchanged code", file=candidate.relative_path)
                continue

            validate_python_code(corrected_code, candidate.relative_path)
            candidate.path.write_text(corrected_code.rstrip() + "\n", encoding="utf-8")
            write_fix_result(Path("fix_result.json"), candidate.relative_path, issue)
            log("INFO", "Fix applied", file_modified=candidate.relative_path, fix_applied=True)
            return 0

        raise AutomationError("No fix generated for any Python file.")
    except AutomationError as exc:
        log("ERROR", "Claude fix failed", error=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
