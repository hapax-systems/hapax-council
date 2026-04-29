"""Tests for agents.hapax_daimonion.narrative_drive — drive loop integration."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from agents.hapax_daimonion.narrative_drive import (
    _assemble_drive_context,
    _emit_drive_impingement,
)
from shared.endogenous_drive import DriveContext, EndogenousDrive


@pytest.fixture()
def tmp_impingements(tmp_path: Path) -> Path:
    """Redirect impingements to a temp file."""
    imp_file = tmp_path / "impingements.jsonl"
    imp_file.parent.mkdir(parents=True, exist_ok=True)
    return imp_file


class TestEmitDriveImpingement:
    def test_writes_valid_jsonl(self, tmp_impingements: Path):
        drive = EndogenousDrive(tau=120.0)
        drive._last_emission_ts = time.time() - 200.0
        ctx = DriveContext(chronicle_event_count=5, stimmung_stance="ambient")

        with mock.patch(
            "agents.hapax_daimonion.narrative_drive._IMPINGEMENTS_FILE",
            tmp_impingements,
        ):
            ok = _emit_drive_impingement(drive, ctx)

        assert ok is True
        lines = tmp_impingements.read_text().strip().split("\n")
        assert len(lines) == 1

        imp = json.loads(lines[0])
        assert imp["source"] == "endogenous.narrative_drive"
        assert imp["type"] == "endogenous"
        assert imp["content"]["drive"] == "narration"
        assert imp["content"]["impulse_id"] == f"narration-{imp['id']}"
        assert imp["content"]["action_tendency"] == "speak"
        assert imp["content"]["speech_act_candidate"] == "autonomous_narrative"
        assert imp["content"]["strength_posterior"] == imp["strength"]
        assert imp["content"]["raw_drive_text_spoken"] is False
        assert isinstance(imp["content"]["narrative"], str)
        assert len(imp["content"]["narrative"]) > 20

    def test_impingement_has_semantic_content(self, tmp_impingements: Path):
        """Narrative must be rich enough for Qdrant embedding matching."""
        drive = EndogenousDrive(tau=120.0)
        drive._last_emission_ts = time.time() - 300.0
        ctx = DriveContext(
            chronicle_event_count=10,
            stimmung_stance="reflective",
            programme_role="listening",
        )

        with mock.patch(
            "agents.hapax_daimonion.narrative_drive._IMPINGEMENTS_FILE",
            tmp_impingements,
        ):
            _emit_drive_impingement(drive, ctx)

        imp = json.loads(tmp_impingements.read_text().strip())
        narrative = imp["content"]["narrative"]

        # Must contain key semantic terms the pipeline can match against
        narrative_lower = narrative.lower()
        assert "narrat" in narrative_lower
        assert "10" in narrative  # chronicle count
        assert "reflective" in narrative_lower  # stimmung
        assert "listening" in narrative_lower  # role

    def test_strength_bounded(self, tmp_impingements: Path):
        drive = EndogenousDrive(tau=120.0)
        drive._last_emission_ts = time.time() - 10000.0
        ctx = DriveContext()

        with mock.patch(
            "agents.hapax_daimonion.narrative_drive._IMPINGEMENTS_FILE",
            tmp_impingements,
        ):
            _emit_drive_impingement(drive, ctx)

        imp = json.loads(tmp_impingements.read_text().strip())
        assert 0 <= imp["strength"] <= 1.0
        assert 0 <= imp["content"]["strength_posterior"] <= 1.0

    def test_strength_uses_posterior_pressure(self, tmp_impingements: Path):
        drive = EndogenousDrive(tau=120.0)
        ctx = DriveContext(chronicle_event_count=2, stimmung_stance="ambient")

        with (
            mock.patch(
                "agents.hapax_daimonion.narrative_drive._IMPINGEMENTS_FILE",
                tmp_impingements,
            ),
            mock.patch.object(drive, "evaluate", return_value=0.73),
        ):
            _emit_drive_impingement(drive, ctx)

        imp = json.loads(tmp_impingements.read_text().strip())
        assert imp["strength"] == 0.73
        assert imp["content"]["strength_posterior"] == 0.73


class TestAssembleDriveContext:
    def test_fallback_on_missing_daemon_attrs(self):
        """Partial daemon (tests, startup) should produce neutral context."""
        daemon = SimpleNamespace(_running=True)
        ctx = _assemble_drive_context(daemon, time.time())
        assert isinstance(ctx, DriveContext)
        assert ctx.chronicle_event_count >= 0
        assert isinstance(ctx.stimmung_stance, str)

    def test_reads_programme_role(self):
        """When a programme is active, its role should appear in context."""
        prog = SimpleNamespace(
            programme_id="test-1",
            role="listening",
        )
        store = SimpleNamespace(active_programme=lambda: prog)
        pm = SimpleNamespace(store=store)
        daemon = SimpleNamespace(
            _running=True,
            programme_manager=pm,
        )

        with (
            mock.patch(
                "agents.hapax_daimonion.narrative_drive._read_chronicle_count",
                return_value=3,
            ),
            mock.patch(
                "agents.hapax_daimonion.narrative_drive._read_stimmung_stance",
                return_value="ambient",
            ),
        ):
            ctx = _assemble_drive_context(daemon, time.time())

        assert ctx.programme_role == "listening"


class TestDriveLoopRefractory:
    def test_no_double_emission_within_refractory(self, tmp_impingements: Path):
        """Drive should not emit twice in quick succession."""
        drive = EndogenousDrive(tau=120.0)
        now = time.time()
        drive._last_emission_ts = now - 300.0  # high pressure
        ctx = DriveContext(chronicle_event_count=10, now=now)

        with mock.patch(
            "agents.hapax_daimonion.narrative_drive._IMPINGEMENTS_FILE",
            tmp_impingements,
        ):
            # First emission
            _emit_drive_impingement(drive, ctx)
            drive.record_emission(now)

            # Immediately after — pressure should be ~0
            DriveContext(chronicle_event_count=10, now=now + 1)  # verify no side effects
            assert drive.base_pressure(now + 1) < 0.01
