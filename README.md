# release-check-poc

Client PR Readiness Gate — proof-of-concept script that gathers evidence (GitHub diff + Jira ticket status) to help a human decide whether a release candidate is ready to ship. It never blocks or auto-approves anything.

This script is the working piece of a larger release-automation proposal — see [PROPOSAL.md](PROPOSAL.md) for the full design (Slack workflow, Jenkins integration, Client PR Readiness Gate, etc.).

## `scripts/release_check_poc.py`

This is the working POC script referenced throughout the proposal (see PROPOSAL.md, sections "POC Scope" and "Architecture"). It produces the readiness report only — it never blocks, gates, or auto-approves a release.

### Setup

```
pip install -r requirements.txt
cp .env_template .env   # then fill in your credentials
```

Environment variables are loaded automatically from `.env` (via `python-dotenv`) when the script runs — no need to `export` them in your shell.

| Variable | Required | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | yes | GitHub PAT (classic: `repo`; fine-grained: Contents + Pull requests read) |
| `GITHUB_REPO` | yes | `owner/repo`, no URL |
| `JIRA_EMAIL` | yes | Jira account email, used for Basic Auth |
| `JIRA_TOKEN` | yes | Jira API token, used as the Basic Auth password |
| `JIRA_BASE` | yes | e.g. `https://elsevier.atlassian.net` |
| `SUPPORT_CHANNEL` | no | Slack channel ID, e.g. `C0A2N9D1G3B` — informational label only, no Slack call is made |

### Usage

```
python scripts/release_check_poc.py <old_version> <new_version>
```

- `old_version` — the version currently in prod / last shipped (base ref)
- `new_version` — the release candidate being considered (head ref)

```
# Current prod is 5.0.9-beta, checking main as the new candidate
python scripts/release_check_poc.py 5.0.9-beta main
```

### What it does

1. Diffs `old_version` → `new_version` via the GitHub compare API, one entry per PR (commits are resolved to their merged PR and de-duplicated; automated `Bump version: ... [ci skip]` commits are dropped).
2. Extracts a Jira ticket key from each PR/commit title (e.g. `AIPL-1234`, `[RSAI-2804]`, `Rtsc 62316` → `RTSC-62316`). No match → flagged `manual review needed`.
3. Looks up each ticket's current Jira status — shown as **info only**, never used to gate the release.
4. Sorts the PR list: **AIPL** tickets first, then **RSAI**, then PRs with no ticket, then everything else; within each group, PRs with a resolved Jira status sort before failed lookups, then alphabetically by status name.
5. Prints a plain-text/Slack-formatted report, ending with a "Step 2" hand-off list of PR links — for a human (or an assistant with its own Slack access) to check against the support channel. This script makes no Slack API calls itself.

### Example output

```
*Client PR Readiness Check* — `5.0.9-beta` → `main`

• *Fix client export timeout (#1793)*
   Link: <https://github.com/org/repo/pull/1793>
   Jira: AIPL-1234 — status: *In Progress* (info only, not a gate)

• *Add retry logic for RSAI feed (#1801)*
   Link: <https://github.com/org/repo/pull/1801>
   Jira: RSAI-2804 — status: *Done* (info only, not a gate)

• *Hotfix logging typo*
   Link: <https://github.com/org/repo/commit/9fceab2d8...>
   :warning: No Jira ticket found in title — *manual review needed*

_This report is informational only — no automated pass/fail verdict is produced._

*Step 2 — PRs to check against <#C0A2N9D1G3B>:*
   • #1793  [AIPL-1234: In Progress]  (Fix client export timeout)
   • #1801  [RSAI-2804: Done]  (Add retry logic for RSAI feed)
   • #1804  [no Jira ticket]  (Hotfix logging typo)
```
