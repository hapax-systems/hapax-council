# Voice Modulation Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dormant 9-dimensional `VocalChainCapability` actually drive Evil Pet + Torso S-4 MIDI CCs from live impingements so Hapax's TTS, heard through a hardware monitor loop, audibly reflects its honest internal state.

**Architecture:** Track A minimal hardware loop per `docs/research/2026-04-19-voice-self-modulation-design.md` §7. Two complementary software changes: (1) explicit 24c MIDI port resolution with fail-open degradation, (2) wiring `activate_from_impingement` + periodic `decay` into the existing `impingement_consumer_loop`. Hardware: `24c MAIN OUT -> Evil Pet -> Torso S-4 -> return` with two physical-topology options (see Task 6). Observability via prometheus counters + a small grafana dashboard fragment. No TTS path change, no Carla/LV2, no affordance-pipeline extension - those are Phases 2+ per research doc §6.

**Tech Stack:**
- Python 3.12 / uv / pytest / unittest.mock (shared council conventions)
- `mido` (MIDI output, already in deps)
- `prometheus_client` (already a hard dep - see `agents/hapax_daimonion/cpal/destination_channel.py` for the existing wrapper pattern)
- Bash (verification script)
- Grafana dashboard JSON fragment (consumed by `grafana/dashboards/`)

---

## File Structure

**Create:**
- `tests/hapax_daimonion/test_vocal_chain_integration.py` - all Phase 1 behaviors under one integration-shaped test module (MIDI port resolution, consumer-loop wiring, decay tick, fail-closed on missing device).
- `scripts/verify-vocal-chain-loop.sh` - audible smoke test that plays a pink-noise burst through the hardware loop and measures the return.
- `grafana/dashboards/voice-vocal-chain.json` - dashboard fragment for the three new counters.
- `docs/runbooks/2026-04-19-voice-modulation-phase-1.md` - operator-facing runbook covering cabling options, port verification, and rollback.

**Modify:**
- `agents/hapax_daimonion/config.py:204` - change `midi_output_port` default from `""` to `"Studio 24c MIDI 1"`.
- `agents/hapax_daimonion/midi_output.py` - add prometheus counter `vocal_chain_cc_send_total{device,cc}`; expose `is_open()` for the consumer loop's fail-open guard.
- `agents/hapax_daimonion/vocal_chain.py` - add `vocal_chain_dimension_activation_total{dimension}` counter in `activate_dimension`; add `vocal_chain_decay_tick_total` counter in `decay`.
- `agents/hapax_daimonion/run_loops_aux.py` - inside `impingement_consumer_loop`, call `daemon._vocal_chain.activate_from_impingement(imp)` on every impingement; run a 1 Hz `decay()` tick on a monotonic clock inside the same loop body.
- `agents/hapax_daimonion/proofs/RESEARCH-STATE.md` Gap 3 section - replace the stale "FIXED" claim with the truthful implementation state as of this PR.

---

## Task 1: MIDI port default resolves to Studio 24c explicitly

**Why first:** The research doc section 1.2 shows `mido.open_output(None)` currently lands on the first kernel MIDI-through node (not a physical device). Every subsequent task depends on CCs actually reaching the hardware.

**Files:**
- Modify: `agents/hapax_daimonion/config.py:204`
- Modify: `agents/hapax_daimonion/midi_output.py`
- Test: `tests/hapax_daimonion/test_vocal_chain_integration.py`

- [ ] **Step 1: Verify the live port name with `aconnect -l`**

Run:

```bash
aconnect -l | grep -E "Studio 24c|MIDI Dispatch"
```

Expected (confirmed 2026-04-19):

```
client 56: 'MIDI Dispatch' [type=kernel,card=10]
    0 'MIDI Dispatch MIDI 1'
client 64: 'Studio 24c' [type=kernel,card=12]
    0 'Studio 24c MIDI 1'
```

If the literal string `Studio 24c MIDI 1` is not present, stop - do not guess. Re-run `aconnect -l`, capture whatever the port is named (e.g. after a firmware update), and use that exact string. Record the chosen string in the runbook (Task 6).

- [ ] **Step 2: Write the failing test for port resolution**

Create `tests/hapax_daimonion/test_vocal_chain_integration.py` with this first test case. Each test file is self-contained per shared council conventions - no conftest.

```python
"""Phase 1 integration tests for the vocal chain MIDI path."""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

from agents._impingement import Impingement, ImpingementType


class TestMidiPortResolution(unittest.TestCase):
    def test_default_port_name_is_studio_24c(self):
        from agents.hapax_daimonion.config import DaimonionConfig

        cfg = DaimonionConfig()
        assert cfg.midi_output_port == "Studio 24c MIDI 1"

    def test_midi_output_opens_named_port(self):
        from agents.hapax_daimonion.midi_output import MidiOutput

        fake_mido = MagicMock()
        fake_port = MagicMock()
        fake_port.name = "Studio 24c MIDI 1"
        fake_mido.open_output.return_value = fake_port

        with patch("agents.hapax_daimonion.midi_output.mido", fake_mido):
            out = MidiOutput(port_name="Studio 24c MIDI 1")
            out.send_cc(channel=0, cc=40, value=42)

        fake_mido.open_output.assert_called_once_with("Studio 24c MIDI 1")
        fake_port.send.assert_called_once()
        msg = fake_port.send.call_args.args[0]
        assert msg.type == "control_change"
        assert msg.channel == 0
        assert msg.control == 40
        assert msg.value == 42

    def test_missing_port_degrades_to_noop_no_crash(self):
        from agents.hapax_daimonion.midi_output import MidiOutput

        fake_mido = MagicMock()
        fake_mido.open_output.side_effect = OSError("no such port")

        with patch("agents.hapax_daimonion.midi_output.mido", fake_mido):
            out = MidiOutput(port_name="Studio 24c MIDI 1")
            # Should NOT raise. Should NOT keep retrying.
            out.send_cc(channel=0, cc=40, value=42)
            out.send_cc(channel=0, cc=40, value=43)

        assert fake_mido.open_output.call_count == 1  # one try, then latched off
        assert out.is_open() is False


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test, verify failure**

Run:

```bash
uv run pytest tests/hapax_daimonion/test_vocal_chain_integration.py::TestMidiPortResolution -v
```

Expected: `test_default_port_name_is_studio_24c` FAILS (current default is `""`), `test_missing_port_degrades_to_noop_no_crash` FAILS (`is_open` does not exist).

- [ ] **Step 4: Update the config default**

Edit `agents/hapax_daimonion/config.py:204`:

```python
    # MIDI output (vocal chain)
    midi_output_port: str = "Studio 24c MIDI 1"  # explicit: reaches Evil Pet + S-4
    midi_evil_pet_channel: int = 0  # 0-indexed MIDI channel
    midi_s4_channel: int = 1  # 0-indexed MIDI channel
```

- [ ] **Step 5: Add `is_open()` + cover the fail-open path in `MidiOutput`**

Edit `agents/hapax_daimonion/midi_output.py`. Append below `close()`:

```python
    def is_open(self) -> bool:
        """True once a port has been successfully opened.

        Used by the impingement consumer loop to skip vocal-chain
        dispatch when the hardware is absent rather than silently
        burning work.
        """
        return self._port is not None and not self._init_failed
```

No other change is needed - `_open_port` already sets `_init_failed=True` on `OSError`, and `send_cc` short-circuits via the existing `if self._init_failed: return` guard.

- [ ] **Step 6: Run test, verify pass**

Run:

```bash
uv run pytest tests/hapax_daimonion/test_vocal_chain_integration.py::TestMidiPortResolution -v
```

Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add agents/hapax_daimonion/config.py \
         agents/hapax_daimonion/midi_output.py \
         tests/hapax_daimonion/test_vocal_chain_integration.py
git commit -m "feat(daimonion): resolve vocal chain MIDI to Studio 24c by default

Default midi_output_port was '', which mido.open_output(None) resolves
to 'Midi Through Port-0' - a kernel loopback. CCs never reached the
Evil Pet or S-4 regardless of affordance activation. Set the explicit
port name and add is_open() for the consumer loop's fail-open guard.

Refs: docs/research/2026-04-19-voice-self-modulation-design.md section 1.2"
```

---

## Task 2: Prometheus counters on MIDI CC send + dimension activation

**Why second:** Any wiring change needs observable evidence. These counters light up the moment Task 3 wires the consumer loop.

**Files:**
- Modify: `agents/hapax_daimonion/midi_output.py`
- Modify: `agents/hapax_daimonion/vocal_chain.py`
- Test: `tests/hapax_daimonion/test_vocal_chain_integration.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/hapax_daimonion/test_vocal_chain_integration.py`:

```python
class TestVocalChainMetrics(unittest.TestCase):
    def test_cc_send_increments_counter(self):
        from agents.hapax_daimonion.midi_output import MidiOutput

        fake_mido = MagicMock()
        fake_port = MagicMock()
        fake_port.name = "Studio 24c MIDI 1"
        fake_mido.open_output.return_value = fake_port

        with patch("agents.hapax_daimonion.midi_output.mido", fake_mido):
            out = MidiOutput(port_name="Studio 24c MIDI 1")
            out.send_cc(channel=0, cc=40, value=42)
            out.send_cc(channel=1, cc=69, value=80)

        from prometheus_client import REGISTRY

        v = REGISTRY.get_sample_value(
            "vocal_chain_cc_send_total",
            {"device": "evil_pet", "cc": "40"},
        )
        assert v is not None and v >= 1.0

        v2 = REGISTRY.get_sample_value(
            "vocal_chain_cc_send_total",
            {"device": "s4", "cc": "69"},
        )
        assert v2 is not None and v2 >= 1.0

    def test_dimension_activation_increments_counter(self):
        from agents.hapax_daimonion.vocal_chain import VocalChainCapability

        midi = MagicMock()
        chain = VocalChainCapability(midi_output=midi, evil_pet_channel=0, s4_channel=1)
        imp = Impingement(
            timestamp=time.time(),
            source="dmn.evaluative",
            type=ImpingementType.SALIENCE_INTEGRATION,
            strength=0.7,
            content={"metric": "vocal.intensity"},
            context={"dimensions": {"intensity": 0.8}},
        )
        chain.activate_from_impingement(imp)

        from prometheus_client import REGISTRY

        v = REGISTRY.get_sample_value(
            "vocal_chain_dimension_activation_total",
            {"dimension": "vocal_chain.intensity"},
        )
        assert v is not None and v >= 1.0

    def test_decay_tick_counter(self):
        from agents.hapax_daimonion.vocal_chain import VocalChainCapability

        midi = MagicMock()
        chain = VocalChainCapability(midi_output=midi, evil_pet_channel=0, s4_channel=1)
        # Prime a nonzero level so decay() has work to do.
        imp = Impingement(
            timestamp=time.time(),
            source="dmn.evaluative",
            type=ImpingementType.SALIENCE_INTEGRATION,
            strength=0.9,
            content={"metric": "vocal.intensity"},
            context={"dimensions": {"intensity": 0.9}},
        )
        chain.activate_from_impingement(imp)

        from prometheus_client import REGISTRY

        before = (
            REGISTRY.get_sample_value("vocal_chain_decay_tick_total") or 0.0
        )
        chain.decay(elapsed_s=1.0)
        after = REGISTRY.get_sample_value("vocal_chain_decay_tick_total") or 0.0
        assert after == before + 1.0
```

- [ ] **Step 2: Run the tests, verify failure**

```bash
uv run pytest tests/hapax_daimonion/test_vocal_chain_integration.py::TestVocalChainMetrics -v
```

Expected: all three FAIL with `None` samples (counters not registered).

- [ ] **Step 3: Add counter registration in `MidiOutput`**

Edit `agents/hapax_daimonion/midi_output.py`. Replace the module body from the top through the `class MidiOutput` line with:

```python
"""MidiOutput - thin mido wrapper for sending MIDI CC messages.

Lazy-initializes the MIDI output port on first send. Fails gracefully
if no MIDI hardware is available (logs warning, becomes a no-op).

Emits ``vocal_chain_cc_send_total{device,cc}`` on every send so the
MIDI path is observable from Grafana without tailing logs. ``device``
is resolved from the CC channel: channel 0 -> evil_pet, channel 1 ->
s4, anything else -> ``unknown``.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

mido: Any = None


def _ensure_mido() -> Any:
    global mido  # noqa: PLW0603
    if mido is None:
        import mido as _mido

        mido = _mido
    return mido


class _CcCounter:
    """``vocal_chain_cc_send_total{device,cc}`` counter wrapper.

    Pattern mirrors ``agents/hapax_daimonion/cpal/destination_channel.py::
    _DestinationCounter``: tolerate duplicate registration (test reloads),
    degrade to no-op when prometheus_client is absent.
    """

    def __init__(self) -> None:
        self._counter: Any = None
        try:
            from prometheus_client import Counter
        except ImportError:  # pragma: no cover
            return
        try:
            self._counter = Counter(
                "vocal_chain_cc_send_total",
                "MIDI control-change messages sent by VocalChainCapability",
                ["device", "cc"],
            )
        except ValueError:
            from prometheus_client import REGISTRY

            self._counter = REGISTRY._names_to_collectors.get(  # noqa: SLF001
                "vocal_chain_cc_send_total"
            )

    def inc(self, device: str, cc: int) -> None:
        if self._counter is None:
            return
        try:
            self._counter.labels(device=device, cc=str(cc)).inc()
        except Exception:  # pragma: no cover
            log.debug("vocal_chain_cc_send_total inc failed", exc_info=True)


_cc_counter = _CcCounter()


def _device_from_channel(channel: int) -> str:
    if channel == 0:
        return "evil_pet"
    if channel == 1:
        return "s4"
    return "unknown"


class MidiOutput:
```

Then inside `send_cc`, after the line `self._port.send(msg)` add:

```python
        _cc_counter.inc(device=_device_from_channel(channel), cc=cc)
```

- [ ] **Step 4: Add counter registration in `VocalChainCapability`**

Edit `agents/hapax_daimonion/vocal_chain.py`. Just below the existing module imports (before `log = logging.getLogger(__name__)`):

```python
from typing import Any

try:
    from prometheus_client import Counter as _PromCounter
except ImportError:  # pragma: no cover
    _PromCounter = None  # type: ignore[assignment]


def _make_counter(name: str, doc: str, labelnames: list[str] | None = None) -> Any:
    if _PromCounter is None:
        return None
    try:
        return _PromCounter(name, doc, labelnames or [])
    except ValueError:
        from prometheus_client import REGISTRY

        return REGISTRY._names_to_collectors.get(name)  # noqa: SLF001


_DIM_COUNTER = _make_counter(
    "vocal_chain_dimension_activation_total",
    "Dimension activations applied by VocalChainCapability",
    ["dimension"],
)
_DECAY_COUNTER = _make_counter(
    "vocal_chain_decay_tick_total",
    "Decay ticks executed by VocalChainCapability",
)
```

Inside `activate_dimension`, immediately after the early `return` guard and before `self._levels[dimension_name] = ...`:

```python
        if _DIM_COUNTER is not None:
            try:
                _DIM_COUNTER.labels(dimension=dimension_name).inc()
            except Exception:
                log.debug("dim counter inc failed", exc_info=True)
```

Inside `decay`, at the very top of the method body:

```python
        if _DECAY_COUNTER is not None:
            try:
                _DECAY_COUNTER.inc()
            except Exception:
                log.debug("decay counter inc failed", exc_info=True)
```

- [ ] **Step 5: Run tests, verify pass**

```bash
uv run pytest tests/hapax_daimonion/test_vocal_chain_integration.py::TestVocalChainMetrics -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add agents/hapax_daimonion/midi_output.py \
         agents/hapax_daimonion/vocal_chain.py \
         tests/hapax_daimonion/test_vocal_chain_integration.py
git commit -m "feat(daimonion): observability for vocal chain CC + decay

Adds three prometheus counters so the MIDI path is externally
observable and the Phase 1 dashboard can show life:
  - vocal_chain_cc_send_total{device,cc}
  - vocal_chain_dimension_activation_total{dimension}
  - vocal_chain_decay_tick_total

Mirrors the _DestinationCounter pattern in cpal/destination_channel.py
for duplicate-registration and import-degradation handling."
```

---

## Task 3: Wire `activate_from_impingement` + `decay` into `impingement_consumer_loop`

**Why third:** Config and counters are in. Now the dead code becomes live code.

**Files:**
- Modify: `agents/hapax_daimonion/run_loops_aux.py` (inside `impingement_consumer_loop`, after the per-candidate dispatch block around line 511)
- Test: `tests/hapax_daimonion/test_vocal_chain_integration.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/hapax_daimonion/test_vocal_chain_integration.py`:

```python
class TestConsumerLoopWiring(unittest.TestCase):
    """Verify run_loops_aux.impingement_consumer_loop invokes the vocal chain."""

    def test_vocal_chain_activated_per_impingement(self):
        """An impingement with dimensions triggers activate_from_impingement."""
        from agents.hapax_daimonion.run_loops_aux import _maybe_activate_vocal_chain

        daemon = MagicMock()
        chain = MagicMock()
        chain.activate_from_impingement.return_value = {"activated": True}
        daemon._vocal_chain = chain
        daemon._midi_output = MagicMock()
        daemon._midi_output.is_open.return_value = True

        imp = Impingement(
            timestamp=time.time(),
            source="dmn.evaluative",
            type=ImpingementType.SALIENCE_INTEGRATION,
            strength=0.7,
            content={"metric": "vocal.intensity"},
            context={"dimensions": {"intensity": 0.8}},
        )

        _maybe_activate_vocal_chain(daemon, imp)

        chain.activate_from_impingement.assert_called_once_with(imp)

    def test_vocal_chain_skipped_when_midi_absent(self):
        """Fail-open: no MIDI hardware, no activation attempt, no crash."""
        from agents.hapax_daimonion.run_loops_aux import _maybe_activate_vocal_chain

        daemon = MagicMock()
        chain = MagicMock()
        daemon._vocal_chain = chain
        daemon._midi_output = MagicMock()
        daemon._midi_output.is_open.return_value = False

        imp = Impingement(
            timestamp=time.time(),
            source="dmn.evaluative",
            type=ImpingementType.SALIENCE_INTEGRATION,
            strength=0.7,
            content={"metric": "vocal.intensity"},
            context={"dimensions": {"intensity": 0.8}},
        )

        _maybe_activate_vocal_chain(daemon, imp)

        chain.activate_from_impingement.assert_not_called()

    def test_vocal_chain_decay_ticks_on_schedule(self):
        """_maybe_tick_vocal_chain_decay fires decay() when >=1s has elapsed."""
        from agents.hapax_daimonion.run_loops_aux import _maybe_tick_vocal_chain_decay

        daemon = MagicMock()
        chain = MagicMock()
        daemon._vocal_chain = chain
        daemon._vocal_chain_last_decay_monotonic = None

        # First call: initializes last-decay timestamp, does NOT decay yet.
        now = 1000.0
        _maybe_tick_vocal_chain_decay(daemon, now=now)
        chain.decay.assert_not_called()
        assert daemon._vocal_chain_last_decay_monotonic == 1000.0

        # 0.5s later: still no decay (threshold 1.0s).
        _maybe_tick_vocal_chain_decay(daemon, now=1000.5)
        chain.decay.assert_not_called()

        # 1.1s after initial: decay fires with elapsed ~1.1s.
        _maybe_tick_vocal_chain_decay(daemon, now=1001.1)
        chain.decay.assert_called_once()
        elapsed_arg = chain.decay.call_args.kwargs.get("elapsed_s") or \
                      chain.decay.call_args.args[0]
        assert 1.05 <= elapsed_arg <= 1.15

    def test_no_vocal_chain_attribute_is_safe(self):
        """Missing daemon._vocal_chain never raises."""
        from agents.hapax_daimonion.run_loops_aux import (
            _maybe_activate_vocal_chain,
            _maybe_tick_vocal_chain_decay,
        )

        class Bare:
            pass

        daemon = Bare()
        imp = Impingement(
            timestamp=time.time(),
            source="dmn.evaluative",
            type=ImpingementType.SALIENCE_INTEGRATION,
            strength=0.5,
            content={},
            context={},
        )
        _maybe_activate_vocal_chain(daemon, imp)  # no raise
        _maybe_tick_vocal_chain_decay(daemon, now=123.0)  # no raise
```

- [ ] **Step 2: Run tests, verify failure**

```bash
uv run pytest tests/hapax_daimonion/test_vocal_chain_integration.py::TestConsumerLoopWiring -v
```

Expected: all four FAIL with `ImportError: cannot import name '_maybe_activate_vocal_chain'`.

- [ ] **Step 3: Add the two helpers at module scope in `run_loops_aux.py`**

Insert immediately above `async def impingement_consumer_loop(daemon: VoiceDaemon) -> None:` (around line 292 in the current file):

```python
# --- Vocal chain dispatch helpers (Phase 1 wiring) -----------------------
#
# The VocalChainCapability is instantiated in init_pipeline but historically
# had no callers of activate_from_impingement or decay. This wiring makes
# the 9-dim MIDI modulation real: each impingement reaching the consumer
# loop offers itself to the chain (chain filters via can_resolve +
# activate_from_impingement); a 1 Hz tick drains the levels so modulation
# relaxes when no new impingements arrive.
#
# Fail-open: if MidiOutput is not open (missing hardware, wrong port),
# we skip activation entirely so no CPU is burned running interpolation
# math whose output goes to /dev/null. Dispatch is idempotent on repeated
# impingements (the chain tracks per-dimension levels internally).
#
# Anti-anthropomorphization invariant: this wiring does not introduce any
# signal->dimension mapping. The mapping lives in vocal_chain.DIMENSIONS and
# is sourced from dmn/stimmung/evaluative dimension blobs the pipeline
# already emits. If a future caller tries to set, e.g., "happy" here, the
# review gate (see docs/research/2026-04-19-voice-self-modulation-design.md
# section 3.3) must reject it.

_VOCAL_DECAY_INTERVAL_S = 1.0


def _maybe_activate_vocal_chain(daemon: Any, imp: Impingement) -> None:
    """Forward an impingement to the vocal chain if wiring is live.

    Safe when ``daemon._vocal_chain`` is absent (tests, degraded startup)
    or when the MIDI output failed to open. All errors are swallowed
    with debug-level logging - vocal modulation must never crash the
    consumer loop.
    """
    chain = getattr(daemon, "_vocal_chain", None)
    if chain is None:
        return
    midi = getattr(daemon, "_midi_output", None)
    # is_open was added in Task 1; tolerate midi=None for unit tests that
    # patch only the chain.
    if midi is not None and hasattr(midi, "is_open") and not midi.is_open():
        return
    try:
        chain.activate_from_impingement(imp)
    except Exception:
        log.debug("vocal chain activation failed (non-fatal)", exc_info=True)


def _maybe_tick_vocal_chain_decay(daemon: Any, now: float | None = None) -> None:
    """Call ``decay()`` at most once per ``_VOCAL_DECAY_INTERVAL_S`` seconds.

    ``now`` is injectable for testing; production code passes
    ``time.monotonic()``.
    """
    chain = getattr(daemon, "_vocal_chain", None)
    if chain is None:
        return
    import time as _time

    current = now if now is not None else _time.monotonic()
    last = getattr(daemon, "_vocal_chain_last_decay_monotonic", None)
    if last is None:
        daemon._vocal_chain_last_decay_monotonic = current
        return
    elapsed = current - last
    if elapsed < _VOCAL_DECAY_INTERVAL_S:
        return
    try:
        chain.decay(elapsed_s=elapsed)
    except Exception:
        log.debug("vocal chain decay failed (non-fatal)", exc_info=True)
    daemon._vocal_chain_last_decay_monotonic = current
```

Add `from typing import Any` to the existing imports at the top of `run_loops_aux.py` if not already present. Also add `from agents._impingement import Impingement` if not already present (it is used in the annotations).

- [ ] **Step 4: Invoke the helpers inside the loop**

Still in `run_loops_aux.py::impingement_consumer_loop`, extend the per-impingement section. Locate the line (around 332):

```python
            for imp in consumer.read_new():
                try:
                    candidates = await asyncio.to_thread(daemon._affordance_pipeline.select, imp)
```

Insert immediately before that `candidates = ...` line (so the vocal chain observes every impingement regardless of candidate selection - the chain applies its own `can_resolve` gate internally):

```python
                    _maybe_activate_vocal_chain(daemon, imp)
```

Then locate the `await asyncio.sleep(0.5)` near the end of the while loop (around line 516). Insert immediately before it:

```python
            _maybe_tick_vocal_chain_decay(daemon)
```

- [ ] **Step 5: Run tests, verify pass**

```bash
uv run pytest tests/hapax_daimonion/test_vocal_chain_integration.py::TestConsumerLoopWiring -v
```

Expected: 4 passed.

- [ ] **Step 6: Run the whole new test module to catch regressions**

```bash
uv run pytest tests/hapax_daimonion/test_vocal_chain_integration.py -v
uv run pytest tests/hapax_daimonion/test_vocal_chain_wiring.py -v
```

Expected: both green.

- [ ] **Step 7: Lint + type-check**

```bash
uv run ruff check agents/hapax_daimonion/run_loops_aux.py \
                   agents/hapax_daimonion/vocal_chain.py \
                   agents/hapax_daimonion/midi_output.py \
                   agents/hapax_daimonion/config.py \
                   tests/hapax_daimonion/test_vocal_chain_integration.py
uv run ruff format --check agents/hapax_daimonion/run_loops_aux.py \
                            agents/hapax_daimonion/vocal_chain.py \
                            agents/hapax_daimonion/midi_output.py \
                            agents/hapax_daimonion/config.py \
                            tests/hapax_daimonion/test_vocal_chain_integration.py
uv run pyright agents/hapax_daimonion/run_loops_aux.py \
               agents/hapax_daimonion/vocal_chain.py \
               agents/hapax_daimonion/midi_output.py
```

Expected: no errors. Fix any that appear before committing.

- [ ] **Step 8: Commit**

```bash
git add agents/hapax_daimonion/run_loops_aux.py \
         tests/hapax_daimonion/test_vocal_chain_integration.py
git commit -m "feat(daimonion): wire vocal chain into impingement consumer loop

Fills the dormant call sites for VocalChainCapability:
activate_from_impingement runs on every impingement the consumer sees,
and decay ticks at 1 Hz. Fail-open when MIDI hardware is absent.

Closes the implementation gap the research doc (section 1.2) calls
out and supersedes the stale RESEARCH-STATE.md Gap 3 'FIXED' claim -
that entry will be replaced in the same epic (Task 7)."
```

---

## Task 4: Hardware return loop verification script

**Files:**
- Create: `scripts/verify-vocal-chain-loop.sh`

- [ ] **Step 1: Write the script**

Create `scripts/verify-vocal-chain-loop.sh` with mode `0755`:

```bash
#!/usr/bin/env bash
# verify-vocal-chain-loop.sh - Phase 1 hardware loop smoke test.
#
# Plays a 1s pink-noise burst through the 24c MAIN OUT (post Kokoro
# route), records whatever comes back on the operator-configured
# return source, and reports RMS + round-trip latency + feedback
# safety margin.
#
# Usage:
#   scripts/verify-vocal-chain-loop.sh [--return-source NAME] [--duration SEC]
#
# Exits 0 on pass, 1 on fail, 2 on setup error.
# Intentionally NOT wired into CI - requires physical cabling.
set -uo pipefail

RETURN_SOURCE="${HAPAX_VOCAL_RETURN_SOURCE:-}"
DURATION="${HAPAX_VOCAL_TEST_DURATION:-1.0}"
TONE_SINK="${HAPAX_VOCAL_TEST_SINK:-hapax-voice-fx-capture}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

log() { printf "[verify-vocal-chain-loop] %s\n" "$*"; }
die() { log "ERROR: $*"; exit 2; }

while [ $# -gt 0 ]; do
    case "$1" in
        --return-source) RETURN_SOURCE="$2"; shift 2 ;;
        --duration) DURATION="$2"; shift 2 ;;
        --sink) TONE_SINK="$2"; shift 2 ;;
        *) die "unknown arg: $1" ;;
    esac
done

command -v pw-cat >/dev/null 2>&1 || die "pw-cat not found"
command -v sox     >/dev/null 2>&1 || die "sox not found (pacman -S sox)"
command -v aconnect >/dev/null 2>&1 || die "aconnect not found"

# 1. Confirm the MIDI target is reachable (Task 1 invariant).
log "[1/4] MIDI port presence"
if aconnect -l | grep -q "Studio 24c MIDI 1"; then
    log "  OK: Studio 24c MIDI 1 visible"
else
    log "  FAIL: 'Studio 24c MIDI 1' not in aconnect -l. Hardware not present?"
    exit 1
fi

# 2. Confirm the playback sink exists.
log "[2/4] Playback sink presence"
if pactl list short sinks | awk '{print $2}' | grep -qx "$TONE_SINK"; then
    log "  OK: $TONE_SINK sink present"
else
    log "  FAIL: sink '$TONE_SINK' absent. Export HAPAX_VOCAL_TEST_SINK or load voice-fx-chain.conf."
    exit 1
fi

# 3. If a return source is configured, confirm it is alive.
if [ -z "$RETURN_SOURCE" ]; then
    log "[3/4] Return source: UNCONFIGURED"
    log "  SKIP: hardware return loop not closed yet (Phase 1 minimal). Stopping after playback."
else
    log "[3/4] Return source presence"
    if pactl list short sources | awk '{print $2}' | grep -qx "$RETURN_SOURCE"; then
        log "  OK: $RETURN_SOURCE present"
    else
        log "  FAIL: return source '$RETURN_SOURCE' absent"
        exit 1
    fi
fi

# 4. Generate a 1s pink-noise probe, play + capture simultaneously, RMS check.
log "[4/4] Playback + return capture"
PROBE="$WORK/probe.wav"
RETURN_WAV="$WORK/return.wav"

sox -n -r 48000 -c 2 "$PROBE" synth "$DURATION" pinknoise vol 0.2 \
    || die "sox probe generation failed"

if [ -n "$RETURN_SOURCE" ]; then
    # Launch capture first, then play.
    timeout $(awk "BEGIN{print $DURATION + 0.5}") \
        pw-cat --record --target "$RETURN_SOURCE" --rate 48000 \
        --channels 2 --format s16 "$RETURN_WAV" &
    REC_PID=$!
    sleep 0.1
fi

pw-cat --playback --target "$TONE_SINK" "$PROBE" \
    || die "pw-cat playback failed"

if [ -n "$RETURN_SOURCE" ]; then
    wait "$REC_PID" 2>/dev/null || true
    if [ ! -s "$RETURN_WAV" ]; then
        log "  FAIL: empty return capture"
        exit 1
    fi
    # Computed RMS in dBFS - <-60 dBFS means silence (no return signal),
    # >-6 dBFS means runaway (potential feedback).
    RMS_AMP=$(sox "$RETURN_WAV" -n stat 2>&1 | awk -F: '/RMS     amplitude/{print $2}' | xargs)
    log "  Return RMS amplitude: $RMS_AMP"

    AMP_DB=$(awk -v a="$RMS_AMP" 'BEGIN{if(a<=0){print -120}else{print 20*log(a)/log(10)}}')
    log "  Return RMS: ${AMP_DB} dBFS"

    # Signal integrity window: -60..-6 dBFS.
    FAIL=0
    awk -v db="$AMP_DB" 'BEGIN{exit !(db < -60)}' && { log "  FAIL: no audible return signal"; FAIL=1; }
    awk -v db="$AMP_DB" 'BEGIN{exit !(db > -6)}'  && { log "  FAIL: return too hot - possible feedback"; FAIL=1; }

    if [ "$FAIL" -ne 0 ]; then exit 1; fi
    log "  OK: return signal in safe window"
fi

log "PASS"
```

- [ ] **Step 2: Mark executable + confirm it runs without a return source configured**

```bash
chmod +x scripts/verify-vocal-chain-loop.sh
scripts/verify-vocal-chain-loop.sh
```

Expected (no return source yet, Phase 1 minimal): exits 0 with `[3/4] Return source: UNCONFIGURED` and plays the probe burst audibly through the monitor. If the script errors at step 2 (sink missing), load the pipewire conf via the existing preset at `config/pipewire/voice-fx-chain.conf` per `config/pipewire/README.md` and retry.

- [ ] **Step 3: Commit**

```bash
git add scripts/verify-vocal-chain-loop.sh
git commit -m "test(daimonion): verify-vocal-chain-loop.sh for Phase 1 smoke

Plays a 1s pink-noise probe through the voice-fx-chain sink and,
when a HAPAX_VOCAL_RETURN_SOURCE is configured, measures the return
RMS to catch (a) no-return and (b) runaway feedback.

Intentionally not wired into CI - requires physical cabling."
```

---

## Task 5: Grafana dashboard fragment

**Files:**
- Create: `grafana/dashboards/voice-vocal-chain.json`

- [ ] **Step 1: Write the dashboard JSON**

Content for `grafana/dashboards/voice-vocal-chain.json` - four panels (CC rate, dimension activation rate, decay ticks, CC-alive stat):

```json
{
  "annotations": {
    "list": [
      {
        "builtIn": 1,
        "datasource": { "type": "grafana", "uid": "-- Grafana --" },
        "enable": true,
        "hide": true,
        "iconColor": "rgba(0, 211, 255, 1)",
        "name": "Annotations & Alerts",
        "type": "dashboard"
      }
    ]
  },
  "description": "Phase 1 vocal chain observability: MIDI CC sends to Evil Pet + Torso S-4, semantic-dimension activations from impingements, decay ticks. Source: agents/hapax_daimonion/vocal_chain.py + midi_output.py via prometheus_client.",
  "editable": true,
  "fiscalYearStartMonth": 0,
  "graphTooltip": 0,
  "id": null,
  "links": [],
  "liveNow": false,
  "panels": [
    {
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 0 },
      "id": 1,
      "title": "CC sends / min by device",
      "type": "timeseries",
      "targets": [
        {
          "expr": "sum by (device) (rate(vocal_chain_cc_send_total[1m]) * 60)",
          "legendFormat": "{{device}}",
          "refId": "A"
        }
      ]
    },
    {
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 0 },
      "id": 2,
      "title": "Dimension activations / min",
      "type": "timeseries",
      "targets": [
        {
          "expr": "sum by (dimension) (rate(vocal_chain_dimension_activation_total[1m]) * 60)",
          "legendFormat": "{{dimension}}",
          "refId": "A"
        }
      ]
    },
    {
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 8 },
      "id": 3,
      "title": "Decay ticks / min",
      "type": "timeseries",
      "targets": [
        {
          "expr": "rate(vocal_chain_decay_tick_total[1m]) * 60",
          "legendFormat": "ticks/min",
          "refId": "A"
        }
      ]
    },
    {
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 8 },
      "id": 4,
      "title": "CC alive (last 5m)",
      "description": "Nonzero means the MIDI path is actually delivering. Use to diagnose 'silent' impingement activity.",
      "type": "stat",
      "targets": [
        {
          "expr": "sum(increase(vocal_chain_cc_send_total[5m]))",
          "refId": "A"
        }
      ]
    }
  ],
  "refresh": "30s",
  "schemaVersion": 39,
  "style": "dark",
  "tags": ["daimonion", "voice", "vocal-chain", "phase-1"],
  "templating": { "list": [] },
  "time": { "from": "now-1h", "to": "now" },
  "timepicker": {},
  "timezone": "",
  "title": "Voice / Vocal Chain - Phase 1",
  "uid": "voice-vocal-chain",
  "version": 1,
  "weekStart": ""
}
```

- [ ] **Step 2: Validate JSON parses**

```bash
python -c "import json, pathlib; json.loads(pathlib.Path('grafana/dashboards/voice-vocal-chain.json').read_text())"
```

Expected: exits 0 silently.

- [ ] **Step 3: Commit**

```bash
git add grafana/dashboards/voice-vocal-chain.json
git commit -m "docs(daimonion): grafana dashboard for vocal chain Phase 1

Four panels (CC rate by device, dimension activation rate, decay
tick rate, 5-minute CC-alive stat). Drop in alongside the studio
cameras dashboard; same prometheus datasource wiring."
```

---

## Task 6: Hardware-topology decision + operator runbook

**Why now:** Software is live. Operator needs a single document that says "plug these here, run this script, see these metrics move." The research doc presents two physical options - the runbook captures both and tags the operator's pick.

**Files:**
- Create: `docs/runbooks/2026-04-19-voice-modulation-phase-1.md`

- [ ] **Step 1: Write the runbook**

Content for `docs/runbooks/2026-04-19-voice-modulation-phase-1.md`:

````markdown
# Voice Modulation Phase 1 - Runbook

**Status:** Operator-facing. Updated as physical topology evolves.
**Research reference:** `docs/research/2026-04-19-voice-self-modulation-design.md` sections 1.2, 2.1, 7.
**Plan reference:** `docs/superpowers/plans/2026-04-19-voice-modulation-phase-1-plan.md`.

## What this changes

The `vocal_chain` module (`agents/hapax_daimonion/vocal_chain.py`) was
instantiated but had no live callers. As of this deployment:

- `midi_output_port` defaults to `Studio 24c MIDI 1`.
- The impingement consumer loop runs `activate_from_impingement` on every
  impingement and ticks `decay` at 1 Hz.
- Three prometheus counters expose the path (see the Phase 1 dashboard).

No TTS path change. No new Carla / LV2 hosting. No new affordances in the
pipeline. Phase 2+ expands scope.

## Physical topology - pick ONE

Both 24c combo jacks (Input 1 = contact mic FL, Input 2 = L12 mix bus FR)
are currently occupied. Two options:

### Option A - Submixer/external-capture return (no 24c input freed)

```
Studio 24c MAIN OUT L -----> Evil Pet audio in
                              |
                              v
                           Evil Pet out -----> Torso S-4 external in
                                                 |
                                                 v
                                              Torso S-4 out -> external submixer -> USB capture
                                                                                      |
                                                                                      v
                                                                              hapax-voice-return
                                                                              (PipeWire source)
                         Studio 24c MIDI OUT --> Evil Pet MIDI IN (ch 1)
                                              -> Torso S-4 MIDI IN (ch 2)
```

Concrete submixer/USB capture = any Class-Compliant device (e.g. a small
Mackie or a second tiny interface) that Linux sees as `alsa_input.*`.
Operator picks. This option preserves contact mic + L12 on the 24c.

### Option B - Free 24c Input 1 (contact mic moves / mutes during Hapax speech)

```
Studio 24c MAIN OUT L -----> Evil Pet audio in
                              |
                              v
                           Evil Pet out -----> Torso S-4 external in
                                                 |
                                                 v
                                              Torso S-4 out -> 24c Input 1
                                                                |
                                                                v
                                                   alsa_input.usb-PreSonus_Studio_24c
                                                                |
                                                                v
                                                        hapax-voice-return
                                                        (PipeWire source)
```

Contact mic either moves to a different interface or is muted during
Hapax-active windows (ducked by the voice activity signal). Faster to
cable but disturbs existing `contact_mic` source.

### Operator pick

Mark ONE of the lines below and delete the others once decided:

- [ ] Option A (submixer return)
- [ ] Option B (free Input 1)

## Verifying the wiring is live

1. MIDI port visible:
   ```
   aconnect -l | grep "Studio 24c MIDI 1"
   ```
2. Service active (after daimonion restart):
   ```
   systemctl --user is-active hapax-daimonion
   ```
3. Counters have nonzero increase:
   ```
   curl -s http://127.0.0.1:<daimonion_prom_port>/metrics | grep vocal_chain_
   ```
   The exposition port depends on the daimonion's running config; check
   `agents/hapax_daimonion/metrics.py` or the dashboard's datasource.
4. Hardware loop smoke test (audible burst on MAIN OUT monitor):
   ```
   scripts/verify-vocal-chain-loop.sh
   ```
   When a return source is configured, pass it via env:
   ```
   HAPAX_VOCAL_RETURN_SOURCE=alsa_input.usb-PreSonus_Studio_24c_... \
       scripts/verify-vocal-chain-loop.sh
   ```

## Rollback

Revert the three commits that land this phase (`feat(daimonion):
resolve vocal chain MIDI`, `feat(daimonion): observability`, `feat(daimonion):
wire vocal chain into impingement consumer loop`). The wiring is
additive; reverting leaves the daemon behaving exactly as it did before
the change (dormant `VocalChainCapability`). No config file edits, no
systemd unit changes, no pipewire config changes.

If the operator hears runaway feedback or harsh artifacts, pull the
audio cable from Evil Pet IN - Kokoro still reaches the main monitor
through the unchanged software path; the hardware loop is parallel.

## Anti-anthropomorphization invariant (reminder)

The mapping from internal signals to vocal dimensions is defined in
`vocal_chain.py::DIMENSIONS` and is driven by measurable stimmung /
DMN evaluative values. No preset in Phase 1 names an emotion. If any
future change proposes `voice.happy` or similar, it violates the
invariant and must be rejected at review time. See the operator's
anti-anthropomorphization memory note and the research doc section 3.3
red-team filter for the authoritative statement.
````

- [ ] **Step 2: Commit**

```bash
git add docs/runbooks/2026-04-19-voice-modulation-phase-1.md
git commit -m "docs(daimonion): Phase 1 voice modulation runbook

Captures both physical-topology options (A = submixer return,
B = free 24c Input 1), the verification checklist, rollback path,
and the anti-anthropomorphization invariant."
```

---

## Task 7: Update RESEARCH-STATE.md Gap 3 entry

**Why:** The current entry claims "FIXED" in Session 20 (2026-03-31). The repo contradicts that claim (grep shows zero callers outside the test module); this plan is the real fix. Fix the record so future sessions do not act on false premises.

**Files:**
- Modify: `agents/hapax_daimonion/proofs/RESEARCH-STATE.md` (around line 365)

- [ ] **Step 1: Replace the Gap 3 paragraph**

Use `Edit` on the file. Replace the existing paragraph that begins with `**Gap 3: Vocal chain impingement wiring (FIXED).**` (one paragraph, ends with `3 tests.`) with:

```markdown
**Gap 3: Vocal chain impingement wiring (RE-FIXED, 2026-04-19).** Session 20's "FIXED" claim did not survive into the repo - ripgrep on 2026-04-19 showed `activate_from_impingement` / `activate_dimension` / `decay` had zero callers outside the test module, the `midi_output_port` default resolved to a kernel loopback rather than the 24c, and `RESEARCH-STATE.md` was the only place asserting the wiring was live. See `docs/research/2026-04-19-voice-self-modulation-design.md` section 1.2 for the audit. `docs/superpowers/plans/2026-04-19-voice-modulation-phase-1-plan.md` lands the actual wiring: `midi_output_port` defaults to `"Studio 24c MIDI 1"`, `impingement_consumer_loop` calls `_maybe_activate_vocal_chain(imp)` per impingement and `_maybe_tick_vocal_chain_decay()` at 1 Hz, `MidiOutput.is_open()` gates fail-open degradation, three prometheus counters expose the path. Tests: `tests/hapax_daimonion/test_vocal_chain_integration.py` (11 cases: port resolution, degraded-open, counter integration, consumer-loop dispatch, decay scheduling, missing-attribute safety). Hardware return loop (Track A Phase 2) still deferred.
```

- [ ] **Step 2: Commit**

```bash
git add agents/hapax_daimonion/proofs/RESEARCH-STATE.md
git commit -m "docs(daimonion): correct Gap 3 vocal chain wiring state

Session 20's 'FIXED' claim did not survive into the repo. This entry
reflects the actual wiring landed in the voice-modulation-phase-1
plan and points at the research doc + plan doc for audit trail."
```

---

## Task 8: End-to-end live-path smoke

**Files:** none new.

- [ ] **Step 1: Run the full new test module + existing wiring tests once more**

```bash
uv run pytest tests/hapax_daimonion/test_vocal_chain_integration.py \
              tests/hapax_daimonion/test_vocal_chain_wiring.py -v
```

Expected: green across the board.

- [ ] **Step 2: Restart daimonion and watch the counters**

```bash
systemctl --user restart hapax-daimonion
sleep 5
curl -s "$(systemctl --user show hapax-daimonion -p Environment --value \
         | tr ' ' '\n' | grep -E '^HAPAX_METRICS_URL=' | cut -d= -f2-)/metrics" \
    2>/dev/null | grep -E '^vocal_chain_' | head
```

If `HAPAX_METRICS_URL` is unset, consult `agents/hapax_daimonion/metrics.py` for the live exposition URL. Expected output contains all three counter series with nonzero or zero sample lines - the point is they are registered.

- [ ] **Step 3: Run the hardware smoke test**

```bash
scripts/verify-vocal-chain-loop.sh
```

Expected: `PASS`. If the script was run before Task 6 picked an option, the return-source branch is skipped - that is still PASS for Phase 1 minimal.

- [ ] **Step 4: Observe live modulation (audible verification, required)**

1. Ensure cable: 24c MAIN OUT L to Evil Pet audio in, Evil Pet out to monitor (or S-4 to monitor).
2. Ensure MIDI: Studio 24c MIDI OUT to Evil Pet MIDI IN (ch 1), optionally to S-4 MIDI IN (ch 2).
3. Trigger an utterance with a known vocal dimension (e.g. ask Hapax a question that will raise `stimmung.error_rate`, or drop a synthetic impingement via the `/dev/shm/hapax-dmn/impingements.jsonl` path with `{"dimensions": {"intensity": 0.8}}`).
4. Verify: the voice audibly changes between idle and impingement-present.
5. Verify: the voice returns to baseline after ~50 s of no activation (default `decay_rate=0.02`/s * 1 s ticks).

If the audio difference is inaudible but the counters advance, the MIDI path works but the hardware CC mappings likely need to be matched to the current Evil Pet / S-4 firmware (a Phase 2+ concern - log an issue, do not attempt to fix during Phase 1).

- [ ] **Step 5: If everything passes, open the PR**

```bash
git push -u origin HEAD
gh pr create --title "Voice modulation Phase 1: wire dormant vocal chain + explicit 24c MIDI" \
             --body "$(cat <<'EOF'
## Summary
- Default midi_output_port now "Studio 24c MIDI 1" with fail-open is_open() guard
- impingement_consumer_loop calls _maybe_activate_vocal_chain per impingement + _maybe_tick_vocal_chain_decay at 1 Hz
- Three prometheus counters (vocal_chain_cc_send_total, vocal_chain_dimension_activation_total, vocal_chain_decay_tick_total) + Grafana dashboard fragment
- scripts/verify-vocal-chain-loop.sh for audible hardware smoke
- Operator runbook at docs/runbooks/2026-04-19-voice-modulation-phase-1.md
- Corrected RESEARCH-STATE.md Gap 3 entry (was stale "FIXED")

## Test plan
- [x] uv run pytest tests/hapax_daimonion/test_vocal_chain_integration.py -v  (11 cases)
- [x] uv run pytest tests/hapax_daimonion/test_vocal_chain_wiring.py -v       (3 cases, regression)
- [x] scripts/verify-vocal-chain-loop.sh  (audible on monitor)
- [x] Live daimonion restart; prometheus counters visible
- [ ] Operator audible diff between idle vs impinged utterance (requires cabling per runbook)

Refs: docs/research/2026-04-19-voice-self-modulation-design.md, docs/superpowers/plans/2026-04-19-voice-modulation-phase-1-plan.md.
EOF
)"
```

---

## Deliverable checklist

- Every `VocalChainCapability` dead-code call site invoked (`activate_from_impingement` in Task 3, `decay` in Task 3).
- Evil Pet + S-4 receive CC changes on impingements (Task 1 explicit port + Task 3 wiring; verified by counters in Task 2 and audibly in Task 8).
- Audible voice change when Hapax speaks vs idle (Task 8 step 4).
- Anti-anthropomorphization invariant preserved: no emotion-named presets introduced; the signal->dimension mapping already lives in `vocal_chain.DIMENSIONS` and the wiring does not add new mappings. Runbook (Task 6) restates the invariant.
- Graceful degradation on missing MIDI hardware (Task 1 step 5, Task 3 fail-open).

## Self-review notes

- **Spec coverage:** research section 1 port fix (Task 1), section 2 wiring (Task 3), section 3 hardware return options (Task 6 runbook + Task 4 script), section 4 observability (Task 2 + Task 5), section 5 regression tests (Task 1/2/3 each append to the same file), section 6 doc update (Task 7).
- **Placeholder scan:** no TBDs, no "TODO later", no "handle edge cases" without concrete code. The one decision left open to the operator (Option A vs B) is explicitly flagged as an operator pick, not an engineer pick.
- **Type consistency:** `_maybe_activate_vocal_chain`, `_maybe_tick_vocal_chain_decay`, `is_open`, `_VOCAL_DECAY_INTERVAL_S`, counter names (`vocal_chain_cc_send_total`, `vocal_chain_dimension_activation_total`, `vocal_chain_decay_tick_total`) used identically across tasks.

## Execution handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-19-voice-modulation-phase-1-plan.md`. Two execution options:**

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
