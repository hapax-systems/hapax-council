"""Tests for the LRR Phase 8 item 12 research-zone activity gate.

The ``active_when_activities`` field on a zone configuration gates the
zone's content cycling on whether any active objective's
``activities_that_advance`` list intersects with the configured set. The
gate is re-evaluated every few seconds so activating or closing an
objective takes visible effect without restarting the compositor.
"""

from __future__ import annotations

from pathlib import Path

import pytest


class TestReadActiveObjectiveActivities:
    def test_missing_dir_returns_empty(self, tmp_path: Path):
        from agents.studio_compositor.overlay_zones import _read_active_objective_activities

        assert _read_active_objective_activities(tmp_path / "nope") == frozenset()

    def test_reads_active_objectives(self, tmp_path: Path):
        from agents.studio_compositor.overlay_zones import _read_active_objective_activities

        (tmp_path / "a.md").write_text(
            "---\n"
            "id: claim-5\n"
            "status: active\n"
            "activities_that_advance: [study, react]\n"
            "---\n\nbody\n",
            encoding="utf-8",
        )
        (tmp_path / "b.md").write_text(
            "---\nid: claim-7\nstatus: closed\nactivities_that_advance: [chat]\n---\n",
            encoding="utf-8",
        )
        (tmp_path / "c.md").write_text(
            "---\nid: claim-9\nstatus: active\nactivities_that_advance: [vinyl]\n---\n",
            encoding="utf-8",
        )
        activities = _read_active_objective_activities(tmp_path)
        assert activities == frozenset({"study", "react", "vinyl"})

    def test_ignores_malformed_files(self, tmp_path: Path):
        from agents.studio_compositor.overlay_zones import _read_active_objective_activities

        (tmp_path / "not-frontmatter.md").write_text("no frontmatter here\n", encoding="utf-8")
        (tmp_path / "bad-yaml.md").write_text(
            "---\nstatus: active\n  activities_that_advance: [unclosed\n---\n",
            encoding="utf-8",
        )
        (tmp_path / "good.md").write_text(
            "---\nstatus: active\nactivities_that_advance: [study]\n---\n",
            encoding="utf-8",
        )
        assert _read_active_objective_activities(tmp_path) == frozenset({"study"})


class TestZoneGate:
    def _make_zone(self, **overrides):
        from agents.studio_compositor.overlay_zones import OverlayZone

        config = {
            "id": "research",
            "folder": "/tmp/does-not-matter",
            "x": 0,
            "y": 0,
            "max_width": 500,
            "active_when_activities": ("study",),
        }
        config.update(overrides)
        return OverlayZone(config)

    def test_default_always_on(self, monkeypatch: pytest.MonkeyPatch):
        from agents.studio_compositor.overlay_zones import OverlayZone

        z = OverlayZone({"id": "m", "folder": "/tmp", "x": 0, "y": 0})
        assert z._gate_open is True
        # tick without active_when never calls the reader.
        called = {"n": 0}
        monkeypatch.setattr(
            "agents.studio_compositor.overlay_zones._read_active_objective_activities",
            lambda *a, **kw: called.update(n=called["n"] + 1) or frozenset(),
        )
        z.tick()
        assert called["n"] == 0

    def test_gate_closed_when_no_active_objectives(self, monkeypatch: pytest.MonkeyPatch):
        z = self._make_zone()
        monkeypatch.setattr(
            "agents.studio_compositor.overlay_zones._read_active_objective_activities",
            lambda *a, **kw: frozenset(),
        )
        z.tick()
        assert z._gate_open is False
        assert z._pango_markup == ""
        assert z._cached_surface is None

    def test_gate_closed_when_activity_mismatch(self, monkeypatch: pytest.MonkeyPatch):
        z = self._make_zone()
        monkeypatch.setattr(
            "agents.studio_compositor.overlay_zones._read_active_objective_activities",
            lambda *a, **kw: frozenset({"vinyl", "chat"}),
        )
        z.tick()
        assert z._gate_open is False

    def test_gate_open_when_activity_matches(self, monkeypatch: pytest.MonkeyPatch):
        z = self._make_zone()
        monkeypatch.setattr(
            "agents.studio_compositor.overlay_zones._read_active_objective_activities",
            lambda *a, **kw: frozenset({"study", "react"}),
        )
        z.tick()
        assert z._gate_open is True

    def test_gate_ttl_caches_reader_call(self, monkeypatch: pytest.MonkeyPatch):
        """Rapid ticks should not pound the filesystem — reader is throttled."""
        z = self._make_zone()
        calls = {"n": 0}

        def fake(*_a, **_kw):
            calls["n"] += 1
            return frozenset({"study"})

        monkeypatch.setattr(
            "agents.studio_compositor.overlay_zones._read_active_objective_activities", fake
        )

        z.tick()
        z.tick()
        z.tick()
        assert calls["n"] == 1  # subsequent ticks within TTL reuse cached verdict

    def test_gate_reopens_after_activity_appears(self, monkeypatch: pytest.MonkeyPatch):
        """After the cache TTL elapses the reader is consulted again."""
        z = self._make_zone()
        monkeypatch.setattr(
            "agents.studio_compositor.overlay_zones._ACTIVITY_CACHE_TTL_S", 0.0, raising=False
        )
        verdicts = [frozenset(), frozenset({"study"})]
        monkeypatch.setattr(
            "agents.studio_compositor.overlay_zones._read_active_objective_activities",
            lambda *a, **kw: verdicts.pop(0) if verdicts else frozenset({"study"}),
        )

        z.tick()
        assert z._gate_open is False
        z.tick()
        assert z._gate_open is True


class TestShippedZoneConfig:
    def test_research_zone_registered_and_gated(self):
        from agents.studio_compositor.overlay_zones import ZONES

        by_id = {z["id"]: z for z in ZONES}
        assert "research" in by_id
        assert by_id["research"].get("active_when_activities") == ("study",)
        assert "research/" in by_id["research"]["folder"]

    def test_other_zones_still_always_on(self):
        from agents.studio_compositor.overlay_zones import ZONES

        by_id = {z["id"]: z for z in ZONES}
        assert "main" in by_id
        assert "active_when_activities" not in by_id["main"]
        assert "lyrics" in by_id
        assert "active_when_activities" not in by_id["lyrics"]

    def test_right_marker_zone_registered_and_gated_on_lyrics(self):
        """``right_marker`` fills the right column whenever lyrics is silent."""
        from agents.studio_compositor.overlay_zones import ZONES

        by_id = {z["id"]: z for z in ZONES}
        assert "right_marker" in by_id
        marker = by_id["right_marker"]
        assert marker.get("gate_when_file_empty") == "/dev/shm/hapax-compositor/track-lyrics.txt"
        # Anchored to the right column at the same x as lyrics.
        lyrics = by_id["lyrics"]
        assert marker["x"] == lyrics["x"]
        assert marker["max_width"] == lyrics["max_width"]


class TestFileEmptyGate:
    """``gate_when_file_empty`` closes a zone whenever the named file has size > 0."""

    def _make_marker_zone(self, gate_path: Path):
        from agents.studio_compositor.overlay_zones import OverlayZone

        return OverlayZone(
            {
                "id": "right_marker",
                "folder": "/tmp/does-not-matter",
                "x": 1350,
                "y": 0,
                "max_width": 500,
                "gate_when_file_empty": str(gate_path),
            }
        )

    def test_default_no_gate_attribute(self):
        from agents.studio_compositor.overlay_zones import OverlayZone

        z = OverlayZone({"id": "m", "folder": "/tmp", "x": 0, "y": 0})
        assert z._gate_when_file_empty is None
        assert z._is_gate_file_populated() is False

    def test_open_when_file_missing(self, tmp_path: Path):
        z = self._make_marker_zone(tmp_path / "nope.txt")
        assert z._is_gate_file_populated() is False

    def test_open_when_file_empty(self, tmp_path: Path):
        gate = tmp_path / "track-lyrics.txt"
        gate.write_text("", encoding="utf-8")
        z = self._make_marker_zone(gate)
        assert z._is_gate_file_populated() is False

    def test_closed_when_file_has_content(self, tmp_path: Path):
        gate = tmp_path / "track-lyrics.txt"
        gate.write_text("Some lyric line\n", encoding="utf-8")
        z = self._make_marker_zone(gate)
        assert z._is_gate_file_populated() is True

    @pytest.mark.parametrize(
        "whitespace,kind",
        [
            ("\n", "single newline"),
            ("\n\n\n", "blank lines"),
            ("   ", "spaces only"),
            ("\t\t", "tabs only"),
            (" \t \n", "mixed whitespace"),
        ],
    )
    def test_open_when_file_is_whitespace_only(
        self, tmp_path: Path, whitespace: str, kind: str
    ) -> None:
        """A lyrics file containing only whitespace (a placeholder
        ``\\n`` from a producer that hasn't fetched real lyrics yet,
        or a track with no operator-curated lyric content) previously
        passed ``st_size > 0`` and closed the right_marker gate even
        though nothing visible would render — leaving the right
        column dark for the silent track. The gate now treats
        whitespace-only content as empty so the right_marker
        aphorism fills the column instead."""
        gate = tmp_path / "track-lyrics.txt"
        gate.write_text(whitespace, encoding="utf-8")
        z = self._make_marker_zone(gate)
        assert z._is_gate_file_populated() is False, (
            f"whitespace-only ({kind}) lyrics should leave the gate open so the "
            f"right_marker aphorism can fill the column"
        )

    def test_tick_short_circuits_when_gate_closed(self, tmp_path: Path):
        gate = tmp_path / "track-lyrics.txt"
        gate.write_text("active track\n", encoding="utf-8")
        z = self._make_marker_zone(gate)
        z._pango_markup = "STALE CONTENT"
        z._cached_surface = object()  # placeholder non-None sentinel
        z.tick()
        assert z._pango_markup == ""
        assert z._cached_surface is None

    def test_tick_proceeds_when_gate_open(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Open gate lets tick fall through to content readers."""
        gate = tmp_path / "missing.txt"  # never created → gate stays open
        z = self._make_marker_zone(gate)
        called = {"folder": 0}
        monkeypatch.setattr(
            z, "_tick_folder", lambda *_a, **_kw: called.__setitem__("folder", called["folder"] + 1)
        )
        z.tick()
        assert called["folder"] == 1

    @pytest.mark.parametrize(
        "whitespace,kind",
        [
            ("\n", "single newline"),
            ("\n\n\n", "blank lines"),
            ("   ", "spaces only"),
            ("\t\t", "tabs only"),
            (" \t \n", "mixed whitespace"),
        ],
    )
    def test_render_skips_whitespace_only_pango_markup(self, whitespace: str, kind: str) -> None:
        """Render path must skip whitespace-only ``_pango_markup``.

        An ANSI file consisting only of whitespace (``ansi_to_pango``
        does not strip its output) or a repo entry whose body parses
        to whitespace-only markup previously passed the render gate's
        truthiness check and triggered ``_rebuild_surface`` plus a
        Cairo paint every frame even though nothing visible renders.
        Skipping the rebuild + paint is wasted work prevention; the
        visible result is identical."""
        from agents.studio_compositor.overlay_zones import OverlayZone

        z = OverlayZone({"id": "z", "folder": "/tmp", "x": 0, "y": 0})
        z._pango_markup = whitespace
        rebuild_calls = {"n": 0}

        def fake_rebuild(_cr) -> None:  # noqa: ANN001
            rebuild_calls["n"] += 1

        z._rebuild_surface = fake_rebuild  # type: ignore[method-assign]
        z.render(cr=None, canvas_w=1920, canvas_h=1080)
        assert rebuild_calls["n"] == 0, (
            f"whitespace-only ({kind}) markup must not trigger surface rebuild"
        )

    def test_path_user_expansion(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """``~`` in the gate path is expanded at construction time."""
        from agents.studio_compositor.overlay_zones import OverlayZone

        monkeypatch.setenv("HOME", str(tmp_path))
        z = OverlayZone(
            {
                "id": "m",
                "folder": "/tmp",
                "x": 0,
                "y": 0,
                "gate_when_file_empty": "~/lyrics.txt",
            }
        )
        assert z._gate_when_file_empty == tmp_path / "lyrics.txt"
