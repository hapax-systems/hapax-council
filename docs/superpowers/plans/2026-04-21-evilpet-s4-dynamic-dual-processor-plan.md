# Evil Pet + S-4 Dynamic Dual-Processor Routing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the dual-engine dynamic routing design per `docs/superpowers/specs/2026-04-21-evilpet-s4-dynamic-dual-processor-design.md`. Deliver 12 topology classes (5 new dual-engine + 7 preserved), 10 use-cases, and a 5 Hz arbiter agent that drives both processors simultaneously under stimmung / programme / impingement control.

**Architecture:** Three phases. Phase A (5 tasks, ~100 LOC) ships software-only fixes without S-4 hardware. Phase B (6 tasks, ~500 LOC) activates when S-4 plugs in: USB enumeration, MIDI lane, dynamic router agent, scene library, companion presets, integration tests. Phase C (5 tasks, ~200 LOC) adds production dynamism: ramp-responsiveness, utterance-boundary semantics, observability closure, dry-run, WARD classifier pre-render.

**Tech Stack:** Python 3.12+ (pydantic, pydantic-ai, pytest, mido), PipeWire filter-chain + loopback + rules, MIDI (via Erica Dispatch + `mido`), Prometheus counters/histograms, Langfuse events, systemd user units for the router daemon.

**Preserved operator constraints** (from prior plan, unchanged):
- All level control software-side (L-12 physical faders drive MONITOR only, NOT broadcast capture).
- Evil Pet is the operator's only active analog monitor path (hardware loop).
- S-4 is USB-direct parallel (not serial after Evil Pet by default; serial only via D5 gesture).
- HARDM / CVS #8 / Ring-2 WARD governance gates non-negotiable.
- No feedback loops; fail-closed on governance.

**New constraints from this design:**
- Both processors engaged simultaneously on every broadcast tick (maximal).
- Routing decisions shift in response to context (dynamic, 5 Hz arbiter).
- No source reaches broadcast unprocessed unless governance-specified bypass active.

---

## Phase A — Software-only (S-4 absent)

### Task A1: Filter-chain drift fix — remove gain_pc_l/r from L-12 capture

**Files:**
- Modify: `config/pipewire/hapax-l12-evilpet-capture.conf`
- Modify: `tests/shared/test_evilpet_s4_gain_discipline.py` (comment-only update)
- Deploy: `~/.config/pipewire/pipewire.conf.d/hapax-l12-evilpet-capture.conf` (operator copies after PR merges)

- [x] **Step 1: Edit conf.** Remove `gain_pc_l` and `gain_pc_r` mixer nodes, remove their `sum_l:In 6` / `sum_r:In 6` links, null the AUX10 / AUX11 input bindings, reduce sum_l/sum_r to 5 inputs. (Done in this PR.)

- [x] **Step 2: Comment update in test.** Update `tests/shared/test_evilpet_s4_gain_discipline.py` comment to reflect that PC-line gain is no longer present; the expected set `{1.0, 1.5, 2.0, 4.0}` is unchanged because sum_l/sum_r still have unity-gain stages. (Comment update only; the set membership is preserved.)

- [x] **Step 3: Run gain discipline test.** `uv run pytest tests/shared/test_evilpet_s4_gain_discipline.py -v` — expected: pass.

- [ ] **Step 4: Deploy live (operator action).**

```bash
cp config/pipewire/hapax-l12-evilpet-capture.conf ~/.config/pipewire/pipewire.conf.d/
systemctl --user restart pipewire pipewire-pulse wireplumber
# Verify
pw-link -l | grep -B1 'hapax-livestream-tap:playback'
```

Expected: `hapax-livestream-tap:playback_FL/FR` is fed by `hapax-l12-evilpet-playback` only; `hapax-l12-evilpet-capture` has no AUX10/AUX11 → sum link.

- [x] **Step 5: Commit.** Bundled into this PR.

---

### Task A2: Hardware loop verification runbook

**Files:**
- Create: `docs/runbooks/evilpet-hardware-loop-verification.md`

- [ ] **Step 1: Write runbook.** 5-step operator procedure:
    1. On L-12: verify MONITOR A knob active on CH11/12; level at ~-3 dB on MONITOR A.
    2. Check Evil Pet OUT → CH1 XLR cable integrity (signal LED on CH1 should pulse with PC playback).
    3. Check CH1 fader up; CH1 should feed CH6 input per prior BROADCAST scene.
    4. Verify CH6 signal LED pulses with Evil Pet effect tail (not just instant attack).
    5. Confirm L-12 SD card BROADCAST scene is loaded (recall on panel).
- [ ] **Step 2: Link from runbook index** (`docs/runbooks/README.md`).
- [ ] **Step 3: Commit.**

---

### Task A3: Notification-sink isolation

**Files:**
- Create: `config/pipewire/hapax-notification-private.conf`
- Create: `config/wireplumber/92-hapax-notification-private.conf` (WP rule to retarget role.notification)
- Create: `tests/pipewire/test_notification_isolation.py`
- Deploy: user PipeWire + WirePlumber conf dirs

- [ ] **Step 1: Write failing test.**

```python
"""Notifications never reach broadcast."""
from pathlib import Path

def test_notification_sink_conf_exists():
    p = Path.home() / ".config/pipewire/pipewire.conf.d/hapax-notification-private.conf"
    assert p.exists(), "notification-private conf missing; deploy via cp"

def test_notification_sink_not_captured_by_l12_filter_chain():
    """The notification sink must not be producable into hapax-l12-evilpet-capture."""
    p = Path.home() / ".config/pipewire/pipewire.conf.d/hapax-notification-private.conf"
    content = p.read_text()
    assert "hapax-l12-evilpet-capture" not in content, \
        "notification sink may not target the L-12 filter-chain"
```

- [ ] **Step 2: Run test, observe fail** (conf missing).

- [ ] **Step 3: Write conf.** A PipeWire loopback that creates a `hapax-notification-private` sink targeting the L-12 MASTER OUT (operator monitor only — NOT the broadcast filter-chain).

- [ ] **Step 4: WirePlumber rule** retargets `media.role = "notification"` streams to `hapax-notification-private` instead of the default sink.

- [ ] **Step 5: Run test, observe pass.**

- [ ] **Step 6: Commit.**

---

### Task A4: State-surface audit + writer reinstatement

**Files:**
- Create: `scripts/hapax-audio-state-audit` (new diagnostic CLI)
- Modify: (TBD based on audit) — likely `agents/visual_layer_aggregator/*` or `agents/hapax_daimonion/stimmung_writer.py`

- [ ] **Step 1: Write audit CLI.** Python script that checks 4 state surfaces (stimmung, voice-tier, programme, evil-pet-state) for presence + freshness + JSON validity. Exits 0 if all healthy, 1 with report otherwise.

- [ ] **Step 2: Run audit.** `scripts/hapax-audio-state-audit`. Identify which surfaces are stale or missing.

- [ ] **Step 3: Reinstate writers.** Per-surface fix depends on audit output; each identified issue becomes a sub-task. Likely targets: stimmung_writer, voice-tier writer.

- [ ] **Step 4: Add to health_monitor** — register `state_surface_freshness` as a monitored signal. Alerts via ntfy on staleness > budget.

- [ ] **Step 5: Commit.**

---

### Task A5: Static S-4 sink producer

**Files:**
- Create: `config/pipewire/hapax-yt-to-s4-bridge.conf`
- Create: `tests/pipewire/test_yt_to_s4_bridge.py`
- Deploy: user PipeWire conf dir

- [ ] **Step 1: Write failing test.**

```python
def test_yt_to_s4_bridge_conf_exists():
    p = Path.home() / ".config/pipewire/pipewire.conf.d/hapax-yt-to-s4-bridge.conf"
    assert p.exists()

def test_yt_to_s4_bridge_producer_ok():
    """When S-4 USB is enumerated, hapax-yt-loudnorm-playback must feed hapax-s4-content."""
    import subprocess
    r = subprocess.run(["pw-link", "-l"], capture_output=True, text=True, timeout=5)
    has_s4 = "alsa_input.usb-Elektron_Torso" in r.stdout
    if not has_s4:
        pytest.skip("S-4 not plugged; bridge is dormant but conf should still load")
    assert "hapax-yt-loudnorm-playback:output_FL" in r.stdout
    assert "-> hapax-s4-content:playback_FL" in r.stdout
```

- [ ] **Step 2: Run test, observe fail/skip.**

- [ ] **Step 3: Write conf** — a PipeWire loopback from `hapax-yt-loudnorm-playback` into `hapax-s4-content`. If S-4 absent, loopback is a no-op (silent consumer).

- [ ] **Step 4: Run test, observe pass (skipped if S-4 absent).**

- [ ] **Step 5: Commit.**

---

## Phase B — S-4 online

### Task B1: S-4 USB enumeration + producer wiring

**Files:**
- Modify: `config/pipewire/hapax-s4-loopback.conf` (concretize target device name after enumeration)
- Create: `tests/pipewire/test_s4_live_enumeration.py`

- [ ] **Step 1: Operator plugs S-4 USB-C; verify.**

```bash
arecord -l | grep -i S-4
lsusb | grep -i Elektron
```

Expected: `alsa_input.usb-Elektron_Torso_S-4_*` appears as card; S-4 appears in lsusb with Elektron vendor ID.

- [ ] **Step 2: Update conf.** Replace the generic `target.object` pattern with the specific device name.

- [ ] **Step 3: Write integration test** (pactl + pw-link assertions).

- [ ] **Step 4: Run test, observe pass.**

- [ ] **Step 5: Commit.**

---

### Task B2: S-4 MIDI lane wiring

**Files:**
- Create: `shared/s4_midi.py` (new module)
- Create: `tests/shared/test_s4_midi.py`

- [ ] **Step 1: Physical wire.** Erica Dispatch OUT 2 → S-4 MIDI IN (DIN cable or TRS adapter per S-4 rear panel).

- [ ] **Step 2: Verify with `aconnect -l`.**

- [ ] **Step 3: Write failing test.**

```python
def test_s4_midi_output_available():
    from shared.s4_midi import find_s4_midi_output
    out = find_s4_midi_output()
    assert out is not None, "S-4 MIDI output not found"

def test_s4_program_change_emit():
    from shared.s4_midi import emit_program_change
    from unittest.mock import MagicMock
    mock_out = MagicMock()
    emit_program_change(mock_out, program=1, channel=0)
    assert mock_out.send.called
```

- [ ] **Step 4: Write `shared/s4_midi.py`.**

```python
"""S-4 MIDI interface — scene recall via program change + per-CC fallback."""
from __future__ import annotations
import logging
import time
from typing import Optional

import mido
from mido import Message

log = logging.getLogger(__name__)

S4_MIDI_CHANNEL = 0

def find_s4_midi_output() -> Optional[mido.ports.BaseOutput]:
    names = mido.get_output_names()
    for name in names:
        if "Torso" in name or "S-4" in name or "S_4" in name:
            return mido.open_output(name)
    for name in names:
        if "MIDI Dispatch" in name and "MIDI 2" in name:
            return mido.open_output(name)
    return None

def emit_program_change(output, program: int, channel: int = S4_MIDI_CHANNEL) -> None:
    msg = Message("program_change", program=program, channel=channel)
    try:
        output.send(msg)
    except Exception as e:
        log.error(f"S-4 program change emit failed: {e}")

def emit_cc(output, cc: int, value: int, channel: int = S4_MIDI_CHANNEL, delay_ms: float = 20.0) -> None:
    msg = Message("control_change", control=cc, value=value, channel=channel)
    try:
        output.send(msg)
        time.sleep(delay_ms / 1000.0)
    except Exception as e:
        log.error(f"S-4 CC emit failed ({cc}={value}): {e}")
```

- [ ] **Step 5: Run test, observe pass.**

- [ ] **Step 6: Commit.**

---

### Task B3: Dynamic router agent

**Files:**
- Create: `agents/audio_router/__init__.py`
- Create: `agents/audio_router/dynamic_router.py`
- Create: `agents/audio_router/state.py` (pydantic models per spec §6.1)
- Create: `agents/audio_router/policy.py` (3-layer policy per spec §6.2)
- Create: `systemd/units/hapax-audio-router.service`
- Create: `tests/audio_router/test_dynamic_router.py`

- [ ] **Step 1: Write failing tests.** ~10 tests covering: state-load, policy-layer-1-safety-clamps, policy-layer-2-lookup, policy-layer-3-salience-max-composition, arbitration-order, tick-cadence.

```python
def test_consent_critical_clamps_to_t0():
    state = make_router_state(consent_critical=True, stance="ENGAGED")
    intent = arbiter_tick(state)
    assert intent.evilpet_preset == "hapax-unadorned"
    assert intent.clamp_reasons == ["consent_critical"]

def test_mode_d_reroutes_voice_t5_to_s4():
    state = make_router_state(mode_d_active=True, impingement_tier_request=5)
    intent = arbiter_tick(state)
    assert intent.evilpet_preset != "hapax-granular-wash"
    assert intent.s4_vocal_scene == "VOCAL-MOSAIC"
    assert "mode_d_mutex" in intent.clamp_reasons
```

- [ ] **Step 2: Run tests, observe fail.**

- [ ] **Step 3: Implement router.** 5 Hz systemd-driven tick. Reads state, applies 3-layer policy, emits CC bursts + program changes + filter-chain gain writes.

- [ ] **Step 4: Implement state + policy modules** per spec §6.1 + §6.2.

- [ ] **Step 5: Ship systemd unit.**

```
[Unit]
Description=Hapax dynamic audio router (Evil Pet + S-4 arbiter)
After=pipewire.service hapax-secrets.service

[Service]
Type=simple
WorkingDirectory=%h/projects/hapax-council
ExecStart=%h/projects/hapax-council/.venv/bin/python -m agents.audio_router.dynamic_router
Restart=on-failure
RestartSec=2s

[Install]
WantedBy=default.target
```

- [ ] **Step 6: Run tests, observe pass.**

- [ ] **Step 7: Commit.**

---

### Task B4: S-4 scene library

**Files:**
- Create: `shared/s4_scenes.py`
- Create: `tests/shared/test_s4_scenes.py`
- Create: `docs/audio/s4-scene-library.md` (aesthetic reference for operator)

- [ ] **Step 1: Write failing tests.**

```python
def test_scene_count_is_10():
    from shared.s4_scenes import SCENES
    assert len(SCENES) == 10

def test_all_required_scenes_present():
    from shared.s4_scenes import SCENES
    required = {"VOCAL-COMPANION","VOCAL-MOSAIC","MUSIC-BED","MUSIC-DRONE",
               "MEMORY-COMPANION","UNDERWATER-COMPANION","SONIC-RITUAL",
               "BEAT-1","RECORD-DRY","BYPASS"}
    assert required == set(SCENES.keys())

def test_scene_schema():
    from shared.s4_scenes import get_scene, S4Scene
    scene = get_scene("VOCAL-COMPANION")
    assert isinstance(scene, S4Scene)
    assert scene.material in {"Bypass", "Tape", "Poly"}
    assert scene.granular in {"Mosaic", "None"}
```

- [ ] **Step 2: Implement scenes** per spec §4.2 table.

- [ ] **Step 3: Run tests, observe pass.**

- [ ] **Step 4: Write aesthetic doc** `docs/audio/s4-scene-library.md`.

- [ ] **Step 5: Commit.**

---

### Task B5: Dual-engine preset pack extension

**Files:**
- Modify: `shared/evil_pet_presets.py` (add `DEFAULT_PAIRINGS` dict)
- Modify: `tests/shared/test_preset_pack_extension.py` (add dual-engine pairing tests)

- [ ] **Step 1: Add `DEFAULT_PAIRINGS`** — dict of Evil Pet preset name → recommended S-4 scene name per spec §4.3.

- [ ] **Step 2: Write test.**

```python
def test_dual_engine_pairings_complete():
    from shared.evil_pet_presets import PRESETS, DEFAULT_PAIRINGS
    from shared.s4_scenes import SCENES
    for name in PRESETS:
        if name == "hapax-mode-d":
            assert DEFAULT_PAIRINGS.get(name) is None
        else:
            assert DEFAULT_PAIRINGS[name] in SCENES
```

- [ ] **Step 3: Run test, observe pass.**

- [ ] **Step 4: Commit.**

---

### Task B6: UC1..UC10 integration tests

**Files:**
- Create: `tests/integration/test_dual_processor_use_cases.py`

- [ ] **Step 1: For each UC1..UC10, write an integration test.**

Example (UC1):

```python
def test_uc1_dual_voice_character_default_topology():
    state = make_router_state(stance="NOMINAL", tts_active=True)
    intent = arbiter_tick(state)
    assert intent.topology == "D1"
    assert intent.evilpet_preset == "hapax-broadcast-ghost"
    assert intent.s4_vocal_scene == "VOCAL-COMPANION"
    assert intent.evilpet_gain == 0.6
    assert intent.s4_vocal_gain == 0.4
```

- [ ] **Step 2: Run all 10 tests, observe pass.**

- [ ] **Step 3: Commit.**

---

## Phase C — Production dynamism

### Task C1: Ramp-time responsiveness

**Files:**
- Modify: `agents/audio_router/dynamic_router.py` (add `compute_ramp_seconds()` and CC-interpolation path)
- Create: `tests/audio_router/test_ramp_responsiveness.py`

- [ ] **Step 1: Write failing test.**

```python
def test_ramp_formula_clamps():
    from agents.audio_router.dynamic_router import compute_ramp_seconds
    assert compute_ramp_seconds(velocity=5.0) == 0.2
    assert compute_ramp_seconds(velocity=0.1) == 2.5
    assert abs(compute_ramp_seconds(velocity=0.8) - 1.0) < 0.01
```

- [ ] **Step 2: Implement `compute_ramp_seconds(velocity)` per spec §6.4.**

- [ ] **Step 3: Add CC-interpolation path** to the router with 20 Hz rate-limit.

- [ ] **Step 4: Run test, observe pass.**

- [ ] **Step 5: Commit.**

---

### Task C2: Utterance-boundary sticky semantics

**Files:**
- Modify: `agents/audio_router/dynamic_router.py`
- Create: `tests/audio_router/test_utterance_boundary.py`

- [ ] **Step 1: Write failing tests.**

```python
def test_tier_sticks_10s_after_silence():
    router = DynamicRouter()
    router.emit_tier(3)
    router.on_tts_silence_start(t0=0.0)
    assert router.active_tier_at(t=5.0) == 3
    assert router.active_tier_at(t=10.1) == 2

def test_operator_override_persists_through_silence():
    router = DynamicRouter()
    router.operator_override_tier(4, sticky=True)
    router.on_tts_silence_start(t0=0.0)
    assert router.active_tier_at(t=20.0) == 4
```

- [ ] **Step 2: Implement silence tracking + revert-after-stick-window.**

- [ ] **Step 3: Run tests, observe pass.**

- [ ] **Step 4: Commit.**

---

### Task C3: Observability closure

**Files:**
- Create: `agents/audio_router/metrics.py`
- Modify: `agents/audio_router/dynamic_router.py`
- Create: `tests/audio_router/test_metrics.py`

- [ ] **Step 1: Register metrics per spec §3.5 + §6 observability.**

```python
from prometheus_client import Counter, Gauge, Histogram

EVILPET_PRESET_ACTIVE = Gauge("hapax_evilpet_preset_active", "", ["preset"])
EVILPET_PRESET_RECALLS = Counter("hapax_evilpet_preset_recalls_total", "", ["preset"])
EVILPET_CC_EMITS = Counter("hapax_evilpet_cc_emits_total", "", ["cc","preset","outcome"])
S4_SCENE_ACTIVE = Gauge("hapax_s4_scene_active", "", ["track","scene"])
S4_SCENE_RECALLS = Counter("hapax_s4_scene_recalls_total", "", ["track","scene"])
ROUTER_TICK_SECONDS = Histogram("hapax_audio_router_tick_seconds", "")
VOICE_TIER_TRANSITIONS = Counter("hapax_voice_tier_transitions_total", "", ["from","to","reason"])
VOICE_TIER_CLAMPS = Counter("hapax_voice_tier_clamp_total", "", ["reason"])
CAPABILITY_HEALTH = Gauge("hapax_capability_health", "", ["capability"])
```

- [ ] **Step 2: Emit Langfuse `voice_tier_transition` events.**

- [ ] **Step 3: Write `router.jsonl` rotation** at `$HOME/hapax-state/audio-router/router.jsonl` (10 MB / keep 5).

- [ ] **Step 4: Wire `capability_health` feedback** into `AffordancePipeline`.

- [ ] **Step 5: Commit.**

---

### Task C4: Dry-run preview (UC8)

**Files:**
- Create: `config/pipewire/hapax-voice-fx-monitor.conf`
- Create: `scripts/hapax-voice-preview`
- Create: `tests/scripts/test_voice_preview.py`

- [ ] **Step 1: Write failing tests.**

```python
def test_voice_preview_sink_separate_from_broadcast():
    r = subprocess.run(["pactl","list","sinks"], capture_output=True, text=True)
    assert "hapax-voice-fx-monitor" in r.stdout

def test_voice_preview_cli_auto_cutoff():
    # mocked test — preview auto-commits or aborts after 10s without --commit
    pass
```

- [ ] **Step 2: Write preview sink conf** routes to L-12 PHONES via Ryzen analog (private operator path), NOT captured by broadcast filter-chain.

- [ ] **Step 3: Write CLI** `hapax-voice-preview <preset>` — routes for 10 s then reverts. `--commit` makes it permanent.

- [ ] **Step 4: Run tests, observe pass.**

- [ ] **Step 5: Commit.**

---

### Task C5: WARD classifier pre-render gate

**Files:**
- Modify: `agents/audio_router/dynamic_router.py`
- Create: `tests/audio_router/test_ward_pregate.py`

- [ ] **Step 1: Write failing tests.**

```python
def test_ward_reject_aborts_dual_engine_transition():
    router = DynamicRouter()
    router.ward_classifier = MagicMock(return_value="REJECT")
    prior_intent = router.active_intent()
    new_intent = make_intent(topology="D1", tier=5, s4_scene="SONIC-RITUAL")
    committed = router.commit_with_ward_check(new_intent)
    assert committed is False
    assert router.active_intent() == prior_intent
```

- [ ] **Step 2: Implement gate.** Before commit, sample 500 ms through UC8 pre-cue path, run Ring-2 WARD classifier, abort on REJECT.

- [ ] **Step 3: Run tests, observe pass.**

- [ ] **Step 4: Commit.**

---

## Execution order

- **Phase A tasks ship in one bundle** (coherent review surface; all five are software-only).
- **Phase B is serial after S-4 plug-in**: B1 → B2 → B3 → B4 → B5 → B6.
- **Phase C is serial after Phase B**: C1 → C2 → C3 → C4 → C5.

## Testing strategy summary

| Phase | Unit | Integration | Regression pin | Governance |
|-------|------|-------------|----------------|------------|
| A | filter-chain schema | PipeWire restart + graph verify | `test_evilpet_s4_gain_discipline.py` | — |
| B | scenes, policy layers | UC1..UC10 | S-4 live-enumeration | consent / Mode D / monetization / WARD |
| C | ramp formula, sticky | router-tick cadence, dry-run sink | — | dual-engine anthropomorphization |

## Rollout checklist

Phase A:
- [ ] A1 filter-chain drift fix committed + deployed live
- [ ] A2 hardware loop verification runbook published
- [ ] A3 notification-sink isolation committed + deployed
- [ ] A4 state-surface audit CLI written + run; surfaces reinstated
- [ ] A5 YT → S-4 bridge conf committed + deployed

Phase B:
- [ ] B1 S-4 physically plugged + USB-enumerated
- [ ] B2 MIDI lane wired + tested
- [ ] B3 dynamic router agent running 5 Hz as systemd unit
- [ ] B4 S-4 scene library shipped
- [ ] B5 dual-engine pairings documented + tested
- [ ] B6 UC1..UC10 integration tests passing

Phase C:
- [ ] C1 ramp formula responsive in live router
- [ ] C2 utterance-boundary stick behavior live
- [ ] C3 Prometheus metrics visible in Grafana; `capability_health` feedback loop live
- [ ] C4 dry-run CLI usable; 10 s auto-cutoff verified
- [ ] C5 WARD pre-render gate aborts at least one test transition

Final:
- [ ] 24-hour live operation with zero `ward_rejected` counter increments under normal usage
- [ ] Operator aesthetic sign-off on D1, D2, D3 defaults

## Post-ship operations

1. **Monitor** Prometheus dashboards for preset recalls, scene recalls, tier transitions, clamps, capability health.
2. **Iterate** preset / scene CC values per operator aesthetic feedback.
3. **Governance** monthly audit of `monetization_opt_ins`, consent-contract usage, WARD classifier WARN counts.
4. **Deprecation** if S-4 becomes primary voice processor (future), transition Evil Pet to secondary.

---

**Next action**: Phase A shipping as one PR bundled with this plan + spec + research + stashes. Phase B starts on operator S-4 plug-in event.
