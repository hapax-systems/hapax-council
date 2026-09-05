from __future__ import annotations

import base64
import hashlib
import importlib.machinery
import json
import stat
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import yaml

from shared.estate_store_registry import (
    DEFAULT_REGISTRY_PATH,
    RegistryError,
    enumerate_stores,
    load_registry,
)


def test_registry_covers_every_declared_consumer_and_vendor_roots_are_flag_only() -> None:
    registry = load_registry()

    consumers = {consumer for store in registry.stores for consumer in store.consumers}
    assert consumers == {
        "assemble",
        "brief-dispatch",
        "census",
        "drift-sweep",
        "pillar-matcher",
        "task-intake",
    }
    vendor_ids = {store.id for store in registry.stores if store.store_class == "vendor-root"}
    assert vendor_ids == {
        "claude-code-project-stores",
        "claude-code-vendor-root",
        "codex-vendor-root",
        "gemini-vendor-root",
        "grok-vendor-root",
        "kimi-vendor-root",
        "opencode-vendor-root",
    }
    assert all(store.action == "flag-only" for store in registry.stores)


def test_registry_rejects_vendor_root_quarantine_even_if_general_policy_is_edited(
    tmp_path: Path,
) -> None:
    payload = yaml.safe_load(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    vendor = next(row for row in payload["stores"] if row["class"] == "vendor-root")
    vendor["action"] = "quarantine"
    mutated = tmp_path / "registry.yaml"
    mutated.write_text(yaml.safe_dump(payload), encoding="utf-8")

    with pytest.raises(RegistryError, match="non-reporting action|flag-only"):
        load_registry(mutated)


def test_grandfathered_rows_have_evidence_and_no_blessing_claim() -> None:
    registry = load_registry()

    grandfathered = [store for store in registry.stores if store.lifecycle == "grandfathered"]
    assert grandfathered
    assert all(store.discovery_evidence for store in grandfathered)
    assert all(not hasattr(store, "operator_blessing") for store in grandfathered)


def test_unknown_host_refuses_instead_of_assuming_a_peer() -> None:
    registry = load_registry()

    with pytest.raises(RegistryError, match="add its alias and peer binding"):
        registry.host_id("unregistered-host")


def test_consumer_enumeration_returns_only_declared_rows_with_resolved_paths(
    tmp_path: Path,
) -> None:
    registry = load_registry()

    stores = enumerate_stores(
        registry, consumer="assemble", host="appendix", home=tmp_path / "operator"
    )

    assert stores
    assert all("assemble" in store.consumers for store in stores)
    assert all("{home}" not in store.locator and "{vault}" not in store.locator for store in stores)
    assert all(store.id != "podium-minio" for store in stores)


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-estate-store-registry"
NATIVE_VARIABLES = (
    "INVOCATION_ID",
    "SYSTEMD_EXEC_PID",
    "TRIGGER_UNIT",
    "TRIGGER_PATH",
    "TRIGGER_TIMER_REALTIME_USEC",
    "TRIGGER_TIMER_MONOTONIC_USEC",
)


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # noqa: ANN201
    module = ModuleType("estate_registry_cli")
    module.__file__ = str(SCRIPT)
    importlib.machinery.SourceFileLoader(module.__name__, str(SCRIPT)).exec_module(module)
    for name in (*NATIVE_VARIABLES, "HAPAX_ESTATE_PEER_SOURCE_ROOT"):
        monkeypatch.delenv(name, raising=False)
    registry = replace(
        load_registry(),
        scan_roots=(
            {"id": "fake-root", "kind": "directory", "path": str(tmp_path / "scan"), "depth": 1},
        ),
    )
    (tmp_path / "scan").mkdir()
    monkeypatch.setattr(module, "load_registry", lambda _path: registry)
    monkeypatch.setattr(module, "_boot_id", lambda: "local-boot", raising=False)
    return module


def _fake_peer():  # noqa: ANN202
    report = {
        "schema": "hapax.estate-drift-report/v1",
        "host": "podium",
        "stage": "report-only",
        "mutation_actions": [],
        "findings": [],
        "finding_count": 0,
    }
    raw = json.dumps(report).encode()
    summary = {
        "report_path": "/fake/reports/peer.json",
        "report_sha256": hashlib.sha256(raw).hexdigest(),
        "report_base64": base64.b64encode(raw).decode(),
        "host": "podium",
        "boot_id": "peer-boot",
        "source": {"physical_root": "/retained/peer", "git_head": "a" * 40},
        "scan_error_count": 0,
    }
    evidence = {
        "schema": "hapax.estate-execution/v1",
        "command": "sweep",
        "host": "podium",
        "boot_id": "peer-boot",
        "source": dict(summary["source"]),
        "status": "unqualified",
        "returncode": 0,
        "errors": [],
        "started_at": "2026-09-05T01:00:00Z",
        "finished_at": "2026-09-05T01:00:01Z",
        "report": {
            "path": summary["report_path"],
            "sha256": summary["report_sha256"],
            "host": "podium",
        },
    }
    return summary, evidence


def _install_peer(cli, monkeypatch, summary, evidence, *, returncode=0):  # noqa: ANN001, ANN202
    from shared.estate_registration import run_peer_command

    streams = (json.dumps(summary) + "\n", "fake peer diagnostic\n" + json.dumps(evidence) + "\n")
    calls = []

    def runner(_argv, **_kwargs):  # noqa: ANN202
        return SimpleNamespace(returncode=returncode, stdout=streams[0], stderr=streams[1])

    def peer(registry, **kwargs):  # noqa: ANN001, ANN202
        calls.append(kwargs)
        return run_peer_command(registry, runner=runner, **kwargs)

    monkeypatch.setattr(cli, "run_peer_command", peer)
    return calls, streams


def _evidence(stderr: str) -> dict:
    rows = [json.loads(line) for line in stderr.splitlines() if line.startswith("{")]
    return [row for row in rows if row.get("schema") == "hapax.estate-execution/v1"][-1]


def test_cli_records_absent_native_metadata_and_local_report_digest(cli, tmp_path, capsys) -> None:
    assert cli.main(["sweep", "--host", "appendix", "--home", str(tmp_path), "--json"]) == 0
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    evidence = _evidence(captured.err)
    assert evidence["native"] == dict.fromkeys(NATIVE_VARIABLES, "absent")
    assert evidence["scheduled"] == "absent"
    assert evidence["status"] == "unqualified"
    assert evidence["source"]["physical_root"] == str(SCRIPT.resolve().parents[1])
    assert evidence["source"]["git_head"] != "absent"
    assert evidence["boot_id"] == "local-boot"
    assert datetime.fromisoformat(evidence["started_at"]) <= datetime.fromisoformat(
        evidence["finished_at"]
    )
    raw = Path(summary["report_path"]).read_bytes()
    assert evidence["report"] == {
        "path": summary["report_path"],
        "sha256": hashlib.sha256(raw).hexdigest(),
        "host": "appendix",
    }
    assert set(json.loads(raw)) == {
        "schema",
        "stage",
        "host",
        "swept_at",
        "candidate_count",
        "finding_count",
        "findings",
        "root_observations",
        "flagged_canary_ids",
        "missed_canary_ids",
        "detector_incident_path",
        "mutation_actions",
    }


def test_cli_peer_binding_and_observed_timer_evidence(cli, monkeypatch, capsys) -> None:
    summary, peer_evidence = _fake_peer()
    calls, _streams = _install_peer(cli, monkeypatch, summary, peer_evidence)
    monkeypatch.setenv("HAPAX_ESTATE_PEER_SOURCE_ROOT", "/retained/peer")
    native = {
        "INVOCATION_ID": "b" * 32,
        "TRIGGER_UNIT": "hapax-estate-drift-sweep.timer",
        "TRIGGER_TIMER_REALTIME_USEC": "1788570000000000",
    }
    for name, value in native.items():
        monkeypatch.setenv(name, value)
    assert cli.main(["sweep-peer", "--host", "appendix", "--json"]) == 0
    captured = capsys.readouterr()
    evidence = _evidence(captured.err)
    assert evidence["host"] == "appendix"
    assert evidence["native"] == {**dict.fromkeys(NATIVE_VARIABLES, "absent"), **native}
    assert evidence["scheduled"] is True
    assert evidence["status"] == "ok"
    assert calls[0]["peer_source_root"] == "/retained/peer" and calls[0]["qualified"]
    assert evidence["peer"]["report_path"] == summary["report_path"]
    assert evidence["peer"]["report_sha256"] == summary["report_sha256"]
    assert evidence["peer"]["computed_sha256"] == summary["report_sha256"]
    assert evidence["peer"]["host"] == "podium"
    assert evidence["peer"]["boot_id"] == "peer-boot"
    assert evidence["peer"]["source"] == summary["source"]
    assert evidence["peer"]["status"] == "ok"


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("digest", "peer_report_digest_mismatch"),
        ("host", "peer_host_mismatch"),
        ("boot", "peer_boot_id_mismatch"),
        ("source", "peer_source_mismatch"),
        ("path", "peer_report_path_mismatch"),
        ("missing_boot", "peer_boot_id_absent"),
        ("missing_digest", "peer_report_digest_absent"),
    ],
)
def test_cli_rejects_mismatched_peer_binding(cli, monkeypatch, capsys, mutation, reason) -> None:
    summary, peer_evidence = _fake_peer()
    if mutation == "digest":
        summary["report_base64"] = base64.b64encode(b'{"host":"podium"}').decode()
    elif mutation == "host":
        peer_evidence["host"] = "appendix"
    elif mutation == "boot":
        peer_evidence["boot_id"] = "different-boot"
    elif mutation == "source":
        summary["source"]["physical_root"] = "/floating/current"
    elif mutation == "path":
        peer_evidence["report"]["path"] = "/fake/other.json"
    elif mutation == "missing_boot":
        summary.pop("boot_id")
    else:
        summary.pop("report_sha256")
    _install_peer(cli, monkeypatch, summary, peer_evidence)
    assert (
        cli.main(["sweep-peer", "--host", "appendix", "--peer-source-root", "/retained/peer"]) != 0
    )
    evidence = _evidence(capsys.readouterr().err)
    assert evidence["status"] == "failed"
    assert reason in evidence["errors"]
    assert evidence["peer"]["status"] == "failed"


def test_cli_preserves_failed_peer_summary_and_diagnostics(cli, monkeypatch, capsys) -> None:
    summary, peer_evidence = _fake_peer()
    peer_evidence.update(status="failed", returncode=23, errors=["scan_errors"])
    _calls, streams = _install_peer(cli, monkeypatch, summary, peer_evidence, returncode=23)
    assert cli.main(["sweep-peer", "--host", "appendix", "--json"]) == 23
    captured = capsys.readouterr()
    assert captured.out == streams[0]
    assert captured.err.startswith(streams[1])
    evidence = _evidence(captured.err)
    assert evidence["status"] == "failed"
    assert evidence["peer"]["returncode"] == 23
    assert evidence["peer"]["report_path"] == summary["report_path"]
    assert "peer_exit_nonzero" in evidence["errors"]


def test_registry_script_keeps_executable_mode_and_python_shebang() -> None:
    assert SCRIPT.read_bytes().splitlines()[0] == b"#!/usr/bin/env python3"
    assert stat.S_IMODE(SCRIPT.stat().st_mode) == 0o755


@pytest.mark.parametrize(
    "native",
    [
        {},
        {"INVOCATION_ID": "c" * 32},
        {"TRIGGER_UNIT": "fake.path", "TRIGGER_PATH": "/fake"},
        {"TRIGGER_UNIT": "fake.timer"},
        {"TRIGGER_TIMER_REALTIME_USEC": "1788570000000000"},
        {"TRIGGER_UNIT": "fake.timer", "TRIGGER_TIMER_REALTIME_USEC": "invalid"},
    ],
)
def test_cli_never_infers_schedule_from_intent_or_incomplete_metadata(
    cli, monkeypatch, tmp_path, capsys, native
) -> None:
    monkeypatch.setenv("HAPAX_ESTATE_SCHEDULED", "true")
    for name, value in native.items():
        monkeypatch.setenv(name, value)
    assert cli.main(["sweep", "--host", "appendix", "--home", str(tmp_path), "--qualified"]) == 0
    evidence = _evidence(capsys.readouterr().err)
    assert evidence["scheduled"] == "absent" and evidence["status"] == "unqualified"


@pytest.mark.parametrize("service_marker", [*NATIVE_VARIABLES, "explicit"])
def test_cli_service_requires_peer_binding(cli, monkeypatch, capsys, service_marker) -> None:
    summary, peer_evidence = _fake_peer()
    _install_peer(cli, monkeypatch, summary, peer_evidence)
    options = ["--qualified"] if service_marker == "explicit" else []
    if service_marker != "explicit":
        monkeypatch.setenv(service_marker, "observed")
    assert cli.main(["sweep-peer", "--host", "appendix", *options]) == 2
    evidence = _evidence(capsys.readouterr().err)
    assert evidence["status"] == "failed"
    assert any("peer_source_root" in reason and "remedy" in reason for reason in evidence["errors"])


def test_cli_preserves_failed_local_report(cli, monkeypatch, tmp_path, capsys) -> None:
    registry = cli.load_registry(None)
    monkeypatch.setattr(
        cli,
        "load_registry",
        lambda _path: replace(
            registry,
            scan_roots=(
                {
                    "id": "missing",
                    "kind": "directory",
                    "path": str(tmp_path / "missing"),
                    "depth": 1,
                },
            ),
        ),
    )
    assert (
        cli.main(
            ["sweep", "--host", "appendix", "--home", str(tmp_path), "--json", "--include-report"]
        )
        == 2
    )
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    raw = Path(summary["report_path"]).read_bytes()
    assert base64.b64decode(summary["report_base64"]) == raw
    report = json.loads(raw)
    assert report["findings"][0]["kind"] == "scan-error"
    evidence = _evidence(captured.err)
    assert evidence["status"] == "failed" and "scan_errors" in evidence["errors"]
    assert evidence["report"]["sha256"] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("field", ["host", "stage", "mutation_actions", "findings"])
def test_cli_binds_report_payload_even_when_envelope_agrees(
    cli, monkeypatch, capsys, field
) -> None:
    summary, peer_evidence = _fake_peer()
    report = json.loads(base64.b64decode(summary["report_base64"]))
    report[field] = {
        "host": "appendix",
        "stage": "other",
        "mutation_actions": ["delete"],
        "findings": None,
    }[field]
    raw = json.dumps(report).encode()
    summary["report_base64"] = base64.b64encode(raw).decode()
    summary["report_sha256"] = peer_evidence["report"]["sha256"] = hashlib.sha256(raw).hexdigest()
    _install_peer(cli, monkeypatch, summary, peer_evidence)
    assert cli.main(["sweep-peer", "--host", "appendix"]) == 2
    evidence = _evidence(capsys.readouterr().err)
    assert evidence["status"] == "failed"
    assert evidence["peer"]["computed_sha256"] == summary["report_sha256"]


def test_cli_refuses_source_or_registry_redirection(cli, tmp_path, capsys) -> None:
    for options in (
        ["--expected-source-root", "/wrong/release"],
        [
            "--expected-source-root",
            str(SCRIPT.resolve().parents[1]),
            "--registry",
            str(tmp_path / "elsewhere.yaml"),
        ],
    ):
        assert cli.main(["sweep", "--host", "appendix", "--home", str(tmp_path), *options]) == 2
        assert (
            "physical source or registry binding mismatch"
            in _evidence(capsys.readouterr().err)["errors"][0]
        )


def test_cli_marks_local_source_change_failed(cli, monkeypatch, tmp_path, capsys) -> None:
    identities = iter(
        [
            {"physical_root": "/retained/local", "git_head": "a" * 40},
            {"physical_root": "/retained/local", "git_head": "b" * 40},
        ]
    )
    monkeypatch.setattr(cli, "_source_identity", lambda: next(identities))
    assert cli.main(["sweep", "--host", "appendix", "--home", str(tmp_path), "--json"]) == 2
    captured = capsys.readouterr()
    assert Path(json.loads(captured.out)["report_path"]).exists()
    evidence = _evidence(captured.err)
    assert evidence["status"] == "failed"
    assert "local_source_changed_during_execution" in evidence["errors"]


def test_cli_local_script_alias_promotion_preserves_physical_identity(
    cli, monkeypatch, tmp_path, capsys
) -> None:
    alias = tmp_path / "current-script"
    alias.symlink_to(SCRIPT)
    loaded = ModuleType("estate_cli_via_alias")
    loaded.__file__ = str(alias)
    importlib.machinery.SourceFileLoader(loaded.__name__, str(alias)).exec_module(loaded)
    monkeypatch.setattr(loaded, "load_registry", cli.load_registry)
    monkeypatch.setattr(loaded, "_boot_id", cli._boot_id)
    original = loaded.sweep

    def promote(*args, **kwargs):  # noqa: ANN202
        alias.unlink()
        alias.symlink_to(tmp_path / "different-script")
        return original(*args, **kwargs)

    monkeypatch.setattr(loaded, "sweep", promote)
    assert loaded.main(["sweep", "--host", "appendix", "--home", str(tmp_path)]) == 0
    evidence = _evidence(capsys.readouterr().err)
    assert evidence["source"]["physical_root"] == str(SCRIPT.resolve().parents[1])
    assert evidence["source"]["git_head"] != "absent"


def test_cli_git_unavailable_is_explicitly_absent(cli, monkeypatch) -> None:
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=128, stdout="", stderr="fake git unavailable"
        ),
    )
    assert cli._source_identity() == {
        "physical_root": str(SCRIPT.resolve().parents[1]),
        "git_head": "absent",
    }


def test_cli_zero_exit_cannot_override_failed_peer_evidence(cli, monkeypatch, capsys) -> None:
    summary, peer_evidence = _fake_peer()
    peer_evidence.update(status="failed", returncode=23, errors=["scan_errors"])
    _install_peer(cli, monkeypatch, summary, peer_evidence, returncode=0)
    assert cli.main(["sweep-peer", "--host", "appendix"]) == 2
    evidence = _evidence(capsys.readouterr().err)
    assert evidence["status"] == "failed" and "peer_execution_failed" in evidence["errors"]


def test_cli_missing_peer_completion_is_failed_evidence(cli, monkeypatch, capsys) -> None:
    summary, _peer_evidence = _fake_peer()
    _install_peer(cli, monkeypatch, summary, {})
    assert cli.main(["sweep-peer", "--host", "appendix"]) == 2
    evidence = _evidence(capsys.readouterr().err)
    assert "peer_execution_evidence_absent_or_ambiguous" in evidence["errors"]


def test_cli_absent_local_boot_is_failed_evidence(cli, monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(cli, "_boot_id", lambda: "absent")
    assert cli.main(["sweep", "--host", "appendix", "--home", str(tmp_path)]) == 2
    evidence = _evidence(capsys.readouterr().err)
    assert evidence["boot_id"] == "absent" and evidence["status"] == "failed"
    assert any("local_boot_id_absent" in reason for reason in evidence["errors"])


def test_cli_frames_evidence_after_unterminated_peer_stderr(cli, monkeypatch, capsys) -> None:
    from shared.estate_registration import PeerCommandResult

    result = PeerCommandResult(
        '{"report_path":"/fake/failed-report.json"}\n',
        "fake failure without trailing newline",
        23,
        {"kind": "physical", "requested": "/retained/peer"},
    )
    monkeypatch.setattr(cli, "run_peer_command", lambda *_args, **_kwargs: result)
    assert cli.main(["sweep-peer", "--host", "appendix"]) == 23
    captured = capsys.readouterr()
    assert captured.out == result.stdout and captured.err.startswith(result.stderr)
    assert _evidence(captured.err)["status"] == "failed"


@pytest.mark.parametrize("filesystem_failed", [False, True], ids=["readable", "denied"])
@pytest.mark.parametrize("outcome", ["two", "zero", "nonzero", "missing", "timeout", "invalid"])
def test_cli_docker_root_keeps_both_observations(
    cli, monkeypatch, tmp_path, capsys, outcome, filesystem_failed
) -> None:
    import os

    from shared import estate_registration

    root = tmp_path / "volumes"
    root.mkdir()
    registry = load_registry()
    docker_row = next(row for row in registry.scan_roots if row["id"] == "docker-volumes")
    registry = replace(registry, scan_roots=({**docker_row, "path": str(root)},))
    monkeypatch.setattr(cli, "load_registry", lambda _path: registry)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    # PATH contains only the fixture: a missing docker cannot reach a real daemon.
    monkeypatch.setenv("PATH", str(fake_bin))
    stdout = {
        "two": "alpha\r\nbeta\r\n",
        "nonzero": "partial\r\n",
        "timeout": "partial\r\n",
        "invalid": "../escape\r\n",
    }.get(outcome, "")
    stderr = "fake docker diagnostic\r\n" if outcome != "missing" else ""
    if outcome != "missing":
        docker = fake_bin / "docker"
        docker.write_text(
            f"#!{sys.executable}\nimport os, sys, time\n"
            "assert sys.argv[1:] == ['volume', 'ls', '--format', '{{.Name}}']\n"
            f"os.write(1, {stdout.encode()!r})\nos.write(2, {stderr.encode()!r})\n"
            + ("time.sleep(30)\n" if outcome == "timeout" else "")
            + f"sys.exit({23 if outcome == 'nonzero' else 0})\n"
        )
        docker.chmod(0o755)
    monkeypatch.setattr(estate_registration, "DOCKER_TIMEOUT_SECONDS", 0.5, raising=False)
    scandir = os.scandir

    def scan(path):  # noqa: ANN001, ANN202
        if filesystem_failed and Path(path) == root:
            raise PermissionError("fake filesystem permission denied")
        return scandir(path)

    monkeypatch.setattr(os, "scandir", scan)
    failed_cli = outcome in {"nonzero", "missing", "timeout", "invalid"}
    failed = filesystem_failed or failed_cli
    code = cli.main(
        ["sweep", "--host", "appendix", "--home", str(tmp_path), "--json", "--include-report"]
    )
    captured = capsys.readouterr()
    assert code == (2 if failed else 0)
    summary = json.loads(captured.out)
    report = json.loads(Path(summary["report_path"]).read_bytes())
    evidence = _evidence(captured.err)
    observations = report["root_observations"]
    assert evidence["root_observations"] == observations
    assert len(observations) == 1
    observed = observations[0]
    assert observed["scan_root"] == "docker-volumes" and observed["path"] == str(root)
    assert observed["kind"] == "docker-volumes"
    assert observed["status"] == ("read-failed" if failed else "read-ok")
    assert observed["candidate_count"] == (2 if outcome == "two" else 0)
    filesystem, command = observed["observations"]
    assert filesystem["method"] == "filesystem"
    assert filesystem["status"] == ("read-failed" if filesystem_failed else "read-ok")
    assert filesystem["candidate_count"] == 0
    assert bool(filesystem["errors"]) == filesystem_failed
    if filesystem_failed:
        assert "fake filesystem permission denied" in filesystem["errors"][0]["error"]
    assert command["method"] == "docker-volume-ls"
    assert command["command"] == ["docker", "volume", "ls", "--format", "{{.Name}}"]
    assert command["status"] == ("read-failed" if failed_cli else "read-ok")
    assert command["stdout"] == stdout and command["stderr"] == stderr
    assert command["returncode"] == (
        "absent" if outcome in {"missing", "timeout"} else 23 if outcome == "nonzero" else 0
    )
    assert command["transport_error"] == (
        {"missing": "FileNotFoundError", "timeout": "timeout"}.get(outcome, "absent")
    )
    assert command["timeout_seconds"] == 0.5
    assert command["candidate_count"] == (2 if outcome == "two" else 0)
    assert bool(command["errors"]) == failed_cli
    if failed_cli:
        assert "docker-volume-ls" in command["errors"][0]["error"]
        assert "remedy" in command["errors"][0]["error"]
    assert summary["scan_error_count"] == int(filesystem_failed) + int(failed_cli)
    assert evidence["status"] == ("failed" if failed else "unqualified")
    assert report["candidate_count"] == (2 if outcome == "two" else 0)
    if outcome == "two":
        assert {
            row["path"] for row in report["findings"] if row["kind"] == "unregistered-store"
        } == {str(root / "alpha"), str(root / "beta")}
    assert report["mutation_actions"] == []
    assert base64.b64decode(summary["report_base64"]) == Path(summary["report_path"]).read_bytes()
