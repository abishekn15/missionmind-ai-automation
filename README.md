# MissionMind AI Automation

This repository contains an end-to-end GitHub Issue driven AI bug-fixing workflow. When an issue is opened in `missionmind-ai-automation`, GitHub Actions parses a full GitHub repository URL from the issue, validates it, clones that repository, asks Claude to patch the affected backend or UI source files, pushes an `ai-fix-*` branch, opens a pull request, and comments the PR URL back on the original issue.

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
Validate https://github.com/<owner>/<repo>
        |
        v
Extract repo_owner and repo_name
        |
        v
Clone repo URL into target-repo/
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

Example target repository URL:

```text
https://github.com/abishekn15/ai-bugfix-demo-repo
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
2. Parse `Repo URL:` and the issue title/body into `parsed_issue.json`.
3. Validate the repo URL and extract `repo_owner` / `repo_name`.
4. Clone the validated repo URL into `target-repo/`.
5. Run Claude using `ANTHROPIC_API_KEY` (default model: **claude-3-haiku-20240307** for lower cost).
6. Overwrite affected source files inside `target-repo/`.
7. Create branch `ai-fix-<issue-number>`.
8. Commit the generated changes.
9. Push the branch.
10. Create a pull request.
11. Comment the PR URL on the original issue.

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

## Claude model (cost)

The workflow sets **`ANTHROPIC_MODEL`** to **`claude-3-haiku-20240307`** (cheap Haiku tier). `scripts/claude_fix.py` uses the same ID as its default if you run it locally without that env var.

If Anthropic returns a billing or credit error, adding credits is required; a cheaper model only reduces cost per run, it does not bypass a zero balance.

To use a different model later, change `ANTHROPIC_MODEL` in `.github/workflows/auto-fix.yml` or set a repository variable and reference it from the workflow.

## Example Issue Format

Create an issue in `missionmind-ai-automation`:

```text
Title:
Division API crashes

Body:
Repo URL:
https://github.com/abishekn15/ai-bugfix-demo-repo

Bug Description:
Division crashes when denominator is 0.

Expected Result:
Should return validation message.

Actual Result:
ZeroDivisionError
```

`Repo URL:` is required. It must be a full GitHub HTTPS repository URL.

## Repo URL Validation Rules

Accepted format:

```text
https://github.com/<owner>/<repo>
```

Valid examples:

```text
https://github.com/openai/openai-python
https://github.com/my-org/hr-worker-api
https://github.com/abishekn15/ai-bugfix-demo-repo
```

Invalid examples:

```text
git@github.com:user/repo.git
ssh://git@github.com/user/repo.git
https://gitlab.com/user/repo
../../../etc/passwd
https://github.com/user
https://github.com/user/repo?ref=main
https://github.com/user/repo.git
```

The parser rejects non-HTTPS URLs, non-GitHub hosts, SSH syntax, local paths, malformed URLs, missing repo names, query strings, fragments, and `.git` suffixes in the issue body.

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
- Repository URLs are strictly validated before clone usage.
- Only `https://github.com/<owner>/<repo>` issue URLs are accepted.
- The workflow never builds or executes arbitrary clone commands from issue text.
- Claude is asked to return only the complete corrected source code for each affected candidate file.
- Claude output is rejected if it is empty, unchanged, Markdown-wrapped, or invalid where validation is available.
- Any UTF-8 text file under `target-repo/` can be scanned and fixed.
- YAML files (`.yml` and `.yaml`) are always ignored.
- Large source files are skipped to keep prompts bounded.
- Structured JSON logs are printed for every major step.

## Bug Scope

The workflow will attempt to fix any clearly reported bug in the target repository. It does not filter by bug type or programming language.

For safety, the automation still stays narrow in how it applies changes:

- any UTF-8 text file under `target-repo/` can be scanned
- `.yml` and `.yaml` files are always ignored
- Claude may overwrite multiple affected candidate files in one run
- generated Python and JSON are validated with Python stdlib parsers
- unchanged, empty, Markdown-wrapped, or malformed Claude output is rejected

## Local Testing

Parse an example issue:

```bash
ISSUE_TITLE="Division API crashes" \
ISSUE_BODY="$(cat <<'EOF'
Repo URL:
https://github.com/abishekn15/ai-bugfix-demo-repo

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
ANTHROPIC_API_KEY="your-anthropic-api-key" \
ANTHROPIC_MODEL="claude-3-haiku-20240307" \
python scripts/claude_fix.py
```

Local commit/push/PR scripts require valid GitHub authentication in the same way the workflow uses `GITHUB_TOKEN`.

## Troubleshooting

`Missing required environment variable: ANTHROPIC_API_KEY`

Add the `ANTHROPIC_API_KEY` repository secret.

`Issue body must include 'Repo URL: https://github.com/<owner>/<repo>'`

Use `Repo URL:` instead of the old `Repo:` field.

`Repo URL must use https://`

SSH URLs such as `git@github.com:user/repo.git`, local paths, and `ssh://` URLs are intentionally rejected.

`Repo URL host must be github.com`

Only GitHub repository URLs are allowed. GitLab, Bitbucket, or private Git server URLs are rejected.

`Repo URL must not include params, query strings, or fragments`

Use the clean repository URL only, for example `https://github.com/abishekn15/ai-bugfix-demo-repo`.

`Claude returned malformed Python` / `Claude returned malformed JSON`

Claude generated code that failed available syntax validation. Reopen the issue with a clearer bug description or rerun the workflow.

`No fix generated for any UTF-8 non-YAML file`

The target repo may not contain a related UTF-8 non-YAML file, or the issue text may not clearly match the code.

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
