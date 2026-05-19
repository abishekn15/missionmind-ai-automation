#!/usr/bin/env python3
"""Render a GitHub Issue comment body from parsed_issue.json.

Used by GitHub Actions after parse_issue.py succeeds so the issue thread shows
what the automation extracted (target repo, bug summary) without reading logs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "Usage: format_issue_comment.py <parsed_issue.json> <output.md>",
            file=sys.stderr,
        )
        return 2

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"Missing input file: {input_path}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON in {input_path}: {exc}", file=sys.stderr)
        return 1

    owner = data.get("repo_owner") or ""
    repo = data.get("repo_name") or ""
    bug = data.get("bug_description") or ""
    title = data.get("issue_title") or ""
    number = data.get("issue_number") or ""

    full_name = f"{owner}/{repo}" if owner and repo else repo

    lines = [
        "### Automation (Phase 2)",
        "",
        "Parsed this issue and recorded the following for the next pipeline steps.",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Issue | #{number} — {title} |",
        f"| Target repository | `{full_name}` |",
        f"| Bug description | {bug} |",
        "",
        "_This comment was posted by GitHub Actions._",
    ]

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
