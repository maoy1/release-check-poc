"""
release_check_poc.py

Client PR Readiness Gate — scaled-down POC.

Scope (per current build track):
- Private/DM-only output — no public posting, no reactions.
- Detection rule: every PR must have a Jira ticket number in its title.
    - Missing ticket -> flagged "manual review needed".
    - Present ticket -> Jira status is looked up and shown, but is
      INFORMATIONAL ONLY. It never blocks or produces a verdict.
- Support-channel thread matching is done by PR URL/link, not by person
  (Slack ID != GitHub ID, unreliable).
- No stored state, no verdict, no gating. Just evidence for a human to read.

Env vars required:
    GITHUB_TOKEN   - GitHub PAT (repo or public_repo scope)
    GITHUB_REPO    - "owner/repo" (NOT the full github.com URL)
    JIRA_EMAIL     - Atlassian account email
    JIRA_TOKEN     - Jira API token (id.atlassian.com/manage-profile/security/api-tokens)
    JIRA_BASE      - e.g. "https://yourcompany.atlassian.net"
    SLACK_USER_TOKEN - xoxp user token with search:read (for support-thread matching)
    SUPPORT_CHANNEL - e.g. "C0A2N9D1G3B" (deng-saip-support)

Example calls:
    # Compare main branch against a release branch before shipping
    python release_check_poc.py release/V5.0.4 main

    # Compare last known-good tag against the new release candidate
    python release_check_poc.py 1.32.5-rc1 V5.0.4

    # Compare two release candidates (e.g. checking what changed since rc1)
    python release_check_poc.py V5.0.2-rc1 V5.0.2

    # Compare a specific commit SHA against a branch
    python release_check_poc.py 8f3a1c2 release/V5.0.4

Note: base_ref/head_ref have defaults ("main"/"HEAD") but you should
always pass both explicitly for a real run - "HEAD" has no meaningful
resolution over the GitHub compare API, and "main" as a base is only
a guess about your branching model.


Note: JIRA_PROJECT_KEY is intentionally NOT used. The project prefix
(e.g. "AIPL") is already embedded in the ticket key extracted from the
PR title (e.g. "AIPL-1234") and is passed straight through to the Jira
issue-lookup endpoint. There is no per-project filtering step in this
script, so no separate project-key config is needed. Multiple projects
work automatically as long as the ticket key in the title matches the
regex below.
"""

import os
import re
import base64
import requests
import truststore
truststore.inject_into_ssl()

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = os.environ["GITHUB_REPO"]              # "owner/repo"
JIRA_EMAIL = os.environ["JIRA_EMAIL"]
JIRA_TOKEN = os.environ["JIRA_TOKEN"]
JIRA_BASE = os.environ["JIRA_BASE"].rstrip("/")      # e.g. https://yourcompany.atlassian.net
SLACK_USER_TOKEN = os.environ.get("SLACK_USER_TOKEN")
SUPPORT_CHANNEL = os.environ.get("SUPPORT_CHANNEL")

TICKET_REGEX = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
AUTOMATED_COMMIT_REGEX = re.compile(r"^Bump version:.*\[ci skip\]$", re.IGNORECASE)


def is_automated_commit(title: str) -> bool:
    """True for CI-generated commits (e.g. version bumps) that aren't real
    PRs and shouldn't be flagged for manual Jira-ticket review."""
    return bool(AUTOMATED_COMMIT_REGEX.match(title or ""))


def get_diff_prs(base_ref: str, head_ref: str):
    """Return the list of PR-like commits/changes between base_ref and head_ref
    using the GitHub compare API. Each item is expected to at least carry a
    title and an html_url so downstream steps can extract tickets and match
    support threads. Automated commits (e.g. CI version bumps) are excluded."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/compare/{base_ref}...{head_ref}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    prs = []
    for commit in data.get("commits", []):
        message = commit.get("commit", {}).get("message", "")
        title = message.splitlines()[0] if message else ""
        if is_automated_commit(title):
            continue
        prs.append({
            "title": title,
            "html_url": commit.get("html_url"),
            "sha": commit.get("sha"),
        })
    return prs


def extract_ticket_from_title(title: str):
    """Pull a Jira ticket key (e.g. AIPL-1234) out of a PR/commit title.
    Returns None if no ticket key is found -> caller should flag for
    manual review. Note: does not match lowercase keys (e.g. aipl-1234)
    - open edge case, not currently handled."""
    match = TICKET_REGEX.search(title or "")
    return match.group(1) if match else None


def get_jira_status(ticket: str):
    """Look up a Jira issue's status. INFORMATIONAL ONLY - the caller must
    never treat this as a pass/fail gate. Returns a dict with status info,
    or an error marker if the lookup fails (e.g. ticket not found)."""
    url = f"{JIRA_BASE}/rest/api/2/issue/{ticket}"
    auth_str = f"{JIRA_EMAIL}:{JIRA_TOKEN}"
    b64_auth = base64.b64encode(auth_str.encode()).decode()
    headers = {
        "Authorization": f"Basic {b64_auth}",
        "Accept": "application/json",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        return {
            "ticket": ticket,
            "status": None,
            "error": f"lookup failed ({resp.status_code})",
        }
    data = resp.json()
    fields = data.get("fields", {})
    return {
        "ticket": ticket,
        "status": fields.get("status", {}).get("name"),
        "summary": fields.get("summary"),
        "error": None,
    }


def find_support_thread_for_pr(pr_url: str):
    """Search the support channel for a message mentioning this PR's URL.
    Matching is done by URL/link, not by person, since Slack IDs and GitHub
    identities don't reliably map to each other.

    NOTE: Slack's search.messages API requires a user token (xoxp with
    search:read scope), not a bot token. This is currently assumed but not
    yet confirmed against this workspace's token setup."""
    if not SLACK_USER_TOKEN or not SUPPORT_CHANNEL:
        return None

    url = "https://slack.com/api/search.messages"
    headers = {"Authorization": f"Bearer {SLACK_USER_TOKEN}"}
    params = {
        "query": f'"{pr_url}" in:#{SUPPORT_CHANNEL}',
        "count": 5,
    }
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if not data.get("ok"):
        return None

    matches = data.get("messages", {}).get("matches", [])
    if not matches:
        return None

    top = matches[0]
    return {
        "permalink": top.get("permalink"),
        "text": top.get("text"),
    }


def build_release_check_report(base_ref: str, head_ref: str):
    """Assemble the final DM-only report. No verdict, no blocking, no state.
    Just evidence: PR list, ticket + Jira status (info-only), and any
    matching support-thread link, for a human to read and decide."""
    prs = get_diff_prs(base_ref, head_ref)

    lines = [f"*Client PR Readiness Check* — `{base_ref}` → `{head_ref}`", ""]

    if not prs:
        lines.append("_No PRs/commits found in this diff._")
        return "\n".join(lines)

    for pr in prs:
        title = pr["title"]
        pr_url = pr["html_url"]
        ticket = extract_ticket_from_title(title)

        lines.append(f"• *{title}*")
        if pr_url:
            lines.append(f"   Link: {pr_url}")

        if not ticket:
            lines.append("   :warning: No Jira ticket found in title — *manual review needed*")
        else:
            jira_info = get_jira_status(ticket)
            if jira_info["error"]:
                lines.append(f"   Jira: {ticket} — lookup error ({jira_info['error']})")
            else:
                lines.append(
                    f"   Jira: {ticket} — status: *{jira_info['status']}* (info only, not a gate)"
                )

        thread = find_support_thread_for_pr(pr_url) if pr_url else None
        if thread:
            lines.append(f"   Related support thread: {thread['permalink']}")

        lines.append("")

    lines.append("_This report is informational only — no automated pass/fail verdict is produced._")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    base_ref = sys.argv[1] if len(sys.argv) > 1 else "main"
    head_ref = sys.argv[2] if len(sys.argv) > 2 else "HEAD"

    report = build_release_check_report(base_ref, head_ref)
    print(report)
