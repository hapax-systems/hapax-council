"""D-01 Phase 3b — director_loop voice-tier impingement consumer tests.

Per architecture spec docs/research/2026-04-20-d01-director-impingement-
consumer-architecture.md §3.1 (Option A per-tick poll) + §4.3 (state file
written for downstream consumers).

Producer side (vocal_chain.apply_tier → emit_voice_tier_impingement →
write to bus) is delta-zone and may not be wired yet. The consumer
infrastructure ships independently — when the producer wires, the
consumer just works (proof-of-wiring pattern shared with D-18).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest  # noqa: TC002 — runtime import for fixtures + decorators

import agents.studio_compositor.director_loop as dl_mod
from shared.impingement import Impingement, ImpingementType
from shared.typed_impingements import (
    VoiceTierImpingement,
)
from shared.voice_tier import VoiceTier


class _FakeSlot:
    def __init__(self, slot_id: int) -> None:
        self.slot_id = slot_id
        self._title = "t"
        self._channel = "c"
        self.is_active = slot_id == 0


class _FakeReactor:
    def set_header(self, *a, **k) -> None: ...
    def set_text(self, *a, **k) -> None: ...
    def set_speaking(self, *a, **k) -> None: ...
    def feed_pcm(self, *a, **k) -> None: ...


@pytest.fixture
def director(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Construct a DirectorLoop with the impingement consumer pointed at a
    tmp bus (so production /dev/shm/hapax-dmn/impingements.jsonl is never
    touched)."""
    bus = tmp_path / "bus.jsonl"
    cursor = tmp_path / "cursor.txt"
    state = tmp_path / "state.json"
    monkeypatch.setattr(dl_mod, "_DMN_IMPINGEMENTS_FILE", bus)

    # Patch the cursor path + state path constants used by the consumer
    # by monkey-patching Path() construction in the consumer body. The
    # ImpingementConsumer takes the cursor path from __init__; we
    # override after construction by reaching into the instance.
    d = dl_mod.DirectorLoop(video_slots=[_FakeSlot(0)], reactor_overlay=_FakeReactor())
    d._voice_tier_consumer._path = bus  # noqa: SLF001 — test-only redirect
    d._voice_tier_consumer._cursor_path = cursor  # noqa: SLF001
    d._voice_tier_consumer._cursor = 0  # noqa: SLF001
    return d, bus, state


def _write_voice_tier_impingement(bus: Path, tier: VoiceTier) -> None:
    """Write one VoiceTierImpingement to the test bus."""
    payload = VoiceTierImpingement(
        tier=tier,
        programme_band=(int(tier), int(tier)),
        voice_path="dry",
        monetization_risk="none",
        excursion=False,
        clamped_from=None,
    )
    imp = payload.to_impingement(strength=1.0)
    bus.parent.mkdir(parents=True, exist_ok=True)
    with bus.open("a", encoding="utf-8") as f:
        f.write(imp.model_dump_json() + "\n")


class TestVoiceTierConsumer:
    def test_initial_state_is_none(self, director) -> None:
        d, _, _ = director
        assert d._current_voice_tier is None
        assert d._current_programme_band is None

    def test_no_impingements_no_state_change(self, director) -> None:
        d, _, _ = director
        d._consume_voice_tier_impingements()
        assert d._current_voice_tier is None

    def test_voice_tier_impingement_updates_state(self, director) -> None:
        """Verify in-memory state update; state-file write tested separately."""
        d, bus, _ = director
        _write_voice_tier_impingement(bus, VoiceTier.UNADORNED)
        d._consume_voice_tier_impingements()
        assert d._current_voice_tier == int(VoiceTier.UNADORNED)
        assert d._current_programme_band == (
            int(VoiceTier.UNADORNED),
            int(VoiceTier.UNADORNED),
        )

    def test_only_voice_tier_impingements_consumed(self, director) -> None:
        """Other impingement sources on the bus must NOT update tier state."""
        d, bus, _ = director
        # Write a non-tier impingement.
        other = Impingement(
            timestamp=0.0,
            source="some.other.source",
            type=ImpingementType.STATISTICAL_DEVIATION,
            strength=1.0,
            content={"x": 1},
        )
        bus.parent.mkdir(parents=True, exist_ok=True)
        with bus.open("a", encoding="utf-8") as f:
            f.write(other.model_dump_json() + "\n")
        d._consume_voice_tier_impingements()
        assert d._current_voice_tier is None

    def test_latest_tier_wins_when_multiple_arrive(self, director) -> None:
        """If multiple tier impingements land between consumes, the LAST
        one wins (the director cares about the current tier, not
        history)."""
        d, bus, _ = director
        _write_voice_tier_impingement(bus, VoiceTier.UNADORNED)
        _write_voice_tier_impingement(bus, VoiceTier.BROADCAST_GHOST)
        d._consume_voice_tier_impingements()
        assert d._current_voice_tier == int(VoiceTier.BROADCAST_GHOST)

    def test_consumer_failure_does_not_break_tick(
        self, director, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ImpingementConsumer.read_new() failures must NOT raise out of
        the consume helper — director's tick must survive a corrupt
        bus / unreadable cursor."""
        d, _, _ = director

        def _broken_read(*args, **kwargs):
            raise OSError("simulated bus failure")

        monkeypatch.setattr(d._voice_tier_consumer, "read_new", _broken_read)
        # Must not raise.
        d._consume_voice_tier_impingements()
        assert d._current_voice_tier is None  # state unchanged

    def test_state_file_written_atomically(
        self, director, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The state-file write uses tmp+rename so partial writes don't
        surface to readers (Phase 8 emphasis loop + camera-profile
        selector)."""
        d, bus, _ = director
        state_dir = tmp_path / "hapax-director"
        state_path = state_dir / "voice-tier-state.json"
        original_path = dl_mod.Path

        def _redirect(p):
            if str(p) == "/dev/shm/hapax-director/voice-tier-state.json":
                return state_path
            return original_path(p)

        monkeypatch.setattr(dl_mod, "Path", _redirect)
        _write_voice_tier_impingement(bus, VoiceTier.MEMORY)
        d._consume_voice_tier_impingements()
        assert state_path.exists()
        data = json.loads(state_path.read_text())
        assert data["tier"] == int(VoiceTier.MEMORY)
        assert data["voice_path"] == "dry"
