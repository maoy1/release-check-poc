#!/usr/bin/env python3
"""
release_check_poc.py

Client PR Readiness Gate - POC (scaled-down scope)

Purpose
-------
Gathers evidence to help a human decide whether the current release
candidate is ready to ship. This script NEVER produces a pass/fail
verdict and NEVER blocks or auto-approves anything - it only surfaces
information for a human to review.

What it does
------------
1. Pulls the PR/commit diff between two refs from GitHub (compare API).
2. Extracts a Jira ticket key from each PR/commit title, if present.
   - Missing ticket -> flagged "manual review needed".
3. Looks up each ticket's current Jira status - shown as INFO ONLY,
   never used to gate/block the release.
4. Assembles a plain evidence report (no verdict).

Two-step approach for support-channel matching
------------------------------------------------
This script does NOT call Slack at all - no bot token, no user token,
no search:read needed. Instead, step 2 below hands off the list of PR
links to a separate step:

  Step 1 (this script): produce the report, including a clearly marked
      "PRs to check against support channel" list (just PR links).
  Step 2 (manual, or via an assistant/orchestrator with its own Slack
      access - e.g. Slackbot acting on the user's behalf): take that
      list of links and check <#SUPPORT_CHANNEL> for any mention of
      each link, then report back which ones were found.

This keeps the script itself free of any Slack credential requirement,
while still fully automating the lookup by handing it to a second step
rather than doing it manually by hand.

Usage
-----
    python release_check_poc.py <old_version> <new_version>

    <old_version>  the version currently in prod / last shipped (base_ref)
    <new_version>  the release candidate being considered (head_ref)

Example calls
--------------
    # Current prod is 5.0.9-beta, checking main as the new candidate
    python release_check_poc.py 5.0.9-beta main

    # Comparing two release tags directly (old -> new)
    python release_check_poc.py 1.32.5-rc1 V5.0.4

    # Old RC -> newer RC
    python release_check_poc.py V5.0.2-rc1 V5.0.4

    # Using a raw commit SHA as the old version
    python release_check_poc.py 9fceab2 main

Note: old_version/new_version default to "main"/"HEAD" if omitted, but
you should always pass both explicitly - GitHub's compare API needs
real ref names that exist on the remote, and "HEAD" has no meaning
there.

Environment variables
----------------------
    GITHUB_TOKEN         GitHub personal access token (classic: repo scope;
                         fine-grained: Contents + Pull requests read)
    GITHUB_REPO          "owner/repo" (no URL, no github.com prefix)
    JIRA_EMAIL           Jira account email (used for Basic Auth)
    JIRA_TOKEN           Jira API token (used for Basic Auth, as the password)
    JIRA_BASE            Jira base URL, e.g. https://elsevier.atlassian.net
    SUPPORT_CHANNEL      (optional, informational only) Slack channel ID
                         for the support channel, e.g. C0A2N9D1G3B
                         (deng-saip-support) - used only to label the
                         hand-off list in the report; no Slack API call
                         is made from this script.

Note on JIRA_PROJECT_KEY: intentionally NOT used. The project prefix
is already embedded in each ticket key extracted from the PR title
(e.g. "AIPL" in "AIPL-1234"), so there is nothing to configure
separately - multiple projects are supported automatically.
"""

import os
import re
import sys
import base64
import requests

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL")
JIRA_TOKEN = os.environ.get("JIRA_TOKEN")
JIRA_BASE = os.environ.get("JIRA_BASE")
SUPPORT_CHANNEL = os.environ.get("SUPPORT_CHANNEL")

# Matches tickets like AIPL-1234, [AIPL-1765], (RSAI-2804), Rtsc 62316
# (letters + optional hyphen/space + digits), case-insensitive.
TICKET_PATTERN = re.compile(r"\b([A-Za-z]{2,10})[\s-](\d{2,6})\b")
AUTOMATED_COMMIT_REGEX = re.compile(r"^Bump version:.*\[ci skip\]$", re.IGNORECASE)


def is_automated_commit(title: str) -> bool:
    """True for CI-generated commits (e.g. version bumps) that aren't real
    PRs and shouldn't be flagged for manual Jira-ticket review."""
    return bool(AUTOMATED_COMMIT_REGEX.match(title or ""))


def extract_ticket_from_title(title):
    """Extract a Jira ticket key from a PR/commit title, normalized to
    UPPERCASE-WITH-HYPHEN form (e.g. "Rtsc 62316" -> "RTSC-62316").
    Returns None if no ticket-like pattern is found.
    """
    match = TICKET_PATTERN.search(title)
    if not match:
        return None
    prefix, number = match.groups()
    return f"{prefix.upper()}-{number}"


PR_NUMBER_PATTERN = re.compile(r"\(#(\d+)\)\s*$")


def extract_pr_number_from_title(title: str) -> str | None:
    """Extract the trailing PR number from a squash-merge commit title,
    e.g. "Some change (#1793)" -> "1793". Returns None if not present
    (e.g. non-squash commits, or titles without a PR reference)."""
    match = PR_NUMBER_PATTERN.search(title)
    return match.group(1) if match else None


def lookup_pr_for_commit(sha: str, headers: dict) -> dict | None:
    """Find the merged PR that a commit belongs to (covers merge-commit
    and rebase merges, where the title has no "(#1234)" suffix)."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/commits/{sha}/pulls"
    resp = requests.get(url, headers=headers, timeout=30)
    if not resp.ok:
        message = resp.json().get("message", "") if resp.content else ""
        print(f"Warning: PR lookup for {sha[:7]} failed ({resp.status_code} {message}). "
              "GITHUB_TOKEN needs 'Pull requests: Read' permission.", file=sys.stderr)
        return None
    pulls = resp.json()
    merged = [p for p in pulls if p.get("merged_at")]
    candidates = merged or pulls
    return candidates[0] if candidates else None


def get_diff_prs(base_ref: str, head_ref: str) -> list[dict]:
    """Return the PRs between base_ref and head_ref, one entry per PR.
    Commits are resolved to their PR (from the squash-merge "(#1234)"
    title suffix, or via the GitHub API otherwise) and deduplicated, since
    the support channel references PRs, not commit SHAs."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        raise RuntimeError("GITHUB_TOKEN and GITHUB_REPO must be set")

    url = f"https://api.github.com/repos/{GITHUB_REPO}/compare/{base_ref}...{head_ref}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    items: dict[str, dict] = {}
    for c in data.get("commits", []):
        title = c["commit"]["message"].split("\n")[0]
        if is_automated_commit(title):
            continue

        pr_number = extract_pr_number_from_title(title)
        pr_title = PR_NUMBER_PATTERN.sub("", title).rstrip() if pr_number else title
        if not pr_number:
            pr = lookup_pr_for_commit(c["sha"], headers)
            if pr:
                pr_number = str(pr["number"])
                pr_title = pr["title"]

        # Fall back to the commit itself if GitHub reports no associated PR.
        key = pr_number or c["sha"]
        if key in items:
            items[key]["shas"].append(c["sha"])
            continue
        items[key] = {
            "title": pr_title,
            "shas": [c["sha"]],
            "url": (f"https://github.com/{GITHUB_REPO}/pull/{pr_number}"
                    if pr_number else c["html_url"]),
            "pr_number": pr_number,
        }
    return list(items.values())


def get_jira_status(ticket_key: str) -> dict:
    """Look up a Jira ticket's status. Informational only - never used
    to gate/block. Returns a dict with status or an error marker."""
    if not (JIRA_EMAIL and JIRA_TOKEN and JIRA_BASE):
        return {"error": "Jira credentials not configured"}

    auth_str = f"{JIRA_EMAIL}:{JIRA_TOKEN}"
    b64_auth = base64.b64encode(auth_str.encode()).decode()
    headers = {
        "Authorization": f"Basic {b64_auth}",
        "Accept": "application/json",
    }
    url = f"{JIRA_BASE}/rest/api/2/issue/{ticket_key}"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 404:
            return {"error": "lookup failed (404)"}
        resp.raise_for_status()
        data = resp.json()
        status = data["fields"]["status"]["name"]
        return {"status": status}
    except requests.RequestException as e:
        return {"error": f"lookup failed ({e})"}


TICKET_PREFIX_ORDER = ["AIPL", "RSAI"]


def pr_sort_key(pr: dict) -> tuple[int, int, str]:
    """Order: AIPL tickets, RSAI tickets, no ticket, then everything else;
    within a group, by Jira status (failed lookups last)."""
    ticket = pr["ticket"]
    if not ticket:
        group = len(TICKET_PREFIX_ORDER)
    else:
        prefix = ticket.split("-")[0]
        group = (TICKET_PREFIX_ORDER.index(prefix) if prefix in TICKET_PREFIX_ORDER
                 else len(TICKET_PREFIX_ORDER) + 1)
    status = (pr["jira_info"] or {}).get("status")
    return (group, 0 if status else 1, (status or "").lower())


def collect_support_check_list(prs: list[dict]) -> list[dict]:
    """Build the hand-off list of PR links for step 2 (support-channel
    check). This script makes NO Slack API calls - it just packages the
    links so a human, or an assistant/orchestrator with its own Slack
    access, can check them against the support channel afterward.
    """
    return [{"title": pr["title"],
             "ref": f"#{pr['pr_number']}" if pr["pr_number"] else pr["shas"][0][:7],
             "jira": pr.get("jira", "")}
            for pr in prs]


def build_release_check_report(old_version: str, new_version: str) -> str:
    """Assemble the final evidence report comparing old_version (currently
    in prod) against new_version (the release candidate). No verdict is
    produced.

    Support-channel matching is NOT done here (see module docstring,
    "Two-step approach") - this script only outputs the hand-off list
    of PR links at the end, for step 2 to check separately.
    """
    prs = get_diff_prs(old_version, new_version)
    for pr in prs:
        pr["ticket"] = extract_ticket_from_title(pr["title"])
        pr["jira_info"] = get_jira_status(pr["ticket"]) if pr["ticket"] else None
    prs.sort(key=pr_sort_key)

    lines = []
    lines.append(f"*Client PR Readiness Check* \u2014 `{old_version}` \u2192 `{new_version}`")
    lines.append("")

    for pr in prs:
        lines.append(f"\u2022 *{pr['title']}*")
        lines.append(f"   Link: <{pr['url']}>")

        ticket = pr["ticket"]
        if not ticket:
            pr["jira"] = "no Jira ticket"
            lines.append("   :warning: No Jira ticket found in title \u2014 *manual review needed*")
        else:
            jira_info = pr["jira_info"]
            if "error" in jira_info:
                pr["jira"] = f"{ticket}: {jira_info['error']}"
                lines.append(f"   Jira: {ticket} \u2014 {jira_info['error']}")
            else:
                pr["jira"] = f"{ticket}: {jira_info['status']}"
                lines.append(f"   Jira: {ticket} \u2014 status: *{jira_info['status']}* (info only, not a gate)")

        lines.append("")

    lines.append("_This report is informational only \u2014 no automated pass/fail verdict is produced._")
    lines.append("")

    # Step 2 hand-off: list of PR links to check against the support
    # channel. No Slack API call happens here - this is just the
    # packaged list for a human or an assistant with Slack access to
    # check afterward.
    check_list = collect_support_check_list(prs)
    channel_label = f"<#{SUPPORT_CHANNEL}>" if SUPPORT_CHANNEL else "the support channel"
    lines.append(f"*Step 2 \u2014 PRs to check against {channel_label}:*")
    for item in check_list:
        lines.append(f"   \u2022 {item['ref']}  [{item['jira']}]  ({item['title']})")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 3:
        print("Usage: python release_check_poc.py <old_version> <new_version>",
              file=sys.stderr)
        print("Warning: old_version/new_version not both provided explicitly - "
              "falling back to defaults, which may not produce a meaningful "
              "comparison.", file=sys.stderr)

    old_version = sys.argv[1] if len(sys.argv) > 1 else "main"
    new_version = sys.argv[2] if len(sys.argv) > 2 else "HEAD"

    report = build_release_check_report(old_version, new_version)
    print(report)


if __name__ == "__main__":
    main()