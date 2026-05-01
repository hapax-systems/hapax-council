---
title: Stakeholder revenue brief automation durability review
date: 2026-04-30
status: decided
task_id: stakeholder-revenue-brief-automation-durability-review
decision: operator-triggered-tool
tags:
  - hapax/audit
  - stakeholder
  - revenue
  - mailer
---

# Stakeholder Revenue Brief Automation Durability Review

## Decision

Do not ship the preserved daily systemd timer. The durable form is an
operator-triggered tool that generates a DOCX by default and sends only when
called with `--send` plus configured sender and recipient addresses.

## Rationale

External stakeholder email is not routine internal synchronization. A daily
timer would create unsolicited outbound communication from a protected research
lane's unreviewed dirty state, and the preserved implementation defaulted to
sending with embedded addresses. That is too much authority for unattended
automation.

The committed tool keeps the useful pieces: source brief rendering, DOCX
generation, change summary, recent-send suppression, Gmail credential
verification, source frontmatter update, and state snapshots. It removes the
risky pieces: no systemd unit, no default send path, no hardcoded recipients,
and no repo-local generated artifacts.

## Durable Channel

- Command: `uv run python scripts/send-stakeholder-revenue-brief.py`
- Default behavior: generate markdown and DOCX only.
- Send behavior: requires `--send`, a configured sender, and at least one
  configured recipient.
- Configuration: CLI args or `HAPAX_STAKEHOLDER_REVENUE_BRIEF_*` environment
  variables.
- Outputs: generated documents go to the vault brief directory; send state goes
  to `~/.local/state/hapax/stakeholder-revenue-brief/`.

## Explicit Non-Actions

- The preserved `hapax-stakeholder-revenue-brief.service` and `.timer` from
  `cx-violet` were not committed.
- No email was sent during this review.
- The protected `cx-violet` worktree was read for evidence only.
- Root-level OpenAI fellowship scrape artifacts remain preserved in `cx-violet`
  pending a parent cleanup decision; they were not committed as repo source.
