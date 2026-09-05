from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import shared.estate_registration as registration_module
from shared.estate_registration import (
    RegistrationError,
    export_canary_health,
    grandfather_fragment,
    observed_host_identity,
    originate_canaries,
    run_peer_command,
    sweep,
)
from shared.estate_store_registry import load_registry, matching_store

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """Keep declarations intact and isolate native reads even for module-only tests."""
    declared = load_registry()
    values = {
        "/proc/sys/kernel/hostname": "hapax-appendix\n",
        # Coordinator readback, 2026-09-05T06:40Z; not learned from the registry.
        "/etc/machine-id": "ffc36d1a0ca64320a3f1c9f1060292af\n",
    }
    read_text = Path.read_text

    def read(path, *args, **kwargs):  # noqa: ANN001, ANN202
        if str(path) in values:
            return values[str(path)]
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    return replace(declared, hosts={host: dict(row) for host, row in declared.hosts.items()})


@pytest.mark.parametrize(
    "value", ["", " \n", OSError("fake unreadable"), UnicodeError("fake invalid")]
)
@pytest.mark.parametrize("field", ["observed_hostname", "observed_machine_id"])
def test_native_identity_absence_uses_only_fixed_read_paths(monkeypatch, field, value) -> None:
    paths = {
        "observed_hostname": "/proc/sys/kernel/hostname",
        "observed_machine_id": "/etc/machine-id",
    }
    calls = []

    def read(path, *, encoding):  # noqa: ANN001, ANN202
        calls.append((str(path), encoding))
        if str(path) == paths[field]:
            if isinstance(value, Exception):
                raise value
            return value
        return "native-value\n"

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setenv("HOSTNAME", "untrusted-host")
    monkeypatch.setenv("MACHINE_ID", "untrusted-machine")
    observed = observed_host_identity()
    assert calls == [(path, "utf-8") for path in paths.values()]
    assert observed[field] == "absent"
    assert observed[next(name for name in paths if name != field)] == "native-value"


def _registry_for(registry, *, depth: int = 1):  # noqa: ANN001, ANN202
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


def test_parent_registration_does_not_register_new_descendant_store(
    registry, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    candidate = home / "Documents" / "Personal" / "30-areas" / "hapax" / "new-garden"

    assert matching_store(registry, candidate.parent, host="appendix", home=home)
    assert matching_store(registry, candidate, host="appendix", home=home) is None


def test_originator_writes_registered_a_and_unregistered_b_as_one_pair(
    registry, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    _make_hapax_root(home)
    result = originate_canaries(registry, host_id="appendix", home=home, now=NOW, token="fixed")

    assert Path(result["canary_a_path"]).is_file()
    registration = json.loads(Path(result["canary_a_registration"]).read_text())
    assert registration["store_id"] == "estate-registration-runtime"
    assert Path(result["canary_b_path"]).is_dir()
    assert Path(result["canary_b_manifest"]).is_file()
    assert not (Path(result["canary_b_path"]) / ".registered").exists()


def test_midnight_canary_b_exercises_home_dot_root(registry, tmp_path: Path) -> None:
    home = tmp_path / "home"
    _make_hapax_root(home)
    midnight = NOW.replace(hour=0)

    result = originate_canaries(
        registry, host_id="appendix", home=home, now=midnight, token="fixed"
    )

    assert Path(result["canary_b_path"]).parent == home
    assert Path(result["canary_b_path"]).name.startswith(".hapax-canary-")


def test_cross_host_health_requires_fresh_a_and_the_matching_b_manifest(
    registry, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    _make_hapax_root(home)
    result = originate_canaries(registry, host_id="appendix", home=home, now=NOW, token="fixed")

    health = export_canary_health(
        registry=registry,
        host_id="appendix",
        home=home,
        now=NOW + timedelta(minutes=60),
    )
    assert health["canary_a_registered"] is True
    assert health["canary_b_manifest_present"] is True

    Path(result["canary_b_manifest"]).unlink()
    with pytest.raises(RegistrationError, match="pair is incomplete"):
        export_canary_health(
            registry=registry,
            host_id="appendix",
            home=home,
            now=NOW + timedelta(minutes=60),
        )


def test_cross_host_health_rejects_stale_canary_a(registry, tmp_path: Path) -> None:
    home = tmp_path / "home"
    _make_hapax_root(home)
    originate_canaries(registry, host_id="appendix", home=home, now=NOW, token="fixed")

    with pytest.raises(RegistrationError, match="restore the hourly originator"):
        export_canary_health(
            registry=registry,
            host_id="appendix",
            home=home,
            now=NOW + timedelta(hours=2),
        )


def test_cross_host_health_rejects_receipt_not_bound_to_registry(registry, tmp_path: Path) -> None:
    home = tmp_path / "home"
    _make_hapax_root(home)
    result = originate_canaries(registry, host_id="appendix", home=home, now=NOW, token="fixed")
    receipt_path = Path(result["canary_a_registration"])
    receipt = json.loads(receipt_path.read_text())
    receipt["store_id"] = "not-registered"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(RegistrationError, match="not bound to its declared store"):
        export_canary_health(registry=registry, host_id="appendix", home=home, now=NOW)


def test_sweep_flags_and_files_without_mutating_candidate(registry, tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = _make_hapax_root(home)
    result = originate_canaries(registry, host_id="appendix", home=home, now=NOW, token="fixed")
    candidate = Path(result["canary_b_path"])
    before = (candidate.stat().st_ino, (candidate / "store.json").read_bytes())

    outcome = sweep(
        _registry_for(registry),
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


@pytest.mark.parametrize("legacy", [False, True], ids=["explicit-detector", "legacy-v1"])
def test_sweep_recovers_flag_receipt_after_interrupted_state_write(
    registry, tmp_path: Path, monkeypatch, legacy
) -> None:
    home = tmp_path / "home"
    _make_hapax_root(home)
    first = originate_canaries(registry, host_id="appendix", home=home, now=NOW, token="first")
    runtime = home / ".cache/hapax/estate-registration"
    reports = runtime / "reports"
    write_json = registration_module._write_json

    def interrupt(path, payload):  # noqa: ANN001, ANN202
        if path.parent.name == "detector-state":
            raise RegistrationError("injected interruption before detector state persistence")
        write_json(path, payload)

    with monkeypatch.context() as fault:
        fault.setattr(registration_module, "_write_json", interrupt)
        with pytest.raises(RegistrationError, match="injected interruption"):
            sweep(_registry_for(registry), host_id="appendix", home=home, now=NOW)
    flag = runtime / "flags" / f"{first['canary_id']}.json"
    if legacy:
        # C2's v1 schema had only this detector as producer, with no explicit
        # detector field. Already-stranded receipts must recover too.
        receipt = json.loads(flag.read_text())
        receipt.pop("detector", None)
        flag.write_text(json.dumps(receipt))
    before = (flag.stat().st_ino, flag.stat().st_mtime_ns, flag.read_bytes())
    assert not list((runtime / "detector-state").glob("*.json"))
    assert not list(reports.glob("estate-drift-*.json"))

    second = originate_canaries(
        registry, host_id="appendix", home=home, now=NOW + timedelta(hours=1), token="second"
    )
    outcome = sweep(
        _registry_for(registry), host_id="appendix", home=home, now=NOW + timedelta(hours=2)
    )
    ids = (first["canary_id"], second["canary_id"])
    assert outcome.flagged_canary_ids == ids
    assert outcome.missed_canary_ids == ()
    assert (flag.stat().st_ino, flag.stat().st_mtime_ns, flag.read_bytes()) == before
    state = json.loads(next((runtime / "detector-state").glob("*.json")).read_text())
    assert state["evaluated_ids"] == sorted(ids)
    assert state["miss_streak"] == 0
    report = json.loads(Path(outcome.report_path).read_text())
    assert report["flagged_canary_ids"] == list(ids)
    repeated = sweep(
        _registry_for(registry), host_id="appendix", home=home, now=NOW + timedelta(hours=3)
    )
    assert repeated.flagged_canary_ids == repeated.missed_canary_ids == ()
    assert (flag.stat().st_ino, flag.stat().st_mtime_ns, flag.read_bytes()) == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "wrong-schema"),
        ("canary_id", "another-canary"),
        ("host", "another-host"),
        ("detector", "another-detector"),
        ("path", "/another-canary"),
        ("action", "quarantine"),
        ("flagged_at", "invalid-time"),
        ("flagged_at", "2026-09-02T12:00:00"),
        ("flagged_at", None),
        ("invalid-json", None),
    ],
)
def test_sweep_refuses_invalid_existing_flag_with_named_repair(
    registry, tmp_path: Path, field, value
) -> None:
    home = tmp_path / "home"
    _make_hapax_root(home)
    canary = originate_canaries(registry, host_id="appendix", home=home, now=NOW, token="first")
    runtime = home / ".cache/hapax/estate-registration"
    flag = runtime / "flags" / f"{canary['canary_id']}.json"
    receipt = {
        "schema": "hapax.estate-canary-flag/v1",
        "canary_id": canary["canary_id"],
        "host": "appendix",
        "detector": "hapax-estate-store-registry sweep",
        "path": canary["canary_b_path"],
        "action": "flag-only",
        "flagged_at": "2026-09-02T12:00:00Z",
    }
    receipt[field] = value
    flag.parent.mkdir(parents=True)
    flag.write_text("{" if field == "invalid-json" else json.dumps(receipt))
    before = flag.read_bytes()
    with pytest.raises(RegistrationError) as failure:
        sweep(_registry_for(registry), host_id="appendix", home=home, now=NOW)
    message = str(failure.value)
    assert "invalid existing canary flag" in message
    assert str(flag) in message
    assert "remedy:" in message and "repair" in message and "rerun" in message
    assert flag.read_bytes() == before
    assert not list((runtime / "detector-state").glob("*.json"))
    assert not list((runtime / "reports").glob("estate-drift-*.json"))


def test_sweep_records_both_missed_streaks_in_one_sweep(registry, tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    _make_hapax_root(home)
    canaries = [
        originate_canaries(
            registry, host_id="appendix", home=home, now=NOW + timedelta(hours=i), token=str(i)
        )
        for i in range(5)
    ]
    # Exact order: miss, miss, flagged, miss, miss.
    monkeypatch.setattr(
        registration_module,
        "scan_candidates",
        lambda *_args, **_kwargs: (
            (registration_module.Candidate(canaries[2]["canary_b_path"], "directory", "fake"),),
            (),
        ),
    )
    outcome = sweep(registry, host_id="appendix", home=home, now=NOW + timedelta(hours=6))
    runtime = home / ".cache/hapax/estate-registration"
    paths = sorted((runtime / "reports").glob("incident-estate-detector-dead-*.json"))
    assert len(paths) == 2
    incidents = [json.loads(path.read_text()) for path in paths]
    assert {row["trigger_canary_id"] for row in incidents} == {
        canaries[1]["canary_id"],
        canaries[4]["canary_id"],
    }
    assert all(row["miss_streak"] == 2 for row in incidents)
    assert all(row["detector"] == "hapax-estate-store-registry sweep" for row in incidents)
    assert Path(outcome.detector_incident_path) in paths
    assert outcome.flagged_canary_ids == (canaries[2]["canary_id"],)
    assert outcome.missed_canary_ids == tuple(canaries[i]["canary_id"] for i in (0, 1, 3, 4))
    state = json.loads(next((runtime / "detector-state").glob("*.json")).read_text())
    assert state["evaluated_ids"] == sorted(row["canary_id"] for row in canaries)
    assert state["miss_streak"] == 2 and state["incident_filed"] is True
    assert json.loads(Path(outcome.report_path).read_text())["mutation_actions"] == []


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("host", "another-host", "wrong host or type"),
        ("canary", "B", "wrong host or type"),
        ("created_at", "invalid-time", "no parseable created_at"),
        ("created_at", None, "no parseable created_at"),
    ],
)
def test_canary_validation_names_record_and_recheck(registry, tmp_path: Path, field, value, reason):
    home = tmp_path / "home"
    _make_hapax_root(home)
    canary = originate_canaries(registry, host_id="appendix", home=home, now=NOW, token="first")
    path = Path(canary["canary_a_registration"])
    receipt = json.loads(path.read_text())
    receipt[field] = value
    path.write_text(json.dumps(receipt))
    before = path.read_bytes()
    with pytest.raises(RegistrationError) as failure:
        export_canary_health(registry=registry, host_id="appendix", home=home, now=NOW)
    message = str(failure.value)
    assert reason in message
    assert str(path) in message
    assert "remedy:" in message and "repair" in message
    assert "originate" in message and "export-canary" in message
    assert path.read_bytes() == before


@pytest.mark.parametrize("failure_kind", ["unreadable", "invalid-json", "non-object", "encoding"])
def test_required_runtime_record_read_error_names_repair_and_recheck(
    registry, tmp_path: Path, monkeypatch, failure_kind
) -> None:
    home = tmp_path / "home"
    _make_hapax_root(home)
    canary = originate_canaries(registry, host_id="appendix", home=home, now=NOW, token="first")
    path = Path(canary["canary_a_registration"])
    if failure_kind == "unreadable":
        read = Path.read_text

        def unreadable(record, *args, **kwargs):  # noqa: ANN001, ANN202
            if record == path:
                raise PermissionError("synthetic permission denied")
            return read(record, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", unreadable)
    else:
        path.write_bytes(
            {"invalid-json": b"{", "non-object": b"[]", "encoding": b"\xff"}[failure_kind]
        )
    before = path.read_bytes()
    with pytest.raises(RegistrationError) as failure:
        export_canary_health(registry=registry, host_id="appendix", home=home, now=NOW)
    message = str(failure.value)
    assert "required runtime record" in message and str(path) in message
    assert "remedy:" in message and "repair" in message and "rerun" in message
    if failure_kind == "unreadable":
        assert "synthetic permission denied" in message
    assert path.read_bytes() == before


def test_sweep_report_collision_preserves_immutable_record(registry, tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    _make_hapax_root(home)
    outcome = sweep(_registry_for(registry), host_id="appendix", home=home, now=NOW)
    report = Path(outcome.report_path)
    before = (report.stat().st_ino, report.stat().st_mtime_ns, report.read_bytes())
    # Force just a report collision; the second sweep has a distinct state identity.
    monkeypatch.setattr(registration_module.secrets, "token_hex", lambda _size: "second")
    colliding_report = report.parent / "estate-drift-appendix-20260902T120000Z-second.json"
    colliding_report.write_bytes(before[2])
    collision_before = (colliding_report.stat().st_ino, colliding_report.read_bytes())
    with pytest.raises(RegistrationError, match="cannot create immutable runtime record"):
        sweep(_registry_for(registry), host_id="appendix", home=home, now=NOW)
    assert (report.stat().st_ino, report.stat().st_mtime_ns, report.read_bytes()) == before
    assert (colliding_report.stat().st_ino, colliding_report.read_bytes()) == collision_before


def test_two_distinct_unflagged_b_instances_file_self_named_incident(
    registry, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    root = _make_hapax_root(home)
    first = originate_canaries(registry, host_id="appendix", home=home, now=NOW, token="one")
    second = originate_canaries(
        registry,
        host_id="appendix",
        home=home,
        now=NOW + timedelta(hours=1),
        token="two",
    )
    dead_scan = replace(
        registry,
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


def test_grandfather_capture_is_evidence_not_blessing(registry, tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = _make_hapax_root(home)
    (root / "existing-garden").mkdir()

    fragment = grandfather_fragment(_registry_for(registry), host_id="appendix", home=home, now=NOW)

    assert fragment["complete_scan"] is True
    assert fragment["operator_blessing"] is None
    row = next(item for item in fragment["stores"] if item["locator"].endswith("existing-garden"))
    assert row["lifecycle"] == "grandfathered"
    assert row["operator_blessing"] is None
    assert "bounded scan" in row["discovery_evidence"]


def test_grandfather_capture_refuses_when_a_scan_root_cannot_be_read(
    registry, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    registry = replace(
        registry,
        scan_roots=(
            {"id": "missing", "kind": "directory", "path": str(home / "missing"), "depth": 1},
        ),
    )

    with pytest.raises(RegistrationError, match="refused incomplete scan"):
        grandfather_fragment(registry, host_id="appendix", home=home, now=NOW)


def test_peer_command_uses_declared_opposite_host_and_no_fallback(registry) -> None:
    calls = []

    def runner(argv, **kwargs):  # noqa: ANN001, ANN202
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"ok": true}\n', stderr="")

    result = run_peer_command(registry, host_id="appendix", command="export-canary", runner=runner)

    assert calls[0][0][5] == "hapax-podium"
    assert "--host podium" in calls[0][0][6]
    assert result.ssh_target == calls[0][0][5]


def test_peer_command_refuses_ssh_failure(registry) -> None:
    def runner(_argv, **_kwargs):  # noqa: ANN202
        return SimpleNamespace(returncode=255, stdout="", stderr="Permission denied")

    with pytest.raises(RegistrationError, match="restore the existing SSH link|repair the peer"):
        run_peer_command(registry, host_id="appendix", command="export-canary", runner=runner)


@pytest.mark.parametrize("binding", [None, "relative/release", "$HOME/release", "/a/../b", "/a//b"])
def test_qualified_peer_requires_safe_binding(registry, binding: str | None) -> None:
    def no_ssh(*_args, **_kwargs):  # noqa: ANN202
        pytest.fail("unsafe binding reached SSH")

    with pytest.raises(RegistrationError, match="peer_source_root.*remedy"):
        run_peer_command(
            registry,
            host_id="appendix",
            command="sweep",
            peer_source_root=binding,
            qualified=True,
            runner=no_ssh,
        )


def test_peer_failure_retains_both_streams_and_exact_returncode(registry) -> None:
    stdout = '  {"report_path":"/fake/failed-report.json"}\npartial output\n'
    stderr = "  fake peer diagnostic\nsecond line\n"

    def runner(*_args, **_kwargs):  # noqa: ANN202
        return SimpleNamespace(returncode=23, stdout=stdout, stderr=stderr)

    result = run_peer_command(
        registry,
        host_id="appendix",
        command="sweep",
        runner=runner,
        check=False,
        peer_source_root="/retained/release",
        qualified=True,
    )
    assert (result.stdout, result.stderr, result.returncode) == (stdout, stderr, 23)
    assert result.failed
    with pytest.raises(RegistrationError) as caught:
        run_peer_command(registry, host_id="appendix", command="sweep", runner=runner)
    assert (
        caught.value.result.stdout,
        caught.value.result.stderr,
        caught.value.result.returncode,
    ) == (
        stdout,
        stderr,
        23,
    )
    assert stdout not in str(caught.value) and stderr not in str(caught.value)


@pytest.fixture
def fake_peer_shell(tmp_path: Path):  # noqa: ANN201
    """Execute only the generated shell in a temporary fake host, never SSH or uv."""
    home = tmp_path / "peer-home"
    old = home / "releases" / "old release"
    new = home / "releases" / "new"
    for root in (old, new):
        (root / "scripts").mkdir(parents=True)
        (root / "config").mkdir()
        (root / "config" / "estate-store-registry.yaml").write_text("fake registry")
        (root / "scripts" / "hapax-estate-store-registry").write_text(
            "from pathlib import Path\nimport json\n"
            "print(json.dumps({'physical_root':str(Path(__file__).resolve().parents[1])}))\n"
        )
    alias = home / ".cache/hapax/source-activation/worktree"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(old, target_is_directory=True)
    for root in (old, new):
        python = root / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text(
            f"#!{sys.executable}\nimport os, sys\nfrom pathlib import Path\n"
            f"alias = Path({str(alias)!r})\nalias.unlink()\nalias.symlink_to({str(new)!r})\n"
            "assert sys.argv[1] == '-I'\n"
            f"os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])\n"
        )
        python.chmod(0o755)

    def runner(argv, **kwargs):  # noqa: ANN001, ANN202
        assert argv[0] == "ssh"  # The network boundary ends here.
        return subprocess.run(
            ["/bin/sh", "-c", argv[6]], env={**os.environ, "HOME": str(home)}, **kwargs
        )

    return old, new, alias, runner


@pytest.mark.parametrize("qualified", [True, False])
def test_peer_pins_physical_tree_before_alias_moves(
    registry, fake_peer_shell, qualified: bool
) -> None:
    old, new, alias, runner = fake_peer_shell
    result = run_peer_command(
        registry,
        host_id="appendix",
        command="sweep",
        runner=runner,
        peer_source_root=str(old) if qualified else None,
        qualified=qualified,
        check=False,
    )
    assert result.returncode == 0
    assert alias.resolve() == new
    assert json.loads(result.stdout)["physical_root"] == str(old)
    assert result.source_binding == {
        "kind": "physical" if qualified else "alias",
        "requested": str(old) if qualified else "$HOME/.cache/hapax/source-activation/worktree",
    }


def test_qualified_peer_rejects_symlink_on_peer(registry, fake_peer_shell) -> None:
    _old, _new, alias, runner = fake_peer_shell
    result = run_peer_command(
        registry,
        host_id="appendix",
        command="sweep",
        runner=runner,
        peer_source_root=str(alias),
        qualified=True,
        check=False,
    )
    assert result.failed
    assert "peer_source_root" in result.stderr and "remedy" in result.stderr


@pytest.mark.parametrize(
    "artifact", ["scripts/hapax-estate-store-registry", "config/estate-store-registry.yaml"]
)
def test_peer_rejects_redirected_release_artifacts(
    registry, fake_peer_shell, artifact: str
) -> None:
    old, new, _alias, runner = fake_peer_shell
    (old / artifact).unlink()
    (old / artifact).symlink_to(new / artifact)
    result = run_peer_command(
        registry,
        host_id="appendix",
        command="sweep",
        runner=runner,
        peer_source_root=str(old),
        qualified=True,
        check=False,
    )
    assert result.failed
    assert "release artifact" in result.stderr


def test_peer_timeout_retains_partial_output_without_inventing_returncode(registry) -> None:
    def runner(*_args, **_kwargs):  # noqa: ANN202
        raise subprocess.TimeoutExpired(
            "fake ssh", 1, output=b"partial summary\n", stderr=b"partial diagnostic\n"
        )

    result = run_peer_command(
        registry, host_id="appendix", command="sweep", runner=runner, check=False
    )
    assert result.failed and result.returncode is None and result.transport_error == "timeout"
    assert result.stdout == "partial summary\n"
    assert result.stderr == "partial diagnostic\n"


def test_peer_capture_preserves_crlf_verbatim(registry) -> None:
    def runner(_argv, **kwargs):  # noqa: ANN202
        return subprocess.run(
            [
                sys.executable,
                "-c",
                "import os; os.write(1, b'fake report\\r\\n'); os.write(2, b'fake diagnostic\\r\\n'); raise SystemExit(23)",
            ],
            **kwargs,
        )

    result = run_peer_command(
        registry, host_id="appendix", command="sweep", runner=runner, check=False
    )
    assert (result.stdout, result.stderr, result.returncode) == (
        "fake report\r\n",
        "fake diagnostic\r\n",
        23,
    )


@pytest.mark.parametrize("command", ["sweep", "export-canary"])
def test_peer_command_pins_release_interpreter_despite_uv_environment(
    registry, monkeypatch, command: str
) -> None:
    for name in (
        "UV_PROJECT_ENVIRONMENT",
        "UV_CONFIG_FILE",
        "UV_PYTHON",
        "UV_WORKING_DIRECTORY",
        "VIRTUAL_ENV",
        "PYTHONHOME",
        "PYTHONPATH",
    ):
        monkeypatch.setenv(name, "/untrusted/redirect")
    calls = []

    def runner(argv, **kwargs):  # noqa: ANN001, ANN202
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    run_peer_command(
        registry,
        host_id="appendix",
        command=command,
        runner=runner,
        peer_source_root="/retained/release",
        qualified=True,
    )
    argv, kwargs = calls[0]
    assert argv[:6] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12", "hapax-podium"]
    remote = argv[6]
    assert "uv" not in remote
    assert "estate_peer_root=/retained/release\n" in remote
    assert 'exec "$estate_peer_root/.venv/bin/python" -I ' in remote
    assert " --qualified" in remote
    assert "--observed-host-override" not in remote
    assert kwargs == {"capture_output": True, "text": False, "timeout": 180, "check": False}


@pytest.mark.parametrize("missing", [True, False], ids=["absent", "not-executable"])
def test_peer_refuses_unavailable_pinned_interpreter(
    registry, fake_peer_shell, missing: bool
) -> None:
    old, _new, alias, runner = fake_peer_shell
    python = old / ".venv/bin/python"
    if missing:
        python.unlink()
    else:
        python.chmod(0o644)
    result = run_peer_command(
        registry,
        host_id="appendix",
        command="sweep",
        runner=runner,
        peer_source_root=str(old),
        qualified=True,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert str(python) in result.stderr
    assert (
        "remedy: provision the verified release virtual environment before enabling"
        in result.stderr
    )
    assert alias.resolve() == old
