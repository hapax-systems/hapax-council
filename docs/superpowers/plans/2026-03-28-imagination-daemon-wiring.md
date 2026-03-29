# Imagination Daemon Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the imagination loop, content resolver, context injection, and proactive gate into the DMN and voice daemons so the full imagination→expression→reflection loop runs in production.

**Architecture:** Imagination loop + resolver as async tasks inside DMN daemon (direct buffer access). Context injection + proactive gate hooked into voice daemon's existing loops. Shared transport via `/dev/shm/hapax-dmn/impingements.jsonl`.

**Tech Stack:** Python 3.12, asyncio, existing modules (imagination.py, imagination_resolver.py, imagination_context.py, proactive_gate.py)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `agents/dmn/buffer.py` | Add `recent_observations(n)` method |
| `agents/dmn/__main__.py` | Launch imagination loop + resolver tasks, drain imagination impingements |
| `agents/hapax_voice/__main__.py` | Wire imagination context fn + proactive gate |
| `tests/test_dmn_imagination_wiring.py` | DMN-side tests |
| `tests/test_voice_imagination_wiring.py` | Voice-side tests |

---

### Task 1: DMNBuffer.recent_observations

**Files:**
- Modify: `agents/dmn/buffer.py`
- Create: `tests/test_dmn_imagination_wiring.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_dmn_imagination_wiring.py
"""Tests for imagination wiring into DMN daemon."""

from agents.dmn.buffer import DMNBuffer


def test_recent_observations_empty():
    buf = DMNBuffer()
    assert buf.recent_observations(5) == []


def test_recent_observations_returns_content():
    buf = DMNBuffer()
    buf.add_observation("Activity: coding. Flow: 0.8.")
    buf.add_observation("Activity: idle. Flow: 0.2.")
    result = buf.recent_observations(5)
    assert result == ["Activity: coding. Flow: 0.8.", "Activity: idle. Flow: 0.2."]


def test_recent_observations_caps_at_n():
    buf = DMNBuffer()
    for i in range(10):
        buf.add_observation(f"obs {i}")
    result = buf.recent_observations(3)
    assert len(result) == 3
    assert result == ["obs 7", "obs 8", "obs 9"]


def test_recent_observations_returns_all_when_fewer_than_n():
    buf = DMNBuffer()
    buf.add_observation("only one")
    result = buf.recent_observations(5)
    assert result == ["only one"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_dmn_imagination_wiring.py -v`
Expected: FAIL with `AttributeError: 'DMNBuffer' object has no attribute 'recent_observations'`

- [ ] **Step 3: Implement recent_observations**

Add to `agents/dmn/buffer.py` in the `DMNBuffer` class, after `__len__`:

```python
    def recent_observations(self, n: int = 5) -> list[str]:
        """Return content strings of the last N observations."""
        obs = list(self._observations)
        return [o.content for o in obs[-n:]]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_dmn_imagination_wiring.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add agents/dmn/buffer.py tests/test_dmn_imagination_wiring.py
git commit -m "feat(dmn): DMNBuffer.recent_observations for imagination context"
```

---

### Task 2: DMN Daemon — Launch Imagination Tasks

**Files:**
- Modify: `agents/dmn/__main__.py`
- Modify: `tests/test_dmn_imagination_wiring.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dmn_imagination_wiring.py`:

```python
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from agents.dmn.__main__ import DMNDaemon


def test_daemon_has_imagination_loop():
    daemon = DMNDaemon()
    assert hasattr(daemon, "_imagination")
    assert daemon._imagination is not None


def test_daemon_drains_imagination_impingements(tmp_path: Path):
    """Imagination impingements drain into the same file as DMN impingements."""
    daemon = DMNDaemon()

    # Simulate a high-salience imagination fragment producing an impingement
    from agents.imagination import ContentReference, ImaginationFragment
    from agents.imagination import maybe_escalate

    frag = ImaginationFragment(
        content_references=[ContentReference(kind="text", source="insight", query=None, salience=0.8)],
        dimensions={"intensity": 0.7},
        salience=0.8,
        continuation=False,
        narrative="An important realization.",
    )
    # Process fragment through the loop (records + publishes + escalates)
    daemon._imagination._process_fragment(frag)

    # Drain should return the impingement
    imps = daemon._imagination.drain_impingements()
    assert len(imps) == 1
    assert imps[0].source == "imagination"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_dmn_imagination_wiring.py::test_daemon_has_imagination_loop -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Modify DMN daemon**

Update `agents/dmn/__main__.py`:

Add imports at the top (after existing imports):

```python
from agents.imagination import ImaginationLoop
from agents.imagination_resolver import cleanup_content_dir, resolve_references, CONTENT_DIR
```

Modify `DMNDaemon.__init__`:

```python
    def __init__(self) -> None:
        self._buffer = DMNBuffer()
        self._pulse = DMNPulse(self._buffer)
        self._imagination = ImaginationLoop()
        self._running = True
        self._start_time = time.monotonic()
```

Modify `DMNDaemon.run` to launch imagination tasks:

```python
    async def run(self) -> None:
        """Main loop — never stops unless signalled."""
        DMN_STATE_DIR.mkdir(parents=True, exist_ok=True)
        log.info("DMN daemon starting")

        # Launch imagination loop as independent async task
        asyncio.create_task(self._imagination_loop())
        asyncio.create_task(self._resolver_loop())

        while self._running:
            try:
                await self._pulse.tick()
                self._write_output()
            except Exception:
                log.exception("DMN tick failed")

            await asyncio.sleep(LOOP_TICK_S)

        log.info("DMN daemon stopped")
```

Add the two async task methods:

```python
    async def _imagination_loop(self) -> None:
        """Run imagination loop on its own variable cadence."""
        from agents.dmn.sensor import read_all

        log.info("Imagination loop starting")
        while self._running:
            try:
                # Read TPN flag for cadence suppression
                try:
                    if TPN_ACTIVE_FILE.exists():
                        active = TPN_ACTIVE_FILE.read_text().strip() == "1"
                        self._imagination.set_tpn_active(active)
                except OSError:
                    pass

                observations = self._buffer.recent_observations(5)
                snapshot = read_all()
                await self._imagination.tick(observations, snapshot)
            except Exception:
                log.debug("Imagination tick failed (non-fatal)", exc_info=True)

            interval = self._imagination.cadence.current_interval()
            await asyncio.sleep(interval)

    async def _resolver_loop(self) -> None:
        """Watch imagination fragments and resolve slow content references."""
        from agents.imagination import ImaginationFragment, CURRENT_PATH

        log.info("Content resolver starting")
        last_fragment_id = ""
        CONTENT_DIR.mkdir(parents=True, exist_ok=True)

        while self._running:
            try:
                if CURRENT_PATH.exists():
                    data = json.loads(CURRENT_PATH.read_text())
                    frag_id = data.get("id", "")
                    if frag_id and frag_id != last_fragment_id:
                        last_fragment_id = frag_id
                        frag = ImaginationFragment.model_validate(data)
                        cleanup_content_dir()
                        resolve_references(frag)
                        log.debug("Resolved content for fragment %s", frag_id)
            except Exception:
                log.debug("Resolver tick failed (non-fatal)", exc_info=True)

            await asyncio.sleep(0.5)
```

Modify `_write_output` to also drain imagination impingements:

```python
    def _write_output(self) -> None:
        """Write buffer, impingements, and status to /dev/shm."""
        # Buffer formatted for U-curve
        buffer_text = self._buffer.format_for_tpn()
        try:
            tmp = BUFFER_FILE.with_suffix(".tmp")
            tmp.write_text(buffer_text, encoding="utf-8")
            tmp.rename(BUFFER_FILE)
        except OSError:
            pass

        # Drain DMN pulse impingements + imagination impingements
        impingements = self._pulse.drain_impingements()
        impingements.extend(self._imagination.drain_impingements())
        if impingements:
            try:
                with IMPINGEMENTS_FILE.open("a", encoding="utf-8") as f:
                    for imp in impingements:
                        f.write(imp.model_dump_json() + "\n")
                log.info("Emitted %d impingements to JSONL", len(impingements))
            except OSError:
                pass

        # Read TPN active flag (anti-correlation signal from voice daemon)
        try:
            if TPN_ACTIVE_FILE.exists():
                active = TPN_ACTIVE_FILE.read_text().strip() == "1"
                self._pulse.set_tpn_active(active)
        except OSError:
            pass

        # Status for monitoring
        status = {
            "running": True,
            "uptime_s": round(time.monotonic() - self._start_time, 1),
            "buffer_entries": len(self._buffer),
            "tick": self._buffer.tick,
            "imagination_active": self._imagination.activation_level > 0,
            "timestamp": time.time(),
        }
        try:
            tmp = STATUS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(status), encoding="utf-8")
            tmp.rename(STATUS_FILE)
        except OSError:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_dmn_imagination_wiring.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add agents/dmn/__main__.py tests/test_dmn_imagination_wiring.py
git commit -m "feat(dmn): launch imagination loop + resolver tasks, drain imagination impingements"
```

---

### Task 3: Voice Daemon — Context Injection + Proactive Gate

**Files:**
- Modify: `agents/hapax_voice/__main__.py`
- Create: `tests/test_voice_imagination_wiring.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_voice_imagination_wiring.py
"""Tests for imagination wiring into voice daemon."""

import json
import time
from pathlib import Path

from agents.imagination_context import format_imagination_context
from agents.proactive_gate import ProactiveGate
from agents.imagination import ContentReference, ImaginationFragment
from shared.impingement import Impingement, ImpingementType


def test_context_injection_returns_string():
    """format_imagination_context is callable and returns a string."""
    result = format_imagination_context()
    assert isinstance(result, str)
    assert "Current Thoughts" in result


def test_context_injection_with_stream(tmp_path: Path):
    """Context injection formats fragments from stream.jsonl."""
    stream = tmp_path / "stream.jsonl"
    stream.write_text(
        json.dumps({"narrative": "thinking about code", "salience": 0.5, "continuation": False}) + "\n"
    )
    result = format_imagination_context(stream)
    assert "thinking about code" in result
    assert "(active thought)" in result


def test_proactive_gate_checks_imagination_source():
    """Gate only fires for imagination-sourced impingements with high salience."""
    gate = ProactiveGate()
    frag = ImaginationFragment(
        content_references=[ContentReference(kind="text", source="insight", query=None, salience=0.8)],
        dimensions={"intensity": 0.7},
        salience=0.9,
        continuation=False,
        narrative="Important realization.",
    )
    state = {
        "perception_activity": "active",
        "vad_active": False,
        "last_utterance_time": time.monotonic() - 60.0,
        "tpn_active": False,
    }
    assert gate.should_speak(frag, state) is True


def test_proactive_gate_rejects_low_salience():
    gate = ProactiveGate()
    frag = ImaginationFragment(
        content_references=[],
        dimensions={},
        salience=0.5,
        continuation=False,
        narrative="idle thought",
    )
    state = {
        "perception_activity": "active",
        "vad_active": False,
        "last_utterance_time": time.monotonic() - 60.0,
        "tpn_active": False,
    }
    assert gate.should_speak(frag, state) is False
```

- [ ] **Step 2: Run test to verify it passes (these test existing modules, should pass immediately)**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_voice_imagination_wiring.py -v`
Expected: 4 passed (these validate the existing modules work correctly for wiring)

- [ ] **Step 3: Modify voice daemon __main__.py**

In the `__init__` section (around line 960, after `self._dmn_fn = render_dmn`), add:

```python
        # Imagination context injection
        from agents.imagination_context import format_imagination_context

        self._imagination_fn = format_imagination_context

        # Proactive gate for imagination-driven speech
        from agents.proactive_gate import ProactiveGate

        self._proactive_gate = ProactiveGate()
        self._last_utterance_time = time.monotonic()
```

In the context wiring section (around line 1171, after `self._conversation_pipeline._dmn_fn = self._dmn_fn`), add:

```python
        self._conversation_pipeline._imagination_fn = self._imagination_fn
```

In `_impingement_consumer_loop` (around line 1844, inside the `for line in new_lines` loop, after the existing `for c in candidates` block), add:

```python
                            # Proactive utterance: imagination-sourced impingements
                            if imp.source == "imagination" and imp.strength >= 0.8:
                                gate_state = {
                                    "perception_activity": (
                                        self.perception.latest.activity
                                        if self.perception.latest
                                        else "unknown"
                                    ),
                                    "vad_active": self.session.is_active,
                                    "last_utterance_time": self._last_utterance_time,
                                    "tpn_active": False,
                                }
                                # Build a proxy fragment for the gate
                                from agents.imagination import ImaginationFragment

                                try:
                                    proxy_frag = ImaginationFragment(
                                        content_references=[],
                                        dimensions=imp.context.get("dimensions", {}),
                                        salience=imp.strength,
                                        continuation=imp.content.get("continuation", False),
                                        narrative=imp.content.get("narrative", ""),
                                    )
                                    if self._proactive_gate.should_speak(proxy_frag, gate_state):
                                        self._proactive_gate.record_utterance()
                                        self._last_utterance_time = time.monotonic()
                                        log.info(
                                            "Proactive utterance triggered: %s",
                                            imp.content.get("narrative", "")[:60],
                                        )
                                except Exception:
                                    log.debug(
                                        "Proactive gate check failed (non-fatal)",
                                        exc_info=True,
                                    )
```

In `conversation_pipeline.py`'s `_update_system_context` method (around line 620, after the existing context fn loop), add imagination context:

```python
        # Imagination context: current thoughts from imagination bus
        _imagination_fn = getattr(self, "_imagination_fn", None)
        if _imagination_fn is not None and not _lockdown:
            try:
                section = _imagination_fn()
                if section:
                    updated += "\n\n" + section
            except Exception:
                log.debug("imagination context fn failed (non-fatal)", exc_info=True)
```

- [ ] **Step 4: Run all wiring tests**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_dmn_imagination_wiring.py tests/test_voice_imagination_wiring.py -v`
Expected: 10 passed

- [ ] **Step 5: Run full imagination test suite to verify no regressions**

Run: `cd ~/projects/hapax-council--beta && uv run pytest tests/test_visual_chain.py tests/test_imagination.py tests/test_imagination_resolver.py tests/test_imagination_context.py tests/test_proactive_gate.py tests/test_dmn_imagination_wiring.py tests/test_voice_imagination_wiring.py -v`
Expected: 87 passed

- [ ] **Step 6: Commit**

```bash
git add agents/hapax_voice/__main__.py agents/hapax_voice/conversation_pipeline.py tests/test_voice_imagination_wiring.py
git commit -m "feat(voice): wire imagination context injection + proactive gate into voice daemon"
```
