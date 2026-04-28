---
type: research-drop
date: 2026-04-28
title: Velocity Report Evidence Baseline Reconciliation
status: shaped
related:
  - docs/research/2026-04-25-velocity-comparison.md
  - docs/research/2026-04-28-velocity-report-audit-coverage-gap.md
  - ~/Documents/Personal/30-areas/hapax/velocity-report-2026-04-25.md
---

# Velocity Report Evidence Baseline Reconciliation

## Summary

The velocity weblog artifact is live and backed by local publication state:

- URL: `https://hapax.weblog.lol/velocity-report-2026-04-25`
- Local source: `~/Documents/Personal/30-areas/hapax/velocity-report-2026-04-25.md`
- Publish state: `~/hapax-state/publish/published/velocity-report-2026-04-25.json`
- Publish log: `~/hapax-state/publish/log/velocity-report-2026-04-25.omg-weblog.json`

The 2026-04-28 audit found a real evidence gap: the original report did not
persist the exact command transcript, window boundary, or raw aggregate output
for the headline quantitative values. Current local git history partially
reproduces the claim family, but not all headline values in one exact 18-hour
window.

## Identifier State

Local state as of 2026-04-28:

- `publish/published/velocity-report-2026-04-25.json` has `doi: null`.
- `surfaces_targeted` for the weblog artifact is `["omg-weblog"]`.
- `packages/hapax-velocity-meter/CITATION.cff` still carries `arXiv:TBD`,
  `10.5281/zenodo.TBD`, and `swh:1:rev:TBD` placeholders.
- No velocity-specific arXiv ID, Zenodo DOI, or SWHID state file was found
  under `~/hapax-state` during this audit.

The public report was corrected on 2026-04-28 to state that DOI, SWHID, arXiv,
and ORCID-update rails are pending follow-on artifacts, not already minted
evidence.

## Reconstruction Commands

Repository set from the report:

- `~/projects/hapax-council`
- `~/projects/hapax-officium`
- `~/projects/hapax-mcp`
- `~/projects/hapax-watch`
- `~/projects/hapax-phone`
- `~/projects/hapax-constitution`

Civil-day current-branch reconstruction:

```bash
git -C "$repo" log \
  --since='2026-04-25 00:00:00 -0500' \
  --until='2026-04-25 23:59:59 -0500' \
  --pretty='%cI %h %s' | wc -l

git -C "$repo" log \
  --since='2026-04-25 00:00:00 -0500' \
  --until='2026-04-25 23:59:59 -0500' \
  --numstat --pretty=format: |
  awk 'NF==3 && $1 ~ /^[0-9]+$/ && $2 ~ /^[0-9]+$/ {a+=$1; d+=$2} END {print a+0,d+0,a+d}'
```

Observed totals across the six local repos:

| Window | Ref Mode | Commits | Additions | Deletions | Churn |
|---|---:|---:|---:|---:|---:|
| 2026-04-25 00:00-23:59 -0500 | current branches | 166 | 61,425 | 767 | 62,192 |
| 2026-04-25 00:00-23:59 -0500 | all refs | 178 | 70,142 | 798 | 70,940 |

Hourly 18-hour current-branch reconstruction:

| Window Start -0500 | Window End -0500 | Commits | Churn |
|---|---|---:|---:|
| 2026-04-25 00:00 | 2026-04-25 18:00 | 111 | 33,767 |
| 2026-04-25 01:00 | 2026-04-25 19:00 | 110 | 33,261 |
| 2026-04-25 02:00 | 2026-04-25 20:00 | 102 | 29,791 |
| 2026-04-25 03:00 | 2026-04-25 21:00 | 101 | 29,839 |
| 2026-04-25 04:00 | 2026-04-25 22:00 | 119 | 46,218 |
| 2026-04-25 05:00 | 2026-04-25 23:00 | 134 | 52,032 |
| 2026-04-25 06:00 | 2026-04-26 00:00 | 143 | 54,196 |
| 2026-04-25 07:00 | 2026-04-26 01:00 | 151 | 56,672 |
| 2026-04-25 08:00 | 2026-04-26 02:00 | 160 | 60,340 |
| 2026-04-25 09:00 | 2026-04-26 03:00 | 168 | 64,761 |

Minute-level current-branch spot check around the 137-commit boundary:

| Window Start -0500 | Window End -0500 | Commits | Churn |
|---|---|---:|---:|
| 2026-04-25 05:21 | 2026-04-25 23:21 | 136 | 52,252 |
| 2026-04-25 05:27 | 2026-04-25 23:27 | 137 | 52,368 |
| 2026-04-25 05:28 | 2026-04-25 23:28 | 138 | 52,951 |

## Interpretation

The weblog baseline is valid as a published, attributable methodology note. The
headline quantitative values should not be treated as formal reproducibility
outputs until a follow-up records:

- exact window boundaries
- ref mode (`HEAD`, `origin/main`, or `--all`)
- repo list and commit SHAs
- PR query and result set
- research-drop count query
- REFUSED-status aggregate query
- CI first-attempt pass-rate query
- raw output files and tool versions

Until that follow-up lands, downstream public-growth work must cite the weblog
with the 2026-04-28 correction note rather than presenting the numbers as a
fully reproduced benchmark.
