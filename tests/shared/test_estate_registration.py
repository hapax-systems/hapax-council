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


@pytest.mark.parametrize("binding", [None, "relative/release", "$HOME/release", "/a/../b", "/a//b"])
def test_qualified_peer_requires_safe_binding(binding: str | None) -> None:
    def no_ssh(*_args, **_kwargs):  # noqa: ANN202
        pytest.fail("unsafe binding reached SSH")

    with pytest.raises(RegistrationError, match="peer_source_root.*remedy"):
        run_peer_command(
            load_registry(),
            host_id="appendix",
            command="sweep",
            peer_source_root=binding,
            qualified=True,
            runner=no_ssh,
        )


def test_peer_failure_retains_both_streams_and_exact_returncode() -> None:
    stdout = '  {"report_path":"/fake/failed-report.json"}\npartial output\n'
    stderr = "  fake peer diagnostic\nsecond line\n"

    def runner(*_args, **_kwargs):  # noqa: ANN202
        return SimpleNamespace(returncode=23, stdout=stdout, stderr=stderr)

    result = run_peer_command(
        load_registry(),
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
        run_peer_command(load_registry(), host_id="appendix", command="sweep", runner=runner)
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
def test_peer_pins_physical_tree_before_alias_moves(fake_peer_shell, qualified: bool) -> None:
    old, new, alias, runner = fake_peer_shell
    result = run_peer_command(
        load_registry(),
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


def test_qualified_peer_rejects_symlink_on_peer(fake_peer_shell) -> None:
    _old, _new, alias, runner = fake_peer_shell
    result = run_peer_command(
        load_registry(),
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
def test_peer_rejects_redirected_release_artifacts(fake_peer_shell, artifact: str) -> None:
    old, new, _alias, runner = fake_peer_shell
    (old / artifact).unlink()
    (old / artifact).symlink_to(new / artifact)
    result = run_peer_command(
        load_registry(),
        host_id="appendix",
        command="sweep",
        runner=runner,
        peer_source_root=str(old),
        qualified=True,
        check=False,
    )
    assert result.failed
    assert "release artifact" in result.stderr


def test_peer_timeout_retains_partial_output_without_inventing_returncode() -> None:
    def runner(*_args, **_kwargs):  # noqa: ANN202
        raise subprocess.TimeoutExpired(
            "fake ssh", 1, output=b"partial summary\n", stderr=b"partial diagnostic\n"
        )

    result = run_peer_command(
        load_registry(), host_id="appendix", command="sweep", runner=runner, check=False
    )
    assert result.failed and result.returncode is None and result.transport_error == "timeout"
    assert result.stdout == "partial summary\n"
    assert result.stderr == "partial diagnostic\n"


def test_peer_capture_preserves_crlf_verbatim() -> None:
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
        load_registry(), host_id="appendix", command="sweep", runner=runner, check=False
    )
    assert (result.stdout, result.stderr, result.returncode) == (
        "fake report\r\n",
        "fake diagnostic\r\n",
        23,
    )


@pytest.mark.parametrize("command", ["sweep", "export-canary"])
def test_peer_command_pins_release_interpreter_despite_uv_environment(
    monkeypatch, command: str
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
        load_registry(),
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
    assert kwargs == {"capture_output": True, "text": False, "timeout": 180, "check": False}


@pytest.mark.parametrize("missing", [True, False], ids=["absent", "not-executable"])
def test_peer_refuses_unavailable_pinned_interpreter(fake_peer_shell, missing: bool) -> None:
    old, _new, alias, runner = fake_peer_shell
    python = old / ".venv/bin/python"
    if missing:
        python.unlink()
    else:
        python.chmod(0o644)
    result = run_peer_command(
        load_registry(),
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
