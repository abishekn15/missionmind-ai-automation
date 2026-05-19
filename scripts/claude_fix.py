#!/usr/bin/env python3
"""Use Claude to generate a safe source-code bug fix inside target-repo/.

This script is intentionally scoped for safe automation:
- reads issue context from parsed_issue.json
- scans any UTF-8 text file under target-repo/ except .yml/.yaml
- asks Claude to fix every affected source file it can identify
- validates generated Python/JSON when possible
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
MIN_KEYWORD_LENGTH = 3
IGNORED_EXTENSIONS = {".yaml", ".yml"}
SKIPPED_DIRECTORIES = {
    ".git",
    ".next",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
}
STOP_WORDS = {
    "actual",
    "and",
    "are",
    "bug",
    "but",
    "can",
    "crash",
    "crashes",
    "does",
    "expected",
    "fix",
    "for",
    "from",
    "issue",
    "not",
    "result",
    "should",
    "the",
    "this",
    "when",
    "with",
}


class AutomationError(RuntimeError):
    """Raised when the automation cannot continue safely."""


@dataclass(frozen=True)
class SourceFile:
    """A UTF-8 text file discovered under target-repo/."""

    path: Path
    relative_path: str
    language: str
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


def safe_relative_path(path: Path, root: Path) -> str:
    """Return a POSIX relative path after ensuring the file is inside target-repo/."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise AutomationError(f"Refusing to read path outside target-repo: {path}") from exc


def should_skip_path(path: Path) -> bool:
    """Skip generated/dependency folders and YAML files."""
    if any(part in SKIPPED_DIRECTORIES for part in path.parts):
        return True
    return path.suffix.lower() in IGNORED_EXTENSIONS


def language_for_markdown(path: Path) -> str:
    """Use a best-effort code fence label without filtering by language."""
    extension = path.suffix.lower().lstrip(".")
    if extension in {"yml", "yaml"}:
        return "yaml"
    return extension or "text"


def discover_source_files(target_repo: Path) -> list[SourceFile]:
    """Read any UTF-8 text file under target-repo/, skipping YAML and generated folders."""
    if not target_repo.is_dir():
        raise AutomationError(f"Missing target repository directory: {target_repo}")

    files: list[SourceFile] = []
    for path in sorted(item for item in target_repo.rglob("*") if item.is_file()):
        if should_skip_path(path):
            continue

        if path.stat().st_size > MAX_FILE_BYTES:
            log("INFO", "Skipping large source file", file=str(path), max_bytes=MAX_FILE_BYTES)
            continue

        relative_path = safe_relative_path(path, target_repo)
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            log("INFO", "Skipping non-UTF-8 source file", file=relative_path)
            continue
        language = language_for_markdown(path)
        files.append(SourceFile(path=path, relative_path=relative_path, language=language, content=content))

    if not files:
        raise AutomationError("No UTF-8 non-YAML files found under target-repo/.")
    return files


def extract_issue_keywords(issue_title: str, bug_description: str) -> set[str]:
    """Extract generic keywords from the report without restricting bug type."""
    text = f"{issue_title}\n{bug_description}".lower()
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]+|\d+", text)
    return {
        word
        for word in words
        if len(word) >= MIN_KEYWORD_LENGTH and word not in STOP_WORDS
    }


def rank_candidate_files(files: list[SourceFile], issue_title: str, bug_description: str) -> list[SourceFile]:
    """Prefer files whose paths/content overlap with the issue text."""
    keywords = extract_issue_keywords(issue_title, bug_description)

    def score(item: SourceFile) -> tuple[int, str]:
        text = f"{item.relative_path}\n{item.content}".lower()
        value = sum(1 for keyword in keywords if keyword in text)
        return (-value, item.relative_path)

    return sorted(files, key=score)


def build_repository_context(files: list[SourceFile]) -> str:
    """Build bounded source context for Claude."""
    blocks: list[str] = []
    total = 0
    for item in files:
        block = f"FILE: {item.relative_path}\n```{item.language}\n{item.content}\n```\n"
        if total + len(block) > MAX_TOTAL_PROMPT_CHARS:
            log("INFO", "Prompt context limit reached", included_files=len(blocks))
            break
        blocks.append(block)
        total += len(block)
    return "\n".join(blocks)


def build_prompt(issue: dict[str, Any], candidate: SourceFile, repository_context: str) -> str:
    """Create a strict prompt that asks Claude for one full corrected file."""
    return f"""You are fixing a source-code bug in a GitHub repository. The bug may be backend or UI/frontend.

Safety rules:
- Modify only the candidate file named below.
- Return ONLY the complete corrected source code for that candidate file.
- Do not include Markdown fences, prose, diffs, explanations, shell commands, or metadata JSON.
- If the candidate file is not the affected file, return exactly: NO_CHANGE
- Preserve the existing style and public API unless the bug fix requires a small behaviour change.
- Fix the reported bug based on the issue and repository context. Do not invent unrelated changes.

Issue title:
{issue["issue_title"]}

Bug description:
{issue["bug_description"]}

Target repository:
{issue["repo_owner"]}/{issue["repo_name"]}

Candidate file to fix:
{candidate.relative_path}

Repository source context:
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


def validate_generated_code(code: str, source_file: SourceFile) -> None:
    """Validate returned code when a safe stdlib parser exists."""
    if source_file.path.suffix.lower() == ".py":
        try:
            ast.parse(code, filename=source_file.relative_path)
        except SyntaxError as exc:
            raise AutomationError(f"Claude returned malformed Python for {source_file.relative_path}: {exc}") from exc
    elif source_file.path.suffix.lower() == ".json":
        try:
            json.loads(code)
        except json.JSONDecodeError as exc:
            raise AutomationError(f"Claude returned malformed JSON for {source_file.relative_path}: {exc}") from exc


def write_fix_result(path: Path, modified_files: list[str], issue: dict[str, Any]) -> None:
    """Persist modified-file metadata for commit and PR scripts."""
    payload = {
        "repo_owner": issue["repo_owner"],
        "repo_name": issue["repo_name"],
        "issue_number": issue["issue_number"],
        "issue_title": issue["issue_title"],
        "modified_files": modified_files,
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

        target_repo = Path("target-repo")
        source_files = discover_source_files(target_repo)
        ranked_files = rank_candidate_files(source_files, str(issue["issue_title"]), str(issue["bug_description"]))
        repository_context = build_repository_context(source_files)
        model = os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL

        modified_files: list[str] = []

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

            validate_generated_code(corrected_code, candidate)
            candidate.path.write_text(corrected_code.rstrip() + "\n", encoding="utf-8")
            modified_files.append(candidate.relative_path)
            log("INFO", "Fix applied", file_modified=candidate.relative_path, fix_applied=True)

        if modified_files:
            write_fix_result(Path("fix_result.json"), modified_files, issue)
            log("INFO", "All fixes applied", modified_files=modified_files, modified_file_count=len(modified_files))
            return 0

        raise AutomationError("No fix generated for any UTF-8 non-YAML file.")
    except AutomationError as exc:
        log("ERROR", "Claude fix failed", error=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
