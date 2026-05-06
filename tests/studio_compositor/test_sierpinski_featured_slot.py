"""Sierpinski renderer Phase 2 yt-feature pins.

When the reverie mixer writes ``/dev/shm/hapax-compositor/featured-yt-slot``
via ``ContentCapabilityRouter.activate_youtube``, the Sierpinski renderer
elevates that slot's opacity above the active-slot baseline. Pins:
  - opacity precedence (featured > active > idle)
  - TTL guard (stale writes decay back to active-only)
  - mtime gate (file re-read only when content actually changes)
  - graceful fallback when file absent / malformed
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from agents.studio_compositor import sierpinski_renderer as sr


def _make_renderer():
    """Bare SierpinskiCairoSource without the gi/cairo runner stack."""
    return sr.SierpinskiCairoSource()


def test_slot_opacity_idle_default() -> None:
    """No featured-slot file present + active=0: slot 0 = active opacity,
    slots 1+2 = idle opacity."""
    r = _make_renderer()
    r.set_active_slot(0)
    assert r._slot_opacity(0) == sr.FEATURED_FALLBACK_OPACITY
    assert r._slot_opacity(1) == sr.FEATURED_IDLE_OPACITY
    assert r._slot_opacity(2) == sr.FEATURED_IDLE_OPACITY


def test_slot_opacity_featured_overrides_active(tmp_path: Path) -> None:
    """When a slot is featured + within TTL, its opacity beats the
    active-slot opacity even if it isn't the active slot."""
    r = _make_renderer()
    r.set_active_slot(0)  # slot 0 is active
    r._featured_slot_id = 2  # but slot 2 is featured
    r._featured_ts = time.time()
    r._featured_level = 1.0
    assert r._slot_opacity(2) == sr.FEATURED_OPACITY_BOOST
    # Active slot loses its highlight when a different slot is featured? No —
    # slot 0 retains active opacity. Featured ELEVATES, doesn't suppress.
    assert r._slot_opacity(0) == sr.FEATURED_FALLBACK_OPACITY
    assert r._slot_opacity(1) == sr.FEATURED_IDLE_OPACITY


def test_slot_opacity_featured_with_low_level() -> None:
    """level=0 leaves opacity at active-baseline; level=1 hits full boost.
    Lerp in between."""
    r = _make_renderer()
    r._featured_slot_id = 1
    r._featured_ts = time.time()
    r._featured_level = 0.0
    # At level=0 the lerp formula returns FEATURED_FALLBACK_OPACITY.
    assert r._slot_opacity(1) == sr.FEATURED_FALLBACK_OPACITY
    r._featured_level = 0.5
    expected = (
        sr.FEATURED_FALLBACK_OPACITY
        + (sr.FEATURED_OPACITY_BOOST - sr.FEATURED_FALLBACK_OPACITY) * 0.5
    )
    assert abs(r._slot_opacity(1) - expected) < 1e-6


def test_slot_opacity_featured_decays_after_ttl(monkeypatch) -> None:
    """A featured write older than FEATURED_TTL_S no longer boosts;
    slot reverts to active/idle baseline."""
    r = _make_renderer()
    r.set_active_slot(0)
    r._featured_slot_id = 2
    r._featured_level = 1.0
    # Set ts well in the past so the decay branch fires.
    r._featured_ts = time.time() - sr.FEATURED_TTL_S - 1.0
    assert r._slot_opacity(2) == sr.FEATURED_IDLE_OPACITY  # back to idle


def test_refresh_reads_file_atomic(tmp_path: Path) -> None:
    """_refresh_featured_yt_slot reads the SHM file when present;
    populates the per-instance state."""
    target = tmp_path / "featured-yt-slot"
    payload = {"slot_id": 1, "level": 0.7, "ts": time.time()}
    target.write_text(json.dumps(payload))

    r = _make_renderer()
    with patch.object(sr, "FEATURED_YT_SLOT_FILE", target):
        r._refresh_featured_yt_slot()
    assert r._featured_slot_id == 1
    assert r._featured_level == 0.7


def test_refresh_mtime_gate_avoids_reparse(tmp_path: Path) -> None:
    """File whose mtime hasn't advanced is NOT re-read — saves JSON parsing
    on every tick when the featured state is stable."""
    target = tmp_path / "featured-yt-slot"
    target.write_text(json.dumps({"slot_id": 0, "level": 1.0, "ts": time.time()}))

    r = _make_renderer()
    with patch.object(sr, "FEATURED_YT_SLOT_FILE", target):
        r._refresh_featured_yt_slot()
        first_mtime = r._featured_file_mtime
        # Second call without writing — mtime unchanged.
        r._refresh_featured_yt_slot()
        assert r._featured_file_mtime == first_mtime


def test_refresh_handles_missing_file(tmp_path: Path) -> None:
    """Absent file is the steady state when no YT featuring has occurred —
    must not raise."""
    r = _make_renderer()
    with patch.object(sr, "FEATURED_YT_SLOT_FILE", tmp_path / "absent"):
        r._refresh_featured_yt_slot()  # should not raise
    assert r._featured_slot_id is None  # default unchanged


def test_refresh_handles_malformed_json(tmp_path: Path) -> None:
    """Half-written / corrupt file is silently ignored — featured state
    stays at the prior value, no exception bubbles up."""
    target = tmp_path / "featured-yt-slot"
    target.write_text("{ not valid json")

    r = _make_renderer()
    with patch.object(sr, "FEATURED_YT_SLOT_FILE", target):
        r._refresh_featured_yt_slot()
    assert r._featured_slot_id is None


def test_refresh_handles_unexpected_payload_shape(tmp_path: Path) -> None:
    """Missing slot_id or non-numeric values: featured state cleared,
    no exception."""
    target = tmp_path / "featured-yt-slot"
    target.write_text(json.dumps({"slot_id": "garbage", "level": "also-garbage"}))

    r = _make_renderer()
    with patch.object(sr, "FEATURED_YT_SLOT_FILE", target):
        r._refresh_featured_yt_slot()
    assert r._featured_slot_id is None


def test_featured_constants_are_in_legible_band() -> None:
    """Sanity-pin the boost amount: featured opacity must be strictly
    higher than active, active strictly higher than idle. If a future
    aesthetic edit breaks this ordering, the elevation effect inverts."""
    assert sr.FEATURED_OPACITY_BOOST > sr.FEATURED_FALLBACK_OPACITY
    assert sr.FEATURED_FALLBACK_OPACITY > sr.FEATURED_IDLE_OPACITY
    assert 0.0 <= sr.FEATURED_IDLE_OPACITY <= 1.0
    assert 0.0 <= sr.FEATURED_OPACITY_BOOST <= 1.0


# ── Defensive featured-slot reader — non-dict JSON root ─────────────────


import pytest


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a"', "string"), ("[1,2]", "list"), ("42", "int")],
)
def test_refresh_featured_handles_non_dict_root(tmp_path: Path, payload: str, kind: str) -> None:
    """Pin ``_refresh_featured_yt_slot`` against a writer producing valid
    JSON whose root is not a mapping. Lines 197-199 call ``data.get(...)``
    inside an ``except (TypeError, ValueError)`` — but a non-dict root
    raises AttributeError on the very first ``.get`` call, escaping the
    catch entirely. Same corruption-class as #2627, #2631, #2632, #2636
    (merged) and #2640, #2642, #2644 (in flight)."""
    target = tmp_path / "featured-yt-slot"
    target.write_text(payload)
    # Set a known prior state so we can detect the reset.
    r = _make_renderer()
    r._featured_slot_id = 7
    with patch.object(sr, "FEATURED_YT_SLOT_FILE", target):
        # The crash path: must not raise even on a corrupt sidecar.
        r._refresh_featured_yt_slot()
    assert r._featured_slot_id is None, f"non-dict root={kind} must clear featured state"
