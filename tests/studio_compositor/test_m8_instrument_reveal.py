"""Tests for ``M8InstrumentReveal`` (cc-task ``activity-reveal-ward-p2-m8-migration``).

Coverage:

1. **Family contract** — subclasses ``ActivityRevealMixin``, declares
   ``WARD_ID="m8-display"``, ``SOURCE_KIND="external_rgba"``, empty
   ``SUPPRESS_WHEN_ACTIVE``.
2. **No Cairo** — ``render_content`` is a no-op (M8 is external_rgba,
   not Cairo-painted).
3. **Device presence** — reads SHM mtime within the freshness window.
4. **Claim score map** — 0.0 absent / 0.30 present / 0.85 present + recruited.
5. **ActivityRouter compatibility** — instances are accepted as
   ``ActivityRouter([...])`` constructor inputs without raising.
6. **Layout wiring** — ``default.json`` and the in-memory
   ``_FALLBACK_LAYOUT`` both carry ``ward_id="m8-display"`` on the M8
   source.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from agents.studio_compositor import m8_instrument_reveal as m8_module
from agents.studio_compositor.activity_reveal_ward import (
    ActivityRevealMixin,
    VisibilityClaim,
)
from agents.studio_compositor.activity_router import ActivityRouter
from agents.studio_compositor.m8_instrument_reveal import (
    M8InstrumentReveal,
)


def _write_shm(path: Path, *, mtime_offset_s: float = 0.0) -> None:
    """Write a stub RGBA frame to ``path`` and stamp its mtime.

    ``mtime_offset_s`` shifts the stamp by ``-N`` seconds so a test
    can simulate "stale by N seconds" without sleeping.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00\x00\x00\xff" * 4)
    if mtime_offset_s != 0.0:
        ts = time.time() - mtime_offset_s
        os.utime(path, (ts, ts))


def _write_recruitment(
    path: Path,
    capability: str,
    *,
    age_offset_s: float = 0.0,
) -> None:
    """Write a recent-recruitment.json with ``capability`` recruited
    ``age_offset_s`` seconds ago."""

    path.parent.mkdir(parents=True, exist_ok=True)
    last_recruited_ts = time.time() - age_offset_s
    payload = {
        "families": {
            capability: {"last_recruited_ts": last_recruited_ts, "ttl_s": 60.0},
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture(autouse=True)
def _enable_feature(monkeypatch):
    """Default the feature flag ON so ``_want_visible`` reaches the
    device-presence path. Tests that assert the flag-OFF fallback
    explicitly delete the env var."""

    monkeypatch.setenv(m8_module._FEATURE_FLAG_ENV, "1")


# ── 1. Family contract ──────────────────────────────────────────────


class TestFamilyContract:
    def test_subclasses_activity_reveal_mixin(self):
        assert issubclass(M8InstrumentReveal, ActivityRevealMixin)

    def test_ward_id(self):
        assert M8InstrumentReveal.WARD_ID == "m8-display"

    def test_source_kind_external_rgba(self):
        """M8 frames are RGBA, not Cairo — SOURCE_KIND must be ``external_rgba``.

        The cc-task explicitly forbids inheriting Cairo machinery the
        M8 path will never use; ``external_rgba`` is the family-base
        signal that says so.
        """

        assert M8InstrumentReveal.SOURCE_KIND == "external_rgba"

    def test_does_not_suppress_other_wards(self):
        """M8 doesn't suppress siblings; siblings (e.g. DURF) suppress IT."""

        assert frozenset() == M8InstrumentReveal.SUPPRESS_WHEN_ACTIVE


# ── 2. No Cairo (cc-task acceptance ¶2) ──────────────────────────────


class TestNoCairo:
    def test_render_content_is_a_noop(self):
        ward = M8InstrumentReveal()
        try:
            # No exception, no return value (None).
            assert ward.render_content() is None
            # Common cairo-source signature variants — also no-op.
            assert ward.render_content(None, 0, 0, 0.0, {}) is None
        finally:
            ward.stop()

    def test_does_not_inherit_homage_transitional_source(self):
        """Pure-mixin lifecycle owner — must not drag Cairo machinery."""

        from agents.studio_compositor.homage.transitional_source import (
            HomageTransitionalSource,
        )

        # Asserts the migration commitment: M8 is NOT a CairoSource.
        assert not issubclass(M8InstrumentReveal, HomageTransitionalSource)


# ── 3. Device presence (cc-task acceptance ¶3) ──────────────────────


class TestDevicePresence:
    def test_absent_when_shm_missing(self, tmp_path: Path):
        ward = M8InstrumentReveal(shm_path=tmp_path / "nonexistent.rgba")
        try:
            assert ward._device_present() is False
        finally:
            ward.stop()

    def test_present_when_shm_freshly_written(self, tmp_path: Path):
        shm = tmp_path / "m8-display.rgba"
        _write_shm(shm)
        ward = M8InstrumentReveal(shm_path=shm)
        try:
            assert ward._device_present() is True
        finally:
            ward.stop()

    def test_absent_when_shm_too_stale(self, tmp_path: Path):
        shm = tmp_path / "m8-display.rgba"
        _write_shm(shm, mtime_offset_s=999.0)
        ward = M8InstrumentReveal(shm_path=shm, device_present_window_s=5.0)
        try:
            assert ward._device_present() is False
        finally:
            ward.stop()


# ── 4. Claim score map (cc-task acceptance ¶4) ──────────────────────


class TestClaimScoreMap:
    def test_zero_when_absent(self, tmp_path: Path):
        ward = M8InstrumentReveal(shm_path=tmp_path / "nonexistent.rgba")
        try:
            assert ward._compute_claim_score() == pytest.approx(0.0)
        finally:
            ward.stop()

    def test_base_score_when_present_no_recruit(self, tmp_path: Path):
        shm = tmp_path / "m8-display.rgba"
        recruitment = tmp_path / "recent-recruitment.json"
        _write_shm(shm)
        # Empty recruitment file — no boost.
        recruitment.write_text(json.dumps({"families": {}}), encoding="utf-8")
        ward = M8InstrumentReveal(shm_path=shm, recruitment_path=recruitment)
        try:
            assert ward._compute_claim_score() == pytest.approx(0.30)
        finally:
            ward.stop()

    def test_base_plus_boost_when_present_and_recruited(self, tmp_path: Path):
        shm = tmp_path / "m8-display.rgba"
        recruitment = tmp_path / "recent-recruitment.json"
        _write_shm(shm)
        _write_recruitment(recruitment, "studio.m8_lcd_reveal", age_offset_s=2.0)
        ward = M8InstrumentReveal(shm_path=shm, recruitment_path=recruitment)
        try:
            # 0.30 + 0.55 = 0.85 (cc-task acceptance criterion ¶4).
            assert ward._compute_claim_score() == pytest.approx(0.85)
        finally:
            ward.stop()

    def test_recruitment_outside_window_does_not_boost(self, tmp_path: Path):
        shm = tmp_path / "m8-display.rgba"
        recruitment = tmp_path / "recent-recruitment.json"
        _write_shm(shm)
        # Recruited 999 s ago — well outside the 60 s window.
        _write_recruitment(recruitment, "studio.m8_lcd_reveal", age_offset_s=999.0)
        ward = M8InstrumentReveal(
            shm_path=shm,
            recruitment_path=recruitment,
            recruitment_window_s=60.0,
        )
        try:
            assert ward._compute_claim_score() == pytest.approx(0.30)
        finally:
            ward.stop()

    def test_other_capability_recruited_does_not_boost(self, tmp_path: Path):
        """Only ``studio.m8_lcd_reveal`` triggers the boost."""

        shm = tmp_path / "m8-display.rgba"
        recruitment = tmp_path / "recent-recruitment.json"
        _write_shm(shm)
        _write_recruitment(recruitment, "studio.m8_remote_control", age_offset_s=2.0)
        ward = M8InstrumentReveal(shm_path=shm, recruitment_path=recruitment)
        try:
            assert ward._compute_claim_score() == pytest.approx(0.30)
        finally:
            ward.stop()


# ── 5. ActivityRouter compatibility (cc-task acceptance ¶5) ─────────


class TestActivityRouterIntegration:
    def test_instance_accepted_by_router_constructor(self):
        ward = M8InstrumentReveal()
        try:
            router = ActivityRouter([ward])
            try:
                assert ward in router.wards
                # describe() reflects the registered ward id.
                describe = router.describe()
                assert "m8-display" in describe["ward_ids"]
            finally:
                router.stop()
        finally:
            ward.stop()

    def test_poll_once_yields_visibility_claim(self, tmp_path: Path):
        """Mixin claim assembly works on the M8 ward without a daemon thread."""

        shm = tmp_path / "m8-display.rgba"
        _write_shm(shm)
        ward = M8InstrumentReveal(shm_path=shm)
        try:
            claim = ward.poll_once()
            assert isinstance(claim, VisibilityClaim)
            assert claim.ward_id == "m8-display"
            assert claim.want_visible is True
            assert claim.score == pytest.approx(0.30)
        finally:
            ward.stop()

    def test_feature_flag_off_keeps_ward_invisible(self, tmp_path: Path, monkeypatch):
        """Default-OFF rollback path: even with SHM fresh, flag-OFF keeps ``want_visible=False``."""

        monkeypatch.delenv(m8_module._FEATURE_FLAG_ENV, raising=False)
        shm = tmp_path / "m8-display.rgba"
        _write_shm(shm)
        ward = M8InstrumentReveal(shm_path=shm)
        try:
            claim = ward.poll_once()
            assert claim.want_visible is False
        finally:
            ward.stop()


# ── 6. Layout wiring (cc-task acceptance ¶6 + ¶7) ───────────────────


class TestLayoutWiring:
    def test_default_json_carries_ward_id(self):
        repo_root = Path(__file__).resolve().parents[2]
        layout = json.loads(
            (repo_root / "config" / "compositor-layouts" / "default.json").read_text()
        )
        sources = {s["id"]: s for s in layout["sources"]}
        m8 = sources["m8-display"]
        assert m8["ward_id"] == "m8-display", (
            "default.json m8-display source must declare ward_id='m8-display' "
            "for the activity-reveal-ward router pairing"
        )

    def test_fallback_layout_mirrors_ward_id(self):
        from agents.studio_compositor import compositor as _comp

        m8 = next(s for s in _comp._FALLBACK_LAYOUT.sources if s.id == "m8-display")
        assert m8.ward_id == "m8-display", (
            "_FALLBACK_LAYOUT m8-display source must declare ward_id='m8-display' "
            "so the in-memory fallback matches the canonical default.json"
        )
