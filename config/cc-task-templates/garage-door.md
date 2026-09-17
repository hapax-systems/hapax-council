---
type: cc-task
task_id: <artifact>-garage-door-<YYYYMMDD>
title: "<one thing, one line, one minute — the artifact and the door it ships through>"
status: offered
assigned_to: unassigned
claimable: true
blocked_reason: null
priority: p1
wsjf: 0.0
effort_class: medium
kind: engineering            # becomes `contribution` automatically when prior art is BACKED and usable
risk_tier: T1
mutation_surface: source
quality_floor: frontier_review_required
authority_level: support_non_authoritative
authority_case: CASE-CAPACITY-ROUTING-001
parent_spec: 30-areas/hapax/frame/coordination-20260904/ADOPTABILITY-DETERMINATION-20260916.md
route_metadata_schema: 1
stage: S1_OFFERED
tags: [cc-task, garage-door]
# ── adoptability block: required on every `garage-door` row (A5); the stage gate
# reads the two receipts (A2); the release gate reads `receipt` and scans the
# install surface for estate nouns (A1/A3/A4). Receipt paths resolve under the vault
# root (~/Documents/Personal) — see docs/governance/adoptability-teeth.md.
adoptability:
  prior_art_receipt: 20-projects/hapax-cc-tasks/_evidence/adoptability/<artifact>/prior-art.yaml
  demand_receipt: 20-projects/hapax-cc-tasks/_evidence/adoptability/<artifact>/demand.yaml
  install_line: "curl -fsSL https://<host>/<artifact>/install.sh | sh"   # (i) signed one-liner; brew/mise/nix too
  platforms: [linux, macos, windows]                                     # (i)
  zero_config: true                                                      # (ii) detects what is present
  ttfv_seconds: 60                                                       # (iii) measured budget, blank VM
  replaces_nothing: true                                                 # (iv) works inside what is already used
  api: "cli + unix socket"                                               # (v) another tool can consume it
  licence: Apache-2.0                                                    # (vii) Apache-2.0 or MIT
  repo_open: <owner>/<artifact>                                          # (vii) public, issues + PRs open
  release_notes: https://github.com/<owner>/<artifact>/releases          # (viii) named releases, notes, cadence
  compare_page: https://<host>/<artifact>/compare                        # (vi) names its one sorting row
  operator_voice_post: https://<weblog>/<why-it-exists>                  # (ix) via the publication bus
  receipt: 20-projects/hapax-cc-tasks/_evidence/adoptability/<artifact>/adoptability.json   # written by scripts/hapax-adoptability-receipt
---

## Why

<Who asked, in their words, and where. The demand receipt carries the evidence.>

## Prior art

<Two differently-shaped searches and their verdict. BACKED (tier, source) and usable ⇒
this row is a contribution to the existing artifact, not a competitor.>

## Exit predicate

<The nine A3 checks measured by `scripts/hapax-adoptability-receipt`, and the release
that passed them.>

## Session log

- <YYYY-MM-DDTHH:MM:SSZ> — minted from config/cc-task-templates/garage-door.md
