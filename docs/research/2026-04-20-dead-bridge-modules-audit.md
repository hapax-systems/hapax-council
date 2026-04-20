---
date: 2026-04-20
author: alpha (Claude Opus 4.7, 1M context, dispatched audit subagent)
audience: operator + alpha + delta + beta
register: scientific, neutral
status: audit catalog — references concrete codebase locations as of 2026-04-19
related:
  - docs/research/2026-04-20-wiring-audit-findings.md
  - docs/research/2026-04-20-wiring-audit-alpha.md
  - docs/research/2026-04-19-expert-system-blinding-audit.md
  - docs/research/2026-04-20-retire-effect-shuffle-design.md
  - docs/superpowers/plans/2026-04-17-volitional-grounded-director-master-plan.md
  - memory: feedback_grounding_exhaustive
  - memory: feedback_no_expert_system_rules
  - memory: project_hapax_data_audit
trigger: |
  Operator discovered agents/studio_compositor/random_mode.py was the
  intended bridge between director-loop fx-family recruitment and chain
  mutation, but was dead code: no systemd unit, no process, no caller.
  Director loop emitted preset.bias impingements; AffordancePipeline
  recruited fx.family.<family>; recruitment was written to
  recent-recruitment.json — but nothing consumed it. The chain stayed on
  whatever activated at boot for the entire stream. "Effects missing" was
  the symptom.
---

# Dead Bridge Modules Audit (2026-04-20)

## §1. TL;DR

The `random_mode` discovery is one of a class of silent architectural
failures: production modules that ship with full implementation, look
architecturally complete, but never run because nothing invokes them
(no systemd unit, no caller, no consumer of the SHM file they
produce, or a typo in the path string). We call these **dead bridges**.

This audit identifies **11 confirmed dead bridges** across the council
stack plus **6 suspected** that need operator confirmation.

The 5 highest-priority broadcast-affecting dead bridges:

1. **`fx_chain_ward_reactor.py:69` writes to wrong SHM directory** —
   `_RECENT_RECRUITMENT_PATH = Path("/dev/shm/hapax/recent-recruitment.json")`
   is the only path mismatch in the codebase. Every other module reads
   `/dev/shm/hapax-compositor/recent-recruitment.json`. The reactor's
   ward-FSM-driven preset family bias never reaches `preset_family_selector`.
   Fix: 1-line path correction. **Broadcast-affecting** — silently disables
   half the bidirectional ward↔FX coupling shipped in HOMAGE Phase 6.

2. **`hapax-rode-wireless-adapter.service` exists in repo but is not
   installed.** The adapter would write
   `/dev/shm/hapax-compositor/voice-source.txt` so daimonion STT can
   route between the desk Yeti and the Rode wireless mic when the
   operator wears it. With the unit absent, `voice-source.txt` is never
   updated and `stt_source_resolver` sits on stale state. Symptom:
   wearing the Rode does not switch STT input. **Broadcast-affecting** —
   degrades on-mic livestream segments to room-mic quality.

3. **`hapax-stream-auto-private.service`/`.timer` exist in repo but are
   not installed.** This is the LRR Phase 6 §5 executive_function-axiom
   compensation enforcer that flips the stream to private mode if the
   operator-consent contract lapses. Without the timer enabled, the
   stream stays public after consent expires. **Broadcast + governance-
   affecting** — directly contradicts the spec it implements.

4. **Programme primitive has zero production consumers.**
   `shared/programme.py` (312 LOC) exports a fully-validated Programme
   model with bias multipliers and constraint envelopes, but no module
   under `agents/` or `logos/` imports it. Only tests + research docs
   reference it. The plan
   `docs/superpowers/plans/2026-04-20-programme-layer-plan.md` declares
   12 phases with consumer wiring as Phases 2-12 — Phase 1 (the
   primitive itself) shipped without its first consumer. KNOWN deferral
   per plan; we list it as **suspected-not-silent** but flag it because
   the operator's `feedback_hapax_authors_programmes` memory expects
   programmes to be running. **Inference-affecting** — currently the
   director loop is meso-less.

5. **`shared/governance/mental_state_redaction.py` ships the redactor
   but no production code calls it.** LRR Phase 6 §4.E spec mandates
   that "Callers that query any of these collections at stream-visible
   render time must invoke `redact_mental_state_if_public()` on each
   returned payload." The 5 affected Qdrant collections
   (operator-episodes, operator-corrections, operator-patterns,
   profile-facts, hapax-apperceptions) ARE queried at stream-visible
   render time. Only `tests/governance/test_mental_state_redaction.py`
   and `tests/logos_api/test_stream_mode_transition_matrix.py`
   reference the redactor. **Broadcast + governance-affecting** —
   private mental-state narrative may surface on the public
   livestream layer.

**Recommended ship sequence** (smallest blast radius first; see §9):
S1 (path-typo, 1 line) → S2 (rode adapter, install unit) → S3 (stream
auto-private, install unit) → S4 (mental-state redaction wiring) →
S5 (BPM publisher and presence-state publisher) → S6 (delete dead-shim
modules) → S7 (Programme consumer Phase 2 per plan).

## §2. Methodology + scope

**Scope:** the hapax-council repository. SHM filesystem `/dev/shm/`.
Operator-side systemd state at the standard XDG user-systemd path
cross-checked with repo unit definitions at `systemd/units/`.

**Excluded:** Rust code (`hapax-logos/src-tauri/`,
`hapax-logos/src-imagination/`, `gst-plugin-glfeedback/`) is checked
only as far as it reads/writes SHM files referenced from Python.
Sister repos (officium, mcp, watch, phone) excluded.

**Method:**

1. **Module-orphan scan.** Enumerate every `.py` under `agents/` and
   for each module count production callers (excluding tests,
   `__pycache__`, the module itself). Modules with 0 production
   callers are candidates.
2. **SHM producer/consumer asymmetry scan.** Enumerate every
   `/dev/shm/hapax*` literal in `agents/`, `shared/`, `logos/`,
   `scripts/`. For each path, count writers (modules with `.write_text`
   / `.write_bytes` / `tmp.replace` / `atomic_write` AND the path) and
   readers. Asymmetric paths (writer-but-no-reader, reader-but-no-
   writer) are dead-bridge candidates.
3. **systemd unit-installation scan.** For each `.service` /
   `.timer` in `systemd/units/`, check whether the user-systemd dir
   contains the unit and whether `systemctl --user is-enabled`
   reports `enabled` / `static` / `not-found`.
4. **Bridge-naming heuristic.** Grep for class names ending in
   `Consumer`, `Reactor`, `Bridge`, `Loader`, `Bus`, `Dispatcher`,
   `Wire`, `Connector`. For each, verify `connect()` /
   `register()` / `start()` is called from a non-test module.
5. **Public-API-but-no-caller scan.** For each module identified in
   (1) and each function with public-style naming, verify a
   non-test caller exists.
6. **Manifest-vs-reality scan.** Cross-reference declared SHM paths
   in `agents/manifests/*.yaml` against actual paths used by code.

Live verification used `stat /dev/shm/...`, `systemctl --user
is-enabled`, and direct `ls` of the user-systemd directory.

**What this audit does not catch:**

- Bridges that ship behind a feature flag (`HAPAX_*_ACTIVE` env vars).
  These look "dead" until the flag is set. We treat them as not-dead
  if a flag-flip turns the wiring on.
- Multi-process Rust↔Python bridges where the Rust side is the
  consumer; we check Rust grep but only for SHM literals.
- Anything where the path is constructed dynamically from a config
  (we'd miss those).

## §3. Confirmed dead bridges

### 3.1 `random_mode.run()` — never invoked from any process

**Files:** `agents/studio_compositor/random_mode.py:107-186`

**Bridge purpose:** read `recent-recruitment.json` for `preset.bias`
family, pick a preset within that family via
`preset_family_selector.pick_from_family`, write
`/dev/shm/hapax-compositor/graph-mutation.json` with smooth fade
transitions every ~30 s. Was the original Phase 3 (volitional-director
epic) consumer — see
`docs/superpowers/plans/2026-04-17-phase-3-compositional-recruitment.md`.

**Evidence of dead state:**

- No `systemd/units/random_mode.service` or similar.
  `Grep "random_mode" systemd/` returns no matches.
- No callsite in `agents/studio_compositor/lifecycle.py` (which spawns
  every other compositor sub-loop).
- `agents/studio_compositor/random_mode.py:180` has an `if __name__ ==
  "__main__":` block but no service or script invokes it.
- `Grep "random_mode" scripts/` returns no matches.
- Live: `pgrep -f random_mode` returns nothing.

**Symptom:** the operator's flagged "effects missing / chain stays the
same all stream" — recruitment is observable but inert.

**Fix difficulty:** known. The replacement bridge
(`preset_recruitment_consumer.process_preset_recruitment`) was wired
into `agents/studio_compositor/state.py:551-555` per
`docs/research/2026-04-20-retire-effect-shuffle-design.md`. The dead
`random_mode.run()` should be deleted; only `MUTATION_FILE` and
`CONTROL_FILE` constants are still imported by
`preset_recruitment_consumer.py:36`.

**Priority:** broadcast-affecting (already-fixed-but-cleanup).

### 3.2 `WardFxReactor._bias_preset_family` writes to wrong SHM directory

**Files:**
- Producer (dead): `agents/studio_compositor/fx_chain_ward_reactor.py:69`
  declares `_RECENT_RECRUITMENT_PATH = Path("/dev/shm/hapax/recent-recruitment.json")`.
- Producer call: `agents/studio_compositor/fx_chain_ward_reactor.py:252-268`
  in `_bias_preset_family`.
- Wiring: `agents/studio_compositor/lifecycle.py:241-244` instantiates
  `WardFxReactor()` and calls `.connect()`.

**Bridge purpose:** ward FSM `ABSENT_TO_ENTERING` events bias the
preset family — write the chosen family name where
`preset_family_selector` will pick it up.

**Evidence of dead state:**

- All 12+ readers in the codebase use
  `/dev/shm/hapax-compositor/recent-recruitment.json` (see
  `agents/studio_compositor/preset_recruitment_consumer.py:40`,
  `agents/studio_compositor/compositional_consumer.py:112`,
  `agents/studio_compositor/random_mode.py:91`,
  `agents/studio_compositor/preset_family_selector.py:8`,
  `agents/studio_compositor/hothouse_sources.py:76`,
  `agents/studio_compositor/hardm_source.py:100`).
- `Grep "/dev/shm/hapax/recent-recruitment"` returns exactly ONE
  match — the producer line itself. **Zero readers.**
- Live: `stat /dev/shm/hapax/recent-recruitment.json` shows the file
  exists, last modified today, with a valid `{"family": "...",
  "source": "ward_fx_reactor", "domain": "...", "ts": ...}` payload —
  written but unread.
- Live: `cat /dev/shm/hapax-compositor/recent-recruitment.json` shows
  the canonical, well-populated 17-key recruitment manifest — none of
  whose entries originated from `WardFxReactor`.

**Symptom:** ward-FSM-driven preset family bias never reaches the
chain mutator. Half of the bidirectional ward↔FX coupling shipped in
HOMAGE Phase 6 (Direction 1, Layer 5) is silently disabled. Wards
still get their direction-2 effects (border pulses, scale bumps), but
ward transitions cannot bias the FX chain back.

**Fix difficulty:** trivial — change the literal at
`agents/studio_compositor/fx_chain_ward_reactor.py:69` to
`Path("/dev/shm/hapax-compositor/recent-recruitment.json")`. Note the
payload schema differs from `compositional_consumer.py`'s upsert
payload, so the merge needs to be additive (use upsert pattern from
`compositional_consumer.py:1534-1556`) rather than replace-the-file.

**Priority:** broadcast-affecting (HIGH — silent regression on
shipped feature).

### 3.3 `hapax-rode-wireless-adapter.service` not installed

**Files:**
- Unit definition: `systemd/units/hapax-rode-wireless-adapter.service`
- Module: `agents/hapax_daimonion/rode_wireless_adapter.py`
- Consumer: `agents/hapax_daimonion/cpal/stt_source_resolver.py`

**Bridge purpose:** detect Rode Wireless Pro UAC2-class device on
PipeWire, route audio to the daimonion STT input by writing
`/dev/shm/hapax-compositor/voice-source.txt`.

**Evidence of dead state:**

- The unit is absent from the user-systemd directory.
- `systemctl --user is-enabled hapax-rode-wireless-adapter.service`
  reports `not-found`.
- The unit's `Type=simple ExecStart=...rode_wireless_adapter` should be
  always-running; nothing else writes `voice-source.txt`.
- `Grep "voice-source\.txt" agents shared logos` shows
  `stt_source_resolver` reading and `rode_wireless_adapter` writing —
  no third writer.

**Symptom:** wearing the Rode wireless mic does not switch STT input.
Operator's voice goes through the desk Blue Yeti regardless. On-mic
livestream segments degrade to room-mic ambient.

**Fix difficulty:** trivial — `systemctl --user enable --now hapax-
rode-wireless-adapter.service`. (Verify the unit's `ExecStart` path
points at the correct interpreter; the unit references
`.venv/bin/python` directly which may need to be `uv run python -m`
form for parity with other daimonion units.)

**Priority:** broadcast-affecting.

### 3.4 `hapax-stream-auto-private.service` + `.timer` not installed

**Files:**
- `systemd/units/hapax-stream-auto-private.service`
- `systemd/units/hapax-stream-auto-private.timer`
- Script: `scripts/hapax-stream-auto-private`
- Spec: `docs/superpowers/specs/2026-04-15-lrr-phase-6-governance-finalization-design.md` §5

**Bridge purpose:** the LRR Phase 6 §5 executive_function compensation
mechanism — flips OBS scene to PRIVATE if consent contract lapses
or any of the gating signals deviate. 15-second cadence per spec.

**Evidence of dead state:**

- The user-systemd directory contains neither the service nor the
  timer.
- `systemctl --user is-enabled hapax-stream-auto-private.timer`
  reports `not-found`.
- The script `scripts/hapax-stream-auto-private` exists and is
  executable.

**Symptom:** stream stays public after consent contract expiry —
direct contradiction of the axioms (`single_user`,
`interpersonal_transparency`) the spec implements.

**Fix difficulty:** trivial — symlink + enable. Verify the script's
gating logic is current.

**Priority:** governance + broadcast-affecting.

### 3.5 `hapax-environmental-emphasis.timer` not installed

**Files:**
- `systemd/units/hapax-environmental-emphasis.service`
- `systemd/units/hapax-environmental-emphasis.timer`
- Script: `scripts/environmental_emphasis_tick.py`
- Module: `agents/environmental_perception/`

**Bridge purpose:** salience-driven hero-mode driver — periodically
recompute environmental salience and write a hero-camera-override
to drive the compositor's auto-camera-pick path.

**Evidence of dead state:**

- The user-systemd directory contains neither the service nor the
  timer.
- `systemctl --user is-enabled hapax-environmental-emphasis.timer`
  reports `not-found`.

**Symptom:** environmental salience never drives auto-camera changes.
Camera hero stays where the last manual / chat-driven cut left it.
The compositor still has the `environmental_salience_emphasis`
module (`agents/studio_compositor/environmental_salience_emphasis.py`)
plumbed into `lifecycle.py` but the upstream tick that would
populate `environmental-hero-override.json` does not run on a
schedule.

**Fix difficulty:** trivial install + verify timer cadence (likely
30s per the script header).

**Priority:** broadcast-affecting (latent until manual hero-locks
expire).

### 3.6 `hapax-soundcloud-sync.timer` not installed

**Files:**
- `systemd/units/hapax-soundcloud-sync.service`
- `systemd/units/hapax-soundcloud-sync.timer`
- Module: `agents/soundcloud_adapter/__main__.py`

**Bridge purpose:** task #131 Phase 1 — periodic SoundCloud likes /
playlist metadata sync into the operator profile.

**Evidence of dead state:** unit is absent from the user-systemd
directory; `systemctl --user is-enabled` reports `not-found`.

**Symptom:** profile dimension `music_taste` cannot include recent
SoundCloud activity. Latent — no other system depends on this for
livestream operation.

**Fix difficulty:** install + auth check.

**Priority:** observability-only / latent.

### 3.7 `hapax-rebuild-gst-plugins.timer` not installed

**Files:**
- `systemd/units/hapax-rebuild-gst-plugins.service`
- `systemd/units/hapax-rebuild-gst-plugins.timer`
- Script: `scripts/rebuild-gst-plugins.sh`

**Bridge purpose:** rebuild the Rust GStreamer plugins (currently
`gst-plugin-glfeedback`) and install to `/usr/lib/gstreamer-1.0`,
then restart affected services. Closes the gap that
`rebuild-services.sh` (Python-only) does not cover.

**Evidence of dead state:** unit is absent from the user-systemd
directory.

**Symptom:** glfeedback (Bachelard Amendment 2 temporal feedback)
plugin source changes do not auto-deploy; operator must manually
`cargo build --release && sudo install`. Latent until the plugin
source is touched.

**Fix difficulty:** install + verify the timer cadence (per the
service's `TimeoutStartSec=300`, the rebuild can take up to 5 min).

**Priority:** observability-only / latent (developer-experience).

### 3.8 `shared/governance/mental_state_redaction.py` has no production caller

**Files:**
- Module: `shared/governance/mental_state_redaction.py`
- Spec: LRR Phase 6 §4.E (referenced in the module docstring)

**Bridge purpose:** when stream is publicly visible, substitute the
sanitized `mental_state_safe_summary` payload field for the raw
narrative on points retrieved from operator-episodes,
operator-corrections, operator-patterns, profile-facts, and
hapax-apperceptions Qdrant collections.

**Evidence of dead state:**

- `Grep "mental_state_redaction|MentalStateRedact"` returns 2 files
  total — both tests
  (`tests/governance/test_mental_state_redaction.py`,
  `tests/logos_api/test_stream_mode_transition_matrix.py`).
- The module docstring asserts: "Callers that query any of these
  collections at stream-visible render time must invoke
  `redact_mental_state_if_public()` on each returned payload." Zero
  callers do.
- The 5 collections ARE queried at stream-visible render time —
  see `shared/perceptual_field.py`, `agents/studio_compositor/
  hothouse_sources.py`, `agents/studio_compositor/twitch_director.py`,
  `agents/studio_compositor/director_loop.py`. None of these
  invoke the redactor before rendering.

**Symptom:** raw mental-state narrative content can surface on the
public livestream layer when the affected collections are queried
during stream-visible rendering. Direct violation of the
`interpersonal_transparency` axiom and LRR Phase 6 spec.

**Fix difficulty:** medium — wrap each query call site (~5-7 sites)
with the redactor + add a regression test that drives the public-stream
path and asserts no raw narrative leaks.

**Priority:** broadcast + governance-affecting (HIGH).

### 3.9 `preset_family_selector.pick_with_scene_bias` has no caller

**Files:** `agents/studio_compositor/preset_family_selector.py:230-310`

**Bridge purpose:** Task #150 Phase 1 — after the family has been
chosen, weight the within-family preset pick by the current scene
classification (e.g. `person-face-closeup` favors `intimate` /
`portrait` tag preset).

**Evidence of dead state:**

- `Grep "pick_with_scene_bias"` returns 4 files: the definition,
  one test, one design doc, and a docstring reference inside
  `agents/studio_compositor/scene_classifier.py:11`. **No production
  caller.**
- `agents/studio_compositor/preset_recruitment_consumer.py:90` calls
  `pick_and_load_mutated` (which forwards to `pick_from_family`) — it
  does NOT call `pick_with_scene_bias`. Scene context is dropped on
  the floor at the recruitment-consumer boundary.

**Symptom:** within-family preset picks are uniform-by-tag (subject
to non-repeat memory). The scene-classifier output that exists in
SHM (`/dev/shm/hapax-compositor/scene-classification.json`) does not
influence which preset the family hands back. Phase 1 of the scene-
bias feature shipped without its consumer.

**Fix difficulty:** trivial-medium — `preset_recruitment_consumer.
process_preset_recruitment` should read scene-classification.json (5
LOC) and call `pick_with_scene_bias` instead of `pick_and_load_mutated`
when the scene is known. Plus a thin scene→graph helper that pairs
`pick_with_scene_bias` with the parametric mutator (the current
`pick_and_load_mutated` does both in one hop).

**Priority:** inference-affecting (HIGH-ish — the dead-bridge chain
fix in §3.2 + the scene-bias wiring would jointly make the chain
respond to ward + scene state instead of just director recruitment).

### 3.10 `agents/_affordance_metrics.py` is a re-export shim with no importers

**Files:**
- `agents/_affordance_metrics.py` (3 LOC, only `from
  shared.affordance_metrics import *`)
- `logos/_affordance_metrics.py` (parallel shim)

**Bridge purpose:** post-shared-dissolution backwards-compat shim.

**Evidence of dead state:**

- `Grep "from agents\._affordance_metrics|from logos\._affordance_metrics"`
  returns no matches.
- The shared/ → agents/_ + logos/_ shim pattern was the dissolution
  migration; for `_affordance_metrics` the migration was performed
  but no importers were left behind.

**Symptom:** none — these are pure dead code, not a behaviour gap.

**Fix difficulty:** trivial — `git rm` both files.

**Priority:** observability-only (housekeeping).

### 3.11 `agents/_langfuse_config.py` side-effect import shim, no importers

**Files:** `agents/_langfuse_config.py` (37 LOC)

**Bridge purpose:** docstring states "Import this module as a side-
effect in any agent script: `from agents import _langfuse_config #
noqa: F401`". The side-effect configures OTel exporter env vars to
route to the local Langfuse.

**Evidence of dead state:**

- `Grep "from agents\._langfuse_config|import _langfuse_config|agents\._langfuse_config"`
  returns no matches outside the module itself.
- No agent script does the import the docstring instructs.

**Symptom:** OTel exporter env vars are not configured by this module.
Either set elsewhere (in which case this module is genuinely dead) or
not set at all (in which case Langfuse traces from agents are missing
the OTel export side, which would explain
`docs/research/2026-04-15-litellm-config-drift-audit.md` observations
about partial trace coverage).

**Fix difficulty:** medium — needs operator to confirm whether
Langfuse OTel is configured by another path. If yes, delete. If no,
add the noqa import to entry-point modules (`agents/__init__.py`
or each `__main__`).

**Priority:** observability-only (latent).

## §4. Suspected-dead bridges (need operator confirmation)

### 4.1 Programme primitive (KNOWN deferral but worth flagging)

**Files:** `shared/programme.py` (312 LOC)

**Status:** Phase 1 (primitive) shipped per
`docs/superpowers/plans/2026-04-20-programme-layer-plan.md`. Phases
2-12 (consumer wiring, director integration, MCP control surface,
cycle/scheduling, observability) are explicitly deferred per the
plan's phase ordering.

**Why we list it here:** the operator memory
`feedback_hapax_authors_programmes` declares programmes as a
load-bearing requirement. The plan defers them post-go-live.
The audit cannot tell whether the deferral has slipped past go-live
without operator confirmation.

**Action:** treat as KNOWN-deferred unless operator updates priority.

### 4.2 `agents/vault_canvas_writer.py` — declared in CLAUDE.md, no scheduler

**Files:**
- `agents/vault_canvas_writer.py`
- CLAUDE.md describes: "`agents/vault_canvas_writer.py` — Generates
  JSON Canvas goal dependency map."

**Evidence:**

- No `vault_canvas_writer.timer` or `.service` exists.
- `obsidian_sync.service` runs `agents.obsidian_sync` which does NOT
  import `vault_canvas_writer`.
- The canvas file path
  (`~/Documents/Personal/20-projects/hapax-goals/goal-map.canvas`)
  may or may not exist on disk depending on operator manual runs.

**Symptom:** goal canvas does not auto-update.

**Action:** confirm operator expectation — is canvas regenerated
manually or expected on a schedule? If scheduled, add a 15-min timer
matching the spec.

### 4.3 `current-bpm.txt` has a reader but no writer

**Files:**
- Reader: `shared/vinyl_rate.py:36, 119` —
  `normalized_bpm_signal()`.
- Consumer: `agents/studio_compositor/director_loop.py` (transitively
  via `normalized_bpm_signal` import path).

**Evidence of dead state:**

- `Grep "current-bpm" agents shared` shows ONLY the reader.
- The reader's docstring references "the beat tracker or audio_capture
  publisher" — neither exists in the codebase.
- `Grep "BeatTracker"` returns no matches.
- `audio_capture.py` does not write `current-bpm.txt`.

**Symptom:** `normalized_bpm_signal()` always returns `None`.
Director music-framing path falls through to default cadence.
Vinyl-rate compensation never gets a real BPM input.

**Action:** decide whether to (a) write a BPM publisher
(e.g. wire librosa beat-tracker to the contact-mic / Yeti capture
loop and emit `current-bpm.txt` every ~5s) or (b) delete the reader
and simplify `vinyl_rate.compensate_bpm` to operator-provided BPM.

### 4.4 `presence-state.json` has readers but no writer

**Files:**
- Reader: `agents/studio_compositor/hothouse_sources.py:75` —
  `_PRESENCE_STATE = Path(os.path.expanduser("~/.cache/hapax-daimonion/presence-state.json"))`.
- Reader: `shared/perceptual_field.py:45` —
  `_PRESENCE_STATE = Path("/dev/shm/hapax-daimonion/presence-state.json")` (different path!).

**Evidence of dead state:**

- Two different paths used by different readers — already a
  consistency bug.
- `Grep "PresenceState\|presence-state"` against
  `agents/hapax_daimonion/presence_engine.py` shows the engine
  computes presence as a behavior dict (`presence_engine.py:107,
  192`) but does NOT write to either SHM path.
- Both candidate files (under `~/.cache/` and under `/dev/shm/`)
  return "No such file or directory."

**Symptom:** hothouse_sources presence cell + perceptual_field
presence-driven gating both fall back to default values. Stream
presence-aware behaviors (e.g. ward emphasis on operator presence)
do not respond to actual presence.

**Action:** add a presence-state writer to `presence_engine.tick()`
that emits the SHM file (canonical path
`/dev/shm/hapax-daimonion/presence-state.json`) — and fix
`hothouse_sources.py:75` to point at the canonical path instead of
`~/.cache/`.

### 4.5 Manifest declares `/dev/shm/hapax-imagination/pipeline/uniforms.json`, actual is `/dev/shm/hapax-imagination/uniforms.json`

**Files:**
- Manifest: `agents/manifests/imagination_resolver.yaml:11`
- Actual canonical path used by Rust DynamicPipeline +
  `agents/reverie/_uniforms.py`: `/dev/shm/hapax-imagination/uniforms.json`.

**Evidence of dead state:**

- `ls /dev/shm/hapax-imagination/pipeline/uniforms.json` → does not
  exist.
- `ls /dev/shm/hapax-imagination/uniforms.json` → exists, written
  every render tick.
- Multiple legacy plan docs still use the `pipeline/uniforms.json`
  path.

**Symptom:** the manifest's `pipeline_state.path` is referenced by
agent-registry queries (`shared/agent_registry.py`) — UI / health
checks that introspect the manifest will report stale state because
the path doesn't exist. Functionally harmless until something
introspects it.

**Action:** correct the manifest line to
`/dev/shm/hapax-imagination/uniforms.json`.

### 4.6 `youtube-viewer-count.txt` has a reader but no in-repo writer

**Files:**
- Reader: `agents/studio_compositor/hothouse_sources.py:77`
  `_YOUTUBE_VIEWER_COUNT = Path("/dev/shm/hapax-compositor/youtube-viewer-count.txt")`.

**Evidence of dead state:**

- No writer found in `agents/`, `shared/`, `logos/`, `scripts/`.
- `ls /dev/shm/hapax-compositor/youtube-viewer-count.txt` → does
  not exist.

**Symptom:** the youtube-viewer-count cell in the hothouse rendering
falls through to the default (likely 0). Latent if the cell isn't
critical to broadcast aesthetics.

**Action:** confirm whether an external (n8n? cron?) workflow writes
this file or whether the reader should be removed / a publisher
added inside `agents/studio_compositor/youtube_description_syncer.py`.

## §5. NOT-dead bridges (defensive documentation)

### 5.1 `preset_recruitment_consumer.process_preset_recruitment`

Looks like an orphan because it's only invoked from one inline
import inside `agents/studio_compositor/state.py:551-555`, but
`state.py::state_reader_loop` IS spawned by
`agents/studio_compositor/lifecycle.py:345`, and the studio compositor
service is `enabled` + `active`. **Wired correctly. This is the
replacement bridge for the original dead `random_mode.run`.**

### 5.2 `WardFxReactor` instantiation

The class IS instantiated and `connect()`-ed at
`agents/studio_compositor/lifecycle.py:241-244`. Direction-2
(FX→ward border-pulse / scale-bump) is functional. Only Direction-1
(ward→preset family bias) is dead — see §3.2.

### 5.3 `monetization_safety` gate

`shared/governance/monetization_safety.py` IS imported by
`shared/affordance_pipeline.py` (single inline `from
shared.governance.monetization_safety import GATE as _MONET_GATE`).
Wired.

### 5.4 `revocation_wiring`

Both `agents/_governance/revocation_wiring.py` and
`logos/_revocation_wiring.py` are referenced by
`logos/api/routes/consent.py` and `logos/api/app.py`. Wired.

### 5.5 `ConsentGatedQdrant`

`shared/governance/qdrant_gate.py` is imported by `shared/config.py`.
Wired.

### 5.6 daimonion `cpal/grounding_bridge.py` and
`cpal/register_bridge.py`

Both are constructed by `agents/hapax_daimonion/cpal/runner.py:84,
90`. Wired.

### 5.7 `ImpingementConsumer`

`shared/impingement_consumer.py` is imported by daimonion's
run_loops_aux + reverie + fortress per the council CLAUDE.md
"Impingement consumer bootstrap" section. Wired.

### 5.8 Programme primitive

Listed in §4.1 — KNOWN-deferred per its plan, not silent dead bridge.

## §6. Producer/consumer SHM-file asymmetry table

Counts come from a grep across `agents/`, `shared/`, `logos/`,
`scripts/` (excluding tests + `__pycache__`). "writers" = modules
containing both the path literal AND a write primitive
(`write_text` / `write_bytes` / `tmp.replace` / `atomic_write*`).
"readers" = any module containing the path literal.

| SHM path | writers | readers | status |
|---|---|---|---|
| `/dev/shm/hapax/recent-recruitment.json` | 1 (fx_chain_ward_reactor) | 0 | **DEAD** §3.2 |
| `/dev/shm/hapax-compositor/current-bpm.txt` | 0 | 1 (vinyl_rate) | **DEAD** §4.3 |
| `/dev/shm/hapax-compositor/youtube-viewer-count.txt` | 0 | 1 (hothouse_sources) | **DEAD** §4.6 |
| `/dev/shm/hapax-compositor/track-lyrics.txt` | 1 (album-identifier.py script) | 1 (overlay_zones) | live (script-driven) |
| `/dev/shm/hapax-daimonion/presence-state.json` | 0 | 2 (hothouse_sources, perceptual_field; different paths) | **DEAD** §4.4 |
| `/dev/shm/hapax-imagination/pipeline/uniforms.json` (manifest) | 0 | 1 (manifest only) | **STALE** §4.5 |
| `/dev/shm/hapax-imagination/uniforms.json` (canonical) | 1 (Rust + reverie) | many | live |
| `/dev/shm/hapax-compositor/recent-recruitment.json` | 2 (compositional_consumer, hardm_publisher script) | 6+ | live |
| `/dev/shm/hapax-compositor/graph-mutation.json` | 2 (chat_reactor, preset_recruitment_consumer) | 1 (state_reader_loop) | live |
| `/dev/shm/hapax-compositor/voice-source.txt` | 1 (rode_wireless_adapter) | 1 (stt_source_resolver) | **DEAD writer** (unit not installed; see §3.3) |

`/dev/shm/hapax-compositor/album-state.json` and
`music-attribution.txt` are written by the
`scripts/album-identifier.py` script (out-of-band), not from inside
the agents tree, so they appear as "0 writers" in the agents-only
scan but are functional. Live `stat` confirms these update every
~30 s.

## §7. Disabled-but-defined systemd units table

Units that exist as `.service` files in `systemd/units/` but are
**not installed** at all in the user-systemd directory. Excludes
units that are intentionally not installed (e.g. `hapax-logos.service`
— operator runs Logos via `pnpm tauri dev` per CLAUDE.md, so the
service is not needed; same for `hapax-kdeconnect-bridge.service`,
`hapax-streamdeck-adapter.service`, `tabbyapi-firewall.service`,
`tabbyapi-hermes8b.service` which target hardware/configs the
operator doesn't currently run).

| Unit | Has timer? | Last changed | Verdict |
|---|---|---|---|
| `hapax-environmental-emphasis.service` + `.timer` | yes | repo Apr-17 | **DEAD** §3.5 |
| `hapax-rode-wireless-adapter.service` | n/a (Type=simple) | repo | **DEAD** §3.3 |
| `hapax-stream-auto-private.service` + `.timer` | yes | repo Apr-16 | **DEAD** §3.4 |
| `hapax-soundcloud-sync.service` + `.timer` | yes | repo | **DEAD** §3.6 |
| `hapax-rebuild-gst-plugins.service` + `.timer` | yes | repo | **DEAD** §3.7 |
| `hapax-lrr-phase-4-integrity.service` + `.timer` | yes | repo Apr-15 | intentional — script exits 3 when collection halt is set, operator-disabled at Phase 4 close |
| `hapax-logos.service` | n/a | repo | intentional — `pnpm tauri dev` is the prod path |
| `hapax-kdeconnect-bridge.service` | n/a | repo | intentional / hardware-conditional |
| `hapax-streamdeck-adapter.service` | n/a | repo | intentional / hardware-conditional |
| `tabbyapi-firewall.service` | n/a | repo | intentional / config-conditional |
| `tabbyapi-hermes8b.service` | n/a | repo | intentional / model-conditional |

## §8. Orphan-script audit

A grep of `scripts/*.py` and `scripts/*.sh` against systemd units
and other scripts (excluding self-references) identifies ~50 scripts
with zero non-self callers. Of these, the following are **expected**
operator-runs-once tools (not dead bridges):

`benchmark_prompt_compression_b6.py`, `calibrate-contact-mic.py`,
`drill-consent-revocation.py`, `enroll_speaker.py`,
`generate_codebase_map.py`, `mock-chat.py`, `record_wake_word.py`,
`render_*_demo*.py`, `s4-configure-base.py`, `evil-pet-configure-base.py`,
`smoke_test_*.py`, `test_wake_handoff.py`, `train_wake_word.py`,
`webcam_timelapse.py`, `audit-audio-topology.sh`,
`compositor-vram-snapshot.sh`, `deploy-heartbeat-to-fleet.sh`,
`hapax-whoami-audit.sh`, `install-*.sh`, `migrate-voice-to-daimonion.sh`,
`pipewire-baseline-snapshot.sh`, etc.

The following are **suspected orphans** that may have lost their
invocation site:

| Script | Suspected purpose | Action |
|---|---|---|
| `scripts/sdlc_axiom_judge.py` | Should be in CI for axiom gating | Confirm `.github/workflows/*` invokes it; if not, wire or delete |
| `scripts/sdlc_plan.py` | Should be in CI for plan generation | Same |
| `scripts/sdlc_review.py` | Should be in CI for adversarial review | Same |
| `scripts/run_deliberations.py` | Likely deliberation-eval timer wrapper | Cross-check `deliberation-eval.service` ExecStart |
| `scripts/provision_dashboards.py` | One-shot Grafana setup | Likely intentional — confirm it ran once and was kept for re-provisioning |
| `scripts/llm_validate.py`, `llm_metadata_gen.py`, `llm_vendor.py`, `llm_import_graph.py` | LLM utility scripts | Likely intentional one-shots |
| `scripts/migrate_*.py` | One-shot migrations | Likely intentional — confirm migration was completed |

## §9. Recommended phased remediation

Ordered by blast radius (smallest first) and broadcast urgency.

**S1 — Single-line fixes (1 PR, 1-line each, no behaviour change beyond
restoring intended wiring):**
- Fix the `WardFxReactor` recruitment path typo (§3.2).
- Fix the `imagination_resolver.yaml` manifest path (§4.5).

**S2 — Install missing systemd units (1 PR, install + enable + verify
3 units):**
- `hapax-rode-wireless-adapter.service` (§3.3).
- `hapax-stream-auto-private.timer` + `.service` (§3.4).
- `hapax-environmental-emphasis.timer` + `.service` (§3.5).

**S3 — Wire the mental-state redactor into all stream-visible Qdrant
query paths (1 PR, ~5-7 callsites, ~50 LOC + tests):**
- §3.8.

**S4 — Wire scene-bias into preset recruitment (1 PR, ~10 LOC + 1
helper):**
- §3.9 — replace `pick_and_load_mutated` call in
  `preset_recruitment_consumer.process_preset_recruitment` with a
  scene-aware variant that reads `scene-classification.json` and
  routes through `pick_with_scene_bias`.

**S5 — Add the missing publishers (medium PR each, ~30-50 LOC + tests):**
- BPM publisher (§4.3) — choose between writing one or simplifying
  the consumer.
- presence-state.json publisher (§4.4) — add a `tick()` write to
  `presence_engine.py`, fix the consumer-side path in
  `hothouse_sources.py:75`.

**S6 — Delete dead shims + dead `random_mode.run()` body (1 PR,
straight deletes):**
- `agents/_affordance_metrics.py` + `logos/_affordance_metrics.py`
  (§3.10).
- `agents/_langfuse_config.py` (§3.11) — only after confirming
  Langfuse OTel is configured by another path.
- `agents/studio_compositor/random_mode.py::run()` body (§3.1) —
  keep `MUTATION_FILE` + `CONTROL_FILE` constants (still imported by
  `preset_recruitment_consumer.py:36`) but delete `run`,
  `transition_in`, `transition_out`, `_read_recruited_family`,
  `apply_graph_with_brightness` and the `__main__` block.

**S7 — Programme consumer Phase 2 (operator-priority decision):**
- §4.1 — execute Phases 2-12 of
  `docs/superpowers/plans/2026-04-20-programme-layer-plan.md` per its
  own ordering. Out of audit-remediation scope.

**S8 — Less-urgent installs (1 PR each, low-priority):**
- `hapax-soundcloud-sync.timer` (§3.6).
- `hapax-rebuild-gst-plugins.timer` (§3.7).
- `vault_canvas_writer` scheduling (§4.2).
- youtube-viewer-count.txt publisher decision (§4.6).
- SDLC scripts in CI verification (§8).

## §10. Open questions

1. **WardFxReactor payload schema.** §3.2 fix involves switching to
   the canonical recruitment path, but the payload schema differs
   from the `compositional_consumer.py` upsert. Should the reactor
   use the upsert pattern (additive) or the replace pattern (current)?
   The chain mutator (§3.1) reads via `compositional_consumer.py:1557
   recent_recruitment_age_s("preset.bias")` — the safest pattern is
   additive upsert under a new key (e.g. `ward.preset_bias`) so
   existing director-driven `preset.bias` semantics aren't disturbed.

2. **Mental-state redaction stream-vs-private gating.** §3.8 requires
   knowing whether stream is publicly visible. Is the gate consent-
   contract-active OR `stream-mode-intent.json` based OR both? The
   spec is in
   `docs/superpowers/specs/2026-04-15-lrr-phase-6-governance-finalization-design.md`
   §4.E but I did not exhaust its conditional ladder.

3. **BPM source.** §4.3 — does the operator want a librosa-based
   publisher (audio-driven), an MPC-pad-clock-based publisher
   (MIDI-driven), or just to delete the unused vinyl-BPM
   compensation path entirely?

4. **Programme go-live timing.** §4.1 — the plan defers 11 phases
   post-go-live. Has go-live happened? If yes, Phase 2 should jump
   the audit-remediation queue.

5. **`hapax-kdeconnect-bridge.service` etc.** §7 — I judged these as
   "intentional, hardware-conditional" non-installs. Operator
   confirmation requested for each.

## §11. Sources (file:line references)

Every claim in §3-§7 is backed by one or more of:

- `agents/studio_compositor/random_mode.py:107-186` — dead-bridge
  `run()` body.
- `agents/studio_compositor/random_mode.py:24-28` — Drop #46 MB-1
  10 Hz write-rate comment that orphans without the loop running.
- `agents/studio_compositor/random_mode.py:36` —
  `MUTATION_FILE = SHM / "graph-mutation.json"` constant still used
  by the replacement consumer.
- `agents/studio_compositor/preset_recruitment_consumer.py:36` —
  imports `MUTATION_FILE` from `random_mode`.
- `agents/studio_compositor/preset_recruitment_consumer.py:55-110` —
  `process_preset_recruitment()` definition.
- `agents/studio_compositor/preset_recruitment_consumer.py:40` —
  canonical recruitment path.
- `agents/studio_compositor/state.py:542-555` — wiring of
  `process_preset_recruitment` into `state_reader_loop` (the live
  replacement bridge).
- `agents/studio_compositor/state.py:195` —
  `def state_reader_loop`.
- `agents/studio_compositor/lifecycle.py:344-345` — spawns
  `state_reader_loop` thread.
- `agents/studio_compositor/fx_chain_ward_reactor.py:69` — wrong
  `_RECENT_RECRUITMENT_PATH` literal (§3.2).
- `agents/studio_compositor/fx_chain_ward_reactor.py:252-268` —
  `_bias_preset_family` writer.
- `agents/studio_compositor/lifecycle.py:240-247` — `WardFxReactor()`
  instantiation + `.connect()`.
- `agents/studio_compositor/compositional_consumer.py:112` —
  canonical recruitment path.
- `agents/studio_compositor/compositional_consumer.py:1534-1556` —
  upsert pattern reference for §3.2 fix.
- `agents/studio_compositor/compositional_consumer.py:1557` —
  `recent_recruitment_age_s` reader entry point.
- `agents/studio_compositor/preset_family_selector.py:8` —
  recruitment path docstring.
- `agents/studio_compositor/preset_family_selector.py:230-310` —
  `pick_with_scene_bias` definition (§3.9).
- `agents/studio_compositor/preset_family_selector.py:313-369` —
  `pick_and_load_mutated` (the function consumer-side calls
  instead).
- `agents/studio_compositor/scene_classifier.py:11` — docstring-only
  reference to `pick_with_scene_bias`.
- `agents/studio_compositor/hothouse_sources.py:75` —
  `_PRESENCE_STATE` reads `~/.cache/...presence-state.json` (wrong
  path).
- `agents/studio_compositor/hothouse_sources.py:76` —
  `_RECENT_RECRUITMENT` correctly uses `/dev/shm/hapax-compositor/`.
- `agents/studio_compositor/hothouse_sources.py:77` —
  `_YOUTUBE_VIEWER_COUNT` reader (§4.6).
- `agents/studio_compositor/hardm_source.py:100` — recruitment
  reader (canonical path).
- `agents/hapax_daimonion/rode_wireless_adapter.py` — writer of
  `voice-source.txt` (only dead because the unit isn't installed).
- `agents/hapax_daimonion/cpal/stt_source_resolver.py` — reader of
  `voice-source.txt`.
- `agents/hapax_daimonion/presence_engine.py:107, 192` — presence
  is exposed as behavior dict but no SHM write.
- `shared/programme.py:252` — `class Programme(BaseModel)` (§4.1).
- `shared/programme.py` (whole file) — 312 LOC, no production
  importers.
- `shared/governance/mental_state_redaction.py` — full file, no
  production callers.
- `shared/vinyl_rate.py:33-36, 116-134` — `current-bpm.txt` reader
  with no writer (§4.3).
- `shared/perceptual_field.py:45` — second `_PRESENCE_STATE` reader
  using the canonical `/dev/shm/...` path (§4.4).
- `agents/manifests/imagination_resolver.yaml:11` — wrong-path
  manifest declaration (§4.5).
- `agents/_affordance_metrics.py` — re-export shim with no importers
  (§3.10).
- `logos/_affordance_metrics.py` — parallel shim, no importers (§3.10).
- `agents/_langfuse_config.py` — side-effect import shim with no
  importers (§3.11).
- `systemd/units/hapax-environmental-emphasis.service` — exists in
  repo, not installed (§3.5).
- `systemd/units/hapax-environmental-emphasis.timer` — exists in
  repo, not installed (§3.5).
- `systemd/units/hapax-stream-auto-private.service` — exists in repo,
  not installed (§3.4).
- `systemd/units/hapax-stream-auto-private.timer` — exists in repo,
  not installed (§3.4).
- `systemd/units/hapax-rode-wireless-adapter.service` — exists in
  repo, not installed (§3.3).
- `systemd/units/hapax-soundcloud-sync.service` + `.timer` — exists
  in repo, not installed (§3.6).
- `systemd/units/hapax-rebuild-gst-plugins.service` + `.timer` —
  exists in repo, not installed (§3.7).
- Live verification artifacts:
  - `stat /dev/shm/hapax/recent-recruitment.json` — file exists,
    last-modified today, evidence the writer is alive but unread.
  - `cat /dev/shm/hapax-compositor/recent-recruitment.json` — 17-key
    canonical recruitment manifest, no entries from
    `WardFxReactor`.
  - `systemctl --user is-active studio-compositor` — `active`
    (state_reader_loop is running).
  - `ls /dev/shm/hapax-daimonion/presence-state.json` — does not
    exist.
  - `ls /dev/shm/hapax-compositor/current-bpm.txt` — does not exist.
  - `ls /dev/shm/hapax-compositor/youtube-viewer-count.txt` — does
    not exist.
  - `systemctl --user is-enabled hapax-{rode-wireless-adapter,stream-auto-private,environmental-emphasis,soundcloud-sync,rebuild-gst-plugins}.*`
    — all return `not-found`.

— end of audit —
