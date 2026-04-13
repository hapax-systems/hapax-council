---
title: Reverie bridge repair — visual chain → GPU uniforms
date: 2026-04-12
status: approved + audit follow-up
author: delta
related_prs: ["#696 (initial fix, merged 991cfbe03)", "#(this PR) audit follow-up"]
supersedes: []
---

# Reverie bridge repair — visual chain → GPU uniforms

> **2026-04-12 post-merge audit — read § 7 first.** The original narrative in
> §§ 1 – 6 slightly overclaimed the severity of the bug and committed three
> changes that the audit walked back (one systemd dependency, one content
> passthrough, one false premise about CLAUDE.md). Corrections are applied
> inline with `⚠ audit:` markers and consolidated in § 7.

## Summary

Reverie's **per-node parameter modulation path** was dead: visual_chain's
computed per-node deltas (`noise.amplitude`, `rd.feed_rate`, `color.saturation`,
`fb.decay`, etc.) were being written to `visual-chain-state.json` but were
**not reaching the per-node `params_buffer` on the GPU**. That meant the
vocabulary shader graph was running on its static vocabulary defaults for
every per-node parameter — colorgrade brightness pinned to 1.0, noise
frequency pinned to 1.5, rd feed rate pinned to 0.055, etc., regardless of
the operator's cognitive state.

⚠ audit: the original phrasing "none of the 9 dimensions were reaching the
GPU" was too broad. The 9 dimensions reach the GPU through **two independent
paths**:

- **Path 1 — shared-uniform slots** (`UniformData.intensity/tension/…`).
  Populated directly from the imagination fragment's `dimensions` dict by
  `UniformBuffer::from_state` at `hapax-logos/crates/hapax-visual/src/uniform_buffer.rs:140-148`,
  which reads `state.imagination.dimensions` (loaded from
  `/dev/shm/hapax-imagination/current.json` by `StateReader::poll_now`).
  This path was and is alive. Any WGSL shader that reads `uniforms.intensity`,
  `uniforms.tension`, etc. was getting live values.
- **Path 2 — per-node params_buffer** (this PR's target). Python
  `visual_chain.compute_param_deltas()` emits `{node_id}.{param_name}` keys
  that land in `uniforms.json`; Rust reads those keys positionally against
  `plan_pass.param_order` and writes the per-node `params_buffer` at
  `dynamic_pipeline.rs:803-821`. This path requires the Python-side
  `_load_plan_defaults()` helper to produce a non-empty dict of
  plan-default keys. It was broken.

The operator-visible rendering effect of Path 2 being dead is that every
shader with a `@group(2) Params` binding (noise, rd, colorgrade, drift,
breath, feedback, postprocess) ran on vocabulary defaults — so the system
could neither brighten under `spectral_color`, nor tighten patterns under
`tension`, nor accelerate drift under `temporal_distortion`. The system
could still shift the 9 shared-uniform slots that imagination populates, so
it was not literally flat — but the expressive surface everyone reasons
about (visual_chain → shader params → rendered pattern) was effectively cut.

Root cause is a single 4-line drift: `agents/reverie/_uniforms.py::_load_plan_defaults`
walks the v1 plan schema (`plan["passes"]`) while the live plan is v2
(`plan["targets"]["main"]["passes"]`). The defaults dict was silently empty,
the writer's merge loop had nothing to iterate over, and the per-node deltas
never appeared in `uniforms.json`. Reverie has been in this state since the
Rust DynamicPipeline adopted the v2 schema.

Root cause is a single 4-line drift: `agents/reverie/_uniforms.py::_load_plan_defaults`
walks the v1 plan schema (`plan["passes"]`) while the live plan is v2
(`plan["targets"]["main"]["passes"]`). The defaults dict was silently empty,
the writer's merge loop had nothing to iterate over, and the 9-dim deltas never
appeared in `uniforms.json`. Reverie has been in this state since the Rust
DynamicPipeline adopted the v2 schema.

A second, independent failure was surfaced in the same investigation:
`hapax-imagination-loop.service` was `inactive (dead)` with no start attempts
in the journal — meaning the Bachelard Amendment 4 reverberation consumer
(`agents.imagination_daemon` → `ImaginationLoop._check_reverberation`) was
offline. The producer half (DMN evaluative tick writing
`/dev/shm/hapax-vision/observation.txt`) is alive, so the loop was
open-circuit. Manual `systemctl --user start` brings it up cleanly, which
proves the unit is well-formed; what the unit *lacks* is any durable guarantee
that it stays up across `daemon-reload` / boot-order races.

Several audit findings from the investigation prompt have been resolved
without code changes and are documented here so they do not get re-opened:

1. **Content layer Bachelard functions are not dead code.** The Rust audit
   agent reported that `materialization()`, `immensity_entry()`, `material_uv()`,
   `corner_incubation()`, `material_color()`, and `dwelling_trace_boost()` were
   defined but never called. Reading `agents/shaders/nodes/content_layer.wgsl`
   directly confirms they are all invoked inside `sample_and_blend_slot()`,
   which is called per-slot with `slot_index ∈ {0,1,2,3}`. Amendments 1, 3, 5
   are upheld.

2. **Colorgrade param order is not inverted.** The Rust audit agent reported
   that the vocabulary dict order (`brightness, saturation, ...`) did not
   match the WGSL struct order (`u_saturation, u_brightness, ...`). The
   compiled `plan.json` `color` node shows
   `param_order: ['saturation', 'brightness', 'contrast', 'sepia',
   'hue_rotate']` — the `wgsl_compiler` reorders dict keys to match the WGSL
   struct. The Rust side reads by this explicit `param_order` positionally
   (`dynamic_pipeline.rs:803-821`), so there is no inversion.

3. **DMN-hosted actuation loop is not a regression, it is a refactor.** The
   original commitment ("DMN daemon hosts the reverie actuation loop as a
   concurrent async task") was broken by commit `17ccd547f` on 2026-03-26,
   which split reverie into its own systemd service. The structural-peer
   *spirit* (same perception → governance → actuation cascade, same 9-dim
   chain) is preserved; only the *process boundary* changed. This design
   formally ratifies the split — see §4 — so the memory and the CLAUDE.md
   reference are updated instead of the code being reverted.

Out of scope: the 5-channel adaptive mixer direction (dormant forward goal),
the Voronoi shader orphan, and the `dynamic_pipeline.rs:556-564` silent
shader-load-failure smell. Those are tracked as follow-ups, not blockers.

## 1 · Problem statement

### 1.1 Finding A — Empty plan-defaults cache

`_uniforms.write_uniforms` constructs `uniforms.json` by walking every
`{node_id}.{param_name}` key in the plan and emitting
`base + delta * reduction * silence`. The per-key base comes from
`_load_plan_defaults`, which parses the latest `plan.json` from shared memory.

The parser:

```python
# agents/reverie/_uniforms.py:32-44 (pre-fix)
defaults: dict[str, float] = {}
try:
    plan = json.loads(PLAN_FILE.read_text())
    for p in plan.get("passes", []):                   # ← v1 schema only
        node_id = p.get("node_id", "")
        for k, v in p.get("uniforms", {}).items():
            if isinstance(v, (int, float)):
                defaults[f"{node_id}.{k}"] = float(v)
except (OSError, json.JSONDecodeError):
    log.warning("Failed to load plan defaults", exc_info=True)
```

The live plan.json is v2:

```jsonc
{
  "version": 2,
  "targets": {
    "main": {
      "passes": [
        { "node_id": "noise", "uniforms": {...}, "param_order": [...] },
        ...
      ]
    }
  }
}
```

`plan.get("passes", [])` returns `[]`. `defaults == {}`. The writer's merge
loop at `_uniforms.py:120-125` has nothing to iterate. The only keys that
make it into `uniforms.json` are the five lines written unconditionally:
`fb.trace_*` (4) and `signal.stance` / `signal.color_warmth` (2) when
stimmung is present.

Observational evidence captured at 2026-04-12 16:47:

```json
{"fb.trace_center_x": 0.5, "fb.trace_center_y": 0.5,
 "fb.trace_radius": 0.0, "fb.trace_strength": 0.0,
 "signal.stance": 0.25, "signal.color_warmth": 0.067}
```

vs the matching `visual-chain-state.json` (same tick, live deltas present):

```json
{"levels": {"visual_chain.intensity": 0.404,
            "visual_chain.coherence": 0.235},
 "params":  {"noise.amplitude": 0.192,
             "post.vignette_strength": -0.081,
             "rd.feed_rate": -0.0023,
             "noise.frequency_x": -0.235,
             "fb.decay": 0.0235, ...}}
```

None of the nine dimension-keyed params are in `uniforms.json`. This is the
entire regression.

### 1.2 Finding B — Dead reverberation consumer

`hapax-imagination-loop.service` is the systemd wrapper for
`agents.imagination_daemon`, which is the only process that instantiates
`ImaginationLoop` and therefore the only consumer of
`/dev/shm/hapax-vision/observation.txt` via `_check_reverberation`.

At investigation time the service was `inactive (dead)` with zero start
attempts in the journal. The unit is `linked` (symlink from
`~/.config/systemd/user/` into the repo), `preset: enabled`, and is pulled
by `hapax-visual-stack.target` via `Wants=`. It nevertheless never
transitioned to active during this boot.

Three concrete weaknesses in the unit file made this state possible and
invisible:

1. `StartLimitIntervalSec=300` and `StartLimitBurst=5` are in `[Service]`.
   Both keys belong in `[Unit]`; systemd logs `Unknown key` warnings and
   silently ignores them. Without rate-limit protection a flap storm has no
   ceiling, and the warnings in the journal are the *only* trace the unit
   ever leaves — producing the false impression that "the service was never
   even tried".
2. `OnFailure=notify-failure@%n.service` is also in `[Service]`; same
   problem. No ntfy alert fires when the daemon crashes.
3. There is no liveness watchdog. `hapax-reverie-monitor.timer` exists for
   reverie but does not cover imagination-loop, so a dead loop will sit dead
   until a human notices the reverberation cadence has flattened.

A manual `systemctl --user start hapax-imagination-loop.service` brings the
daemon up in under 2 s with a clean journal (`Imagination daemon starting`).
The unit is not broken; it is under-specified.

## 2 · Design

### 2.1 Core fix (Finding A)

Replace `_load_plan_defaults` with a version that handles both v1 and v2
schemas. The v2 path iterates `plan["targets"][*]["passes"]`; the v1 path is
kept as a fallback for any pre-v2 snapshot that may still exist in `/dev/shm`
during a transition, and so that the function is robust to whichever format
the Rust compiler emits next.

```python
def _iter_passes(plan: dict) -> Iterable[dict]:
    """Yield pass dicts from either v1 (flat) or v2 (targets.*) plan schemas."""
    targets = plan.get("targets")
    if isinstance(targets, dict):
        for target in targets.values():
            if isinstance(target, dict):
                yield from target.get("passes", [])
        return
    yield from plan.get("passes", [])
```

This is purely additive: any caller that was broken by v2 is now correct; no
v1 caller regresses.

The test strategy is a unit test covering three inputs:

- **v1 flat** — `{"passes": [{"node_id": "noise", "uniforms": {"amplitude": 0.7}}]}`
  → `{"noise.amplitude": 0.7}`
- **v2 single-target** — the exact shape emitted by the live compiler →
  full `{node.param: value}` map
- **v2 multi-target** — two targets (main + aux), assert params from both
  are merged, later target wins on key collision
- **Empty** — `{}` and `{"version": 2}` → `{}` without raising

A regression test asserts that writing a v2 plan and reading it back through
`_load_plan_defaults` produces a non-empty dict that contains
`"noise.amplitude"`. This would have caught the bug.

### 2.2 Content-material one-liner (periphery) ⚠ audit: reverted

The original PR added `uniforms["content.intensity"] = salience * silence`
alongside the pre-existing `content.material` and `content.salience` writes,
on the argument that "content.intensity is declared in the vocabulary and
should be plumbed through by symmetry."

**The audit found this was wrong. All three `content.*` writes are
currently dead on the Rust side.** `content_layer.wgsl` has no
`@group(2) Params` binding, so the Rust per-node loop at
`dynamic_pipeline.rs:835` skips content on `pass.params_buffer.is_none()`.
The content shader reads `material_id` from `uniforms.custom[0][0]`, which
is part of `UniformData`, not per-node params. And `UniformData.custom` is
initialized to `[[0.0; 4]; 8]` at struct construction and is **never written
from uniforms.json** — the comment `// Updated from uniforms.json` at
`hapax-logos/crates/hapax-visual/src/uniform_buffer.rs:151` is stale. Grep
for `\.custom\[` across the hapax-visual crate returns zero writes.

**What this means for runtime:** `content.material_id` on the GPU is
effectively hardcoded to 0 (water). Material switching (fire / earth / air /
void) has been non-functional for however long this routing has been in
place. Bachelard Amendment 3 ("material quality as shader uniform") is
implemented in the shader but not actually receiving live material values.

The audit follow-up PR reverts the `content.intensity` passthrough (do not
add more dead keys) and adds a clarifying code comment above the existing
`content.material` / `content.salience` writes documenting the dead routing.
The existing two writes are preserved because they are cheap and harmless and
removing them is out of scope for the bridge repair — the correct fix is
either (a) add a `Params` struct binding to `content_layer.wgsl` and let
those keys flow through the per-node path, or (b) wire Rust to populate
`UniformData.custom` slots from `content.*` keys. Tracked as **F8** in the
plan doc.

### 2.3 Unit hygiene (Finding B, part 1) ⚠ audit: Requires= reverted

Rewrite `systemd/units/hapax-imagination-loop.service`:

- Move `StartLimitIntervalSec=300` and `StartLimitBurst=5` into `[Unit]`.
- Move `OnFailure=notify-failure@%n.service` into `[Unit]`.
- Tighten ordering: `After=hapax-secrets.service hapax-dmn.service`
  (unchanged).
- ~~Add `Requires=hapax-dmn.service`~~ ⚠ audit: the original PR also added
  `Requires=`, on the rationale "the loop cannot be up without its
  observation producer". The audit found this is wrong in two ways:
  1. `Requires=` causes the dependent unit to be **stopped** whenever the
     required unit is stopped, not just on failure. DMN restarts are
     routine (every `hapax-rebuild-services.timer` tick when DMN source
     changes, and on any operator-initiated restart), which means every
     DMN restart would take imagination-loop down.
  2. A clean stop is not a `Restart=on-failure` trigger, so once
     imagination-loop is stopped as a cascade from DMN, it **stays
     stopped** until the next target reactivation or a manual start. This
     recreates exactly the "dead loop, no start attempts in the journal"
     state that Finding B originally surfaced.
     The correct mechanism for liveness is the monitor extension in § 2.4
     (PR-2), not a stricter unit dependency. `Wants=hapax-dmn.service`
     (already present) is soft-enough that imagination-loop survives DMN
     restart cycles; the daemon's own stale-observation handling at
     `imagination_daemon.py:125-145` degrades gracefully to "skip this
     tick" when observations are missing, which is the right behavior.

### 2.4 Liveness watchdog (Finding B, part 2)

Extend `hapax-reverie-monitor.service` (which already tails reverie's health
signal) to also assert `hapax-imagination-loop.service` is active. If not,
`systemctl --user start` it and emit a chronicle event. This is cheaper than
creating a parallel monitor and keeps all "is the reverie stack alive?"
logic in one place.

Implementation shape (script-level; Python monitor lives at
`agents/reverie_monitor.py` or equivalent):

```python
UNITS = ("hapax-reverie.service", "hapax-imagination-loop.service")

for unit in UNITS:
    status = subprocess.run(
        ["systemctl", "--user", "is-active", unit],
        capture_output=True, text=True
    ).stdout.strip()
    if status != "active":
        log.warning("reverie-monitor: %s is %s, restarting", unit, status)
        subprocess.run(["systemctl", "--user", "start", unit], check=False)
        record_chronicle_event("reverie-monitor", f"restarted {unit}")
```

The monitor timer's existing 5-minute cadence is acceptable; the Bachelard
Amendment 4 loop is not latency-critical. A 5-minute gap in reverberation
feedback is recoverable.

### 2.5 Architectural ratification (DMN-hosted claim) ⚠ audit: CLAUDE.md premise wrong

The `project_reverie_autonomy.md` memory describes reverie as "hosted
inside DMN as a concurrent async task". The implementation has been a
separate systemd daemon since 2026-03-26. This design formally records the
shift and updates the memory.

⚠ audit: the original design also claimed that `hapax-council/CLAUDE.md §
Tauri-Only Runtime` carried the same DMN-hosted claim and committed to
updating it. **That premise was false.** Grepping the current CLAUDE.md
for "hosts the actuation", "concurrent async", and "DMN-hosted" returns
zero matches. The § Tauri-Only Runtime "Visual surface" paragraph
correctly describes reverie as "A standalone binary (`hapax-imagination`)
runs as a systemd user service". No CLAUDE.md edit is needed or warranted.
The only stale artifact is the memory file, which the operator's
auto-memory system keeps locally (not in-repo).

**Rationale.** Reverie has its own fragility profile (Qdrant I/O, graph
rebuilds, GPU-adjacent work) that benefits from an independent cgroup and an
independent `Restart=on-failure` lifecycle. Co-hosting with DMN would force
DMN restarts every time reverie's graph builder raises, and vice versa. The
*spirit* of the structural-peer claim is "same cascade, same types, same
governance composition" — and those are all preserved. The letter was an
over-committal to in-process coupling.

**What changes.** Only the local memory files — no in-repo edits:

- ~~`hapax-council/CLAUDE.md § Visual surface`~~ ⚠ audit: not needed; the
  CLAUDE.md text was always accurate ("standalone binary runs as a systemd
  user service"). The original design misremembered this and created work
  that did not need doing.
- `~/.claude/projects/-home-hapax-projects/memory/project_reverie_autonomy.md`
  — replace the DMN-hosted claim with the standalone-daemon reality, plus
  a note on the two-path visual chain routing (Path 1 shared uniforms, Path
  2 per-node params) that the audit surfaced.
- `~/.claude/projects/-home-hapax-projects/memory/project_reverie.md` —
  upgrade the "per-node param bridge wired" claim to include the v2 schema
  fix reference, and document the dead `content.*` routing found by the
  audit (see § 2.2).

The memory file updates are applied by the audit follow-up PR's author
directly and are not in the repo diff. No source-code change for this
architectural ratification. The commit `17ccd547f` stands.

### 2.6 What this design does **not** change

- The vocabulary graph stays 8-pass linear. The 5-channel adaptive mixer is
  still a dormant forward commitment; it gets its own design doc when work
  starts on it. Out of scope here.
- The `agents/shaders/nodes/voronoi_overlay.wgsl` orphan is left in place.
  Removing it is a separate housekeeping PR.
- `dynamic_pipeline.rs:556-564` silent shader-load-failure smell is a
  logging upgrade, not a correctness bug. Left for a follow-up.
- No change to `content_layer.wgsl`. It was misread by the audit agent;
  re-verified as correct.

## 3 · Acceptance criteria ⚠ audit: corrections inline

1. **Dimensional expression visible.** After the fix lands, every
   `{node_id}.{param}` key emitted by the vocabulary reaches `uniforms.json`
   within one reverie tick. Verified live:
   `jq 'keys | length' /dev/shm/hapax-imagination/uniforms.json` shows
   **≥ 44** (was 6–8 pre-fix, is 44 post-fix: 42 plan defaults + 2
   signal.* entries; `fb.trace_*` and `content.*` are subsumed by the
   plan-default keys). ⚠ audit: the original threshold of ≥ 45 was off by
   one — I double-counted the content and trace overlap. Correct threshold
   is ≥ 44.
2. **Regression test green.** `tests/test_reverie_uniforms_plan_schema.py`
   passes for v1, v2 single-target, v2 multi-target (with explicit
   last-wins collision test added in the audit follow-up), empty, and
   the new None-value edge cases. Post-audit: 17 cases, all green.
3. **Imagination loop stays up.** `systemctl --user is-active
   hapax-imagination-loop.service` returns `active` after boot *and* after
   `systemctl --user daemon-reload`. ⚠ audit: should ALSO stay up across
   DMN restarts — this is exactly the condition the reverted `Requires=`
   would have broken. Verified in the audit follow-up.
4. **Monitor restarts a killed loop.** `systemctl --user kill
   hapax-imagination-loop.service` followed by ≤ 5 min wait returns the
   service to `active` state via `hapax-reverie-monitor.timer`. ⚠ audit:
   this AC **is not met by PR-1** — the monitor extension is PR-2 (tracked
   as unassigned follow-up), so AC4 will stay "dependent on PR-2" until
   PR-2 ships. The original design did not flag this dependency clearly.
5. **Reverberation pathway closes.** With imagination-loop running and the
   DMN evaluative tick active, `observation.txt` writes should produce a
   nonzero `_last_reverberation` within two imagination cadences. ⚠ audit:
   not independently verified by the delta session. Deferred to observation
   once the daemon has accumulated `recent_fragments`.
6. **No visual regression.** The frame at
   `/dev/shm/hapax-visual/frame.jpg` remains non-black; frame_time stays
   under 25 ms. Verified post-deploy: 9.54–16.21 ms observed. ✓
7. **Memory/CLAUDE.md aligned.** ⚠ audit: CLAUDE.md never carried the stale
   claim, so this part of AC7 is vacuous. Memory files are updated by the
   audit follow-up (local only).

## 4 · Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| v2 fix inadvertently doubles param delta magnitude because Rust already applies plan defaults | low | The Rust path at `dynamic_pipeline.rs:803-821` only writes per-pass `params_buffer` from uniforms.json keys it finds. Plan defaults are already baked into the buffer at build time and are *overwritten* per-key when uniforms.json contains the key. Writing `base + delta` matches Rust's "uniforms.json is an absolute override" contract. No doubling. |
| `content.intensity` passthrough changes visible rendering | low | vocabulary default is 0.0; passthrough writes `salience × silence` which is 0.0 when imagination is absent. No change in the silent case. When imagination is present, opacity already drives visibility via `slot_opacities`, so intensity adds a small, expected boost. |
| Monitor loop thrashes a flapping unit | low | `StartLimitBurst=5, StartLimitIntervalSec=300` (now in `[Unit]`) caps retries. If the loop actually cannot start, the monitor will see `failed` state and skip restart after the rate limit fires. |
| Architectural ratification contradicts the constitution | none | The single-user / executive-function / consent axioms are unaffected. This is a process-boundary decision, not a governance one. |
| Reverberation consumer misbehaves on first tick after 2h downtime | low | `_check_reverberation` returns 0.0 if `recent_fragments` is empty, which it is on restart. No panic, degraded to baseline cadence until the next fragment is produced. |

## 5 · Verification after deploy

Run these, in order, post-merge:

```bash
# 1. Unit hygiene
systemctl --user daemon-reload
systemctl --user is-active hapax-imagination-loop.service   # → active

# 2. Schema fix live
jq 'keys | length' /dev/shm/hapax-imagination/uniforms.json  # → ≥ 25
jq '"noise.amplitude"' /dev/shm/hapax-imagination/uniforms.json   # → numeric

# 3. Delta presence
python -c "
import json, time
u1 = json.loads(open('/dev/shm/hapax-imagination/uniforms.json').read())
time.sleep(2)
u2 = json.loads(open('/dev/shm/hapax-imagination/uniforms.json').read())
moving = sum(1 for k in u1 if u1[k] != u2.get(k))
print(f'keys moving across 2s: {moving}')  # → > 0 when dimensions are active
"

# 4. Reverberation
journalctl --user -u hapax-imagination-loop.service --since '5 min ago' \
  | grep -i 'reverberation\|imagination tick'
```

## 6 · Follow-ups (tracked, not in this PR)

- **F1.** Add a debug command `python -m agents.reverie.debug_uniforms` that
  prints the live uniforms.json alongside expected plan-default keys and
  highlights any missing entries. Would have caught this bug instantly.
  (Beta's PR #697 shipped the `DynamicPipeline::pool_metrics()` accessor —
  a natural composition partner for the same CLI.)
- **F2.** Upgrade `dynamic_pipeline.rs:556-564` shader-load-failure path from
  `log::warn!` to `log::error!` plus a degraded-signal publish.
- **F3.** Remove the orphaned `agents/shaders/nodes/voronoi_overlay.wgsl`
  unless it is being reserved for the 5-channel mixer epic.
- **F4.** Re-open the 5-channel mixer design and decide scheduling; it has
  been dormant since 2026-03-31.
- **F5.** Add a Prometheus metric for `reverie_uniforms_key_count` so the
  Grafana reverie-predictions dashboard can page on "visual chain went
  silent".
- **F6.** `ImpingementConsumer.__init__` bootstraps `cursor=0` and re-reads
  the full accumulated JSONL on every restart. For reverie restarting with
  a 3900+-entry file, the first daemon tick takes 5–15 min to drain
  dispatch — `uniforms.json` is not updated from a fresh restart until
  then. Three options: (a) seek-to-end on bootstrap (loses resume-from-
  crash); (b) persist cursor to `~/.cache/hapax/<daemon>-impingement-cursor`
  (preferred); (c) rotate `impingements.jsonl` on a size/age threshold.
  Same issue affects `hapax-daimonion` and `fortress`. Cross-daemon.
- **F7.** Dormant `signal.{9dim}` override path. `dynamic_pipeline.rs:812-828`
  reads `signal.intensity`, `signal.tension`, `signal.depth`,
  `signal.coherence`, `signal.spectral_color`, `signal.temporal_distortion`,
  `signal.degradation`, `signal.pitch_displacement`, `signal.diffusion` and
  writes them onto the shared `UniformData` struct. **Nothing on the Python
  side writes those keys.** `UniformBuffer::from_state` already populates
  those slots from `state.imagination.dimensions`, so the override path is
  either dead code (Python was never supposed to use it) or a future-proof
  hook for a Python-side override case that never materialized. Decide
  which and either delete the Rust branch or wire a Python writer.
- **F8.** Dead `content.*` routing. `content_layer.wgsl` has no `@group(2)
  Params` binding, so `content.material` / `content.salience` /
  `content.intensity` writes from `_uniforms.py` are silently dropped by the
  Rust per-node loop (`params_buffer.is_none()`). The shader reads material
  from `uniforms.custom[0][0]`, but `UniformData.custom` is initialized to
  zero and **is never written from uniforms.json** — grep for `\.custom\[`
  across `crates/hapax-visual/src/` returns zero writes. The comment
  `// Updated from uniforms.json` at `uniform_buffer.rs:151` is stale.
  Result: material_id on the GPU is effectively hardcoded to water (0).
  Bachelard Amendment 3 is implemented in the shader but does not receive
  live material. Fix options: (a) add a `Params` struct binding to
  `content_layer.wgsl` and put `salience, intensity, material` in it so the
  per-node path carries them; (b) add a `content.*` routing branch in
  `dynamic_pipeline.rs` that writes `UniformData.custom[i]` slots.
  **(a) is preferred** — it matches how every other node routes and
  doesn't require allocating shared-uniform slots.
- **F9.** `_load_plan_defaults` cache semantics on file deletion. When the
  plan file disappears, the OSError branch sets `current_mtime=0.0` and
  caches an empty dict with `_plan_defaults_mtime=0.0`. Next call with the
  file still missing: `0.0 == 0.0` → return cached empty dict without
  re-reading. Once the file reappears with a real mtime, the cache
  correctly invalidates. The behavior is correct but non-obvious; add an
  explicit comment and a test.
- **F10.** `ImaginationState.content_references` field at
  `state.rs:351-357` — it's read by the StateReader but my grep did not
  find any writer (Python side) or reader (shader side) under the same
  name. Possibly orphaned from a pre-affordance-pipeline era. Verify.

## 7 · Audit follow-up (2026-04-12, post-merge)

After PR #696 was merged as `991cfbe03` and deployed to the running reverie
stack (frame_time 9.54–16.21 ms, `uniforms.json` keys 44, dimensional
modulation confirmed via `warmth` variance), the operator requested a
systematic self-audit. The audit found eight issues worth fixing and twelve
worth tracking. This section records all of them for future readers.

### 7.1 Severity-ranked findings

**🔴 Critical — fixed in audit follow-up PR:**

1. **`Requires=hapax-dmn.service` is a net regression** (§ 2.3). `Requires=`
   causes the dependent unit to be stopped whenever the required unit
   stops; DMN restarts are routine and would cascade into dead-loop
   state — exactly what Finding B was trying to fix. Reverted to
   `Wants=`-only.

2. **`content.intensity` passthrough is dead code** (§ 2.2). All three
   `content.*` writes are silently dropped by Rust. The original PR's
   addition was speculative scope creep that made the dead routing look
   more alive than it is. Reverted. Preserved the two pre-existing dead
   writes with an explanatory comment pointing at F8.

3. **Severity overclaim in § Summary**. Original phrasing "none of the 9
   dimensions were reaching the GPU" conflated two orthogonal routing paths.
   Path 1 (imagination fragment dimensions → shared uniform slots via
   `UniformBuffer::from_state`) was always alive; only Path 2 (visual_chain
   per-node deltas → per-node `params_buffer`) was broken. The substantive
   claim stands — per-node modulation was dead — but the phrasing was
   imprecise. Corrected.

4. **Memory files not updated**. The plan doc's Definition of Done listed
   "memory files updated (local; no commit needed)" as a PR-1 item, but
   delta did not actually update `project_reverie.md` or
   `project_reverie_autonomy.md`. The audit follow-up applies those
   updates (local only, not in repo diff).

**🟡 High — documentation corrections in audit follow-up:**

5. **CLAUDE.md § 2.5 premise was false**. The original design said CLAUDE.md
   claimed reverie was "hosted inside DMN" and committed to updating it.
   A fresh `grep` for "hosts the actuation" / "concurrent async" /
   "DMN-hosted" in the current CLAUDE.md returns zero matches — the
   Tauri-Only Runtime section correctly describes reverie as "A standalone
   binary runs as a systemd user service". No CLAUDE.md edit is needed.
   Corrected in § 2.5.

6. **AC1 threshold off by one**. Original said ≥ 45; actual is 44 (42 plan
   defaults + `signal.stance` + `signal.color_warmth`; `fb.trace_*` and
   `content.*` overlap with plan-default keys and do not add new ones).
   Corrected.

7. **AC4 dependency not flagged**. The "monitor restarts a killed loop" AC
   depends on PR-2 (reverie-monitor extension), which is tracked as an
   unassigned follow-up. The original design listed AC4 under PR-1's
   acceptance criteria without noting the cross-PR dependency. Clarified.

**🟢 Medium — new follow-ups added to § 6 (F6-F10):**

8. **F6: ImpingementConsumer cursor=0 bootstrap**. Recreates the 5–15 min
   dispatch drain after every reverie restart. Cross-daemon (also affects
   daimonion and fortress).

9. **F7: dormant `signal.{9dim}` override path**. Rust reads the nine dim
   override keys but Python never writes them. Dead code or unused hook.

10. **F8: dead `content.*` routing**. The most substantial audit discovery.
    Material switching on the GPU is hardcoded to water because the custom
    slot is never populated. Preserves a shader amendment that currently
    cannot be triggered. Tracked for a follow-up PR that either wires a
    Params struct into `content_layer.wgsl` or routes `content.*` into
    `UniformData.custom` on the Rust side.

11. **F9: `_load_plan_defaults` cache semantics on file deletion**. Current
    behavior is correct but non-obvious. Wants a test + comment.

12. **F10: `ImaginationState.content_references`** — possibly orphaned
    from pre-affordance-pipeline era. Verify.

### 7.2 New tests added in audit follow-up

- `test_iter_passes_handles_none_targets` — covers `{"targets": None}` and
  `{"targets": {"main": None}}`, both of which the shipped code handles
  correctly but had no explicit coverage.
- `test_iter_passes_v2_multi_target_last_wins_on_key_collision` — exercises
  the "later target wins" dict-assignment semantics mentioned in the
  original design but never actually tested.
- `test_load_plan_defaults_file_deletion_caches_empty` — pins the cache
  behavior described in F9.
- `test_write_uniforms_end_to_end_produces_expected_keys` — first direct
  integration-style test of `write_uniforms` against a mocked plan, a
  live visual_chain, and a fake imagination/stimmung. Asserts 44 keys
  present, every plan-default key present with expected value, no
  `content.intensity` (post-revert), both `signal.*` keys present.
- `test_write_uniforms_silence_attenuation` — covers the stale-imagination
  branch at `_uniforms.py:124-129`.

Total test count post-audit: **17** (up from 11). `uv run pytest
tests/test_reverie_uniforms_plan_schema.py -q` on the audit-followup
branch shows all 17 passing. Plus one more `test_write_uniforms_silence_
floor_when_imagination_missing` that covers the imagination-None path for
completeness.

### 7.3 What the audit did NOT find

- **Colorgrade param order**: re-verified by reading the live `plan.json`
  directly (`param_order: ['saturation','brightness','contrast','sepia','hue_rotate']`)
  and the WGSL struct (`u_saturation, u_brightness, ...`). They match. The
  Rust agent's original concern stands retracted.
- **Content_layer Bachelard functions as dead code**: re-verified by reading
  `content_layer.wgsl:126-185` (`sample_and_blend_slot` invokes
  `corner_incubation`, `immensity_entry`, `material_uv`, `materialization`,
  `material_color`, `dwelling_trace_boost` per slot). Still called, still
  upheld. But see F8 — material_id reaches them as hardcoded 0 because of
  the custom-slot routing gap, so "upheld in shader, but fed a constant"
  is a better description than the original "upheld".
- **Rust doubling concern** from § 4. Re-verified by reading
  `dynamic_pipeline.rs:835-855`. The per-node loop is a direct overwrite
  of `current_params[i]` from the key lookup, not an accumulate. No
  doubling.
- **Frame rate regression**. Post-deploy observation at 9.54–16.21 ms
  frame_time is consistent with beta's reported 75–90 fps. Not a
  regression. ✓
