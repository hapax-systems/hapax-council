"""Tests for the u6-periodic-tick-driver layout-tick driver.

cc-task: u6-periodic-tick-driver. Verifies that the periodic driver
- builds a state_provider from /dev/shm + ~/.cache files,
- adapts LayoutStore for apply_layout_switch,
- emits hapax_layout_switch_dispatched_total{layout, reason} per tick,
- honors HAPAX_LAYOUT_TICK_DISABLED env-flag.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from agents.studio_compositor import layout_tick_driver
from agents.studio_compositor.layout_state import LayoutState
from agents.studio_compositor.layout_switcher import LayoutSwitcher
from agents.studio_compositor.layout_tick_driver import (
    _driver_tick,
    _LayoutStoreAdapter,
    _read_segment_layout_pressure,
    _RenderedLayoutStateAdapter,
    build_state_provider,
    run_layout_tick_loop,
    start_layout_tick_driver,
)
from agents.studio_compositor.segment_layout_control import (
    LayoutDecisionReason,
    LayoutDecisionStatus,
    LayoutNeedKind,
    SegmentActionIntent,
)
from shared.compositor_model import Layout

NOW = 1_000.0
REPO_ROOT = Path(__file__).resolve().parents[2]

# ── env-flag gate ──────────────────────────────────────────────────


def test_disabled_env_flag_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(layout_tick_driver.ENV_DISABLE, "1")

    class _Stub:
        _layout_store = object()

    result = start_layout_tick_driver(_Stub())
    assert result is None


def test_enabled_starts_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(layout_tick_driver.ENV_DISABLE, raising=False)

    @dataclass
    class _FakeStore:
        _name: str | None = "garage-door"

        def active_name(self) -> str | None:
            return self._name

        def get(self, name: str) -> Any:
            return None

        def get_active(self) -> Any:
            return None

        def reload_changed(self) -> list[str]:
            return []

        def set_active(self, name: str) -> bool:
            return True

    class _Compositor:
        _layout_store = _FakeStore()

    compositor = _Compositor()
    # Patch the daemon thread loop so it doesn't actually spin forever.
    monkeypatch.setattr(
        layout_tick_driver,
        "run_layout_tick_loop",
        lambda **kwargs: 0,
    )
    thread = start_layout_tick_driver(compositor)
    assert thread is not None
    thread.join(timeout=2.0)


def test_no_layout_store_returns_none() -> None:
    class _Compositor:
        pass

    compositor = _Compositor()
    result = start_layout_tick_driver(compositor)
    assert result is None


# ── state provider ─────────────────────────────────────────────────


def test_state_provider_returns_safe_defaults_with_no_signals(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No state files → safe defaults (consent_safe=False, vinyl=False, etc)."""
    monkeypatch.delenv("HAPAX_CONSENT_EGRESS_GATE", raising=False)
    monkeypatch.setattr(layout_tick_driver, "ALBUM_STATE_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(
        layout_tick_driver,
        "VINYL_OPERATOR_OVERRIDE_FLAG",
        tmp_path / "missing.flag",
    )
    monkeypatch.setattr(layout_tick_driver, "DIRECTOR_INTENT_JSONL", tmp_path / "missing.jsonl")

    state = build_state_provider()()
    assert state["consent_safe_active"] is False
    assert state["vinyl_playing"] is False
    assert state["director_activity"] is None


def test_state_provider_reads_vinyl_override_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    flag = tmp_path / "vinyl-operator-active.flag"
    flag.write_text("")
    monkeypatch.setattr(layout_tick_driver, "VINYL_OPERATOR_OVERRIDE_FLAG", flag)
    monkeypatch.setattr(layout_tick_driver, "ALBUM_STATE_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(layout_tick_driver, "DIRECTOR_INTENT_JSONL", tmp_path / "missing.jsonl")
    monkeypatch.delenv("HAPAX_CONSENT_EGRESS_GATE", raising=False)

    state = build_state_provider()()
    assert state["vinyl_playing"] is True


def test_state_provider_reads_director_activity_tail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    intent = tmp_path / "director-intent.jsonl"
    intent.write_text(
        '{"activity": "react", "ts": 1234567890.0}\n{"activity": "vinyl", "ts": 1234567891.0}\n'
    )
    monkeypatch.setattr(layout_tick_driver, "DIRECTOR_INTENT_JSONL", intent)
    monkeypatch.setattr(layout_tick_driver, "ALBUM_STATE_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(
        layout_tick_driver,
        "VINYL_OPERATOR_OVERRIDE_FLAG",
        tmp_path / "missing.flag",
    )
    monkeypatch.delenv("HAPAX_CONSENT_EGRESS_GATE", raising=False)

    state = build_state_provider()()
    assert state["director_activity"] == "vinyl"


def test_state_provider_consent_safe_env_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_CONSENT_EGRESS_GATE", "1")

    state = build_state_provider()()
    assert state["consent_safe_active"] is True


def test_active_segment_pressure_derives_bounded_runtime_intents(tmp_path: Path) -> None:
    state_file = tmp_path / "active-segment.json"
    state_file.write_text(
        json.dumps(
            {
                "programme_id": "programme:seg-1",
                "current_beat_index": 4,
                "prepared_artifact_ref": {
                    "artifact_sha256": "sha256:abc123",
                    "prep_session_id": "prep-1",
                    "model_id": "command-r",
                },
                "host_presence": "drop-me",
                "spoken_argument": "drop-me",
                "current_beat_layout_intents": {
                    "beat_index": 4,
                    "responsibility_mode": "hapax_responsible_live",
                    "read_mtime": NOW - 2.0,
                    "needs": [
                        {
                            "kind": "chat_participation_surface",
                            "priority": 80,
                            "source_action_kind": "chat_poll",
                            "evidence_ref": "beat:4:intent:chat_poll",
                            "expected_visible_effect": "layout.surface.chat_prompt.visible",
                            "ttl_ms": 12000,
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    pressure = _read_segment_layout_pressure(state_file, now=NOW)
    intents = pressure["segment_layout_intents"]

    assert isinstance(intents, tuple)
    assert len(intents) == 1
    intent = intents[0]
    assert intent.intent_id == "programme:seg-1:4:layout-need-0-0"
    assert intent.kind == LayoutNeedKind.CHAT_RESPONSE.value
    assert intent.requested_at == NOW - 2.0
    assert intent.ttl_s == 12.0
    assert intent.priority == 80
    assert intent.programme_id == "programme:seg-1"
    assert intent.beat_index == 4
    assert intent.target_ref == "chat_poll"
    assert intent.authority_ref == "prepared_artifact:sha256:abc123"
    assert intent.evidence_refs == (
        "beat:4:intent:chat_poll",
        "prepared_artifact:sha256:abc123",
    )
    assert intent.expected_effects == ("layout.surface.chat_prompt.visible",)
    assert intent.requested_layout is None
    assert intent.spoken_text_ref is None


def test_active_segment_pressure_refuses_supported_need_with_forbidden_fields(
    tmp_path: Path,
) -> None:
    state_file = tmp_path / "active-segment.json"
    state_file.write_text(
        json.dumps(
            {
                "programme_id": "programme:seg-1",
                "current_beat_index": 4,
                "prepared_artifact_ref": "sha256:abc123",
                "current_beat_layout_intents": {
                    "needs": [
                        {
                            "kind": "chat_participation_surface",
                            "evidence_ref": "beat:4:intent:chat_poll",
                            "requested_layout": "segment-chat",
                            "surface": {"surface_id": "unsafe-surface"},
                            "z_order": 5,
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    pressure = _read_segment_layout_pressure(state_file, now=NOW)

    assert pressure["segment_layout_intents"] == ()
    refusals = pressure["segment_layout_refusals"]
    assert isinstance(refusals, tuple)
    assert refusals[0]["reason"] == "forbidden_segment_layout_authority_field"
    assert refusals[0]["need_kind"] == "chat_participation_surface"
    assert refusals[0]["forbidden_fields"] == (
        "requested_layout",
        "surface",
        "surface.surface_id",
        "z_order",
    )


def test_active_segment_pressure_maps_tier_chat_comparison_aliases(tmp_path: Path) -> None:
    state_file = tmp_path / "active-segment.json"
    state_file.write_text(
        json.dumps(
            {
                "programme_id": "programme:seg-1",
                "current_beat_index": 6,
                "prepared_artifact_ref": "sha256:abc123",
                "current_beat_layout_intents": {
                    "needs": [
                        {"kind": "tier_status_surface", "evidence_ref": "prior:tier"},
                        {"kind": "chat_participation_surface", "evidence_ref": "prior:chat"},
                        {
                            "kind": "source_comparison_surface",
                            "evidence_ref": "prior:comparison",
                        },
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    pressure = _read_segment_layout_pressure(state_file, now=NOW)
    kinds = [intent.kind for intent in pressure["segment_layout_intents"]]

    assert kinds == [
        LayoutNeedKind.TIER_STATUS.value,
        LayoutNeedKind.CHAT_RESPONSE.value,
        LayoutNeedKind.SOURCE_COMPARISON.value,
    ]


def test_active_segment_pressure_maps_ranked_list_to_ranked_ward(tmp_path: Path) -> None:
    state_file = tmp_path / "active-segment.json"
    state_file.write_text(
        json.dumps(
            {
                "programme_id": "programme:seg-1",
                "current_beat_index": 6,
                "prepared_artifact_ref": "sha256:abc123",
                "current_beat_layout_intents": {
                    "needs": [{"kind": "ranked_list_surface", "evidence_ref": "prior:ranked"}]
                },
            }
        ),
        encoding="utf-8",
    )

    pressure = _read_segment_layout_pressure(state_file, now=NOW)
    intents = pressure["segment_layout_intents"]

    assert isinstance(intents, tuple)
    assert len(intents) == 1
    assert intents[0].kind == LayoutNeedKind.RANKED_LIST.value
    assert intents[0].expected_effects == ("ward:ranked-list-panel",)


def test_active_segment_pressure_refuses_unsupported_and_forbidden_needs(tmp_path: Path) -> None:
    state_file = tmp_path / "active-segment.json"
    state_file.write_text(
        json.dumps(
            {
                "programme_id": "programme:seg-1",
                "current_beat_index": 5,
                "prepared_artifact_ref": "sha256:def456",
                "current_beat_layout_intents": [
                    {
                        "needs": [
                            {"kind": "countdown", "layout_name": "segment-list"},
                            {"kind": "camera", "coordinates": [0, 0, 100, 100]},
                            {"kind": "mood", "cues": ["pulse"]},
                        ]
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    pressure = _read_segment_layout_pressure(state_file, now=NOW)

    assert pressure["segment_layout_intents"] == ()
    refusals = pressure["segment_layout_refusals"]
    assert isinstance(refusals, tuple)
    assert [item["need_kind"] for item in refusals] == ["countdown", "camera", "mood"]
    assert all(item["reason"] == "forbidden_segment_layout_authority_field" for item in refusals)
    assert refusals[0]["forbidden_fields"] == ("layout_name",)
    assert refusals[1]["forbidden_fields"] == ("coordinates",)
    assert refusals[2]["forbidden_fields"] == ("cues",)


def test_refused_only_segment_pressure_suppresses_legacy_default_switch() -> None:
    store = _FakeStore(
        layouts={
            "default": _FakeLayout("default"),
            "vinyl-focus": _FakeLayout("vinyl-focus"),
        },
        _active="default",
    )
    adapter = _LayoutStoreAdapter(store)
    switcher = LayoutSwitcher(initial_layout="default")
    state_provider = lambda: {  # noqa: E731
        "consent_safe_active": False,
        "vinyl_playing": True,
        "director_activity": None,
        "stream_mode": None,
        "segment_layout_intents": (),
        "segment_layout_pressure_seen": True,
        "segment_layout_refusals": (
            {
                "need_kind": "chat_participation_surface",
                "reason": "forbidden_segment_layout_authority_field",
                "forbidden_fields": ("requested_layout",),
            },
        ),
    }

    receipt = _driver_tick(
        state_provider=state_provider,
        layout_state=adapter,
        loader=adapter,
        switcher=switcher,
    )

    assert receipt.status is LayoutDecisionStatus.REFUSED
    assert receipt.reason is LayoutDecisionReason.NO_LAYOUT_NEEDS
    assert store.set_active_calls == []
    assert store.active_name() == "default"


# ── adapter contract ───────────────────────────────────────────────


@dataclass
class _FakeLayout:
    name: str


@dataclass
class _FakeStore:
    """Minimal LayoutStore-shape for adapter tests."""

    layouts: dict[str, Any] = field(default_factory=dict)
    _active: str | None = None
    set_active_calls: list[str] = field(default_factory=list)
    reload_calls: int = 0

    def get(self, name: str) -> Any:
        return self.layouts.get(name)

    def get_active(self) -> Any:
        if self._active is None:
            return None
        return self.layouts.get(self._active)

    def set_active(self, name: str) -> bool:
        self.set_active_calls.append(name)
        if name not in self.layouts:
            return False
        self._active = name
        return True

    def reload_changed(self) -> list[str]:
        self.reload_calls += 1
        return []

    def active_name(self) -> str | None:
        return self._active

    def list_available(self) -> list[str]:
        return sorted(self.layouts)


def _load_layout(path: str) -> Layout:
    return Layout.model_validate_json((REPO_ROOT / path).read_text(encoding="utf-8"))


def test_adapter_load_returns_layout() -> None:
    store = _FakeStore(layouts={"default": _FakeLayout("default")})
    adapter = _LayoutStoreAdapter(store)
    layout = adapter.load("default")
    assert layout.name == "default"


def test_adapter_load_triggers_reload_on_miss() -> None:
    store = _FakeStore()
    adapter = _LayoutStoreAdapter(store)
    with pytest.raises(KeyError):
        adapter.load("missing")
    assert store.reload_calls >= 1


def test_adapter_mutate_drives_set_active() -> None:
    store = _FakeStore(
        layouts={
            "default": _FakeLayout("default"),
            "vinyl-focus": _FakeLayout("vinyl-focus"),
        }
    )
    adapter = _LayoutStoreAdapter(store)
    adapter.mutate(lambda _previous: store.layouts["vinyl-focus"])
    assert store.set_active_calls == ["vinyl-focus"]


# ── periodic loop semantics ────────────────────────────────────────


def test_run_layout_tick_loop_emits_dispatch_counter_per_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Counter increments every tick, regardless of whether a switch applies."""
    increments: list[tuple[str, str]] = []

    def _fake_increment(layout_name: str, reason: str) -> None:
        increments.append((layout_name, reason))

    monkeypatch.setattr(layout_tick_driver, "_emit_dispatch_counter", _fake_increment)

    store = _FakeStore(
        layouts={
            "default": _FakeLayout("default"),
            "vinyl-focus": _FakeLayout("vinyl-focus"),
        }
    )
    store._active = "default"
    adapter = _LayoutStoreAdapter(store)
    switcher = LayoutSwitcher(initial_layout="default")
    state_provider = lambda: {  # noqa: E731
        "consent_safe_active": False,
        "vinyl_playing": True,
        "director_activity": None,
        "stream_mode": None,
    }

    iter_count = run_layout_tick_loop(
        layout_state=adapter,
        loader=adapter,
        switcher=switcher,
        state_provider=state_provider,
        interval_s=0.0,
        sleep_fn=lambda _s: None,
        iterations=3,
    )
    assert iter_count == 3
    assert len(increments) == 3
    # Each iteration recommends vinyl-focus (vinyl_playing=True).
    assert all(name == "vinyl-focus" for name, _ in increments)
    assert all(reason == "vinyl_playing" for _, reason in increments)


def test_run_layout_tick_loop_handles_missing_layout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KeyError from loader is logged + swallowed; counter still increments."""
    increments: list[tuple[str, str]] = []
    monkeypatch.setattr(
        layout_tick_driver,
        "_emit_dispatch_counter",
        lambda l, r: increments.append((l, r)),
    )

    store = _FakeStore()
    # Empty store — loader.load("default") raises KeyError.
    adapter = _LayoutStoreAdapter(store)
    switcher = LayoutSwitcher(initial_layout=None)
    state_provider = lambda: {  # noqa: E731
        "consent_safe_active": False,
        "vinyl_playing": False,
        "director_activity": None,
        "stream_mode": None,
    }

    iter_count = run_layout_tick_loop(
        layout_state=adapter,
        loader=adapter,
        switcher=switcher,
        state_provider=state_provider,
        interval_s=0.0,
        sleep_fn=lambda _s: None,
        iterations=2,
    )
    assert iter_count == 2
    # Counter still emitted both times — driver alive even with no layouts loaded.
    assert len(increments) == 2


def test_responsible_segment_tick_escapes_static_then_accepts_rendered_readback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    garage = _load_layout("config/layouts/garage-door.json")
    segment_list = _load_layout("config/compositor-layouts/segment-list.json")
    store = _FakeStore(
        layouts={
            "garage-door": garage,
            "segment-list": segment_list,
        },
        _active="garage-door",
    )
    rendered_state = LayoutState(garage)
    adapter = _RenderedLayoutStateAdapter(store, rendered_state)
    switcher = LayoutSwitcher(initial_layout="garage-door")
    switcher._responsible_segment_state = {}
    monkeypatch.setattr(
        layout_tick_driver,
        "SEGMENT_LAYOUT_RECEIPT_FILE",
        tmp_path / "segment-layout-receipt.json",
    )

    intent = SegmentActionIntent(
        intent_id="programme:seg-1:4:layout-need-0-0",
        kind=LayoutNeedKind.RANKED_LIST.value,
        requested_at=NOW - 1.0,
        priority=80,
        ttl_s=30.0,
        evidence_refs=("prior:ranked-list", "prepared_artifact:sha256:abc123"),
        programme_id="programme:seg-1",
        beat_index=4,
        target_ref="artifact:ranked",
        authority_ref="prepared_artifact:sha256:abc123",
        expected_effects=("ward:ranked-list-panel",),
    )
    state_provider = lambda: {  # noqa: E731
        "consent_safe_active": False,
        "vinyl_playing": False,
        "director_activity": None,
        "stream_mode": None,
        "segment_layout_intents": (intent,),
        "segment_action_intents_ref": "active-segment:sha256:abc123",
        "segment_playback_ref": "segment-playback:beat-4",
        "ward_properties": {"ranked-list-panel": {"visible": True, "alpha": 1.0}},
    }

    monkeypatch.setattr(layout_tick_driver.time, "time", lambda: NOW)
    first = _driver_tick(
        state_provider=state_provider,
        layout_state=adapter,
        loader=adapter,
        switcher=switcher,
    )

    assert first.status is LayoutDecisionStatus.HELD
    assert first.reason is LayoutDecisionReason.DEFAULT_STATIC_LAYOUT_IN_RESPONSIBLE_HOSTING
    assert first.selected_layout == "segment-list"
    assert first.applied_layout_changes == ("segment-list",)
    assert rendered_state.get().name == "segment-list"
    assert store.active_name() == "segment-list"
    assert first.receipt_metadata["layout_state_before_hash"]
    assert first.receipt_metadata["layout_state_after_hash"]

    monkeypatch.setattr(layout_tick_driver.time, "time", lambda: NOW + 1.0)
    second = _driver_tick(
        state_provider=state_provider,
        layout_state=adapter,
        loader=adapter,
        switcher=switcher,
    )

    assert second.status is LayoutDecisionStatus.ACCEPTED
    assert second.reason is LayoutDecisionReason.ACCEPTED
    assert second.selected_layout == "segment-list"
    assert "rendered-layout-state:segment-list" in second.readback_refs[0]
    assert "ward:ranked-list-panel" in second.satisfied_effects

    receipt_payload = json.loads(
        (tmp_path / "segment-layout-receipt.json").read_text(encoding="utf-8")
    )
    assert receipt_payload["status"] == "accepted"
    assert receipt_payload["selected_layout"] == "segment-list"


def test_runtime_readback_requires_fresh_blit_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    segment_list = _load_layout("config/compositor-layouts/segment-list.json")
    store = _FakeStore(layouts={"segment-list": segment_list}, _active="segment-list")
    rendered_state = LayoutState(segment_list)
    adapter = _RenderedLayoutStateAdapter(store, rendered_state)

    monkeypatch.setattr(
        layout_tick_driver,
        "_recent_blit_readbacks",
        lambda _wards, *, now: {},
    )

    readback = layout_tick_driver._runtime_layout_readback(
        layout_state=adapter,
        state={},
        now=NOW,
    )

    assert "ranked-list-panel" in readback.active_wards
    assert readback.ward_properties == {}
    assert "no-fresh-blit" in readback.readback_ref


def test_runtime_readback_uses_fresh_blit_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    segment_list = _load_layout("config/compositor-layouts/segment-list.json")
    store = _FakeStore(layouts={"segment-list": segment_list}, _active="segment-list")
    rendered_state = LayoutState(segment_list)
    adapter = _RenderedLayoutStateAdapter(store, rendered_state)

    monkeypatch.setattr(
        layout_tick_driver,
        "_recent_blit_readbacks",
        lambda _wards, *, now: {
            "ranked-list-panel": {
                "observed_at": now - 0.25,
                "source_pixels": 400,
                "effective_alpha": 0.9,
            }
        },
    )

    readback = layout_tick_driver._runtime_layout_readback(
        layout_state=adapter,
        state={},
        now=NOW,
    )

    ranked = readback.ward_properties["ranked-list-panel"]
    assert ranked["visible"] is True
    assert ranked["rendered_blit"] is True
    assert ranked["source_pixels"] == 400
    assert readback.readback_ref.startswith("rendered-blit-readback:segment-list:")


def test_stop_event_breaks_loop() -> None:
    stop_event = threading.Event()
    stop_event.set()  # already set — first iteration check breaks
    store = _FakeStore()
    adapter = _LayoutStoreAdapter(store)
    switcher = LayoutSwitcher(initial_layout=None)
    state_provider = lambda: {  # noqa: E731
        "consent_safe_active": False,
        "vinyl_playing": False,
        "director_activity": None,
        "stream_mode": None,
    }

    iter_count = run_layout_tick_loop(
        layout_state=adapter,
        loader=adapter,
        switcher=switcher,
        state_provider=state_provider,
        interval_s=0.0,
        sleep_fn=lambda _s: None,
        stop_event=stop_event,
    )
    assert iter_count == 0


# ── metric registration ────────────────────────────────────────────


def test_dispatched_counter_registered_in_compositor_registry() -> None:
    """Counter must be on REGISTRY so :9482 scrape exposes it."""
    from agents.studio_compositor import metrics

    metrics._init_metrics()
    assert metrics.HAPAX_LAYOUT_SWITCH_DISPATCHED_TOTAL is not None
    # Verify registry membership via collect.
    found = False
    if metrics.REGISTRY is not None:
        for collector in metrics.REGISTRY._collector_to_names:  # type: ignore[attr-defined]
            for name in metrics.REGISTRY._collector_to_names[collector]:  # type: ignore[attr-defined]
                if name == "hapax_layout_switch_dispatched_total":
                    found = True
                    break
    assert found, "counter not registered on compositor REGISTRY"
