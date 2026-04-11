# Studio Audio Stream Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SIGSTOP-based youtube slot audio management with PipeWire per-stream volume control, fix director threading races, and route TTS to the assistant sink.

**Architecture:** New `SlotAudioControl` class wraps `wpctl` for idempotent per-node volume. Director merges speech + slot advance into a single locked thread. TTS targets the assistant PipeWire role sink. youtube-player loses all pause/SIGSTOP code.

**Tech Stack:** Python 3.12, PipeWire (`wpctl`, `pw-dump`), threading.Lock, subprocess

**Spec:** `docs/superpowers/specs/2026-04-11-studio-audio-stream-control-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `agents/studio_compositor/audio_control.py` | Create | PipeWire node discovery + per-stream volume control |
| `tests/test_audio_control.py` | Create | Unit tests for SlotAudioControl (mocked subprocess) |
| `agents/studio_compositor/director_loop.py` | Edit | Wire audio control, merge speech+advance threads, remove SIGSTOP code |
| `agents/hapax_daimonion/pw_audio_output.py` | Edit | Add `--target` parameter for sink routing |
| `scripts/youtube-player.py` | Edit | Remove toggle_pause, SIGSTOP, pause endpoints |

---

### Task 1: SlotAudioControl — node discovery and volume control

**Files:**
- Create: `agents/studio_compositor/audio_control.py`
- Create: `tests/test_audio_control.py`

- [ ] **Step 1: Write failing tests for node discovery and volume control**

Create `tests/test_audio_control.py`:

```python
"""Tests for SlotAudioControl PipeWire volume management."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, call, patch

from agents.studio_compositor.audio_control import SlotAudioControl


def _make_pw_dump_output(nodes: dict[int, str]) -> str:
    """Build minimal pw-dump JSON with node entries.

    Args:
        nodes: mapping of node_id -> media.name
    """
    return json.dumps(
        [
            {
                "id": nid,
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {"media.name": name, "node.name": "Lavf62.12.100"},
                    "state": "running",
                },
            }
            for nid, name in nodes.items()
        ]
    )


PW_DUMP_3_SLOTS = _make_pw_dump_output(
    {241: "youtube-audio-0", 258: "youtube-audio-1", 285: "youtube-audio-2"}
)


class TestNodeDiscovery:
    @patch("subprocess.run")
    def test_discovers_node_by_media_name(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        assert ctrl.discover_node("youtube-audio-0") == 241
        assert ctrl.discover_node("youtube-audio-2") == 285

    @patch("subprocess.run")
    def test_caches_node_ids(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.discover_node("youtube-audio-0")
        ctrl.discover_node("youtube-audio-0")
        # pw-dump called once, cached on second call
        assert mock_run.call_count == 1

    @patch("subprocess.run")
    def test_returns_none_for_missing_stream(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        assert ctrl.discover_node("youtube-audio-99") is None


class TestSetVolume:
    @patch("subprocess.run")
    def test_set_volume_calls_wpctl(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.set_volume(0, 0.5)
        # First call is pw-dump (discovery), second is wpctl
        wpctl_call = mock_run.call_args_list[-1]
        assert wpctl_call == call(
            ["wpctl", "set-volume", "241", "0.5"],
            timeout=2,
            capture_output=True,
        )

    @patch("subprocess.run")
    def test_set_volume_invalidates_cache_on_failure(self, mock_run: MagicMock) -> None:
        # First pw-dump succeeds, wpctl fails, second pw-dump re-discovers
        pw_dump_result = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        wpctl_fail = MagicMock(returncode=1)
        mock_run.side_effect = [pw_dump_result, wpctl_fail, pw_dump_result, MagicMock(returncode=0)]
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.set_volume(0, 1.0)  # discover + fail + re-discover + retry
        assert mock_run.call_count == 4


class TestMuteAllExcept:
    @patch("subprocess.run")
    def test_mutes_inactive_unmutes_active(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.mute_all_except(1)
        # After pw-dump, expect 3 wpctl calls: slot 0 muted, 1 unmuted, 2 muted
        wpctl_calls = [c for c in mock_run.call_args_list if "wpctl" in str(c)]
        volumes = {c.args[0][2]: c.args[0][3] for c in wpctl_calls}
        assert volumes["241"] == "0.0"   # slot 0 muted
        assert volumes["258"] == "1.0"   # slot 1 active
        assert volumes["285"] == "0.0"   # slot 2 muted


class TestMuteAll:
    @patch("subprocess.run")
    def test_mutes_all_slots(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=PW_DUMP_3_SLOTS, returncode=0)
        ctrl = SlotAudioControl(slot_count=3)
        ctrl.mute_all()
        wpctl_calls = [c for c in mock_run.call_args_list if "wpctl" in str(c)]
        for c in wpctl_calls:
            assert c.args[0][3] == "0.0"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_audio_control.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.studio_compositor.audio_control'`

- [ ] **Step 3: Implement SlotAudioControl**

Create `agents/studio_compositor/audio_control.py`:

```python
"""PipeWire per-stream volume control for YouTube audio slots.

Wraps wpctl for idempotent volume management. No toggle semantics —
set_volume(slot, 0.0) is always mute, set_volume(slot, 1.0) is always full.
Node IDs are discovered from pw-dump and cached, with automatic invalidation
on wpctl failure (handles ffmpeg restarts that change node IDs).
"""

from __future__ import annotations

import json
import logging
import subprocess

log = logging.getLogger(__name__)


class SlotAudioControl:
    """Per-slot YouTube audio volume control via PipeWire."""

    def __init__(self, slot_count: int = 3) -> None:
        self._slot_count = slot_count
        self._node_cache: dict[str, int] = {}  # stream_name -> node_id

    def _refresh_cache(self) -> None:
        """Parse pw-dump to discover youtube-audio node IDs."""
        self._node_cache.clear()
        try:
            result = subprocess.run(
                ["pw-dump"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            nodes = json.loads(result.stdout)
            for node in nodes:
                if node.get("type") != "PipeWire:Interface:Node":
                    continue
                props = node.get("info", {}).get("props", {})
                media_name = props.get("media.name", "")
                if media_name.startswith("youtube-audio-"):
                    self._node_cache[media_name] = node["id"]
        except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError) as exc:
            log.warning("pw-dump failed: %s", exc)

    def discover_node(self, stream_name: str) -> int | None:
        """Find PipeWire node ID for a named stream.

        Returns cached result if available, otherwise runs pw-dump.
        """
        if stream_name in self._node_cache:
            return self._node_cache[stream_name]
        if not self._node_cache:
            self._refresh_cache()
        return self._node_cache.get(stream_name)

    def set_volume(self, slot_id: int, level: float) -> None:
        """Set volume for youtube-audio-{slot_id}. Idempotent.

        Args:
            slot_id: 0, 1, or 2
            level: 0.0 = silent, 1.0 = full volume
        """
        stream_name = f"youtube-audio-{slot_id}"
        node_id = self.discover_node(stream_name)
        if node_id is None:
            log.debug("No PipeWire node for %s", stream_name)
            return

        try:
            result = subprocess.run(
                ["wpctl", "set-volume", str(node_id), str(level)],
                timeout=2,
                capture_output=True,
            )
            if result.returncode != 0:
                # Node ID stale (ffmpeg restarted) — invalidate and retry once
                log.debug("wpctl failed for node %d, re-discovering", node_id)
                self._node_cache.clear()
                self._refresh_cache()
                node_id = self._node_cache.get(stream_name)
                if node_id is not None:
                    subprocess.run(
                        ["wpctl", "set-volume", str(node_id), str(level)],
                        timeout=2,
                        capture_output=True,
                    )
        except subprocess.TimeoutExpired:
            log.warning("wpctl timed out for %s", stream_name)

    def mute_all_except(self, active_slot: int) -> None:
        """Set active slot to 1.0, all others to 0.0."""
        for slot_id in range(self._slot_count):
            self.set_volume(slot_id, 1.0 if slot_id == active_slot else 0.0)

    def mute_all(self) -> None:
        """Mute all YouTube audio streams."""
        for slot_id in range(self._slot_count):
            self.set_volume(slot_id, 0.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_audio_control.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Lint**

Run: `cd ~/projects/hapax-council && uv run ruff check agents/studio_compositor/audio_control.py tests/test_audio_control.py && uv run ruff format agents/studio_compositor/audio_control.py tests/test_audio_control.py`

- [ ] **Step 6: Commit**

```bash
git add agents/studio_compositor/audio_control.py tests/test_audio_control.py
git commit -m "feat(compositor): add SlotAudioControl for PipeWire per-stream volume"
```

---

### Task 2: Route TTS to assistant sink

**Files:**
- Modify: `agents/hapax_daimonion/pw_audio_output.py:30-53` (PwAudioOutput.__init__ and _ensure_process)
- Modify: `agents/hapax_daimonion/pw_audio_output.py:122-148` (play_pcm function)

- [ ] **Step 1: Add target parameter to PwAudioOutput**

Edit `agents/hapax_daimonion/pw_audio_output.py`. Change the `__init__` to accept an optional `target` parameter, and thread it into the pw-cat command in `_ensure_process`:

```python
class PwAudioOutput:
    """Persistent pw-cat playback subprocess.

    Keeps a single pw-cat --playback process alive and writes PCM
    to its stdin. Thread-safe. Auto-restarts on subprocess death.
    """

    def __init__(
        self, sample_rate: int = 24000, channels: int = 1, target: str | None = None
    ) -> None:
        self._rate = sample_rate
        self._channels = channels
        self._target = target
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def _ensure_process(self) -> subprocess.Popen | None:
        """Start or restart the pw-cat subprocess."""
        if self._process is not None and self._process.poll() is None:
            return self._process
        try:
            cmd = [
                "pw-cat",
                "--playback",
                "--raw",
                "--format",
                "s16",
                "--rate",
                str(self._rate),
                "--channels",
                str(self._channels),
            ]
            if self._target:
                cmd.extend(["--target", self._target])
            cmd.append("-")
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.info("pw-cat playback started (pid=%d, rate=%d)", self._process.pid, self._rate)
            return self._process
        except FileNotFoundError:
            log.error("pw-cat not found — install pipewire")
            return None
        except Exception as exc:
            log.warning("Failed to start pw-cat playback: %s", exc)
            return None
```

Also update the `play_pcm` one-shot function to accept a `target` parameter:

```python
def play_pcm(
    pcm: bytes, rate: int = 24000, channels: int = 1, target: str | None = None
) -> None:
    """One-shot blocking PCM playback via pw-cat.

    Spawns a pw-cat process, writes all PCM, waits for completion.
    Use for infrequent playback (chimes, samples). For high-frequency
    writes, use PwAudioOutput instead.
    """
    try:
        cmd = [
            "pw-cat",
            "--playback",
            "--raw",
            "--format",
            "s16",
            "--rate",
            str(rate),
            "--channels",
            str(channels),
        ]
        if target:
            cmd.extend(["--target", target])
        cmd.append("-")
        subprocess.run(
            cmd,
            input=pcm,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        log.error("pw-cat not found — install pipewire")
    except subprocess.TimeoutExpired:
        log.warning("pw-cat playback timed out")
    except Exception as exc:
        log.warning("pw-cat playback failed: %s", exc)
```

- [ ] **Step 2: Update director's _play_audio to use assistant target**

Edit `agents/studio_compositor/director_loop.py:921-930`. Change the `PwAudioOutput` instantiation to target the assistant sink:

```python
    def _play_audio(self, pcm: bytes) -> None:
        """Play PCM using persistent pw-cat subprocess targeting assistant sink."""
        try:
            if not hasattr(self, "_audio_output") or self._audio_output is None:
                from agents.hapax_daimonion.pw_audio_output import PwAudioOutput

                self._audio_output = PwAudioOutput(
                    sample_rate=24000,
                    channels=1,
                    target="input.loopback.sink.role.assistant",
                )
            self._audio_output.write(pcm)
        except Exception:
            log.exception("Audio playback error")
```

- [ ] **Step 3: Lint**

Run: `cd ~/projects/hapax-council && uv run ruff check agents/hapax_daimonion/pw_audio_output.py agents/studio_compositor/director_loop.py && uv run ruff format agents/hapax_daimonion/pw_audio_output.py agents/studio_compositor/director_loop.py`

- [ ] **Step 4: Commit**

```bash
git add agents/hapax_daimonion/pw_audio_output.py agents/studio_compositor/director_loop.py
git commit -m "feat(audio): route TTS to assistant PipeWire sink for OBS separation"
```

---

### Task 3: Refactor director threading — merge speech + advance

**Files:**
- Modify: `agents/studio_compositor/director_loop.py:199-228` (remove _find_mixer_node, _duck_music)
- Modify: `agents/studio_compositor/director_loop.py:247-264` (add _transition_lock and _audio_control to __init__)
- Modify: `agents/studio_compositor/director_loop.py:345-384` (remove start's sync call, remove _next_slot, remove _sync_slot_playback)
- Modify: `agents/studio_compositor/director_loop.py:386-463` (simplify _loop, remove _advance thread)
- Modify: `agents/studio_compositor/director_loop.py:855-910` (rewrite _speak_activity, remove _transition_to_reactor, remove _advance_after_speak)

This task has many edits. Apply them in sequence — each edit builds on the previous.

- [ ] **Step 1: Remove _find_mixer_node and _duck_music**

Delete lines 199-228 in `director_loop.py`. Remove the `_MIXER_NODE_ID` global, `_find_mixer_node()`, and `_duck_music()` functions:

```python
# DELETE this entire block (lines 199-228):
_MIXER_NODE_ID: str | None = None


def _find_mixer_node() -> str | None:
    ...

def _duck_music(level: float) -> None:
    ...
```

- [ ] **Step 2: Add _transition_lock and _audio_control to __init__**

Edit the `__init__` method (line 247). Add two new fields after `self._tts_lock`:

```python
    def __init__(self, video_slots: list, reactor_overlay) -> None:
        self._slots = video_slots
        self._reactor = reactor_overlay
        self._activity = "react"  # current activity
        self._activity_start = 0.0
        self._state = "IDLE"  # IDLE or SPEAKING
        self._active_slot = 0
        self._video_start_time = 0.0
        self._last_perception = 0.0
        self._accumulated_reacts: list[str] = []
        self._reaction_history: list[str] = []  # persists across turns
        self._reaction_count: int = 0
        self._last_album_track = ""  # for vinyl track-change detection
        self._tts_manager = None
        self._tts_lock = threading.Lock()
        self._transition_lock = threading.Lock()
        self._audio_control: SlotAudioControl | None = None
        self._running = False
        self._thread = None
        self._load_memory()
```

Add the import at the top of the file (with the other imports):

```python
from agents.studio_compositor.audio_control import SlotAudioControl
```

- [ ] **Step 3: Rewrite start() — initialize audio control, mute inactive slots**

Replace the `start` method (line 345-353):

```python
    def start(self) -> None:
        self._running = True
        self._video_start_time = time.monotonic()
        self._audio_control = SlotAudioControl(slot_count=len(self._slots))
        if self._slots:
            self._slots[self._active_slot].is_active = True
            self._audio_control.mute_all_except(self._active_slot)
        self._thread = threading.Thread(target=self._loop, daemon=True, name="director-loop")
        self._thread.start()
        log.info("Director loop started (slot %d active)", self._active_slot)
```

- [ ] **Step 4: Remove _next_slot and _sync_slot_playback**

Delete `_next_slot` (lines 358-360) and `_sync_slot_playback` (lines 362-384) entirely. Slot advancement now happens only inside `_do_speak_and_advance` under the transition lock.

- [ ] **Step 5: Simplify _loop — remove _advance thread**

Replace the `_loop` method. Remove the `_advance` inner function and the thread that spawns it. The loop now just calls `_speak_activity` which handles everything:

```python
    def _loop(self) -> None:
        """Unified loop: Hapax decides what to do each tick."""
        while self._running:
            try:
                if self._state == "SPEAKING":
                    time.sleep(0.5)
                    continue

                # Check for finished videos — reload from playlist
                for s in self._slots:
                    if s.check_finished():
                        log.info("Slot %d finished, reloading from playlist", s.slot_id)
                        threading.Thread(
                            target=self._reload_slot_from_playlist,
                            args=(s.slot_id,),
                            daemon=True,
                        ).start()

                now = time.monotonic()
                if now - self._last_perception < PERCEPTION_INTERVAL:
                    time.sleep(0.5)
                    continue
                self._last_perception = now

                # Build unified prompt with all signals + activity capabilities
                prompt = self._build_unified_prompt()
                images = self._gather_images()

                # Single LLM call — Hapax chooses activity + content
                result = self._call_activity_llm(prompt, images)
                if not result:
                    time.sleep(1.0)
                    continue

                # Parse activity choice
                activity = "react"
                text = result
                try:
                    obj = json.loads(result) if result.startswith("{") else None
                    if obj:
                        activity = obj.get("activity", "react")
                        text = obj.get("react", "")
                except (json.JSONDecodeError, TypeError):
                    pass

                # Handle activity
                if activity == "silence" or not text:
                    if self._activity != "silence":
                        log.info("Activity: silence")
                        self._activity = activity
                        self._reactor.set_header("SILENCE")
                    time.sleep(5.0)
                    continue

                if activity != self._activity:
                    log.info("Activity: %s → %s", self._activity, activity)
                    self._activity = activity
                    self._reactor.set_header(activity.upper())

                # Speak — speech + slot advance happen in one thread
                self._speak_activity(text, activity)

            except Exception:
                log.exception("Director loop error")
            time.sleep(0.5)
```

- [ ] **Step 6: Rewrite _speak_activity as unified speak-and-advance**

Replace `_speak_activity` (lines 855-886) and delete `_transition_to_reactor` (lines 888-910). The new `_speak_activity` merges speech, slot advance, and audio control into one thread guarded by `_transition_lock`:

```python
    def _speak_activity(self, text: str, activity: str) -> None:
        """Speak text, then advance slot if reacting. Single thread, locked."""
        self._state = "SPEAKING"
        self._reactor.set_text(text)
        self._reactor.set_speaking(True)
        log.info("%s [%s]: %s", activity.upper(), self._activity, text[:80])

        def _do_speak_and_advance():
            with self._transition_lock:
                try:
                    pcm = self._synthesize(text)
                    if pcm:
                        if self._audio_control:
                            self._audio_control.mute_all()
                        self._reactor.feed_pcm(pcm)
                        self._play_audio(pcm)
                        time.sleep(0.3)
                except Exception:
                    log.exception("TTS error")

                # Advance slot atomically (react mode only)
                if activity == "react":
                    self._slots[self._active_slot].is_active = False
                    self._accumulated_reacts.clear()
                    self._active_slot = (self._active_slot + 1) % len(self._slots)
                    self._slots[self._active_slot].is_active = True
                    self._video_start_time = time.monotonic()
                    self._last_perception = 0.0
                    log.info("Now playing slot %d", self._active_slot)

                # Restore audio on new active slot
                if self._audio_control:
                    self._audio_control.mute_all_except(self._active_slot)

                # Bookkeeping
                self._log_to_obsidian(text, activity)
                ts = datetime.now().strftime("%H:%M")
                label = f'[{ts}] {activity}: "{text}"'
                self._reaction_history.append(label)
                if len(self._reaction_history) > 20:
                    self._reaction_history = self._reaction_history[-20:]
                self._reactor.set_speaking(False)
                self._reactor.set_text("")
                self._state = "IDLE"

        threading.Thread(
            target=_do_speak_and_advance, daemon=True, name=f"speak-{activity}"
        ).start()
```

- [ ] **Step 7: Remove any remaining references to deleted functions**

Search for calls to `_sync_slot_playback`, `_duck_music`, `_next_slot`, `_transition_to_reactor`, `_advance_after_speak` in director_loop.py and remove them. The `_loop` method should no longer reference any of these.

Run: `cd ~/projects/hapax-council && grep -n "_sync_slot_playback\|_duck_music\|_next_slot\|_transition_to_reactor\|_advance_after_speak\|_find_mixer_node" agents/studio_compositor/director_loop.py`
Expected: No output (all references removed)

- [ ] **Step 8: Lint**

Run: `cd ~/projects/hapax-council && uv run ruff check agents/studio_compositor/director_loop.py && uv run ruff format agents/studio_compositor/director_loop.py`

- [ ] **Step 9: Commit**

```bash
git add agents/studio_compositor/director_loop.py
git commit -m "refactor(director): merge speech+advance into locked thread, wire SlotAudioControl"
```

---

### Task 4: Remove pause/SIGSTOP from youtube-player

**Files:**
- Modify: `scripts/youtube-player.py:57` (remove paused field from VideoSlot.__init__)
- Modify: `scripts/youtube-player.py:72,193` (remove paused reset in play/stop)
- Modify: `scripts/youtube-player.py:195-204` (delete toggle_pause)
- Modify: `scripts/youtube-player.py:207` (simplify is_playing)
- Modify: `scripts/youtube-player.py:213-222` (remove paused from get_status)
- Modify: `scripts/youtube-player.py:233,515-628` (remove legacy pause globals/functions)
- Modify: `scripts/youtube-player.py:649-660` (remove paused from legacy get_status)
- Modify: `scripts/youtube-player.py:731-776` (remove pause HTTP endpoints)

- [ ] **Step 1: Remove paused field and toggle_pause from VideoSlot**

In `scripts/youtube-player.py`, edit the `VideoSlot` class:

Remove `self.paused: bool = False` from `__init__` (line 57).

Remove `self.paused = False` from `play()` (line 72) and `stop()` (line 193).

Delete the entire `toggle_pause` method (lines 195-204):
```python
# DELETE:
    def toggle_pause(self) -> bool:
        if self.process is None:
            return False
        if self.paused:
            self.process.send_signal(signal.SIGCONT)
            self.paused = False
        else:
            self.process.send_signal(signal.SIGSTOP)
            self.paused = True
        return self.paused
```

Simplify `is_playing` (line 207) — remove the `and not self.paused` check:
```python
    def is_playing(self) -> bool:
        return self.process is not None and self.process.poll() is None
```

Remove `paused` from `get_status` (lines 213-222):
```python
    def get_status(self) -> dict:
        running = self.process is not None and self.process.poll() is None
        return {
            "slot": self.slot_id,
            "playing": running,
            "url": self.url,
            "title": self.title,
            "channel": self.channel,
            "finished": self.is_finished(),
        }
```

- [ ] **Step 2: Remove legacy pause globals and functions**

Remove the global `paused = False` (line 233).

In `play_video()` (line 515), remove `paused` from the global statement and remove `paused = False`.

In `stop_current()` (line 596), remove `paused` from the global statement and remove `paused = False`.

Delete the entire `toggle_pause()` function (lines 615-628):
```python
# DELETE:
def toggle_pause() -> bool:
    """Pause/resume ffmpeg via SIGSTOP/SIGCONT."""
    global paused
    ...
```

Remove `paused` from legacy `get_status()` (lines 649-660):
```python
def get_status() -> dict:
    """Current player status."""
    running = current_process is not None and current_process.poll() is None
    return {
        "playing": running,
        "url": current_url,
        "title": current_title,
        "channel": current_channel,
        "queue_length": len(queue),
        "queue": [q["url"] for q in queue],
    }
```

- [ ] **Step 3: Remove pause HTTP endpoints**

In the `Handler.do_POST` method, remove the per-slot pause handler (the `elif action == "pause"` branch around line 753-755):
```python
# DELETE this branch:
                elif action == "pause":
                    with slot.lock:
                        p = slot.toggle_pause()
                    self._json({"paused": p, "slot": slot_id})
```

Remove the legacy `/pause` endpoint (around line 775-776):
```python
# DELETE this branch:
        elif self.path == "/pause":
            with slots[0].lock:
                p = slots[0].toggle_pause()
            self._json({"paused": p})
```

- [ ] **Step 4: Remove unused signal import if SIGSTOP/SIGCONT were the only uses**

Check if `signal.SIGTERM` is still used (it is, in `stop()`). Keep the `import signal` but verify no references to SIGSTOP or SIGCONT remain:

Run: `cd ~/projects/hapax-council && grep -n "SIGSTOP\|SIGCONT\|toggle_pause\|\.paused" scripts/youtube-player.py`
Expected: No output

- [ ] **Step 5: Lint**

Run: `cd ~/projects/hapax-council && uv run ruff check scripts/youtube-player.py && uv run ruff format scripts/youtube-player.py`

- [ ] **Step 6: Commit**

```bash
git add scripts/youtube-player.py
git commit -m "refactor(youtube-player): remove SIGSTOP pause mechanism, pure play/stop daemon"
```

---

### Task 5: Integration verification

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_audio_control.py tests/test_studio_compositor.py -v`
Expected: All tests pass

- [ ] **Step 2: Lint all changed files**

Run: `cd ~/projects/hapax-council && uv run ruff check agents/studio_compositor/audio_control.py agents/studio_compositor/director_loop.py agents/hapax_daimonion/pw_audio_output.py scripts/youtube-player.py`
Expected: No errors

- [ ] **Step 3: Live verification — audio control**

With youtube-player running and 3 slots loaded, verify PipeWire control works:

```bash
# Find node IDs
pw-dump | python3 -c "
import json, sys
for n in json.load(sys.stdin):
    if n.get('type') == 'PipeWire:Interface:Node':
        p = n.get('info',{}).get('props',{})
        if 'youtube-audio' in p.get('media.name',''):
            print(f'{n[\"id\"]} {p[\"media.name\"]}')"

# Test mute/unmute (substitute actual node IDs)
wpctl set-volume <slot0_id> 0.0
wpctl set-volume <slot1_id> 0.0
wpctl set-volume <slot2_id> 1.0
# Only slot 2 should be audible
```

- [ ] **Step 4: Live verification — TTS routing**

```bash
# Check that TTS goes through assistant sink during speech
# Trigger a TTS event, then check:
pw-dump | python3 -c "
import json, sys
for n in json.load(sys.stdin):
    if n.get('type') == 'PipeWire:Interface:Node':
        p = n.get('info',{}).get('props',{})
        if 'pw-cat' in p.get('node.name','') and n.get('info',{}).get('state') == 'running':
            print(f'{n[\"id\"]} target={p.get(\"target.object\",\"default\")}')"
```

- [ ] **Step 5: Restart compositor service**

```bash
systemctl --user restart studio-compositor.service
journalctl --user -eu studio-compositor --no-pager -n 20 | grep -i "director\|audio\|slot"
```

Confirm director starts, initializes SlotAudioControl, and mutes inactive slots on first tick.
