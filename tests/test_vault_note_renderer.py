"""Tests for shared/vault_note_renderer.py — LRR Phase 2 item 7."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest  # noqa: TC002 — runtime dep for fixtures

from shared.stream_archive import SegmentSidecar
from shared.vault_note_renderer import (
    VAULT_ENV_VAR,
    maybe_write_note,
    note_path_for,
    render_note_body,
    vault_path_from_env,
)


def _fake_sidecar(**overrides: object) -> SegmentSidecar:
    now = datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)
    defaults = {
        "segment_id": "segment00042",
        "segment_path": "/tmp/segment00042.ts",
        "condition_id": "cond-phase-a-baseline-qwen-001",
        "segment_start_ts": now,
        "segment_end_ts": now + timedelta(seconds=4),
        "reaction_ids": ["rx-1", "rx-2"],
        "active_activity": "study",
        "stimmung_snapshot": {"stance": "READY"},
    }
    defaults.update(overrides)  # type: ignore[arg-type]
    return SegmentSidecar.new(**defaults)  # type: ignore[arg-type]


class TestVaultEnvGate:
    def test_env_unset_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(VAULT_ENV_VAR, raising=False)
        assert vault_path_from_env() is None

    def test_env_empty_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(VAULT_ENV_VAR, "   ")
        assert vault_path_from_env() is None

    def test_env_set_returns_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv(VAULT_ENV_VAR, str(tmp_path))
        result = vault_path_from_env()
        assert result == tmp_path


class TestNotePath:
    def test_path_uses_start_month(self, tmp_path: Path) -> None:
        sidecar = _fake_sidecar()
        path = note_path_for(sidecar, tmp_path)
        assert (
            path
            == tmp_path
            / "30-areas"
            / "legomena-live"
            / "archive"
            / "2026-04"
            / "segment-segment00042.md"
        )


class TestRenderBody:
    def test_body_contains_key_fields(self) -> None:
        sidecar = _fake_sidecar()
        body = render_note_body(sidecar)
        assert "segment00042" in body
        assert "cond-phase-a-baseline-qwen-001" in body
        assert "study" in body
        assert "READY" in body
        assert "rx-1" in body
        assert body.startswith("---\n")
        assert "\n---\n" in body

    def test_body_handles_missing_optional_fields(self) -> None:
        sidecar = _fake_sidecar(
            condition_id=None,
            active_activity=None,
            stimmung_snapshot={},
            reaction_ids=[],
        )
        body = render_note_body(sidecar)
        assert "(unknown)" in body
        assert "(none)" in body


class TestMaybeWriteNoteGated:
    def test_gate_closed_returns_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv(VAULT_ENV_VAR, raising=False)
        sidecar = _fake_sidecar()
        assert maybe_write_note(sidecar) is None

    def test_vault_missing_returns_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Set env but point at a non-existent dir
        monkeypatch.setenv(VAULT_ENV_VAR, str(tmp_path / "no-vault"))
        assert maybe_write_note(_fake_sidecar()) is None

    def test_writes_when_gate_open(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv(VAULT_ENV_VAR, str(tmp_path))
        sidecar = _fake_sidecar()
        result = maybe_write_note(sidecar)
        assert result is not None
        assert result.exists()
        body = result.read_text(encoding="utf-8")
        assert "segment00042" in body

    def test_does_not_overwrite_existing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(VAULT_ENV_VAR, str(tmp_path))
        sidecar = _fake_sidecar()
        first = maybe_write_note(sidecar)
        assert first is not None
        first.write_text("OPERATOR COMMENTARY — DO NOT CLOBBER")

        second = maybe_write_note(sidecar)
        assert second is None
        assert "OPERATOR COMMENTARY" in first.read_text(encoding="utf-8")
