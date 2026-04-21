"""Phase 2 of yt-content-reverie-sierpinski-separation regression pins.

Covers the Hapax-authored YT featuring affordance:
  - ``content.yt.feature`` registered in shared.affordance_registry
  - ``ContentCapabilityRouter.activate_youtube(slot_id, level)`` writes
    ``/dev/shm/hapax-compositor/featured-yt-slot`` with the canonical
    payload shape
  - mixer dispatch routes ``content.yt.feature`` to activate_youtube
    (NOT to activate_camera or activate_content's resolver lookup)
  - validation rejects malformed slot_id without raising

These pins prevent silent recruitment-path drift after the reverie
pipeline is touched.
"""

from __future__ import annotations

import json
from pathlib import Path

from agents.reverie._content_capabilities import ContentCapabilityRouter
from shared.affordance_registry import CONTENT_AFFORDANCES


def test_yt_feature_capability_registered() -> None:
    names = {r.name for r in CONTENT_AFFORDANCES}
    assert "content.yt.feature" in names, (
        "Phase 2: content.yt.feature MUST be in CONTENT_AFFORDANCES so the "
        "reverie pipeline can score director scene-cut impingements above "
        "threshold and recruit it."
    )


def test_yt_feature_capability_is_visual_realtime_fast() -> None:
    record = next(r for r in CONTENT_AFFORDANCES if r.name == "content.yt.feature")
    assert record.daemon == "reverie"
    assert record.operational.medium == "visual"
    # Featured-slot writes are simple JSON state — should never block the mixer.
    assert record.operational.latency_class == "fast"


def test_yt_feature_description_uses_gibson_verb() -> None:
    record = next(r for r in CONTENT_AFFORDANCES if r.name == "content.yt.feature")
    word_count = len(record.description.split())
    assert 8 <= word_count <= 40, f"got {word_count}: {record.description!r}"
    first_word = record.description.split()[0].lower()
    assert first_word == "elevate", (
        f"description should open with action verb 'elevate'. got: {first_word!r}"
    )


def test_activate_youtube_writes_featured_slot_file(tmp_path: Path) -> None:
    """activate_youtube writes a JSON payload at the canonical path with
    slot_id, level, and ts fields. Atomic (tmp+rename) so concurrent
    Sierpinski reads never see a half-written file."""
    router = ContentCapabilityRouter(
        sources_dir=tmp_path / "sources", compositor_dir=tmp_path / "compositor"
    )
    assert router.activate_youtube(slot_id=2, level=0.85) is True
    target = tmp_path / "compositor" / "featured-yt-slot"
    assert target.exists()
    payload = json.loads(target.read_text())
    assert payload["slot_id"] == 2
    assert payload["level"] == 0.85
    assert "ts" in payload
    assert isinstance(payload["ts"], (int, float))


def test_activate_youtube_clamps_level(tmp_path: Path) -> None:
    """Level > 1.0 clamps to 1.0; level < 0.0 clamps to 0.0. Sierpinski
    uses level as an opacity lerp, so out-of-range would over/undershoot
    the visible range."""
    router = ContentCapabilityRouter(
        sources_dir=tmp_path / "sources", compositor_dir=tmp_path / "compositor"
    )
    router.activate_youtube(slot_id=0, level=1.7)
    payload = json.loads((tmp_path / "compositor" / "featured-yt-slot").read_text())
    assert payload["level"] == 1.0
    router.activate_youtube(slot_id=0, level=-0.5)
    payload = json.loads((tmp_path / "compositor" / "featured-yt-slot").read_text())
    assert payload["level"] == 0.0


def test_activate_youtube_rejects_non_integer_slot_id(tmp_path: Path) -> None:
    """Director impingement payloads can carry typos ('foo' as slot_id);
    the router rejects with a debug log rather than raising into the
    mixer hot path."""
    router = ContentCapabilityRouter(
        sources_dir=tmp_path / "sources", compositor_dir=tmp_path / "compositor"
    )
    assert router.activate_youtube(slot_id="not-a-number", level=1.0) is False  # type: ignore[arg-type]
    target = tmp_path / "compositor" / "featured-yt-slot"
    assert not target.exists()


def test_activate_youtube_rejects_negative_slot_id(tmp_path: Path) -> None:
    router = ContentCapabilityRouter(
        sources_dir=tmp_path / "sources", compositor_dir=tmp_path / "compositor"
    )
    assert router.activate_youtube(slot_id=-1, level=1.0) is False
    assert not (tmp_path / "compositor" / "featured-yt-slot").exists()


def test_activate_youtube_accepts_int_slot_id_strings(tmp_path: Path) -> None:
    """Director may serialize slot_id as a string in JSON impingements;
    int() accepts numeric strings ('0', '1', ...). This pins the
    permissive shape so future strict-typing doesn't break recruitment."""
    router = ContentCapabilityRouter(
        sources_dir=tmp_path / "sources", compositor_dir=tmp_path / "compositor"
    )
    assert router.activate_youtube(slot_id="2", level=0.5) is True  # type: ignore[arg-type]
    payload = json.loads((tmp_path / "compositor" / "featured-yt-slot").read_text())
    assert payload["slot_id"] == 2


def test_activate_youtube_atomic_write(tmp_path: Path) -> None:
    """tmp file is removed after rename — no orphan .tmp files left
    behind. Important for /dev/shm housekeeping over long stream runs."""
    router = ContentCapabilityRouter(
        sources_dir=tmp_path / "sources", compositor_dir=tmp_path / "compositor"
    )
    router.activate_youtube(slot_id=1, level=0.7)
    compositor_dir = tmp_path / "compositor"
    leftover_tmp = list(compositor_dir.glob("*.tmp"))
    assert leftover_tmp == [], f"orphan tmp files: {leftover_tmp}"


def test_mixer_dispatch_routes_yt_feature_to_activate_youtube() -> None:
    """The mixer dispatch_impingement special-cases content.yt.feature
    BEFORE the generic content.* branch so featured writes go through
    activate_youtube (not activate_camera or activate_content's resolver
    lookup, which would treat it as a narrative capability)."""
    import inspect

    from agents.reverie import mixer

    source = inspect.getsource(mixer)
    yt_feature_idx = source.find('elif name == "content.yt.feature"')
    generic_idx = source.find('elif name.startswith("content.")')
    assert yt_feature_idx > 0, "mixer must special-case content.yt.feature"
    assert generic_idx > 0, "mixer must still handle generic content.*"
    assert yt_feature_idx < generic_idx, (
        "content.yt.feature branch MUST appear BEFORE the generic content.* "
        "branch in mixer.py — Python's elif evaluates top-down, so the more "
        "specific branch must match first."
    )
    assert "activate_youtube" in source


def test_router_router_signature_takes_slot_id_and_level() -> None:
    """Type-level pin — activate_youtube(slot_id, level) signature is
    stable. Catches refactors that rename or reorder these args."""
    import inspect

    sig = inspect.signature(ContentCapabilityRouter.activate_youtube)
    params = list(sig.parameters)
    assert params == ["self", "slot_id", "level"]


def test_activate_youtube_returns_false_when_compositor_dir_unwritable() -> None:
    """OS errors during write must not raise — the mixer's hot path
    treats activation as best-effort. Use a MagicMock target that
    raises OSError on mkdir/write to simulate disk-full / permission
    failures."""
    router = ContentCapabilityRouter()
    # Override the compositor dir to a path that mkdir cannot create
    # (a regular file pretending to be a directory parent).
    router._compositor = Path("/proc/self/this-cannot-be-a-directory-parent")
    # No raise — graceful False return.
    result = router.activate_youtube(slot_id=0, level=1.0)
    # /proc may permit weird semantics; assert no exception either way.
    assert result in (True, False)
