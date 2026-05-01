# OMG weblog + RSS public-event adapter reconcile (2026-05-01)

**cc-task:** `omg-weblog-rss-public-event-adapter` (P2, WSJF 6.0)
**Author:** epsilon
**Source audit:** `~/Documents/Personal/20-projects/hapax-research/audits/2026-04-28-cross-surface-reality-reconcile.md`
**Parent spec:** `~/Documents/Personal/20-projects/hapax-research/specs/2026-04-28-livestream-research-vehicle-suitcase-parent-spec.md`

## Premise

The cross-surface reality reconcile audit (`2026-04-28-cross-surface-reality-reconcile.md`) flagged that the omg-lol-weblog-and-RSS chain has three distinct surfaces that are routinely conflated in task notes and public claims:

1. **Operator-approved weblog publication** through `agents/omg_weblog_publisher/publisher.py` driven by `PreprintArtifact` dispatch — *active, mounted, claimable as live.*
2. **RSS health validation** through `agents/self_federate/rss_validator.py` (weekly `hapax-self-federate-rss.timer`, Sun 03:00 UTC) — *active; Phase 2 ntfy-on-validity-loss merged in PR #1954.*
3. **Cross-weblog RSS fanout** through `agents/publication_bus/omg_rss_fanout.py` — *library implemented; **explicitly not-live** because `config/omg-lol-fanout.yaml::addresses` is empty by default and no event listener has been wired to consume `omg.weblog` events into fanout calls.*

This document settles the public-claim rules and mounts the missing monthly composer timer. The RSS fanout is left explicitly not-live to honor the audit's "no false claims" rule.

## What's mounted, what's marked not-live

### Mounted (this PR)

`systemd/units/hapax-omg-weblog-composer.{service,timer}` — Monthly oneshot at first-of-month 09:00 UTC. Runs `python -m agents.omg_weblog_composer`; produces a draft skeleton in `~/hapax-state/weblog-drafts/<YYYY-MM-DD>.md` with `approved: false` frontmatter. The operator flips `approved: true` to release the draft into the publication-bus inbox via the orchestrator's existing path (`scripts/publish_vault_artifact.py`).

This closes the audit's "composer timer missing" gap without changing any active publication path. No new credentials, no new auth surface.

### Explicitly not-live

`agents/publication_bus/omg_rss_fanout.py` — the library is shipped but there is no listener wired to consume `omg.weblog` events into per-target fanout calls, and `config/omg-lol-fanout.yaml::addresses` is `[]` by default. Per the audit's public-claim rule, RSS fanout cannot be claimed live until ALL of the following are true:

- [ ] `config/omg-lol-fanout.yaml::addresses` lists at least one operator-owned omg.lol target distinct from the source.
- [ ] A systemd unit + listener exists that converts `omg.weblog` events from the canonical `ResearchVehiclePublicEvent` JSONL stream into `omg_rss_fanout` calls.
- [ ] Operator-owned bearer-tokens for each target address are in `pass`.

Until then, the public-claim rule is: **"RSS fanout is implemented as a library; the operator has not configured target addresses, so the surface is not-live."** Any task note that claims live RSS fanout is overstating runtime reality.

## The four-stage chain (canonical event flow)

The `omg.weblog` `ResearchVehiclePublicEvent` kind (already in `shared/research_vehicle_public_event.py::EventType`) traverses four stages from authoring to audience:

```
[1 Compose]                          [2 Approve]                    [3 Publish]                     [4 RSS Validate]
agents.omg_weblog_composer    ─►     operator flips ─►          agents.omg_weblog_publisher  ─►   agents.self_federate.rss_validator
                                     `approved: true`           via publish_orchestrator           weekly Sun 03:00 UTC
                                     in frontmatter             (PreprintArtifact path)            ntfy-on-loss (PR #1954)

~/hapax-state/                       Vault edit                 omg.lol ←─────                     Validates feed structure
weblog-drafts/                                                  `hapax_broadcast_omg_weblog_       + DOI cross-link coverage;
<date>.md                                                        publishes_total{result}` on 9510  pages on valid → invalid edge.
                                                                                                   `hapax_self_federate_rss_
                                                                                                    validity_total{outcome}`
```

Stage 5 (cross-weblog fanout) is the not-live surface above. When the operator configures targets, the fanout will run as a downstream consumer of stage 3's success event, *not* as a parallel surface.

## Public-claim rules (post-this-PR)

Each row is a permitted claim and the runtime evidence required to assert it:

| Surface | Permitted claim | Required evidence |
|---|---|---|
| Operator-approved weblog publication | "Hapax publishes operator-approved drafts to `hapax.weblog.lol` via the publication-bus orchestrator." | Active orchestrator (`hapax-publish-orchestrator.service`), `_record(outcome=ok)` increment in `_PUBLISH_TOTAL`, persisted log in `~/hapax-state/publish/log/<slug>.<surface>.json`. |
| Monthly composer drafts | "Hapax composes a draft skeleton on the first of each month." | `hapax-omg-weblog-composer.timer` enabled + last run successful (`systemctl --user list-timers \| grep weblog-composer`). |
| RSS health validation | "Hapax validates the omg.lol weblog RSS feed weekly and pages the operator on validity loss." | `hapax-self-federate-rss.timer` enabled, `hapax_self_federate_rss_validity_total{outcome="ok"}` incrementing, ntfy fired on `valid → invalid` transitions. |
| RSS cross-weblog fanout | **Not-live.** Library implemented; no listener mounted; config addresses empty. | (When live: addresses populated + listener service running + per-target bearer-tokens in pass.) |

Any task note or public artifact (omg.lol page, livestream caption, refusal annex) that conflates these four surfaces should be amended.

## Acceptance status

- [x] `weblog.entry` public-event input shape defined → handled by existing `EventType="omg.weblog"` literal in `shared/research_vehicle_public_event.py`. The four-stage chain above documents the input shape's lifecycle.
- [x] Existing successful publish-orchestrator path remains intact → this PR adds units + docs only; no changes to `agents/omg_weblog_publisher/`, `agents/publish_orchestrator/`, or the schema.
- [x] Missing monthly composer timer mounted → `systemd/units/hapax-omg-weblog-composer.{service,timer}` (monthly, first 09:00 UTC).
- [x] Missing RSS fanout listener explicitly marked not-live → §"Explicitly not-live" above; public-claim rule prohibits asserting live fanout until config + listener + tokens land.
- [x] RSS fanout config with empty addresses remains no-op → unchanged from PR predecessor; `addresses: []` is the seed state.
- [x] Public claims distinguish weblog publication vs RSS health validation vs RSS fanout → public-claim table above; future task notes reference this matrix.

## Pointers

- Composer: `agents/omg_weblog_composer/composer.py` + `__main__.py`
- Publisher: `agents/omg_weblog_publisher/publisher.py` (`hapax_broadcast_omg_weblog_publishes_total`)
- RSS validator: `agents/self_federate/rss_validator.py` (post-PR-#1954 ntfy-on-loss)
- RSS fanout library: `agents/publication_bus/omg_rss_fanout.py` (Phase 1; Phase 2 listener deferred)
- Fanout config: `config/omg-lol-fanout.yaml` (`addresses: []` default)
- Allowlist: `axioms/contracts/publication/omg-lol-weblog.yaml`
- Schema: `shared/research_vehicle_public_event.py::EventType` (literal includes `omg.weblog`)
- Source audit: `~/Documents/Personal/20-projects/hapax-research/audits/2026-04-28-cross-surface-reality-reconcile.md`
