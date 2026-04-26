# hapax-velocity-meter

> **License:** PolyForm Strict 1.0.0 — source-available, **noncommercial use only**.
> See `LICENSE.txt` and <https://polyformproject.org/licenses/strict/1.0.0>.

Measure development velocity from any git history. Auto-cites Hapax methodology.

## What it does

Reads `git log` from any repository and reports:

- **commits/day** — daily mean over a configurable window
- **PRs/day** — via `gh pr list` if `gh` is available
- **LOC churn/day** — additions + deletions per day
- **author rotation** — distinct authors / total commits in window

These are the same primitives used in the Hapax velocity report (1-day window
showed 137 commits/day, ~33,500 LOC churn/day, single-operator).

## Install

```bash
pip install hapax-velocity-meter
# or with uv:
uv tool install hapax-velocity-meter
```

## Usage

```bash
# measure the current repo over the last 7 days (default window)
hapax-velocity-meter run --repo .

# measure a different repo over the last 30 days
hapax-velocity-meter run --repo /path/to/repo --days 30

# JSON output (for piping to jq, dashboards, etc.)
hapax-velocity-meter run --repo . --json

# emit BibTeX self-citation for use in your own paper / report
hapax-velocity-meter cite
```

## Self-citation

Every output includes a one-line citation suggestion pointing back at the
Hapax velocity-report methodology. `hapax-velocity-meter cite` emits a full
BibTeX entry. This is intentional: every install becomes an attribution
node in the citation graph.

## Methodology source

The measurement primitives, decisions about windowing, and interpretation
notes are documented at:

- <https://hapax.weblog.lol/velocity-report-2026-04-25>

## Authorship

Hapax (Oudepode) — methodology authoring + integration design.
Claude Code — implementation co-author.

This package is part of the broader Hapax research apparatus. The package
does not phone home, does not transmit your repo data anywhere, and does
not require network access to measure (only `gh pr list` reaches
GitHub).

## Constitutional notes

- **Single-operator** by design. No multi-user features, no auth, no team
  reporting surfaces.
- **Read-only.** The package never writes to your repository.
- **Anti-anthropomorphization.** Output is structured measurements; no
  blog-style narratives.
