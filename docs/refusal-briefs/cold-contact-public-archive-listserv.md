# Refusal Brief: Public-Archive Listserv Participation

**Slug:** `cold-contact-public-archive-listserv`
**Axiom tag:** `feedback_full_automation_or_no_engagement`, `single_user`
**Refusal classification:** Operator-mediated reply not daemon-tractable
**Status:** REFUSED — no listserv subscriptions for outbound posting; no `agents/listserv_poster/`.
**Date:** 2026-04-26
**Related cc-task:** `cold-contact-public-archive-listserv`
**Sibling tasks:**
  - `leverage-mktg-listserv-thematic-participation` (publish-only path; offered, depends on mail-monitor)

## What was refused

- Daemon subscription to public-archive listservs (empyre, sc-users-archive, MSR threads, etc.) for the purpose of outbound posting + reply-thread participation
- `agents/listserv_poster/` package
- Reply-thread engagement on any listserv where Hapax has posted
- Per-post operator-approval gating (the trial-period anti-pattern)

## Why this is refused

### Operator-mediated reply problem

Listservs are conversational threads. Once Hapax posts, replies arrive
by email. Daemon-side reply composition + send is contemplated, but a
single human reply triggers operator-mediated thread management:

- "Did you mean X?" — requires operator interpretation
- "I disagree because Y" — requires operator-physical engagement
- "Tell me more about Z" — requires operator-physical follow-up
- Off-list private mail prompted by an on-list post — requires
  operator-physical disposition

The constitutional envelope cannot hold across reply branches. Each
reply is a forking path; daemon-only handling either ignores the
forks (rude / unprofessional) or forwards to operator-physical
attention (violates full-automation).

### Constitutional incompatibility

Per `feedback_full_automation_or_no_engagement` (operator
constitutional directive 2026-04-25T16:55Z): the operator refuses
research / engagement surfaces not fully Hapax-automated. The
original drop-2 §3 mechanic #2 design required operator-approval
gating on every drafted post — that's the trial-period
anti-pattern itself.

### Difference from the publish-only sibling

`leverage-mktg-listserv-thematic-participation` is a separate
cc-task with a publish-only contract: daemon posts thematic
content on a cadence; daemon NEVER replies; replies arrive via
mail-monitor's standard category dispatch. That contract
structurally precludes operator-mediated reply by routing replies
through the existing mail-monitor classifier (they get treated as
cold-contact replies, not as listserv threads).

This refusal-brief covers the **non-publish-only** posture:
two-way listserv participation. The publish-only path remains
offered (depends on mail-monitor 006/007) and is the
daemon-tractable replacement.

## Daemon-tractable boundary

Authorized inbound listserv handling:
- **Mail-monitor classifier-and-dispatch** treats listserv mail as
  cold-contact replies; daemon files to vault per category
  disposition

Authorized outbound listserv interaction:
- **None** in this refusal-brief's scope. The publish-only sibling
  (when shipped) is the path; this brief refuses two-way
  participation.

## Refused implementation

- NO `agents/listserv_poster/` for two-way listserv engagement
- NO daemon subscription to listservs solely for outbound posting
- NO operator-approval-gate on drafted posts
- NO reply-composition logic in any listserv-adjacent module

## Lift conditions

This is a constitutional refusal. Lift requires removal of
`feedback_full_automation_or_no_engagement` from MEMORY.md. Probe
path: `~/.claude/projects/-home-hapax-projects/memory/MEMORY.md`.
Lift keyword: absence of the
`feedback_full_automation_or_no_engagement` entry.

The `refused-lifecycle-constitutional-watcher` daemon (when shipped)
will check this probe per its cadence policy.

## Cross-references

- cc-task vault note: `cold-contact-public-archive-listserv.md`
- Publish-only sibling: `leverage-mktg-listserv-thematic-participation.md`
- Mail-monitor classifier: `agents/mail_monitor/processors/`
- Source research: drop-2 §3 mechanic #2 (originally proposed,
  now-refused)
- Constitutional reference: `feedback_full_automation_or_no_engagement`
  (2026-04-25)
