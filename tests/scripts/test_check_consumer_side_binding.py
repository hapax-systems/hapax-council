"""Canaries for whole-tree consumer-side producer binding analysis."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check-producer-consumers.py"
FRAME_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "consumer-side-frame-elements.json"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_consumer_side_binding", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(repo: Path, relative: str, source: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _unwritten_repo(repo: Path) -> None:
    _write(
        repo,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "REPO_ROOT = Path(__file__).resolve().parents[1]\n"
        "ORPHAN = REPO_ROOT / 'config' / 'orphan.json'\n"
        "def load_orphan():\n"
        "    return ORPHAN.read_text(encoding='utf-8')\n",
    )


def test_consumer_reads_unwritten_artifact(gate, tmp_path: Path) -> None:
    _unwritten_repo(tmp_path)
    report = gate.analyse_consumer_side(tmp_path, [])
    matches = [
        item
        for item in report.findings
        if item.kind == "consumer-reads-unwritten-artifact"
        and item.reader.pattern == "config/orphan.json"
    ]
    assert len(matches) == 1


def test_consumer_producer_path_mismatch(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/writer.py",
        "from pathlib import Path\n"
        "OUTPUT = Path.home() / '.cache' / 'alpha'\n"
        "def write_widget_binding(key):\n"
        "    path = OUTPUT / f'widget-binding-{key}.json'\n"
        "    path.write_text('{}', encoding='utf-8')\n",
    )
    _write(
        tmp_path,
        "shared/reader.py",
        "from pathlib import Path\n"
        "from shared.writer import write_widget_binding\n"
        "INPUT = Path.home() / '.cache' / 'beta'\n"
        "def load_widget_binding(key):\n"
        "    path = INPUT / f'widget-binding-{key}.json'\n"
        "    return path.read_text(encoding='utf-8')\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    mismatch = [
        item
        for item in report.findings
        if item.kind == "consumer-producer-path-mismatch" and item.reader.family == "widget_binding"
    ]
    assert len(mismatch) == 1
    assert mismatch[0].reader.pattern == "~/.cache/beta/widget-binding-*.json"
    assert mismatch[0].writers[0].pattern == "~/.cache/alpha/widget-binding-*.json"


def test_committed_read_pattern_is_counted_as_excluded(
    gate, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "REPO_ROOT = Path(__file__).resolve().parents[1]\n"
        "def load_config():\n"
        "    return (REPO_ROOT / 'config' / 'tracked.json').read_text()\n",
    )
    monkeypatch.setattr(
        gate, "_git_tracked_paths", lambda _root: frozenset({"config/tracked.json"})
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert report.exclusions["committed-in-repository"] == 1
    assert not report.findings


def test_system_read_pattern_is_counted_as_excluded(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def load_meminfo():\n"
        "    return Path('/proc/meminfo').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert report.exclusions["system-path"] == 1
    assert not report.findings


def test_bare_glob_is_counted_as_corpus_walk(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\ndef walk_corpus():\n    return list(Path('*').rglob('*.md'))\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert report.exclusions["corpus-walk"] == 1
    assert not report.findings


def test_unwritten_finding_deduplicates_reader_sites(gate, tmp_path: Path) -> None:
    _unwritten_repo(tmp_path)
    for index in range(3):
        _write(
            tmp_path,
            f"agents/other_consumer_{index}.py",
            "from pathlib import Path\n"
            "REPO_ROOT = Path(__file__).resolve().parents[1]\n"
            f"def read_orphan_{index}():\n"
            "    return (REPO_ROOT / 'config' / 'orphan.json').read_text()\n",
        )
    report = gate.analyse_consumer_side(tmp_path, [])
    findings = [
        finding
        for finding in report.findings
        if finding.kind == "consumer-reads-unwritten-artifact"
        and finding.reader.pattern == "config/orphan.json"
    ]
    assert len(findings) == 1
    assert findings[0].reader_count == 4
    assert len(findings[0].readers) == 3


def test_non_python_producer_downgrades_cache_finding(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "STATUS = Path.home() / '.cache' / 'hapax' / 'service' / 'status.json'\n"
        "def load_status():\n"
        "    return STATUS.read_text()\n",
    )
    _write(tmp_path, "scripts/producer.sh", "#!/bin/sh\nprintf status.json\n")
    report = gate.analyse_consumer_side(tmp_path, [])
    matches = [
        finding
        for finding in report.findings
        if finding.reader.pattern == "~/.cache/hapax/service/status.json"
    ]
    assert [finding.kind for finding in matches] == [
        "consumer-reads-artifact-with-non-python-producer"
    ]
    assert "scripts/producer.sh" in matches[0].detail


def test_pattern_matching_normalises_home_and_separators(gate) -> None:
    assert gate._patterns_match(r"$HOME\cache\wanted.json", "~/cache/wanted.json")


def test_glob_reader_rejects_same_directory_wrong_extension_writer(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def load_cache():\n"
        "    return list(Path('cache').glob('*.json'))\n",
    )
    _write(
        tmp_path,
        "shared/writer.py",
        "from pathlib import Path\n"
        "def write_cache():\n"
        "    Path('cache/unrelated.txt').write_text('unrelated')\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    matches = [item for item in report.findings if item.reader.pattern == "cache/*.json"]
    assert [item.kind for item in matches] == ["consumer-reads-unwritten-artifact"]


def test_fixed_reader_rejects_same_directory_incompatible_writer_glob(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def load_cache():\n"
        "    return Path('cache/wanted.json').read_text()\n",
    )
    _write(
        tmp_path,
        "shared/writer.py",
        "from pathlib import Path\n"
        "def write_cache(name):\n"
        "    (Path('cache') / f'{name}.txt').write_text('unrelated')\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    matches = [item for item in report.findings if item.reader.pattern == "cache/wanted.json"]
    assert [item.kind for item in matches] == ["consumer-reads-unwritten-artifact"]


def test_fixed_reader_rejects_same_directory_different_fixed_basename(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def load_cache():\n"
        "    return Path('cache/wanted.json').read_text()\n",
    )
    _write(
        tmp_path,
        "shared/writer.py",
        "from pathlib import Path\n"
        "def write_cache():\n"
        "    Path('cache/other.json').write_text('unrelated')\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    matches = [item for item in report.findings if item.reader.pattern == "cache/wanted.json"]
    assert [item.kind for item in matches] == ["consumer-reads-unwritten-artifact"]


def test_dynamic_root_read_with_only_a_test_writer_stays_unwritten(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "def load_metadata(root):\n"
        "    return (root / 'nested' / 'wanted.metadata.json').read_text()\n",
    )
    _write(
        tmp_path,
        "tests/writer.py",
        "from pathlib import Path\n"
        "def write_metadata():\n"
        "    Path('elsewhere/wanted.metadata.json').write_text('{}')\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    matches = [
        finding
        for finding in report.findings
        if finding.reader.pattern == "*/nested/wanted.metadata.json"
    ]
    assert [finding.kind for finding in matches] == ["consumer-reads-unwritten-artifact"]
    assert not matches[0].writers


def test_dynamic_root_read_with_live_same_basename_writer_is_downgraded(
    gate, tmp_path: Path
) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "def load_metadata(root):\n"
        "    return (root / 'nested' / 'wanted.metadata.json').read_text()\n",
    )
    _write(
        tmp_path,
        "shared/writer.py",
        "from pathlib import Path\n"
        "def write_metadata():\n"
        "    Path('elsewhere/wanted.metadata.json').write_text('{}')\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    matches = [
        finding
        for finding in report.findings
        if finding.reader.pattern == "*/nested/wanted.metadata.json"
    ]
    assert [finding.kind for finding in matches] == ["consumer-reads-artifact-under-dynamic-root"]
    assert matches[0].writers[0].pattern == "elsewhere/wanted.metadata.json"


def test_dynamic_root_reader_rejects_wildcard_basename_writer(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "def load_metadata(root, name):\n"
        "    return (root / 'nested' / f'{name}.metadata.json').read_text()\n",
    )
    _write(
        tmp_path,
        "tests/writer.py",
        "def write_metadata(root, name):\n"
        "    (root / 'elsewhere' / f'{name}.metadata.json').write_text('{}')\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    matches = [
        finding
        for finding in report.findings
        if finding.reader.pattern == "*/nested/*.metadata.json"
    ]
    assert [finding.kind for finding in matches] == ["consumer-reads-unwritten-artifact"]


def test_dynamic_root_read_without_same_basename_writer_stays_unwritten(
    gate, tmp_path: Path
) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "def load_metadata(root, name):\n"
        "    return (root / 'nested' / f'{name}.metadata.json').read_text()\n",
    )
    _write(
        tmp_path,
        "tests/writer.py",
        "from pathlib import Path\n"
        "def write_metadata():\n"
        "    Path('nested/unrelated.txt').write_text('unrelated')\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    matches = [
        finding
        for finding in report.findings
        if finding.reader.pattern == "*/nested/*.metadata.json"
    ]
    assert [finding.kind for finding in matches] == ["consumer-reads-unwritten-artifact"]
    assert (
        matches[0].detail == "searched=python-writers, non-python-mentions, docs, config, systemd"
    )


def test_runbook_only_mention_is_documented_elsewhere(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "STATUS = Path('/dev/shm/hapax-external/status.json')\n"
        "def load_status():\n"
        "    return STATUS.read_text()\n",
    )
    _write(
        tmp_path,
        "docs/runbooks/external-status.md",
        "The remote sensor publishes `/dev/shm/hapax-external/status.json`.\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    matches = [
        finding
        for finding in report.findings
        if finding.reader.pattern == "/dev/shm/hapax-external/status.json"
    ]
    assert [finding.kind for finding in matches] == ["consumer-reads-artifact-documented-elsewhere"]
    assert "docs/runbooks/external-status.md" in matches[0].detail


def test_undocumented_shared_memory_read_stays_unwritten(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "STATUS = Path('/dev/shm/hapax-external/status.json')\n"
        "def load_status():\n"
        "    return STATUS.read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    matches = [
        finding
        for finding in report.findings
        if finding.reader.pattern == "/dev/shm/hapax-external/status.json"
    ]
    assert [finding.kind for finding in matches] == ["consumer-reads-unwritten-artifact"]
    assert (
        matches[0].detail == "searched=python-writers, non-python-mentions, docs, config, systemd"
    )


def test_pairing_requires_specific_directory_and_stem_identity(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/reader.py",
        "from pathlib import Path\n"
        "INPUT = Path.home() / '.cache' / 'audio-processor' / 'state.json'\n"
        "def load_state():\n"
        "    return INPUT.read_text()\n",
    )
    _write(
        tmp_path,
        "shared/unrelated_writer.py",
        "from pathlib import Path\n"
        "OUTPUT = Path.home() / '.cache' / 'gdrive-sync' / 'state.json'\n"
        "def save_state():\n"
        "    OUTPUT.write_text('{}')\n",
    )
    unrelated = gate.analyse_consumer_side(tmp_path, [])
    assert not any(
        finding.kind == "consumer-producer-path-mismatch" for finding in unrelated.findings
    )

    _write(
        tmp_path,
        "shared/specific_writer.py",
        "from pathlib import Path\n"
        "OUTPUT = Path('/run/user/1000/audio-processor/state.json')\n"
        "def save_state():\n"
        "    OUTPUT.write_text('{}')\n",
    )
    specific = gate.analyse_consumer_side(tmp_path, [])
    mismatch = [
        finding
        for finding in specific.findings
        if finding.kind == "consumer-producer-path-mismatch"
    ]
    assert len(mismatch) == 1
    assert mismatch[0].writers[0].path == Path("shared/specific_writer.py")


def test_consumer_side_allowlist_is_a_reasoned_exit(gate, tmp_path: Path) -> None:
    _unwritten_repo(tmp_path)
    allowlist_path = tmp_path / "scripts" / "producer-consumer-allowlist.json"
    allowlist_path.parent.mkdir(parents=True)
    allowlist_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "kind": "consumer_side",
                        "pattern": "consumer-reads-unwritten-artifact:config/orphan.json",
                        "reason": "fixture is consumed outside the synthetic repository",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    report = gate.analyse_consumer_side(tmp_path, gate.load_allowlist(allowlist_path))
    assert not report.findings
    assert len(report.allowlisted) == 1


def test_unresolvable_paths_are_counted(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/dynamic.py",
        "def load_dynamic(path):\n    return path.read_text(encoding='utf-8')\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert report.unresolvable >= 1


def test_nested_scope_assignment_does_not_resolve_outer_read(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def load_artifact():\n"
        "    def configure_inner_scope():\n"
        "        artifact = Path('artifacts/inner-only.json')\n"
        "        return artifact\n"
        "    return artifact.read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert report.unresolvable == 1
    assert not any(
        finding.reader.pattern == "artifacts/inner-only.json" for finding in report.findings
    )


def test_same_scope_assignment_resolves_read_as_unwritten(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def load_artifact():\n"
        "    artifact = Path('artifacts/same-scope.json')\n"
        "    return artifact.read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    matches = [
        finding
        for finding in report.findings
        if finding.reader.pattern == "artifacts/same-scope.json"
    ]
    assert report.unresolvable == 0
    assert [finding.kind for finding in matches] == ["consumer-reads-unwritten-artifact"]


def test_nested_package_module_import_pairs_reader_with_writer(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pkg/sub/mod.py",
        "from pathlib import Path\n"
        "ARTIFACT = Path('artifacts/package-state.json')\n"
        "def write_package_state():\n"
        "    ARTIFACT.write_text('{}')\n",
    )
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "from pkg.sub.mod import write_package_state\n"
        "ARTIFACT = Path('artifacts/package-state.json')\n"
        "def load_package_state():\n"
        "    return ARTIFACT.read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert gate._module_name(Path("pkg/sub/mod.py")) == "pkg.sub.mod"
    assert any(
        pair.reader.path == Path("shared/consumer.py")
        and pair.writer.path == Path("pkg/sub/mod.py")
        for pair in report.pairs
    )


def test_package_init_writer_is_named_and_paired_as_package(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pkg/__init__.py",
        "from pathlib import Path\n"
        "ARTIFACT = Path('artifacts/package-init-state.json')\n"
        "def write_package_init_state():\n"
        "    ARTIFACT.write_text('{}')\n",
    )
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "from pkg import write_package_init_state\n"
        "ARTIFACT = Path('artifacts/package-init-state.json')\n"
        "def load_package_init_state():\n"
        "    return ARTIFACT.read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert gate._module_name(Path("pkg/__init__.py")) == "pkg"
    assert any(
        pair.reader.path == Path("shared/consumer.py")
        and pair.writer.path == Path("pkg/__init__.py")
        for pair in report.pairs
    )


def test_frame_marks_matching_producer_as_decayed(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/writer.py",
        "from pathlib import Path\n"
        "REPO_ROOT = Path(__file__).resolve().parents[1]\n"
        "ARTIFACT = REPO_ROOT / 'artifacts' / 'state.json'\n"
        "def write_state():\n"
        "    ARTIFACT.write_text('{}', encoding='utf-8')\n",
    )
    _write(
        tmp_path,
        "shared/reader.py",
        "from pathlib import Path\n"
        "REPO_ROOT = Path(__file__).resolve().parents[1]\n"
        "ARTIFACT = REPO_ROOT / 'artifacts' / 'state.json'\n"
        "def load_state():\n"
        "    return ARTIFACT.read_text(encoding='utf-8')\n",
    )
    mass = tmp_path / "mass.yaml"
    mass.write_text(
        "members:\n"
        "  - id: synthetic-producer\n"
        f"    location: {{path: '{tmp_path / 'artifacts'}', patterns: ['*.json']}}\n",
        encoding="utf-8",
    )

    without_frame = gate.analyse_consumer_side(tmp_path, [])
    assert not any(
        item.kind == "consumer-reads-decayed-producer" for item in without_frame.findings
    )

    with_frame = gate.analyse_consumer_side(
        tmp_path,
        [],
        frame_path=FRAME_FIXTURE,
        mass_path=mass,
    )
    decay = [item for item in with_frame.findings if item.kind == "consumer-reads-decayed-producer"]
    assert len(decay) == 1
    assert "member=synthetic-producer relation=scope_exited verdict=TRUE" in decay[0].detail


def test_default_mass_path_preserves_current_symlink(gate, tmp_path: Path) -> None:
    procedure = tmp_path / "procedure"
    mass = procedure / "declaration" / "mass.yaml"
    mass.parent.mkdir(parents=True)
    mass.write_text("members: []\n", encoding="utf-8")
    epoch = procedure / "_runs" / "epochs" / "run-1"
    epoch.mkdir(parents=True)
    (procedure / "_runs" / "current").symlink_to(epoch, target_is_directory=True)
    logical_frame = procedure / "_runs" / "current" / "elements.json"
    assert gate._default_mass_path(logical_frame) == mass


def test_shallow_frame_path_preserves_report_only_error_contract(
    gate,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    frame = Path("/tmp/elements.json")
    observed: dict[str, Path] = {}

    def fail_loading(_frame: Path, mass: Path, _repo_root: Path):
        observed["mass"] = mass
        raise OSError(f"missing mass {mass}")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gate, "load_decayed_members", fail_loading)
    args = gate.build_parser().parse_args(["--consumer-side", "--frame", str(frame)])

    assert gate.run_consumer_side(args) == 0
    output = capsys.readouterr().out
    assert observed["mass"] == Path("/declaration/mass.yaml")
    assert "[REPORT-ERROR] consumer-side analysis incomplete:" in output
    assert "consumer-side gate is REPORT-ONLY" in output


def test_json_report_records_the_head_it_measured(tmp_path: Path) -> None:
    """A report that does not say which tree it describes cannot be consulted by anything later
    (the dominator consumer refused to read one without a head — L-170); the report now carries
    the commit, the dirty flag, the frame epoch it was given and the decayed members it used."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "REPO_ROOT = Path(__file__).resolve().parents[1]\n"
        "ARTIFACT = REPO_ROOT / 'artifacts' / 'orphan.json'\n"
        "def load():\n"
        "    return ARTIFACT.read_text()\n",
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=tmp_path, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()
    epoch = tmp_path / "procedure" / "_runs" / "epochs" / "20260903T204725Z-d693f20c"
    epoch.mkdir(parents=True)
    (epoch / "elements.json").write_text(
        json.dumps([{"id": "r", "payload": {"verdicts": []}}]), encoding="utf-8"
    )
    (tmp_path / "procedure" / "declaration").mkdir()
    (tmp_path / "procedure" / "declaration" / "mass.yaml").write_text("members: []\n")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--consumer-side",
            "--frame",
            str(epoch / "elements.json"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads((tmp_path / ".consumer-side-report.json").read_text(encoding="utf-8"))
    measured = payload["measured"]
    assert measured["head"] == head
    assert measured["dirty"] is False
    assert measured["generated_at"].endswith("Z")
    assert measured["instrument_rev"] == "check-producer-consumers/consumer-side/1"
    assert measured["frame"]["epoch"] == "20260903T204725Z-d693f20c"
    assert measured["frame"]["decayed_members"] == []


def test_console_caps_each_finding_kind_and_points_to_json(tmp_path: Path) -> None:
    for index in range(26):
        _write(
            tmp_path,
            f"shared/consumer_{index}.py",
            "from pathlib import Path\n"
            "REPO_ROOT = Path(__file__).resolve().parents[1]\n"
            f"ARTIFACT = REPO_ROOT / 'artifacts' / 'orphan-{index}.json'\n"
            f"def load_orphan_{index}():\n"
            "    return ARTIFACT.read_text()\n",
        )
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--consumer-side"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    report_path = tmp_path / ".consumer-side-report.json"
    assert result.returncode == 0
    assert result.stdout.splitlines()[0].startswith("consumer-side counts:")
    assert result.stdout.count("[REPORT] consumer-reads-unwritten-artifact") == 25
    assert f"consumer-side full JSON report: {report_path}" in result.stdout
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["summary"]["findings_by_kind"]["consumer-reads-unwritten-artifact"] == 26
    assert len(payload["findings"]) == 26


def test_unwritable_json_report_path_is_report_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("blocks report directory creation", encoding="utf-8")
    report_path = blocked_parent / "consumer-side-report.json"
    monkeypatch.setenv("RUNNER_TEMP", str(blocked_parent))

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--consumer-side"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert f"[REPORT-ERROR] {report_path}:" in result.stdout
    assert "consumer-side counts:" in result.stdout
    assert "consumer-side gate is REPORT-ONLY" in result.stdout


def test_nonserialisable_finding_is_a_report_only_json_error(
    gate,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _unwritten_repo(tmp_path)
    report = gate.analyse_consumer_side(tmp_path, [])
    report.findings[0] = replace(report.findings[0], detail=object())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gate, "analyse_consumer_side", lambda *_args, **_kwargs: report)

    result = gate.run_consumer_side(gate.build_parser().parse_args(["--consumer-side"]))
    output = capsys.readouterr().out

    assert result == 0
    assert (
        f"[REPORT-ERROR] {tmp_path / '.consumer-side-report.json'}: "
        "Object of type object is not JSON serializable"
    ) in output
    assert "[REPORT] consumer-reads-unwritten-artifact" in output
    assert "consumer-side gate is REPORT-ONLY" in output


def _assert_report_only_error(
    result: subprocess.CompletedProcess[str], report_path: Path, bad_path: Path
) -> None:
    assert result.returncode == 0
    error_lines = [line for line in result.stdout.splitlines() if line.startswith("[REPORT-ERROR]")]
    assert len(error_lines) == 1
    assert str(bad_path) in error_lines[0]
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["summary"]["errors"] == 1
    assert len(payload["errors"]) == 1
    assert str(bad_path) in payload["errors"][0]


def test_malformed_frame_is_a_recorded_report_only_error(tmp_path: Path) -> None:
    frame = tmp_path / "malformed-frame.json"
    mass = tmp_path / "mass.yaml"
    frame.write_text("{not-json", encoding="utf-8")
    mass.write_text("members: []\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--consumer-side",
            "--frame",
            str(frame),
            "--mass",
            str(mass),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    _assert_report_only_error(result, tmp_path / ".consumer-side-report.json", frame)


def test_malformed_mass_is_a_recorded_report_only_error(tmp_path: Path) -> None:
    frame = tmp_path / "frame.json"
    mass = tmp_path / "malformed-mass.yaml"
    frame.write_text("[]\n", encoding="utf-8")
    mass.write_text("members: [\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--consumer-side",
            "--frame",
            str(frame),
            "--mass",
            str(mass),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    _assert_report_only_error(result, tmp_path / ".consumer-side-report.json", mass)


def test_malformed_allowlist_is_a_recorded_report_only_error(tmp_path: Path) -> None:
    allowlist = tmp_path / "malformed-allowlist.json"
    allowlist.write_text("{not-json", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--consumer-side",
            "--allowlist",
            str(allowlist),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    _assert_report_only_error(result, tmp_path / ".consumer-side-report.json", allowlist)


def test_real_tree_names_both_known_consumer_side_instances(gate) -> None:
    report = gate.analyse_consumer_side(
        REPO_ROOT, gate.load_allowlist(REPO_ROOT / gate.DEFAULT_ALLOWLIST_PATH)
    )
    registry = [
        item
        for item in report.findings
        if item.reader.pattern == "config/platform-capability-registry.json"
    ]
    assert registry
    assert {item.kind for item in registry} == {"consumer-reads-unwritten-artifact"}

    binding_pairs = [item for item in report.pairs if item.family == "claim_dispatch_binding"]
    assert binding_pairs
    assert all(item.reader.pattern == item.writer.pattern for item in binding_pairs)
    assert any(item.reader.path == Path("shared/sdlc_claim.py") for item in binding_pairs)
    assert any(item.writer.path == Path("shared/sdlc_task_store.py") for item in binding_pairs)


def test_consumer_side_arm_is_load_bearing(tmp_path: Path) -> None:
    _unwritten_repo(tmp_path)
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--consumer-side"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "consumer-reads-unwritten-artifact" in result.stdout
    assert "config/orphan.json" in result.stdout
    assert "REPORT-ONLY" in result.stdout
