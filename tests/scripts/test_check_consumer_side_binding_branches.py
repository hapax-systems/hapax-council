"""Branch, glob, modelled-API and helper-resolution canaries (seventh review round of #4626).

Codex's sixth-round criticals: mutually exclusive branches collapsed into one path state; `*` in a
consumer glob crossed directory separators; the modelled `module.open` APIs were shadowed by the
generic open branch; a qualified helper call resolved to the caller's own helper; decayed findings
were not deduplicated by read pattern; report errors named no next action.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check-producer-consumers.py"
FRAME_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "consumer-side-frame-elements.json"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_consumer_side_branches", SCRIPT_PATH)
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


def _unwritten_patterns(report, path: str) -> set[str]:
    return {
        finding.reader.pattern
        for finding in report.findings
        if finding.kind == "consumer-reads-unwritten-artifact" and finding.reader.path == Path(path)
    }


def test_a_read_after_if_else_sees_both_branches(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def load_state(flag):\n"
        "    artifact = Path('artifacts/before.json')\n"
        "    if flag:\n"
        "        artifact = Path('artifacts/taken.json')\n"
        "    else:\n"
        "        artifact = Path('artifacts/not-taken.json')\n"
        "    return artifact.read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    patterns = _unwritten_patterns(report, "shared/consumer.py")
    assert {"artifacts/taken.json", "artifacts/not-taken.json"} <= patterns
    assert "artifacts/before.json" not in patterns
    assert report.unresolvable == 0


def test_a_read_after_if_without_else_keeps_the_fall_through_value(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def load_state(flag):\n"
        "    artifact = Path('artifacts/before.json')\n"
        "    if flag:\n"
        "        artifact = Path('artifacts/taken.json')\n"
        "    return artifact.read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert {"artifacts/before.json", "artifacts/taken.json"} <= _unwritten_patterns(
        report, "shared/consumer.py"
    )


def test_a_conditional_read_expression_reports_both_branch_patterns(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def load_state(flag):\n"
        "    return (Path('artifacts/left.json') if flag else "
        "Path('artifacts/right.json')).read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert {"artifacts/left.json", "artifacts/right.json"} <= _unwritten_patterns(
        report, "shared/consumer.py"
    )
    assert report.unresolvable == 0


def test_a_partly_unresolved_conditional_read_counts_the_unknown_branch(
    gate, tmp_path: Path
) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def load_state(flag, choose):\n"
        "    return (Path('artifacts/known.json') if flag else choose()).read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "artifacts/known.json" in _unwritten_patterns(report, "shared/consumer.py")
    assert report.unresolvable == 1


def test_try_except_and_loops_fork_the_value_state(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def load_state(items):\n"
        "    try:\n"
        "        artifact = Path('artifacts/tried.json')\n"
        "    except OSError:\n"
        "        artifact = Path('artifacts/handled.json')\n"
        "    for _item in items:\n"
        "        artifact = Path('artifacts/looped.json')\n"
        "    return artifact.read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert {
        "artifacts/tried.json",
        "artifacts/handled.json",
        "artifacts/looped.json",
    } <= _unwritten_patterns(report, "shared/consumer.py")


def test_except_handler_sees_state_entering_the_raising_assignment(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def load_state(choose):\n"
        "    artifact = Path('artifacts/fallback.json')\n"
        "    try:\n"
        "        artifact = choose()\n"
        "    except OSError:\n"
        "        return artifact.read_text()\n"
        "    return ''\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "artifacts/fallback.json" in _unwritten_patterns(report, "shared/consumer.py")


def test_except_handler_does_not_see_state_after_the_last_raising_statement(
    gate, tmp_path: Path
) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def load_state():\n"
        "    artifact = Path('artifacts/fallback.json')\n"
        "    try:\n"
        "        Path('artifacts/primary.json').read_text()\n"
        "        artifact = Path('artifacts/after-read.json')\n"
        "    except OSError:\n"
        "        return artifact.read_text()\n"
        "    return ''\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    patterns = _unwritten_patterns(report, "shared/consumer.py")
    assert "artifacts/fallback.json" in patterns
    assert "artifacts/primary.json" in patterns
    assert "artifacts/after-read.json" not in patterns


def test_too_many_branch_states_collapse_to_unresolvable_not_a_guess(gate, tmp_path: Path) -> None:
    branches = "".join(
        f"    if flags[{i}]:\n        artifact = Path('artifacts/branch-{i}.json')\n"
        for i in range(12)
    )
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def load_state(flags):\n"
        "    artifact = Path('artifacts/start.json')\n"
        + branches
        + "    return artifact.read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    # Past the cap the divergent name collapses to unresolved; branches below the collapse fork
    # again from that state. Every pattern the read reports must be a value a branch really
    # assigned — the cap may lose values, it may never invent one — and nothing crashes.
    real = {"artifacts/start.json", *(f"artifacts/branch-{i}.json" for i in range(12))}
    reported = _unwritten_patterns(report, "shared/consumer.py")
    assert reported <= real
    assert reported or report.unresolvable >= 1


def test_a_consumer_glob_does_not_match_a_writer_in_a_subdirectory(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/writer.py",
        "from pathlib import Path\n"
        "REPO_ROOT = Path(__file__).resolve().parents[1]\n"
        "def write_state():\n"
        "    (REPO_ROOT / 'cache' / 'sub' / 'wanted.json').write_text('{}')\n",
    )
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "from shared.writer import write_state\n"
        "REPO_ROOT = Path(__file__).resolve().parents[1]\n"
        "def load_state():\n"
        "    return [p.read_text() for p in (REPO_ROOT / 'cache').glob('*.json')]\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert not any(pair.writer.path == Path("shared/writer.py") for pair in report.pairs)
    assert gate._patterns_match("cache/*.json", "cache/sub/wanted.json") is False
    assert gate._patterns_match("cache/**/*.json", "cache/sub/wanted.json") is True
    assert gate._patterns_match("cache/*.json", "cache/wanted.json") is True


def test_negated_glob_class_has_shell_semantics_and_rejects_the_excluded_name(gate) -> None:
    assert gate._patterns_match("cache/[!a].json", "cache/b.json") is True
    assert gate._patterns_match("cache/[!a].json", "cache/a.json") is False


def test_invalid_glob_range_is_a_reported_no_match(
    gate, capsys: pytest.CaptureFixture[str]
) -> None:
    assert gate._patterns_match("cache/[z-a].json", "cache/z.json") is False
    output = capsys.readouterr().out
    assert "[REPORT-ERROR] glob pattern 'cache/[z-a].json'" in output
    assert "next action:" in output


def test_invalid_glob_range_preserves_the_report_only_command_contract(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def load_state():\n"
        "    return list(Path('cache').glob('[z-a].json'))\n",
    )
    _write(
        tmp_path,
        "shared/writer.py",
        "from pathlib import Path\ndef save_state():\n    Path('cache/z.json').write_text('{}')\n",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--consumer-side"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "[REPORT-ERROR] glob pattern 'cache/[z-a].json'" in result.stdout
    assert "consumer-side gate is REPORT-ONLY" in result.stdout


def test_lambda_body_reads_are_scanned(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "load_later = lambda: Path('artifacts/lambda-orphan.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "artifacts/lambda-orphan.json" in _unwritten_patterns(report, "shared/consumer.py")
    assert report.unresolvable == 0


def test_unresolved_lambda_body_read_increments_the_count(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "load_later = lambda artifact: artifact.read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert report.unresolvable == 1


def test_nested_helpers_cannot_replace_a_module_level_path_helper(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def artifact_path():\n"
        "    return Path('artifacts/module.json')\n"
        "class Shadow:\n"
        "    def artifact_path(self):\n"
        "        return Path('artifacts/method.json')\n"
        "def enclosing():\n"
        "    def artifact_path():\n"
        "        return Path('artifacts/nested.json')\n"
        "    return artifact_path\n"
        "def load_state():\n"
        "    return artifact_path().read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    patterns = _unwritten_patterns(report, "shared/consumer.py")
    assert "artifacts/module.json" in patterns
    assert "artifacts/method.json" not in patterns
    assert "artifacts/nested.json" not in patterns


def test_nested_caller_resolves_its_lexically_nearest_path_helper(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def artifact_path():\n"
        "    return Path('artifacts/module.json')\n"
        "def load_state():\n"
        "    def artifact_path():\n"
        "        return Path('artifacts/nested-orphan.json')\n"
        "    return artifact_path().read_text()\n"
        "def write_module_state():\n"
        "    artifact_path().write_text('{}')\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    patterns = _unwritten_patterns(report, "shared/consumer.py")
    assert "artifacts/nested-orphan.json" in patterns
    assert "artifacts/module.json" not in patterns


@pytest.mark.parametrize(
    ("call", "operation", "action"),
    [
        ("shelve.open(DB)", "shelve.open", "read"),
        ("dbm.open(DB)", "dbm.open", "read"),
        ("tarfile.open(DB)", "tarfile.open", "read"),
        ("tarfile.open(DB, 'w')", "tarfile.open", "write"),
        ("zipfile.ZipFile(DB, mode='w')", "zipfile.ZipFile", "write"),
        ("sqlite3.connect(DB)", "sqlite3.connect", "read"),
    ],
)
def test_modelled_file_backed_apis_are_reached(
    gate, tmp_path: Path, call: str, operation: str, action: str
) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "import dbm, shelve, sqlite3, tarfile, zipfile\n"
        "from pathlib import Path\n"
        "DB = Path('cache/state.db')\n"
        f"def use_db():\n    return {call}\n",
    )
    accesses, unresolved, _imports, unrecognised = gate.collect_artifact_accesses(tmp_path)
    matches = [
        access
        for access in accesses
        if access.pattern == "cache/state.db" and access.operation == operation
    ]
    assert matches and matches[0].action == action, (accesses, unresolved, unrecognised)
    assert unresolved == 0
    assert unrecognised == {}


def test_a_qualified_helper_call_never_resolves_to_the_local_helper(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "other.py",
        "from pathlib import Path\ndef artifact_path():\n    return Path('artifacts/other.json')\n",
    )
    _write(
        tmp_path,
        "shared/consumer.py",
        "import other\n"
        "from pathlib import Path\n"
        "def artifact_path():\n"
        "    return Path('artifacts/local.json')\n"
        "def load_state():\n"
        "    return other.artifact_path().read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    patterns = _unwritten_patterns(report, "shared/consumer.py")
    assert "artifacts/other.json" in patterns
    assert "artifacts/local.json" not in patterns


def test_a_qualified_call_to_an_unknown_module_is_unresolvable(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def artifact_path():\n"
        "    return Path('artifacts/local.json')\n"
        "def load_state(client):\n"
        "    return client.artifact_path().read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "artifacts/local.json" not in _unwritten_patterns(report, "shared/consumer.py")
    assert report.unresolvable == 1


def test_decayed_findings_merge_reader_sites_of_one_pattern(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/writer.py",
        "from pathlib import Path\n"
        "REPO_ROOT = Path(__file__).resolve().parents[1]\n"
        "ARTIFACT = REPO_ROOT / 'artifacts' / 'state.json'\n"
        "def write_state():\n"
        "    ARTIFACT.write_text('{}', encoding='utf-8')\n",
    )
    for name in ("reader_a", "reader_b"):
        _write(
            tmp_path,
            f"shared/{name}.py",
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
    report = gate.analyse_consumer_side(tmp_path, [], frame_path=FRAME_FIXTURE, mass_path=mass)
    decay = [item for item in report.findings if item.kind == "consumer-reads-decayed-producer"]
    assert len(decay) == 1
    assert decay[0].reader_count == 2
    assert {reader.path for reader in decay[0].readers} == {
        Path("shared/reader_a.py"),
        Path("shared/reader_b.py"),
    }
