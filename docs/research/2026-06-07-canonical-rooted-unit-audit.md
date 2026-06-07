# Canonical-rooted systemd unit audit — migrate python units to the source-activation deploy tree

- **Date:** 2026-06-07
- **Task:** `deploy-migrate-canonical-rooted-units-to-source-activation-20260607`
- **AuthorityCase:** CASE-SEGMENT-BATCH1-BASELINE-20260607
- **Parent request:** REQ-20260607-segment-batch1-baseline
- **Mutation scope:** `systemd/units/`, `tests/systemd/`, `docs/`

## Root cause

Live user services that set `WorkingDirectory=%h/projects/hapax-council` run
from the operator's **canonical interactive worktree**. That worktree tracks
whatever feature branch the operator currently has checked out — frequently far
behind `origin/main`, often with uncommitted local edits — so the service
executes **stale code**. `hapax-segment-prep.service` crashed daily on a removed
`CouncilConfig(max_models=…)` signature for exactly this reason: the fix landed
in `main` (#3989) but was unreachable from the stale checkout.

The same hazard applies to any unit that (a) is rooted at the canonical worktree
**and** (b) runs `python -m agents.*` / `python -m shared.*`, because `python -m`
imports from the current working directory.

## Correct pattern (reference: `hapax-daimonion.service`)

Run from the main-tracking **source-activation deploy tree** promoted by
`hapax-source-activate`, via that tree's own `.venv`:

```ini
WorkingDirectory=%h/.cache/hapax/source-activation/worktree
Environment=PATH=%h/.cache/hapax/source-activation/worktree/.venv/bin:%h/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONPATH=%h/.cache/hapax/source-activation/worktree
ExecStart=%h/.cache/hapax/source-activation/worktree/.venv/bin/python -m agents.<module>
```

`hapax-source-activate` provisions that tree with `uv sync --all-extras`
(`scripts/hapax-source-activate:726`), so the deploy `.venv` carries **all
optional dependency groups** — direct `.venv/bin/python` is therefore safe for
units that previously relied on `uv run` or on a `--extra`. It does **not**
provision the separate `.venv-ingest`, so ingest units are excluded (below).

`hapax-segment-prep.service` additionally gains the fail-closed source-freshness
guard `hapax-compositor-runtime-source-check`, mirroring daimonion.

> **Note on the working drop-in.** The task note pointed at a runtime drop-in
> `~/.config/systemd/user/hapax-segment-prep.service.d/10-source-activation.conf`.
> That file is **not present** on this host and the unit is not currently loaded
> in the live user manager, so the migration was verified against the canonical
> reference (`hapax-daimonion.service`) and the already-migrated public-event
> units instead. Runtime install is out of scope (`runtime_mutation_authorized:
> false`); on merge, `hapax-post-merge-deploy` installs the repo units.

## Inventory

90 repo service units are canonical-rooted **and** run `python -m agents.*` /
`python -m shared.*` (the silently-stale class). Disposition:

| Disposition | Count |
|---|---|
| **Migrated now** | 23 |
| Deferred — audio / live-egress / broadcast / compositor / vision / video | 24 |
| Deferred — uv→direct conversion (batch 2) | 27 |
| Deferred — public publication egress | 6 |
| Deferred — external-platform-coupled (YouTube / SoundCloud / Stream Deck) | 6 |
| Deferred — dedicated `.venv-ingest` not provisioned by source-activate | 2 |
| Deferred — provider-billing-sensitive | 1 |
| Deferred — special unit shape (device-conditioned, separately contract-tested) | 1 |

Units rooted at the canonical worktree whose ExecStart is a **shell wrapper or a
`python <script>.py`** (not `python -m agents/shared`) are out of this task's
precise criterion and are not listed; several legitimately operate on the
canonical worktree by design (e.g. `hapax-worktree-gc`, `hapax-post-merge-deploy`).

### Migrated now (23)

Purely-local daemons with no external egress and no audio/broadcast/compositor
coupling. `hapax-segment-prep` is the flagship (uv→direct + source-freshness
guard); the remaining 22 already used an explicit `.venv/bin/python` and are a
pure path-repoint.

| Unit | Module |
|---|---|
| `hapax-segment-prep.service` | `agents.hapax_daimonion.daily_segment_prep` |
| `vault-context-writer.service` | `agents.vault_context_writer` |
| `health-connect-parse.service` | `agents.health_connect_parser` |
| `hapax-information-density.service` | `agents.information_density_daemon` |
| `hapax-impingement-sampler.service` | `agents.quality_observability.impingement_sampler` |
| `hapax-inflection-bridge.service` | `agents.inflection_to_impingement` |
| `hapax-quota-observability.service` | `agents.quota_observability` |
| `hapax-conversion-broker.service` | `agents.conversion_broker` |
| `hapax-cred-watch.service` | `agents.hapax_cred_monitor` |
| `hapax-sprint-tracker.service` | `agents.sprint_tracker` |
| `hapax-relay-to-cc-tasks.service` | `agents.relay_to_cc_tasks` |
| `hapax-refused-lifecycle-conditional.service` | `agents.refused_lifecycle.conditional_watcher` |
| `hapax-refused-lifecycle-constitutional.service` | `agents.refused_lifecycle.constitutional_watcher` |
| `hapax-refused-lifecycle-structural.service` | `agents.refused_lifecycle.structural_watcher` |
| `hapax-refusal-brief-rotate.service` | `agents.refusal_brief` |
| `hapax-dataset-card-generator.service` | `agents.dataset_card_generator` |
| `hapax-mail-monitor-fallback.service` | `agents.mail_monitor.fallback` |
| `hapax-mail-monitor-watch-renewal.service` | `agents.mail_monitor.watch_renewal` |
| `hapax-mail-monitor-weekly-digest.service` | `agents.mail_monitor.digest` |
| `hapax-kdeconnect-bridge.service` | `agents.kdeconnect_bridge` |
| `hapax-chronicle-quality-exporter.service` | `agents.quality_observability.chronicle_exporter` |
| `hapax-self-federate-rss.service` | `agents.self_federate.rss_validator` |
| `hapax-omg-weblog-composer.service` | `agents.omg_weblog_composer` |

### Deferred — audio / live-egress / broadcast / compositor / vision / video (24)

This task is declared `audio_or_live_egress_sensitive: false`; migrating these
would change which code version drives audio routing, broadcast/HLS egress, the
studio compositor, or camera/vision capture — a change that must run under an
audio-/live-egress-authorized task and the `scripts/hapax-audio-routing-check`
discipline (CLAUDE.md PROTECTED AUDIO INVARIANTS).

`audio-processor`, `av-correlator`, `hapax-audio-ab-recorder`,
`hapax-audio-ducker`, `hapax-audio-perception`, `hapax-audio-router`,
`hapax-audio-safety`, `hapax-audio-signal-assertion`,
`hapax-broadcast-audio-health`, `hapax-broadcast-audio-health-producer`,
`hapax-broadcast-egress-loopback-producer`, `hapax-channel-trailer`,
`hapax-feedback-loop-detector`, `hapax-live-cuepoints`, `hapax-lufs-panic-cap`,
`hapax-overlay-producer`, `hapax-pipewire-graph-shadow`,
`hapax-rode-wireless-adapter`, `hapax-steamdeck-monitor` (HDMI→broadcast PiP),
`hapax-video-cam@`, `hapax-vision-observer`, `studio-person-detector`,
`video-processor`, `visual-layer-aggregator`.

### Deferred — uv→direct conversion, batch 2 (27)

Non-sensitive `uv run python -m …` units. Converting `uv run` to direct
`.venv/bin/python` carries per-unit semantics (e.g. `hapax-operator-awareness`
has an explicit "intentionally goes through uv … lock-managed environment"
comment and is `Type=notify`; `hapax-vault-coherence` uses `--extra logos-api
--directory`). The transform is proven in this PR by `hapax-segment-prep`;
batch 2 should convert these with individual review to keep blast radius
reviewable.

`chrome-sync`, `claude-code-sync`, `deliberation-eval`, `dev-story-index`,
`flow-journal`, `gcalendar-sync`, `gdrive-sync`, `git-sync`, `gmail-sync`,
`hapax-content-candidate-discovery`, `hapax-content-resolver`, `hapax-dmn`,
`hapax-imagination-loop`, `hapax-omg-lol-fanout`, `hapax-operator-awareness`,
`hapax-reverie-monitor`, `hapax-vault-coherence`, `hapax-weekly-review`,
`langfuse-sync`, `manifest-snapshot`, `obsidian-sync`, `policy-decide-promote`,
`profile-update`, `screen-context`, `stimmung-sync`, `storage-arbiter`,
`weather-sync`.

### Deferred — public publication egress (6)

These push to external/public destinations (DataCite DOIs, ORCID, the
`hapax-assets` CDN repo, preprint surface fan-out). `public_claim_sensitive:
false` on this task; migrating changes which code version emits public
claims/DOIs, so they belong with a publication-authorized batch alongside the
already-migrated social posters (`hapax-bluesky-post`, etc.).

`hapax-assets-publisher`, `hapax-datacite-graph-publish`, `hapax-datacite-mirror`,
`hapax-datacite-snapshot`, `hapax-orcid-verifier`, `hapax-publish-orchestrator`.

### Deferred — external-platform-coupled (6)

Coupled to a live external platform (YouTube live chat/telemetry/thumbnails,
SoundCloud, Elgato Stream Deck control surface).

`hapax-soundcloud-sync`, `hapax-streamdeck-adapter`, `hapax-thumbnail-rotator`,
`hapax-youtube-chat-reader`, `hapax-youtube-telemetry`, `youtube-sync`.

### Deferred — dedicated ingest venv (2)

Run `.venv-ingest/bin/python`, a separate environment that `hapax-source-activate`
does **not** provision (`uv sync --all-extras` builds `.venv` only). Migrating
requires source-activate to also provision `.venv-ingest`.

`rag-ingest`, `hapax-vault-bulk-rescan`.

### Deferred — provider-billing-sensitive (1)

`hapax-money-rails` (`agents.payment_processors`). `provider_billing_sensitive:
false` on this task.

### Deferred — special unit shape (1)

`hapax-m8-control` is device-conditioned (`ConditionPathExists=/dev/hapax-m8-serial`)
with no `WorkingDirectory` and a dedicated contract test
(`tests/systemd/test_canonical_units_installable.py`). Out of the pure-path
class; migrate under M8-specific review.

## Regression pin + forward guard

`tests/systemd/test_source_activation_rooted_python_units.py`:

1. `test_segment_prep_runs_from_source_activation_like_daimonion` — pins the
   flagship (rooting, deploy-venv python for condition/pre/start, the
   source-freshness guard, no `uv run`, no canonical residue).
2. `test_migrated_unit_is_source_activation_rooted` — parametrised over all 23
   migrated units.
3. `test_no_unexpected_canonical_rooted_python_units` — forward guard: the set
   of canonical-rooted `python -m agents/shared` units must stay within
   `KNOWN_CANONICAL_EXCEPTIONS` (the 67 deferred units above). A new
   canonical-rooted python unit, or a migrated unit regressing, fails the test.
4. `test_known_canonical_exceptions_all_exist` — keeps the allow-list honest.

Updated existing pins to the new rooting: `test_content_prep_residency_guards`,
`test_dataset_card_generator_timer`, `test_mail_monitor_fallback_units`.

`uv run pytest tests/systemd/` → 230 passed, 2 skipped.

## Recommended follow-up tasks

- **Batch 2 — uv→direct conversion** of the 27 non-sensitive uv-run units.
- **Audio/live-egress batch** (24) under audio-routing-check discipline.
- **Publication-egress batch** (6) under a publication-authorized task.
- **External-platform batch** (6).
- **Provision `.venv-ingest` in `hapax-source-activate`**, then migrate the 2
  ingest units.
- Migrate `hapax-m8-control` under M8-specific review.

As each batch lands, the migrated units simply leave the forward-guard's
canonical set; no allow-list churn is required to stay green.
