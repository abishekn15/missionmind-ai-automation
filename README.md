# MissionMind AI Automation

Phase 1 creates a GitHub Issue-driven automation entry point. When a new issue is opened, GitHub Actions reads the issue title and body, extracts the target repository name and bug description, and prints structured logs.

## Files Created

- `.github/workflows/auto-fix.yml` defines the GitHub Actions workflow.
- `scripts/parse_issue.py` parses the issue payload and prints structured logs.

## How The Workflow Triggers

The workflow runs only when a GitHub Issue is opened:

```yaml
on:
  issues:
    types:
      - opened
```

It does not run when an issue is edited, closed, reopened, labeled, assigned, or commented on.

## Issue Format

Create a GitHub Issue with this structure:

```text
Title:
Login API returns 500

Body:
Repo: HR-worker-api

Bug Description:
Login API crashes when email is empty

Expected Result:
Validation error

Actual Result:
500 Internal Server Error
```

Required fields:

- `Repo:` is the target repository name.
- `Bug Description:` describes the bug that later automation phases can process.

## How To Create An Issue

1. Push this repository to GitHub.
2. Open the repository in GitHub.
3. Go to `Issues`.
4. Click `New issue`.
5. Use a title like `Login API returns 500`.
6. Add the issue body using the required format above.
7. Click `Submit new issue`.

GitHub Actions will start automatically after the issue is opened.

## How To View Logs

1. Open the repository in GitHub.
2. Go to the `Actions` tab.
3. Select the `Auto Fix Issue Parser` workflow run.
4. Open the `parse-issue` job.
5. Review the `Print raw issue details` and `Parse issue request` steps.

The parser prints JSON logs similar to:

```json
{"bug_description": "Login API crashes when email is empty", "issue_author": "octocat", "issue_number": "1", "issue_title": "Login API returns 500", "issue_url": "https://github.com/example/repo/issues/1", "level": "INFO", "message": "Parsed GitHub Issue successfully", "repo_name": "HR-worker-api"}
```

## How To Test Locally

Run the parser with environment variables that match the GitHub Actions workflow:

```bash
ISSUE_TITLE="Login API returns 500" \
ISSUE_BODY="$(cat <<'EOF'
Repo: HR-worker-api

Bug Description:
Login API crashes when email is empty

Expected Result:
Validation error

Actual Result:
500 Internal Server Error
EOF
)" \
ISSUE_NUMBER="1" \
ISSUE_URL="https://github.com/your-org/missionmind-ai-automation/issues/1" \
ISSUE_AUTHOR="your-github-username" \
python scripts/parse_issue.py
```

Expected result: the command exits successfully and prints structured JSON logs containing `repo_name` and `bug_description`.

## Values To Replace

Replace these example values with your real project values:

- `HR-worker-api`: the repository name written in each GitHub Issue after `Repo:`.
- `your-org`: your GitHub organization or username in local test URLs.
- `missionmind-ai-automation`: your GitHub repository name if it is different.
- `your-github-username`: your GitHub username for local testing.

No API keys, tokens, or secrets are required for Phase 1.
