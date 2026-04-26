# Refusal Brief: Public Dashboards as Marketing

**Slug:** `awareness-refused-public-marketing-dashboards`
**Axiom tag:** `feedback_full_automation_or_no_engagement`, `project_academic_spectacle_strategy`, `feedback_co_publishing_auto_only_unsettled_contribution`
**Refusal classification:** Anti-pattern #7 (drop-6 §10) — marketing-shaped scrutiny surface
**Status:** REFUSED — no Grafana public dashboard, no embed-in-website real-time stats, no Twitch dashboard widget.
**Date:** 2026-04-26
**Related cc-task:** `awareness-refused-public-marketing-dashboards`
**Sibling refusal-briefs:**
  - `awareness-acknowledge-affordances.md`
  - `awareness-additional-affordances.md`
  - `awareness-aggregation-api.md`

## What was refused

- Public-facing real-time Grafana dashboards
- "Watch Hapax in real-time" embed widgets on operator's homepage / weblog
- Twitch / YouTube dashboard overlay surfacing live awareness state
- Public Prometheus exporter scrape endpoint accessible from internet
- Static-site generators that render aggregated awareness data into
  marketing pages
- Any "demo this capability" interactive surface targeted at public
  audience consumption

## Why this is refused

### Audience-relationship-implies-maintenance

Per `feedback_full_automation_or_no_engagement` (operator
constitutional directive 2026-04-25T16:55Z): any public-facing
surface implying "scrutinize-able capability demo" creates an
audience-relationship that implies ongoing operator-physical
maintenance:

- Visitors expecting freshness → operator pressure to maintain uptime
- Visitors filing dashboard-bug reports → operator-physical triage
- Visitors asking "what does this metric mean?" → operator-physical
  documentation maintenance
- Marketing-surface degradation = perceived project decline → operator
  pressure to over-invest in surface polish

The constitutional posture forecloses these maintenance loops.

### Academic-spectacle, not marketing-spectacle

Per `project_academic_spectacle_strategy` (2026-04-25 directive):
academic outreach is via the livestream (`project_livestream_is_research`)
+ DataCite citation graph + refusal-as-data substrate, NOT via
marketing surfaces. The livestream's spectacle/disorientation
character is the engagement vector; a glossy dashboard would
contradict that character.

### Authorship indeterminacy collapse

Per `feedback_co_publishing_auto_only_unsettled_contribution`
(2026-04-25 directive): operator's unsettled contribution is a
celebrated feature; authorship indeterminacy is the 7th polysemic-
surface channel. Dashboards-as-marketing implicitly attribute
"capability" to the system as a discrete agent — collapsing the
authorship indeterminacy.

### Anti-anthropomorphization

Marketing dashboards anthropomorphize the system as a "demonstrable
agent." Hapax is constitutionally signal-density-on-a-grid, not a
trying-to-trend product. Per drop-3 anti-pattern §10 (the parent
pattern of this refusal): pinned repos / marketing surfaces are the
"trying to trend" affordance refused across the workspace.

## Daemon-tractable boundary

The ONE authorized public ambient awareness surface is:

- **omg.lol statuslog** (per `awareness-omg-lol-public-safe-filter.md`,
  offered cc-task; depends on awareness-state-stream-canonical) —
  intentionally low-fidelity, public-safe-filtered subset of awareness
  state, fanned out to operator's omg.lol address. Inherits omg.lol's
  text-based constraints (no real-time charts, no interactive
  affordances).

That surface is not refused because it's structurally low-fidelity
and inherits omg.lol's bounded engagement model (read, no reply
surface, no interactivity). It's an ambient-pulse pattern, not a
marketing-dashboard pattern.

## Refused implementation

- NO `grafana/dashboards/public-*.json`
- NO `nginx` reverse-proxy exposing internal Prometheus to public
- NO embed JavaScript on `hapax.weblog.lol` rendering real-time stats
- NO Twitch panel pulling live awareness data
- NO `awareness/marketing_renderer/` package
- NO scheduled job that publishes static dashboard pages

## Lift conditions

This is a constitutional refusal grounded in three directives. Lift
requires retirement of any of:

- `feedback_full_automation_or_no_engagement`
- `project_academic_spectacle_strategy`
- `feedback_co_publishing_auto_only_unsettled_contribution`

Probe path for all three: `~/.claude/projects/-home-hapax-projects/memory/MEMORY.md`.

The `refused-lifecycle-constitutional-watcher` daemon (when shipped)
will check the probe per its cadence policy.

## Cross-references

- cc-task vault note: `awareness-refused-public-marketing-dashboards.md`
- Authorized public ambient: `awareness-omg-lol-public-safe-filter.md`
- Sibling refusals: `awareness-aggregation-api.md`,
  `awareness-acknowledge-affordances.md`,
  `awareness-additional-affordances.md`
- Companion refusal: `repo-pres-pinned-repos-removal.md` (pinned
  repos = trying-to-trend affordance, same anti-pattern)
- Source research: drop-6 §10 anti-pattern #7
