# MissionMind AI Automation

Phase 1 creates a GitHub Issue-driven automation entry point. When a new issue is opened, GitHub Actions reads the issue title and body, extracts the target repository name and bug description, and prints structured logs.

**Phase 2** (current): after a successful parse, the workflow writes `parsed_issue.json`, posts an acknowledgement comment on the same issue, and shallow-clones the target repository into `target-repo/` on the runner (for upcoming fix/analysis steps).

## Files Created

- `.github/workflows/auto-fix.yml` defines the GitHub Actions workflow.
- `scripts/parse_issue.py` parses the issue payload, prints structured logs, and writes `parsed_issue.json`.
- `scripts/format_issue_comment.py` builds the Markdown body for the acknowledgement comment.

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

- `Repo:` is the target repository name (short name, for example `HR-worker-api`).
- `Bug Description:` describes the bug that later automation phases can process.

Optional fields:

- `Owner:` or `Org:` — GitHub user or organization that owns the target repo. If omitted, the workflow uses the automation repository’s owner (`github.repository_owner`) as `DEFAULT_REPO_OWNER`.

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
5. Review the `Print raw issue details`, `Parse issue request`, `Post acknowledgement on issue`, and `Shallow clone target repository` steps.

The parser prints JSON logs similar to:

```json
{"bug_description": "Login API crashes when email is empty", "issue_author": "octocat", "issue_number": "1", "issue_title": "Login API returns 500", "issue_url": "https://github.com/example/repo/issues/1", "level": "INFO", "message": "Parsed GitHub Issue successfully", "repo_name": "HR-worker-api", "repo_owner": "example"}
```

## How To Test Locally

Run the parser with the same environment variables the workflow uses. If the issue body does **not** contain `Owner:` or `Org:`, set `DEFAULT_REPO_OWNER` (usually your GitHub user or org):

```bash
DEFAULT_REPO_OWNER="your-github-org-or-user" \
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

Expected: structured JSON logs, a `parsed_issue.json` file in the working directory, and fields including `repo_name`, `repo_owner`, and `bug_description`.

To preview the acknowledgement comment GitHub will post:

```bash
python scripts/format_issue_comment.py parsed_issue.json issue_ack_comment.md
cat issue_ack_comment.md
```

To point at a target repo in another org without setting `DEFAULT_REPO_OWNER`, add a line to the issue body:

```text
Owner: some-other-org
Repo: HR-worker-api
```

## Values To Replace

Replace these example values with your real project values:

- `HR-worker-api`: the repository name written in each GitHub Issue after `Repo:`.
- `your-github-org-or-user`: your GitHub org or username used as `DEFAULT_REPO_OWNER` in local runs (the workflow sets this from the automation repo owner on GitHub).
- `your-org`: your GitHub organization or username in local test URLs.
- `missionmind-ai-automation`: your GitHub repository name if it is different.
- `your-github-username`: your GitHub username for local testing.

## Phase 2: Secrets and permissions

- **Permissions**: the workflow uses `issues: write` so it can post the acknowledgement comment.
- **Optional secret `TARGET_REPO_CLONE_TOKEN`**: use a fine-grained PAT or classic PAT with `contents: read` on the **target** repository when it is private or when the default `GITHUB_TOKEN` cannot read it (for example another org). If unset, the clone step uses `github.token`, which is enough for many same-owner public repos.

No other secrets are required for the parse, comment, and clone steps on typical public same-owner setups.

## Phase 3 (next ideas)

Examples of what you can add next: run static analysis or tests in `target-repo/`, call an AI/Cursor API to propose a patch, push a branch and open a pull request on the target repo, or dispatch a workflow in the target repository. Those steps need additional tokens (for example `contents: write` on the target repo for PR creation).
