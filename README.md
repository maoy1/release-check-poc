Release Automation Proposal
This canvas was generated using AI, which can produce inaccurate or harmful responses. Review for accuracy and safety before using.

Summary

We release once or twice a week, and each release requires a release owner to collect information, coordinate confirmations, start or monitor jobs, check the deployed service, and post status updates. Most of this work is repetitive coordination and watching rather than engineering judgment.
We propose a Slack-based release workflow that keeps the existing release thread and human approval model, while automating the information gathering, status updates, health checks, and final summary. The first version should be a small pilot that runs alongside real releases and can be expanded after we understand the operational edge cases.

Problem

The current release process repeatedly requires someone to:

* post a planned-release message
* compare staging and production and copy the ticket list from Jira
* contact client teams for readiness confirmation
* inspect the regression run
* open Jenkins and locate the deployment job
* monitor the deployment while it runs
* check the health endpoint or New Relic after deployment
* find and share the sanity-test link and monitor its result
* post the final release status

These tasks are individually simple but consume attention during the release window and are easy to perform inconsistently under time pressure. We have also seen a real release incident where a merge to main introduced untested tickets and required a rollback to a prior known-good tag. Around the same period, sanity results were also suspected to be flaky due to an unrelated service issue, independent of the release itself — a reminder that "sanity failed" and "release is unsafe" are not always the same thing, and the automation needs to distinguish them rather than treat every failed check identically.
We have also had cases where regression failed but the team still needed to ship a specific version, and made a deliberate, human decision to proceed anyway. In addition, production deployment is being moved off the main pipeline entirely — prod deploys must go through the dedicated release pipeline going forward. Both points affect what the automation should assume: a failed check should stop automatic progression and ask a human, not silently block or silently override, and the bot should always point at the release pipeline's Jenkins job specifically, not the main build.
A separate but related pain point: it is not always clear which version can safely be released, because a version can contain a client PR that has not been confirmed release-ready by that client team. Client PRs are typically raised as tickets in the support channel, and someone has to manually find the PR, find which client it belongs to, and ask whether it is safe to release — complicated further by the fact that a person's Slack identity and their GitHub identity are not reliably the same, making automatic matching by person unreliable. This needs its own handling in addition to the Jira/regression readiness checks.
A generated readiness report could make the staging vs. production difference and other known signals visible before release approval. The automation would reduce coordination toil; it would not by itself guarantee that an untested change cannot enter a release.

Goals and non-goals

Goals

* Reduce manual information gathering and release-status posting
* Make the release state and relevant evidence visible in one Slack thread
* Preserve explicit human approval before deployment
* Make failures stop clearly and return control to a human
* Create a repeatable release record that can be reviewed afterwards
* Surface, before approval, any client PR in the release that has not been confirmed release-ready by its client team

Non-goals

* Automatically deciding whether a release is safe
* Automatically deploying immediately after a readiness report
* Automatically retrying failed checks without an explicit policy
* Automatically rolling back a release
* Replacing client-team ownership of their readiness decisions
* Automatically matching people across Slack and GitHub identities

Proposed workflow

1. A team member posts the usual kickoff message, for example: :threadparrot: Planned Release v5.0.4
2. Slack Workflow Builder starts the workflow from the release kickoff message and passes the release version and thread context to the backend service.
3. The bot posts a readiness report containing, where available: the staging/production version or commit difference; the associated Jira tickets and their current status; regression-test status; any client PR included in this version that has not been confirmed release-ready by its client team (see Client PR Readiness Gate below); known missing or inconsistent information; and links to the underlying sources.
4. The designated release owner reviews the report and confirms readiness using an explicit approval action. The bot records the approver, timestamp, release version, and thread before continuing. If regression, a client PR gate, or another check is failing, the owner can still approve explicitly with a stated reason — this is recorded as an override, not hidden or treated as if the check had passed.
5. After approval, the bot posts the relevant Jenkins deployment link, scoped to the dedicated release pipeline (not the main build pipeline, which is being removed from the prod-deploy path). The release owner still deliberately starts the deployment through Jenkins.
6. The bot monitors the Jenkins job and posts state changes such as queued, running, succeeded, failed, or timed out.
7. After a successful deployment, the bot checks the health endpoint and reports the observed version and result. This reduces the need to inspect EKS or New Relic manually for the basic deployment confirmation.
8. The bot posts the sanity-test link and reports the test result when available.
9. The bot posts a final summary containing the release version, approval record (including any explicit override and its stated reason), deployment result, observed health-check result, sanity-test result, client PR gate status, and links to the relevant evidence.

All status and result messages remain in the release thread so that the process is visible to the team. The bot must clearly distinguish a successful check from an unavailable, incomplete, or explicitly overridden check.

POC Scope (Building Now)

Trigger: manual, private only — a DM to the bot or an equivalent private query. No public channel post, no workflow trigger tied to release kickoff messages yet.
What it does, on demand, for the latest staging-vs-prod diff:

1. Diff current latest version (staging) against production using the existing GitHub compare logic.
2. For each commit/PR in that diff, check the PR title for a Jira ticket number — this is the required convention for all PRs.
    1. No ticket number found in the title → flag as needing manual review and notify the requester directly; do not attempt to guess or classify the PR further.
    2. Ticket number found → look up and show its Jira status as information only. Ticket status is not used to block anything in this POC, since ticket status has never been part of the team's actual release-gating process.
3. Separately, for each PR found, search the support channel for a message containing that PR's link (matched by URL, not by person) and if found, surface the Slack thread so the requester can read the client conversation directly.
4. Reply privately (DM) with the full list: every PR in the diff, its Jira ticket + status if present, a manual-review flag if no ticket number was found, and a link to the matching support-channel thread if one exists.

What this POC deliberately does not do:

* No reaction prompts posted to new support tickets.
* No structured "ready to release" / "hold" signal capture.
* No public message anywhere — DM only.
* No blocking verdict — it assembles evidence; the requester still decides.
* No release-version state tracking between calls; each call is a fresh on-demand lookup against the current latest version.

This POC is a stepping stone toward the full Client PR Readiness Gate below, which remains the next planned build.

Client PR Readiness Gate

This addresses the "which version can actually be released" pain point directly.

Problem in more detail

Client PRs are raised in the support channel as review/merge tickets, tagged to a business unit or client team, with a GitHub PR link in the thread. Approval of the code (a reviewer says LGTM) and confirmation that it is safe to release are currently conflated — there is no structured signal for the second one. When a version is being prepared, someone has to manually search the support channel, find the relevant PR thread, and ask the client team directly whether it is safe to include, or whether the release should roll back that change. This is slow, easy to miss, and complicated by Slack-to-GitHub identity mismatches.

Proposed POC

Since this signal does not exist today, build it as part of this POC rather than assuming client teams already provide it.

1. Capture the signal early, at ticket creation. When a PR review/merge ticket is posted in the support channel, the bot posts a follow-up prompt in the same thread asking the client team to confirm, once the PR is approved, whether it is release-ready: :white_check_mark: = ready to release, :no_entry: = hold, do not release yet. This captures the decision while the client team is already engaged with the ticket, without needing to map Slack identities to GitHub identities — the confirmation happens natively in Slack, by whoever is on the thread.
2. Match by PR link, not by person, when cross-referencing the release diff against open client PR tickets — matching on the PR URL/number is reliable; matching on person is not, given the identity mismatch.
3. If no signal exists yet at release time (ticket predates this change, or nobody has reacted), the release-readiness report should say so explicitly and the bot should proactively ask the client team in the original ticket thread, rather than the release owner having to track it down manually.
4. If a client team responds "hold" — either via the reaction or by replying directly in the ticket thread when asked — the readiness report must show this clearly as a blocking flag, not a soft warning. The release owner can still choose to override it explicitly with a stated reason (for example, if the client later confirms verbally that it is fine, or the PR is dropped from the version), but the override and its reason must be recorded the same way as a regression override, never silently treated as approval.
5. Scope of the signal: a reaction means "ready whenever this ships next," not tied to one specific release version, to avoid ambiguity. A client team asking to hold a specific version specifically is treated as an explicit hold for that release only.

Why build this now rather than defer it

This gap matters as much as the Jenkins/Jira readiness work, since "which version can be released" is blocked on this today, not just made less convenient. Building a first version alongside the main POC — even a simple reaction-based signal plus a link-based match — replaces a fully manual, easy-to-miss lookup with a visible, recorded flag before approval.

Human control and safety constraints

* Only an explicitly designated release owner can approve the release.
* Approval applies to one specific release version and thread.
* Approval does not trigger deployment automatically; the owner starts the Jenkins job deliberately.
* Any failed, timed-out, unavailable, inconsistent, or unconfirmed client-PR check stops the automated progression and reports the issue in the thread.
* A human decides whether to investigate, continue, postpone, roll back, ask the client team, or explicitly override a specific failing check with a stated reason.
* The bot must not silently retry a failed check, silently treat an override as a pass, silently treat "no response yet" from a client team as approval, or create duplicate deployment actions.
* Every action and result should be traceable to the release thread and its underlying source link.

MVP scope

The initial pilot should focus on the highest-value, lowest-risk steps:

1. Start from the existing planned-release message.
2. Generate and post the readiness report.
3. Include a first version of the client PR readiness gate: prompt for the release-ready reaction on new PR review tickets, and match open/hold PRs against the release diff by PR link.
4. Post the Jenkins deployment link (release pipeline only) after explicit human approval, including support for a recorded override if a check is failing.
5. Monitor and report Jenkins status.
6. Post a final deployment summary, including client PR gate status.

Health-endpoint verification and sanity-test monitoring can be added in the next phase after the basic workflow has been used successfully.

Architecture

Team member posts planned-release message
                    |
                    v
        Slack Workflow Builder
       (keyword/message trigger)
                    |
                    v
             Backend service
       (release state and actions)
     /        |         |         \
    v         v         v          v
 GitHub     Jira     Jenkins    Support channel
                    (release      (client PR
                     pipeline      tickets +
                     only)         release-ready
                                   reactions)
     \        |         |         /
      v       v         v        v
      Readiness report and status data
                    |
                    v
             Slack release thread

The backend can be implemented as a small AWS Lambda service — a working proof-of-concept already exists (keyword-triggered webhook, version parsing, GitHub/Jira lookups, report formatting) and can be extended rather than built from scratch. It was sanity-checked against real release messages from the channel and works correctly, though it currently uses placeholder values for the GitHub repo and Jira instance, and should be pointed at the actual AIPL Jira project key before use. The client PR gate is new work on top of this and will need to read messages/reactions from the support channel in addition to GitHub, Jira, and Jenkins.
The backend needs to retain enough state to associate each event with one release version and Slack thread, and to associate each client PR ticket with its release-ready status independent of any specific release. Monitoring should resume safely after an individual request finishes rather than relying on one request remaining open until Jenkins or the sanity test completes. The exact mechanism — such as an existing scheduler, workflow engine, queue, or other durable job mechanism — should be confirmed during implementation. It must support retries without duplicate messages or actions.
The integration should use the minimum access required for Jira, GitHub, Jenkins, AWS, and Slack. Credentials should remain in the approved secret store and should not be posted to Slack.

Failure scenarios to handle

The pilot should define and test behavior for at least these cases:

* the kickoff message has no version or an invalid version
* one source system is unavailable
* the readiness report is incomplete
* a release with the same version is started twice
* two releases are active at the same time
* Jenkins is queued for an unusually long time
* the deployment fails or times out
* the deployment succeeds but the health check reports the wrong version
* the sanity test fails or does not return a result
* the sanity test fails for reasons unrelated to the release itself (e.g. an external service issue), and the owner needs to record an explicit override rather than being blocked indefinitely
* regression is failing but the owner has a deliberate reason to proceed anyway, and needs that decision recorded rather than hidden
* a client PR included in the version has no release-ready signal yet, and the bot needs to flag it and prompt the client team rather than assuming it is safe
* a client team explicitly responds "hold" on a PR included in the version, and the release owner must see this as a blocking flag, not a soft note
* the bot receives a duplicate event or restarts while monitoring

In each case, the expected behavior is to report the known state, link to the source where possible, avoid taking an irreversible action, and hand the next decision back to the release owner.

Success criteria for the pilot

Run the workflow alongside three real releases and compare it with the current process. The pilot is successful if it:

* removes most manual preparation and status-posting work
* keeps all release decisions with the designated release owner
* produces one readable release record in Slack, including any overrides and their stated reasons
* surfaces every client PR in the release diff with its confirmation status, without the release owner having to search for it manually
* does not create duplicate or misleading release actions
* makes incomplete, failed, or overridden checks visible rather than hiding them
* gives us enough evidence to decide whether health and sanity-test automation should be added

Where practical, record the approximate time spent by the release owner before and during the pilot, along with issues discovered and any manual steps that remain necessary.

Initial estimate

Existing readiness-report scripts and Lambda/webhook scaffolding can provide a starting point. The estimate below is for planning only and should be refined after confirming the available APIs and the durable monitoring mechanism.

Piece
	Work
	Initial estimate

Readiness report
	Polish existing script, error handling, project keys, and links
	2–4 hrs

Slack workflow
	Kickoff trigger, thread context, and message formatting
	1–3 hrs

Approval and release state
	Designated approver, state transitions, override recording, duplicate protection
	3–7 hrs

Client PR readiness gate
	Ticket-creation prompt, reaction capture, PR-link matching against release diff, hold handling
	6–10 hrs

Jenkins integration
	Post release-pipeline job link and report status changes
	3–6 hrs

Final summary
	Compile release evidence and outcome, including PR gate status
	1–2 hrs

Pilot testing
	Run alongside a real release and fix edge cases
	3–6 hrs

MVP total
	
	~19–38 hrs


Health checks and sanity-test monitoring should be estimated separately after the MVP exposes the actual API, timing, and failure-handling requirements.

Open decisions

* What is the designated release-owner approval action?
* Which users or role are authorized to approve a release?
* What is the canonical source for the staging/production difference and release ticket list?
* Which status changes are useful enough to post, rather than creating noise?
* What timeout should cause monitoring to stop and notify the release owner?
* Should a failed sanity test always stop the process, or can the owner explicitly mark it as accepted with a reason? What is required for that record (reason text, approver identity, both)?
* Which existing platform component should provide durable monitoring state?
* Should the client PR readiness gate apply to all support tickets, or only ones tagged as PR review/merge requests?
* Who on the client side is allowed to give the release-ready reaction, or respond "hold" — anyone on the thread, or a specific role?
* If a client PR has no response at all by release time, should that block approval by default, or only show as an open flag the owner can override?
* After the pilot, should health checks and sanity-test monitoring be added to the same workflow?

Recommendation

Build the MVP — including a first version of the client PR readiness gate — as a low-risk assistant to the existing release process, run it in parallel with three releases, and use the results to decide which additional steps are safe and valuable to automate. This should reduce late release work and close the "which version can be released" gap, without changing accountability or weakening the team's release controls.
