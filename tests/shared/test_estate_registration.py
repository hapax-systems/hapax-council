from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared.estate_registration import (
    RegistrationError,
    export_canary_health,
    grandfather_fragment,
    originate_canaries,
    run_peer_command,
    sweep,
)
from shared.estate_store_registry import load_registry, matching_store

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _registry_for(home: Path, *, depth: int = 1):  # noqa: ANN202
    registry = load_registry()
    return replace(
        registry,
        scan_roots=(
            {
                "id": "vault-hapax-top-level",
                "kind": "directory",
                "path": "{vault}/30-areas/hapax",
                "depth": depth,
            },
        ),
    )


def _make_hapax_root(home: Path) -> Path:
    root = home / "Documents" / "Personal" / "30-areas" / "hapax"
    root.mkdir(parents=True)
    return root


def test_parent_registration_does_not_register_new_descendant_store(tmp_path: Path) -> None:
    registry = load_registry()
    home = tmp_path / "home"
    candidate = home / "Documents" / "Personal" / "30-areas" / "hapax" / "new-garden"

    assert matching_store(registry, candidate.parent, host="appendix", home=home)
    assert matching_store(registry, candidate, host="appendix", home=home) is None


def test_originator_writes_registered_a_and_unregistered_b_as_one_pair(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _make_hapax_root(home)
    result = originate_canaries(
        load_registry(), host_id="appendix", home=home, now=NOW, token="fixed"
    )

    assert Path(result["canary_a_path"]).is_file()
    registration = json.loads(Path(result["canary_a_registration"]).read_text())
    assert registration["store_id"] == "estate-registration-runtime"
    assert Path(result["canary_b_path"]).is_dir()
    assert Path(result["canary_b_manifest"]).is_file()
    assert not (Path(result["canary_b_path"]) / ".registered").exists()


def test_midnight_canary_b_exercises_home_dot_root(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _make_hapax_root(home)
    midnight = NOW.replace(hour=0)

    result = originate_canaries(
        load_registry(), host_id="appendix", home=home, now=midnight, token="fixed"
    )

    assert Path(result["canary_b_path"]).parent == home
    assert Path(result["canary_b_path"]).name.startswith(".hapax-canary-")


def test_cross_host_health_requires_fresh_a_and_the_matching_b_manifest(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _make_hapax_root(home)
    result = originate_canaries(
        load_registry(), host_id="appendix", home=home, now=NOW, token="fixed"
    )

    health = export_canary_health(
        registry=load_registry(),
        host_id="appendix",
        home=home,
        now=NOW + timedelta(minutes=60),
    )
    assert health["canary_a_registered"] is True
    assert health["canary_b_manifest_present"] is True

    Path(result["canary_b_manifest"]).unlink()
    with pytest.raises(RegistrationError, match="pair is incomplete"):
        export_canary_health(
            registry=load_registry(),
            host_id="appendix",
            home=home,
            now=NOW + timedelta(minutes=60),
        )


def test_cross_host_health_rejects_stale_canary_a(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _make_hapax_root(home)
    originate_canaries(load_registry(), host_id="appendix", home=home, now=NOW, token="fixed")

    with pytest.raises(RegistrationError, match="restore the hourly originator"):
        export_canary_health(
            registry=load_registry(),
            host_id="appendix",
            home=home,
            now=NOW + timedelta(hours=2),
        )


def test_cross_host_health_rejects_receipt_not_bound_to_registry(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _make_hapax_root(home)
    result = originate_canaries(
        load_registry(), host_id="appendix", home=home, now=NOW, token="fixed"
    )
    receipt_path = Path(result["canary_a_registration"])
    receipt = json.loads(receipt_path.read_text())
    receipt["store_id"] = "not-registered"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(RegistrationError, match="not bound to its declared store"):
        export_canary_health(registry=load_registry(), host_id="appendix", home=home, now=NOW)


def test_sweep_flags_and_files_without_mutating_candidate(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = _make_hapax_root(home)
    result = originate_canaries(
        load_registry(), host_id="appendix", home=home, now=NOW, token="fixed"
    )
    candidate = Path(result["canary_b_path"])
    before = (candidate.stat().st_ino, (candidate / "store.json").read_bytes())

    outcome = sweep(
        _registry_for(home),
        host_id="appendix",
        home=home,
        now=NOW + timedelta(days=1),
        report_root=root / "reports",
    )

    assert result["canary_id"] in outcome.flagged_canary_ids
    assert any(row["path"] == str(candidate) for row in outcome.findings)
    assert candidate.is_dir()
    assert (candidate.stat().st_ino, (candidate / "store.json").read_bytes()) == before
    report = json.loads(Path(outcome.report_path).read_text())
    assert report["mutation_actions"] == []


def test_sweep_implementation_has_no_rename_move_or_delete_operation() -> None:
    source = (Path(__file__).resolve().parents[2] / "shared" / "estate_registration.py").read_text(
        encoding="utf-8"
    )

    assert "os.replace(" not in source
    assert ".rename(" not in source
    assert ".unlink(" not in source
    assert "shutil.move(" not in source
    assert "shutil.rmtree(" not in source


def test_two_distinct_unflagged_b_instances_file_self_named_incident(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = _make_hapax_root(home)
    first = originate_canaries(load_registry(), host_id="appendix", home=home, now=NOW, token="one")
    second = originate_canaries(
        load_registry(),
        host_id="appendix",
        home=home,
        now=NOW + timedelta(hours=1),
        token="two",
    )
    dead_scan = replace(
        load_registry(),
        scan_roots=(
            {"id": "dead-detector", "kind": "directory", "path": str(root / "empty"), "depth": 1},
        ),
    )
    (root / "empty").mkdir()

    outcome = sweep(
        dead_scan,
        host_id="appendix",
        home=home,
        now=NOW + timedelta(days=1),
        report_root=root / "reports",
    )

    assert outcome.missed_canary_ids == (first["canary_id"], second["canary_id"])
    assert outcome.detector_incident_path is not None
    incident = json.loads(Path(outcome.detector_incident_path).read_text())
    assert incident["detector"] == "hapax-estate-store-registry sweep"
    assert incident["reason"] == "two consecutive distinct Canary B instances passed unflagged"


def test_grandfather_capture_is_evidence_not_blessing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = _make_hapax_root(home)
    (root / "existing-garden").mkdir()

    fragment = grandfather_fragment(_registry_for(home), host_id="appendix", home=home, now=NOW)

    assert fragment["complete_scan"] is True
    assert fragment["operator_blessing"] is None
    row = next(item for item in fragment["stores"] if item["locator"].endswith("existing-garden"))
    assert row["lifecycle"] == "grandfathered"
    assert row["operator_blessing"] is None
    assert "bounded scan" in row["discovery_evidence"]


def test_grandfather_capture_refuses_when_a_scan_root_cannot_be_read(tmp_path: Path) -> None:
    home = tmp_path / "home"
    registry = replace(
        load_registry(),
        scan_roots=(
            {"id": "missing", "kind": "directory", "path": str(home / "missing"), "depth": 1},
        ),
    )

    with pytest.raises(RegistrationError, match="refused incomplete scan"):
        grandfather_fragment(registry, host_id="appendix", home=home, now=NOW)


def test_peer_command_uses_declared_opposite_host_and_no_fallback() -> None:
    calls = []

    def runner(argv, **kwargs):  # noqa: ANN001, ANN202
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"ok": true}\n', stderr="")

    run_peer_command(load_registry(), host_id="appendix", command="export-canary", runner=runner)

    assert calls[0][0][5] == "hapax-podium"
    assert "--host podium" in calls[0][0][6]


def test_peer_command_refuses_ssh_failure() -> None:
    def runner(_argv, **_kwargs):  # noqa: ANN202
        return SimpleNamespace(returncode=255, stdout="", stderr="Permission denied")

    with pytest.raises(RegistrationError, match="restore the existing SSH link|repair the peer"):
        run_peer_command(
            load_registry(), host_id="appendix", command="export-canary", runner=runner
        )
