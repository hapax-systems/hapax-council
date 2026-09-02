"""Canaries for whole-tree consumer-side producer binding analysis."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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
