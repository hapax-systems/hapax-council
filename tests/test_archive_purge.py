"""Tests for scripts/archive-purge.py — LRR Phase 2 item 9."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest  # noqa: TC002 — runtime dep for fixtures

from shared.stream_archive import SegmentSidecar, atomic_write_json, sidecar_path_for

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "archive-purge.py"

_spec = importlib.util.spec_from_file_location("archive_purge", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
archive_purge = importlib.util.module_from_spec(_spec)
sys.modules["archive_purge"] = archive_purge
_spec.loader.exec_module(archive_purge)


def _seed_archive(tmp_path: Path) -> tuple[Path, list[Path], list[Path]]:
    """Seed an archive with 2 cond-a segments + 1 cond-b segment.

    Returns (root, cond_a_segment_paths, cond_a_sidecar_paths).
    """
    root = tmp_path / "archive"
    hls_dir = root / "hls" / "2026-04-14"
    hls_dir.mkdir(parents=True)

    base = datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)
    cond_a_segments: list[Path] = []
    cond_a_sidecars: list[Path] = []
    specs = [
        ("segment00001", "cond-a"),
        ("segment00002", "cond-a"),
        ("segment00003", "cond-b"),
    ]
    for i, (seg_id, cond_id) in enumerate(specs):
        seg_path = hls_dir / f"{seg_id}.ts"
        seg_path.write_bytes(b"X" * 1024)
        sidecar = SegmentSidecar.new(
            segment_id=seg_id,
            segment_path=seg_path,
            condition_id=cond_id,
            segment_start_ts=base + timedelta(seconds=4 * i),
            segment_end_ts=base + timedelta(seconds=4 * (i + 1)),
        )
        sidecar_p = sidecar_path_for(seg_path)
        atomic_write_json(sidecar_p, sidecar.to_json())
        if cond_id == "cond-a":
            cond_a_segments.append(seg_path)
            cond_a_sidecars.append(sidecar_p)
    return root, cond_a_segments, cond_a_sidecars


class TestDryRunDefault:
    def test_dry_run_does_not_delete(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, segs, sidecars = _seed_archive(tmp_path)
        pointer = tmp_path / "current.txt"
        pointer.write_text("cond-inactive")

        rc = archive_purge.main(
            [
                "--condition",
                "cond-a",
                "--archive-root",
                str(root),
                "--active-condition-pointer",
                str(pointer),
            ]
        )
        assert rc == 0
        # No files deleted
        for p in segs + sidecars:
            assert p.exists(), f"{p} should still exist in dry-run mode"

        stdout = capsys.readouterr().out
        assert '"mode": "dry_run"' in stdout
        assert '"segments_affected": 2' in stdout

    def test_dry_run_still_writes_audit_log(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, _, _ = _seed_archive(tmp_path)
        pointer = tmp_path / "current.txt"
        pointer.write_text("cond-inactive")

        archive_purge.main(
            [
                "--condition",
                "cond-a",
                "--archive-root",
                str(root),
                "--active-condition-pointer",
                str(pointer),
            ]
        )
        log = (root / "purge.log").read_text(encoding="utf-8").strip().splitlines()
        assert len(log) == 1
        entry = json.loads(log[0])
        assert entry["mode"] == "dry_run"
        assert entry["condition_id"] == "cond-a"
        assert entry["segments_affected"] == 2


class TestConfirmDelete:
    def test_confirm_deletes(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        root, segs, sidecars = _seed_archive(tmp_path)
        pointer = tmp_path / "current.txt"
        pointer.write_text("cond-inactive")

        rc = archive_purge.main(
            [
                "--condition",
                "cond-a",
                "--confirm",
                "--archive-root",
                str(root),
                "--active-condition-pointer",
                str(pointer),
            ]
        )
        assert rc == 0
        for p in segs + sidecars:
            assert not p.exists(), f"{p} should be deleted"

        # cond-b segment should still exist
        cond_b_segments = list((root / "hls" / "2026-04-14").glob("segment00003*"))
        assert len(cond_b_segments) == 2  # segment + sidecar

    def test_confirmed_run_writes_audit_entry(self, tmp_path: Path) -> None:
        root, _, _ = _seed_archive(tmp_path)
        pointer = tmp_path / "current.txt"
        pointer.write_text("cond-inactive")

        archive_purge.main(
            [
                "--condition",
                "cond-a",
                "--confirm",
                "--reason",
                "consent revocation",
                "--archive-root",
                str(root),
                "--active-condition-pointer",
                str(pointer),
            ]
        )
        log = (root / "purge.log").read_text(encoding="utf-8").strip().splitlines()
        entry = json.loads(log[-1])
        assert entry["mode"] == "confirmed"
        assert entry["reason"] == "consent revocation"


class TestActiveConditionGuard:
    def test_refuses_to_purge_active(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, segs, sidecars = _seed_archive(tmp_path)
        pointer = tmp_path / "current.txt"
        pointer.write_text("cond-a")  # active

        rc = archive_purge.main(
            [
                "--condition",
                "cond-a",
                "--confirm",
                "--archive-root",
                str(root),
                "--active-condition-pointer",
                str(pointer),
            ]
        )
        assert rc == 2
        for p in segs + sidecars:
            assert p.exists(), f"{p} must NOT be deleted when condition is active"

    def test_allows_purge_when_pointer_absent(self, tmp_path: Path) -> None:
        root, segs, _ = _seed_archive(tmp_path)
        rc = archive_purge.main(
            [
                "--condition",
                "cond-a",
                "--confirm",
                "--archive-root",
                str(root),
                "--active-condition-pointer",
                str(tmp_path / "no-pointer.txt"),
            ]
        )
        assert rc == 0
        for p in segs:
            assert not p.exists()


def _write_contract(
    contracts_dir: Path,
    *,
    contract_id: str,
    person_id: str,
    active: bool,
) -> None:
    """Write a minimal consent contract YAML for test fixtures."""
    contracts_dir.mkdir(parents=True, exist_ok=True)
    body = f"""\
id: {contract_id}
parties: [operator, {person_id}]
scope: [biometric]
direction: one_way
visibility_mechanism: on_request
created_at: '2026-01-01T00:00:00Z'
"""
    if not active:
        body += "revoked_at: '2026-04-15T00:00:00Z'\n"
    (contracts_dir / f"{contract_id}.yaml").write_text(body, encoding="utf-8")


class TestConsentRevocationTieIn:
    """LRR Phase 2 spec §3.9 consent-revocation hook."""

    def test_no_contract_passes_consent_check(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, segs, _ = _seed_archive(tmp_path)
        contracts_dir = tmp_path / "contracts"
        contracts_dir.mkdir()  # empty dir — no contracts
        rc = archive_purge.main(
            [
                "--condition",
                "cond-a",
                "--confirm",
                "--archive-root",
                str(root),
                "--active-condition-pointer",
                str(tmp_path / "no-pointer.txt"),
                "--consent-revoked-for",
                "simon",
                "--contracts-dir",
                str(contracts_dir),
            ]
        )
        assert rc == 0
        assert "consent check passes" in capsys.readouterr().err
        for p in segs:
            assert not p.exists()

    def test_revoked_contract_passes_consent_check(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A revoked contract is indistinguishable from 'no contract' to the
        `ConsentRegistry.get_contract_for()` accessor (which only returns
        active contracts). Both resolve to 'consent check passes' — what
        matters is that a LIVE contract does NOT exist, regardless of
        whether it was never created or was created-then-revoked."""
        root, segs, _ = _seed_archive(tmp_path)
        contracts_dir = tmp_path / "contracts"
        _write_contract(
            contracts_dir,
            contract_id="simon-biometric",
            person_id="simon",
            active=False,
        )
        rc = archive_purge.main(
            [
                "--condition",
                "cond-a",
                "--confirm",
                "--archive-root",
                str(root),
                "--active-condition-pointer",
                str(tmp_path / "no-pointer.txt"),
                "--consent-revoked-for",
                "simon",
                "--contracts-dir",
                str(contracts_dir),
            ]
        )
        assert rc == 0
        err = capsys.readouterr().err
        # get_contract_for() only returns active contracts, so a revoked
        # contract reads as "no contract" — both paths pass the check.
        assert "consent check passes" in err
        for p in segs:
            assert not p.exists()

    def test_live_contract_refuses_purge(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, segs, _ = _seed_archive(tmp_path)
        contracts_dir = tmp_path / "contracts"
        _write_contract(
            contracts_dir,
            contract_id="simon-biometric",
            person_id="simon",
            active=True,
        )
        rc = archive_purge.main(
            [
                "--condition",
                "cond-a",
                "--confirm",
                "--archive-root",
                str(root),
                "--active-condition-pointer",
                str(tmp_path / "no-pointer.txt"),
                "--consent-revoked-for",
                "simon",
                "--contracts-dir",
                str(contracts_dir),
            ]
        )
        assert rc == 3
        err = capsys.readouterr().err
        assert "LIVE" in err
        # Segments must be preserved when consent check refuses
        for p in segs:
            assert p.exists(), f"{p} must NOT be deleted when contract is live"

    def test_audit_log_records_consent_revoked_for_field(self, tmp_path: Path) -> None:
        root, _, _ = _seed_archive(tmp_path)
        contracts_dir = tmp_path / "contracts"
        contracts_dir.mkdir()
        archive_purge.main(
            [
                "--condition",
                "cond-a",
                "--confirm",
                "--archive-root",
                str(root),
                "--active-condition-pointer",
                str(tmp_path / "no-pointer.txt"),
                "--consent-revoked-for",
                "simon",
                "--contracts-dir",
                str(contracts_dir),
                "--reason",
                "guardian revoked simon scope",
            ]
        )
        log_path = root / "purge.log"
        assert log_path.exists()
        entries = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
        assert entries[-1]["consent_revoked_for"] == "simon"
        assert entries[-1]["reason"] == "guardian revoked simon scope"

    def test_audit_log_omits_consent_field_when_not_set(self, tmp_path: Path) -> None:
        root, _, _ = _seed_archive(tmp_path)
        archive_purge.main(
            [
                "--condition",
                "cond-a",
                "--confirm",
                "--archive-root",
                str(root),
                "--active-condition-pointer",
                str(tmp_path / "no-pointer.txt"),
            ]
        )
        log_path = root / "purge.log"
        entries = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
        assert "consent_revoked_for" not in entries[-1]


class TestFilesystemAtomicity:
    """Queue #146 G2 — filesystem partial-failure behaviour.

    Phase 2 unit tests cover the happy paths for purge but do not exercise
    the per-target OSError branch in the confirmed-delete loop. A purge
    that partially fails should: (a) still write an audit entry, (b)
    report errors to stderr, (c) continue through remaining targets so
    one broken segment does not strand the rest.
    """

    def test_audit_log_still_written_when_unlink_fails(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root, segs, sidecars = _seed_archive(tmp_path)
        pointer = tmp_path / "current.txt"
        pointer.write_text("cond-inactive")

        failing = segs[0]
        real_unlink = Path.unlink

        def patched_unlink(self: Path, *args: object, **kwargs: object) -> None:
            if self == failing:
                raise PermissionError(f"EACCES (simulated): {self}")
            real_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", patched_unlink)

        rc = archive_purge.main(
            [
                "--condition",
                "cond-a",
                "--confirm",
                "--archive-root",
                str(root),
                "--active-condition-pointer",
                str(pointer),
            ]
        )
        assert rc == 0, "purge should return 0 even on partial failure"

        captured = capsys.readouterr()
        assert "EACCES (simulated)" in captured.err
        assert str(failing) in captured.err

        log_path = root / "purge.log"
        assert log_path.exists(), "audit log must be written even on partial failure"
        entries = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
        final = entries[-1]
        assert final["mode"] == "confirmed"
        assert final["segments_affected"] == 2

        assert failing.exists(), "the segment whose unlink raised must remain on disk"
        assert not segs[1].exists(), "the healthy segment must have been deleted"
        assert not sidecars[1].exists(), "the healthy sidecar must have been deleted"

    def test_purge_continues_past_missing_segment(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root, segs, sidecars = _seed_archive(tmp_path)
        pointer = tmp_path / "current.txt"
        pointer.write_text("cond-inactive")

        segs[0].unlink()
        assert not segs[0].exists()
        assert sidecars[0].exists()

        rc = archive_purge.main(
            [
                "--condition",
                "cond-a",
                "--confirm",
                "--archive-root",
                str(root),
                "--active-condition-pointer",
                str(pointer),
            ]
        )
        assert rc == 0
        assert not sidecars[0].exists(), "orphan sidecar must still be deleted"
        assert not segs[1].exists()
        assert not sidecars[1].exists()

        log_path = root / "purge.log"
        entries = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
        assert entries[-1]["segments_affected"] == 2
