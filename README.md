# MissionMind AI Automation

This repository contains an end-to-end GitHub Issue driven AI bug-fixing workflow. When an issue is opened in `missionmind-ai-automation`, GitHub Actions parses the issue, clones the public same-owner target repo, asks Claude to patch the affected Python file, pushes an `ai-fix-*` branch, opens a pull request, and comments the PR URL back on the original issue.

## Architecture

```text
GitHub Issue opened
        |
        v
.github/workflows/auto-fix.yml
        |
        v
scripts/parse_issue.py -> parsed_issue.json
        |
        v
Clone target repo into target-repo/
        |
        v
scripts/claude_fix.py -> fix_result.json
        |
        v
scripts/git_commit_push.py -> git_result.json
        |
        v
scripts/create_pr.py -> pr_result.json
        |
        v
scripts/comment_pr.py -> comment PR URL on original issue
```

Target repository for the current demo:

```text
ai-bugfix-demo-repo
```

## Workflow Execution Flow

The workflow runs only for newly opened issues:

```yaml
on:
  issues:
    types:
      - opened
```

The job uses `ubuntu-latest` and Python `3.11`, then runs:

1. Checkout the automation repository.
2. Parse the issue title/body into `parsed_issue.json`.
3. Clone the target repo into `target-repo/` using only the built-in `GITHUB_TOKEN`.
4. Run Claude using `ANTHROPIC_API_KEY`.
5. Overwrite only the affected Python file inside `target-repo/`.
6. Create branch `ai-fix-<issue-number>`.
7. Commit the generated change.
8. Push the branch.
9. Create a pull request.
10. Comment the PR URL on the original issue.

## GitHub Settings

In the automation repository settings, enable GitHub Actions and set workflow permissions so the built-in token can write:

```yaml
permissions:
  contents: write
  pull-requests: write
  issues: write
```

This implementation intentionally does **not** use:

- `TARGET_REPO_CLONE_TOKEN`
- `TARGET_REPO_PUSH_TOKEN`

It uses only:

- built-in `GITHUB_TOKEN`
- `ANTHROPIC_API_KEY`

Important GitHub limitation: `GITHUB_TOKEN` is scoped by GitHub to the repository where the workflow runs. The clone works for your public same-owner demo repo. If GitHub blocks pushing a branch or creating a PR in another repository, that is a platform permission boundary, not a script bug.

## Required Secret

Create this repository secret in `missionmind-ai-automation`:

```text
ANTHROPIC_API_KEY
```

Steps:

1. Open GitHub repository settings.
2. Go to `Secrets and variables` -> `Actions`.
3. Click `New repository secret`.
4. Name: `ANTHROPIC_API_KEY`.
5. Value: your Anthropic API key.

## Example Issue Format

Create an issue in `missionmind-ai-automation`:

```text
Title:
Division API crashes

Body:
Repo: ai-bugfix-demo-repo

Bug Description:
Division crashes when denominator is 0.

Expected Result:
Should return validation message.

Actual Result:
ZeroDivisionError
```

`Repo:` is required. `Owner:` / `Org:` is optional. If omitted, the workflow uses the same GitHub owner as the automation repository.

## Example Generated PR

The workflow creates a branch like:

```text
ai-fix-17
```

The PR title will be:

```text
AI Fix: Division API crashes
```

The PR body includes:

- source issue number
- source issue title
- AI-generated fix notice
- modified files
- human review disclaimer

After PR creation, the original issue receives a comment:

```text
AI-generated fix PR created:
https://github.com/abishekn15/ai-bugfix-demo-repo/pull/1

Please review before merging.
```

## Safety Protections

- The workflow never pushes directly to `main`.
- Branches are always named `ai-fix-<issue-number>`.
- Automation scripts only modify files inside `target-repo/`.
- Issue body text is never executed as a shell command.
- Repository names are validated before clone/push usage.
- Claude is asked to return only complete corrected Python code.
- Claude output is rejected if it is empty, unchanged, Markdown-wrapped, or invalid Python.
- Only Python files under `target-repo/` are scanned.
- Large Python files are skipped to keep prompts bounded.
- Structured JSON logs are printed for every major step.

## Supported Bug Types

The current `claude_fix.py` supports focused Python fixes for:

- division by zero
- missing validation
- wrong HTTP status code

Unsupported bug categories fail safely instead of producing broad or risky edits.

## Local Testing

Parse an example issue:

```bash
DEFAULT_REPO_OWNER="abishekn15" \
ISSUE_TITLE="Division API crashes" \
ISSUE_BODY="$(cat <<'EOF'
Repo: ai-bugfix-demo-repo

Bug Description:
Division crashes when denominator is 0.

Expected Result:
Should return validation message.

Actual Result:
ZeroDivisionError
EOF
)" \
ISSUE_NUMBER="1" \
ISSUE_URL="https://github.com/abishekn15/missionmind-ai-automation/issues/1" \
ISSUE_AUTHOR="abishekn15" \
python scripts/parse_issue.py
```

Clone the demo repo locally:

```bash
rm -rf target-repo
git clone --depth 1 https://github.com/abishekn15/ai-bugfix-demo-repo.git target-repo
```

Run Claude locally:

```bash
ANTHROPIC_API_KEY="your-anthropic-api-key" python scripts/claude_fix.py
```

Local commit/push/PR scripts require valid GitHub authentication in the same way the workflow uses `GITHUB_TOKEN`.

## Troubleshooting

`Missing required environment variable: ANTHROPIC_API_KEY`

Add the `ANTHROPIC_API_KEY` repository secret.

`Unsupported bug type`

Use one of the currently supported bug categories: division by zero, missing validation, or wrong HTTP status code.

`Claude returned malformed Python`

Claude generated code that failed Python syntax validation. Reopen the issue with a clearer bug description or rerun the workflow.

`No fix generated for any Python file`

The target repo may not contain a related `.py` file, or the issue text may not clearly match the code.

`git push failed`

The branch push can fail if GitHub does not allow this workflow repository’s `GITHUB_TOKEN` to write to the target repository. This is a GitHub token scope limitation. For your current public same-owner demo, clone is expected to work; push/PR depends on GitHub allowing cross-repository writes from the workflow token.

`gh pr create failed`

Check that the branch was pushed successfully and that workflow permissions include `pull-requests: write`.

## Future Improvements

- Add test discovery and run tests before creating a PR.
- Add file-level allowlists for larger repositories.
- Support multi-file fixes with a stricter patch format.
- Add retry labels or issue comments on failed automation.
- Add a human approval gate before pushing AI-generated changes.
- Support private or cross-org targets with an explicit GitHub App installation.
