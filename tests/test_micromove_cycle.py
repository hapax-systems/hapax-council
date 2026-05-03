"""Tests for cc-task u4-eight-slot-micromove-cycle-activate (Phase 0)."""

from __future__ import annotations

import threading

import pytest

from shared.micromove_cycle import (
    CYCLE_LENGTH,
    MICROMOVE_SLOTS,
    MicromoveAction,
    MicromoveCycle,
    slot_by_name,
)


class TestSlotCatalog:
    def test_exactly_eight_slots(self) -> None:
        """The U4 cc-task title pins the count: '8-slot micromove cycle'."""
        assert len(MICROMOVE_SLOTS) == 8
        assert CYCLE_LENGTH == 8

    def test_slot_indices_are_dense_and_zero_based(self) -> None:
        for expected_idx, action in enumerate(MICROMOVE_SLOTS):
            assert action.slot == expected_idx, (
                f"slot {expected_idx} has .slot={action.slot}; the cycle math depends "
                f"on dense zero-based indexing"
            )

    def test_slot_names_are_unique(self) -> None:
        names = [a.name for a in MICROMOVE_SLOTS]
        assert len(names) == len(set(names)), f"duplicate slot names: {names}"

    def test_axes_cover_spatial_tonal_focal(self) -> None:
        axes = {a.axis for a in MICROMOVE_SLOTS}
        for axis in ("spatial", "tonal", "focal"):
            assert axis in axes, f"missing axis {axis!r} in slot catalog"

    def test_cc_task_example_slots_present(self) -> None:
        """The cc-task body cites zoom-in / pan-left / blur as examples —
        a vocabulary that drops one is a regression vs the operator's intent."""
        for cited in ("zoom-in", "pan-left", "blur"):
            assert slot_by_name(cited) is not None, (
                f"cc-task example slot {cited!r} absent from MICROMOVE_SLOTS"
            )

    def test_every_slot_has_hint(self) -> None:
        for action in MICROMOVE_SLOTS:
            assert isinstance(action.hint, dict)
            assert action.hint, (
                f"slot {action.name!r} has empty hint; consumers won't know what to fire"
            )
            assert "duration_ticks" in action.hint, (
                f"slot {action.name!r} hint missing 'duration_ticks' (consumer-facing convention)"
            )


class TestCycleAdvance:
    def test_starts_at_slot_zero(self) -> None:
        cycle = MicromoveCycle()
        assert cycle.current_slot() == 0
        assert cycle.current_action().slot == 0

    def test_tick_advances_one_slot(self) -> None:
        cycle = MicromoveCycle()
        action = cycle.tick()
        assert action.slot == 1
        assert cycle.current_slot() == 1

    def test_tick_wraps_after_eight(self) -> None:
        cycle = MicromoveCycle()
        # After 8 ticks we should be back at slot 0 (the cycle wrapped exactly once).
        for _ in range(8):
            cycle.tick()
        assert cycle.current_slot() == 0

    def test_full_cycle_visits_every_slot(self) -> None:
        cycle = MicromoveCycle()
        seen = {cycle.current_slot()}
        for _ in range(CYCLE_LENGTH - 1):
            seen.add(cycle.tick().slot)
        assert seen == set(range(CYCLE_LENGTH)), (
            f"a full 8-tick run did not visit every slot; saw {seen}"
        )

    def test_reset_returns_to_zero(self) -> None:
        cycle = MicromoveCycle()
        for _ in range(5):
            cycle.tick()
        assert cycle.current_slot() == 5
        cycle.reset()
        assert cycle.current_slot() == 0


class TestSlotByNameLookup:
    @pytest.mark.parametrize(
        "name",
        [
            "zoom-in",
            "zoom-out",
            "pan-left",
            "pan-right",
            "blur",
            "sharpen",
            "warm-tint",
            "cool-tint",
        ],
    )
    def test_lookup_succeeds_for_every_canonical_name(self, name: str) -> None:
        action = slot_by_name(name)
        assert action is not None
        assert isinstance(action, MicromoveAction)
        assert action.name == name

    def test_lookup_returns_none_for_unknown(self) -> None:
        assert slot_by_name("zoom-sideways") is None


class TestThreadSafety:
    """A director-loop tick() and a metrics scrape current_slot() must
    not race on the slot index. With 8 slots and N concurrent ticks,
    final index = N % 8 deterministically."""

    def test_concurrent_ticks_advance_deterministically(self) -> None:
        cycle = MicromoveCycle()
        TICKS = 80  # 10 full cycles → final index 0
        threads = [threading.Thread(target=cycle.tick) for _ in range(TICKS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert cycle.current_slot() == TICKS % CYCLE_LENGTH
