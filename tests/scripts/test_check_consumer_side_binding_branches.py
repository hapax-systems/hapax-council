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


def test_every_known_pattern_survives_the_branch_state_cap(gate, tmp_path: Path) -> None:
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
    real = {"artifacts/start.json", *(f"artifacts/branch-{i}.json" for i in range(12))}
    assert _unwritten_patterns(report, "shared/consumer.py") == real
    assert report.unresolvable == 0


def test_branch_state_join_keeps_bare_string_read_patterns(gate, tmp_path: Path) -> None:
    branches = "".join(f"    if flags[{i}]:\n        artifact = 'branch-{i}'\n" for i in range(12))
    _write(
        tmp_path,
        "shared/consumer.py",
        "def load_state(flags):\n"
        "    artifact = 'start'\n" + branches + "    return open(artifact).read()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    expected = {"start", *(f"branch-{i}" for i in range(12))}
    assert _unwritten_patterns(report, "shared/consumer.py") == expected
    assert report.unresolvable == 0


@pytest.mark.parametrize(
    ("definition", "pattern"),
    [
        (
            "def load(value=Path('artifacts/function-default.json').read_text()):\n"
            "    return value\n",
            "artifacts/function-default.json",
        ),
        (
            "async def load(value=Path('artifacts/async-default.json').read_text()):\n"
            "    return value\n",
            "artifacts/async-default.json",
        ),
        (
            "@Path('artifacts/decorator.json').read_text()\ndef load():\n    return None\n",
            "artifacts/decorator.json",
        ),
        (
            "class Load(Path('artifacts/class-base.json').read_text()):\n    pass\n",
            "artifacts/class-base.json",
        ),
        (
            "class Load:\n    state = Path('artifacts/class-body.json').read_text()\n",
            "artifacts/class-body.json",
        ),
    ],
)
def test_definition_time_reads_are_scanned(
    gate, tmp_path: Path, definition: str, pattern: str
) -> None:
    _write(tmp_path, "shared/consumer.py", "from pathlib import Path\n" + definition)
    report = gate.analyse_consumer_side(tmp_path, [])
    assert pattern in _unwritten_patterns(report, "shared/consumer.py")
    assert report.unresolvable == 0


def test_unresolved_definition_time_read_increments_the_count(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "def load(value=artifact.read_text()):\n    return value\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert report.unresolvable == 1


@pytest.mark.parametrize("exit_statement", ["return 1", "raise RuntimeError"])
def test_finally_read_is_scanned_after_abrupt_try_exit(
    gate, tmp_path: Path, exit_statement: str
) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def load():\n"
        "    try:\n"
        f"        {exit_statement}\n"
        "    finally:\n"
        "        Path('artifacts/finally.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "artifacts/finally.json" in _unwritten_patterns(report, "shared/consumer.py")
    assert report.unresolvable == 0


def test_function_parameter_shadows_imported_transfer_alias(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "from shutil import copy2 as duplicate\n"
        "SOURCE = Path('artifacts/source.json')\n"
        "DESTINATION = Path('artifacts/destination.json')\n"
        "def invoke_callback(duplicate):\n"
        "    duplicate(SOURCE, DESTINATION)\n"
        "def load_destination():\n"
        "    return DESTINATION.read_text()\n",
    )
    accesses, unresolved, _imports, _unrecognised = gate.collect_artifact_accesses(tmp_path)
    assert not any(
        access.operation == "copy2"
        and access.pattern
        in {
            "artifacts/source.json",
            "artifacts/destination.json",
        }
        for access in accesses
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "artifacts/destination.json" in _unwritten_patterns(report, "shared/consumer.py")
    assert unresolved == 0


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


@pytest.mark.parametrize("loop", ["for", "async for"])
@pytest.mark.parametrize("collection", ["[{items}]", "({items},)", "{{{items}}}"])
@pytest.mark.parametrize("operation", ["read_text()", "write_text('{}')"])
def test_loop_target_rebinding_preserves_real_accesses(
    gate, tmp_path: Path, loop: str, collection: str, operation: str
) -> None:
    items = "Path('artifacts/new.json'), Path('artifacts/other.json')"
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nasync def use():\n"
        "    artifact = Path('artifacts/old.json')\n"
        f"    {loop} artifact in {collection.format(items=items)}:\n"
        f"        artifact.{operation}\n"
        "Path('artifacts/old.json').read_text()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {item.pattern for item in accesses if item.lineno == 5} == {
        "artifacts/new.json",
        "artifacts/other.json",
    }
    assert unresolved == 0
    patterns = _unwritten_patterns(gate.analyse_consumer_side(tmp_path, []), "shared/consumer.py")
    assert "artifacts/old.json" in patterns
    if operation == "read_text()":
        assert {"artifacts/new.json", "artifacts/other.json"} <= patterns


@pytest.mark.parametrize("loop", ["for", "async for"])
@pytest.mark.parametrize("target", ["artifact", "(label, artifact)"])
@pytest.mark.parametrize("iterable", ["items", "[f'artifacts/{unknown}.json']"])
def test_loop_target_unknown_iterable_is_unresolved(
    gate, tmp_path: Path, loop: str, target: str, iterable: str
) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nasync def use(items):\n"
        "    artifact = Path('artifacts/old.json')\n"
        f"    {loop} {target} in {iterable}:\n"
        "        artifact.write_text('{}')\n        artifact.read_text()\n"
        "Path('artifacts/old.json').read_text()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not [item for item in accesses if item.lineno in (5, 6)]
    assert unresolved == 2
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "artifacts/old.json" in _unwritten_patterns(report, "shared/consumer.py")
    assert len(report.unresolved_paths) == 2
    assert all("artifact" in site for site in report.unresolved_paths)


@pytest.mark.parametrize("loop", ["for", "async for"])
def test_loop_target_tuple_unpacking_binds_each_component(gate, tmp_path: Path, loop: str) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nasync def use():\n"
        "    source = Path('artifacts/old-source.json')\n"
        "    dest = Path('artifacts/old-dest.json')\n"
        f"    {loop} source, (label, dest) in ["
        "(Path('artifacts/source.json'), ('label', Path('artifacts/dest.json')))]:\n"
        "        source.read_text()\n        dest.write_text('{}')\n"
        "Path('artifacts/old-dest.json').read_text()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {(item.action, item.pattern) for item in accesses if item.lineno in (6, 7)} == {
        ("read", "artifacts/source.json"),
        ("write", "artifacts/dest.json"),
    }
    assert unresolved == 0
    assert "artifacts/old-dest.json" in _unwritten_patterns(
        gate.analyse_consumer_side(tmp_path, []), "shared/consumer.py"
    )


@pytest.mark.parametrize(
    ("iterable", "expected", "unresolved"),
    [
        ("[Path('artifacts/new.json')]", {"artifacts/new.json"}, 0),
        ("items", {"artifacts/old.json"}, 1),
        ("[]", {"artifacts/old.json"}, 0),
    ],
    ids=["nonempty-literal", "possibly-empty", "empty-literal"],
)
def test_loop_target_post_loop_keeps_zero_iteration_and_body_end(
    gate, tmp_path: Path, iterable: str, expected: set[str], unresolved: int
) -> None:
    """Dossier: zero iterations are possible only when the iterable may be empty.

    The former non-empty literal pin included an impossible old.json exit. Keep
    the possibly-empty and empty iterable siblings beside the corrected pin.
    """
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\ndef use():\n"
        "    artifact = Path('artifacts/old.json')\n"
        f"    for artifact in {iterable}:\n        pass\n"
        "    artifact.read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _unwritten_patterns(report, "shared/consumer.py") == expected
    assert report.unresolvable == unresolved


@pytest.mark.parametrize(
    ("flow", "expected", "unresolved"),
    [
        pytest.param(
            "if flag:\n    ARTIFACT = Path('artifacts/a.json')\nelse:\n    ARTIFACT = Path('artifacts/b.json')\n",
            {"artifacts/a.json", "artifacts/b.json"},
            0,
            id="if-else",
        ),
        pytest.param(
            "for item in items:\n    ARTIFACT = Path('artifacts/a.json')\n",
            {"artifacts/old.json", "artifacts/a.json"},
            0,
            id="loop",
        ),
        pytest.param(
            "while flag:\n    ARTIFACT = Path('artifacts/a.json')\n",
            {"artifacts/old.json", "artifacts/a.json"},
            0,
            id="while",
        ),
        pytest.param(
            "try:\n    ARTIFACT = Path('artifacts/a.json')\nexcept OSError:\n    ARTIFACT = Path('artifacts/b.json')\n",
            {"artifacts/a.json", "artifacts/b.json"},
            0,
            id="try",
        ),
        pytest.param(
            "if flag:\n    ARTIFACT = unknown\nelse:\n    ARTIFACT = Path('artifacts/b.json')\n",
            {"artifacts/b.json"},
            1,
            id="unbounded",
        ),
    ],
)
def test_function_inherits_module_post_flow_bindings(
    gate, tmp_path: Path, flow, expected, unresolved
) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "ARTIFACT = Path('artifacts/old.json')\n"
        + flow
        + "def write_state():\n    ARTIFACT.write_text('{}')\n"
        "Path('artifacts/old.json').read_text()\n",
    )
    accesses, count, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write"} == expected
    assert count == unresolved
    report = gate.analyse_consumer_side(tmp_path, [])
    assert ("artifacts/old.json" in _unwritten_patterns(report, "shared/consumer.py")) == (
        "artifacts/old.json" not in expected
    )
    assert len(report.unresolved_paths) == unresolved


def test_loop_unpacking_keeps_known_sibling_of_dynamic_component(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\ndef use(unknown):\n"
        "    for known, dynamic in [(Path('artifacts/known.json'), f'artifacts/{unknown}.json')]:\n"
        "        known.read_text()\n        dynamic.write_text('{}')\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _unwritten_patterns(report, "shared/consumer.py") == {"artifacts/known.json"}
    assert report.unresolvable == 1


@pytest.mark.parametrize("loop", ["for", "async for"])
@pytest.mark.parametrize(
    "target", ["known, *rest, dest", "*rest, known, dest", "known, dest, *rest"]
)
def test_loop_starred_target_retains_fixed_siblings(gate, tmp_path: Path, loop, target) -> None:
    items = {
        "known, *rest, dest": "Path('artifacts/known.json'), unknown, Path('artifacts/dest.json')",
        "*rest, known, dest": "unknown, Path('artifacts/known.json'), Path('artifacts/dest.json')",
        "known, dest, *rest": "Path('artifacts/known.json'), Path('artifacts/dest.json'), unknown",
    }[target]
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nasync def use(unknown):\n"
        f"    {loop} {target} in [({items})]:\n"
        "        known.read_text()\n        dest.write_text('{}')\n"
        "        rest.read_text()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {(a.action, a.pattern) for a in accesses if a.bounded} == {
        ("read", "artifacts/known.json"),
        ("write", "artifacts/dest.json"),
    }
    assert unresolved == 1  # A starred capture is a list, not a modelled path.


@pytest.mark.parametrize("loop", ["for", "async for"])
def test_loop_unpacking_freezes_components_before_iterations(gate, tmp_path: Path, loop) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nasync def use(unknown):\n"
        "    artifact = Path('artifacts/start')\n    piece = 'a'\n"
        f"    {loop} suffix, dynamic in [(piece, unknown), (piece, unknown)]:\n"
        "        artifact /= suffix\n        piece = 'b'\n"
        "    artifact.write_text('{}')\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {(a.action, a.pattern) for a in accesses if a.bounded} == {
        ("write", "artifacts/start/a/a")
    }
    assert unresolved == 0


@pytest.mark.parametrize("loop", ["for", "async for"])
@pytest.mark.parametrize(
    "iterable",
    ["{Path('artifacts/known.json')}", "[Path('artifacts/known.json'), *items]"],
    ids=["set", "unknown-expansion"],
)
def test_loop_fallback_retains_known_access_and_uncertain_accumulation(
    gate, tmp_path: Path, loop, iterable
) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nasync def use(items):\n"
        "    artifact = Path('artifacts/start')\n"
        f"    {loop} piece in {iterable}:\n"
        "        piece.read_text()\n        artifact /= piece\n"
        "    artifact.write_text('{}')\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert "artifacts/known.json" in {a.pattern for a in accesses if a.action == "read"}
    assert not [a for a in accesses if a.action == "write" and a.bounded]
    assert unresolved > 0


def test_capped_loop_retains_known_sibling_of_dynamic_component(gate, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(gate, "_MAX_BINDING_STATES", 1)
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\ndef use(unknown):\n"
        "    for known, dynamic in [(Path('artifacts/first.json'), unknown), "
        "(Path('artifacts/second.json'), unknown)]:\n"
        "        known.read_text()\n        dynamic.write_text('{}')\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _unwritten_patterns(report, "shared/consumer.py") == {
        "artifacts/first.json",
        "artifacts/second.json",
    }
    assert report.unresolvable > 0
    assert any("literal loop iteration cap" in site for site in report.capped_expressions)


def test_a_descriptor_held_in_a_variable_is_not_certified_as_a_filename(
    gate, tmp_path: Path
) -> None:
    """A literal is not the only way a descriptor arrives.

    `fd = 3; open(fd, "w")` resolved to the pattern "3" and certified a file of that name.
    Narrowing the earlier repair to literal integers left this open, which the review caught.
    """

    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def emit():\n"
        "    fd = 3\n"
        "    open(fd, 'w').close()\n"
        "def load():\n"
        "    return Path('3').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "3" in _unwritten_patterns(report, "shared/consumer.py")
    assert not [pair for pair in report.pairs if pair.writer.pattern == "3"]


def test_keyword_unpacking_withholds_both_rename_operands(gate, tmp_path: Path) -> None:
    """`**kw` may carry either descriptor, and the call site does not say which.

    A name scan sees `dst_dir_fd=` when it is written out and nothing when it is unpacked, so
    the earlier repair was bypassed by a form it never examined. An undetermined keyword set is
    not an absent one.
    """

    _write(
        tmp_path,
        "shared/consumer.py",
        "import os\n"
        "from pathlib import Path\n"
        "def promote(**kw):\n"
        "    os.rename('a/tmp.json', 'a/final.json', **kw)\n"
        "def load():\n"
        "    return Path('a/final.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "a/final.json" in _unwritten_patterns(report, "shared/consumer.py")
    assert not [pair for pair in report.pairs if pair.writer.pattern == "a/final.json"]


def test_a_custom_opener_withholds_the_written_path(gate, tmp_path: Path) -> None:
    """`opener` returns a descriptor of its own choosing, so the literal is not evidence."""

    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def emit(op):\n"
        "    open('a/final.json', 'w', opener=op).close()\n"
        "def load():\n"
        "    return Path('a/final.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "a/final.json" in _unwritten_patterns(report, "shared/consumer.py")
    assert not [pair for pair in report.pairs if pair.writer.pattern == "a/final.json"]


def test_empty_str_component_preserves_the_actual_report(gate, tmp_path: Path) -> None:
    """``str()`` is the empty string, and an empty component is not ``.``.

    The earlier pin asserted a withhold at the resolver, on the reasoning that a lone withheld
    write produces no finding or pair so the report could not tell "withheld" from "certified as
    `.`". That reasoning was right about a *lone* write and wrong as a general rule: concatenating
    the component onto a real name makes the two states differ downstream, which is what this
    asserts. Reading `str()` as the current directory would write `.artifacts/old.json` and pair
    with the reader below.
    """

    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "Path(str() + 'artifacts/old.json').write_text('{}')\n"
        "Path('.artifacts/old.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert ".artifacts/old.json" in _unwritten_patterns(report, "shared/consumer.py")
    assert not [pair for pair in report.pairs if pair.reader.pattern == ".artifacts/old.json"]


def test_an_integer_file_descriptor_is_not_certified_as_a_filename(gate, tmp_path: Path) -> None:
    """``open(3, 'w')`` names no file this scanner can bind.

    The descriptor's target was established at a call this expression does not carry, so
    treating the integer as a literal filename certifies a wrong file.
    """

    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def emit():\n"
        "    open(3, 'w').close()\n"
        "def load():\n"
        "    return Path('3').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "3" in _unwritten_patterns(report, "shared/consumer.py")
    assert not [pair for pair in report.pairs if pair.writer.pattern == "3"]


def test_a_descriptor_relative_rename_destination_is_withheld(gate, tmp_path: Path) -> None:
    """``dst`` under ``dst_dir_fd`` is relative to the descriptor, not to this scanner's root.

    The literal it carries therefore names a different file than the one written, and the
    directory the descriptor refers to is established elsewhere.
    """

    _write(
        tmp_path,
        "shared/consumer.py",
        "import os\n"
        "from pathlib import Path\n"
        "def promote(fd):\n"
        "    os.rename('artifacts/tmp.json', 'artifacts/final.json', dst_dir_fd=fd)\n"
        "def load():\n"
        "    return Path('artifacts/final.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "artifacts/final.json" in _unwritten_patterns(report, "shared/consumer.py")
    assert not [pair for pair in report.pairs if pair.writer.pattern == "artifacts/final.json"]


# ------------------------------------------------------------------------------------------
# Scalar evidence: what a value's TYPE establishes about whether it names a file. Descriptor
# identity is typed evidence; a numeric filename is still a path; and an explicit conversion of
# a known scalar is a real name, not a guess. The pairs below are deliberate — each withhold has
# a companion asserting the neighbouring case is still resolved, because the old rule withheld
# by spelling and lost correct readers along with the descriptors.
# ------------------------------------------------------------------------------------------


def report_for(gate, tmp_path, body):
    source = tmp_path / "shared/example.py"
    source.parent.mkdir()
    source.write_text("from pathlib import Path\nimport io\n" + body)
    return gate.analyse_consumer_side(tmp_path, [])


#: One kind at a time: an absent write is `consumer-reads-unwritten-artifact`, a located write
#: whose execution is undetermined is `consumer-reads-artifact-with-unresolved-writer`, and which
#: the report chose is the discrimination rather than noise to read past.
ABSENT_WRITER = "consumer-reads-unwritten-artifact"
UNRESOLVED_WRITER = "consumer-reads-artifact-with-unresolved-writer"


def unwritten(report, kind: str = ABSENT_WRITER):
    return {finding.reader.pattern for finding in report.findings if finding.kind == kind}


@pytest.mark.parametrize("prefix", ["str()", "''", "str('')"])
def test_empty_component_cannot_hide_different_reader(gate, tmp_path, prefix):
    report = report_for(
        gate,
        tmp_path,
        f"Path({prefix} + 'artifacts/old.json').write_text('{{}}')\n"
        "Path('.artifacts/old.json').read_text()\n",
    )
    assert ".artifacts/old.json" in unwritten(report)
    assert not [pair for pair in report.pairs if pair.reader.pattern == ".artifacts/old.json"]


@pytest.mark.parametrize(
    "path_expr", ["Path(str()) / 'artifacts/old.json'", "Path(str() + 'artifacts/old.json')"]
)
def test_empty_component_preserves_correct_writer(gate, tmp_path, path_expr):
    report = report_for(
        gate,
        tmp_path,
        f"({path_expr}).write_text('{{}}')\nPath('artifacts/old.json').read_text()\n",
    )
    assert "artifacts/old.json" not in unwritten(report)
    assert any(
        pair.writer.pattern == pair.reader.pattern == "artifacts/old.json" for pair in report.pairs
    )


@pytest.mark.parametrize("value", ["3", "True", "False", "0", "-3"])
@pytest.mark.parametrize("binding", [False, True], ids=["literal", "variable"])
@pytest.mark.parametrize("function", ["open", "io.open"])
def test_typed_descriptor_never_certifies_its_printed_name(
    gate, tmp_path, value, binding, function
):
    setup = f"fd = {value}\n" if binding else ""
    expression = "fd" if binding else value
    label = value
    report = report_for(
        gate,
        tmp_path,
        setup + f"{function}({expression}, 'w', closefd=False).close()\n"
        f"Path({label!r}).read_text()\n",
    )
    assert label in unwritten(report)
    assert not [pair for pair in report.pairs if pair.writer.pattern == label]
    assert report.unresolvable > 0


@pytest.mark.parametrize("filename", ["3", "2024", "True"])
@pytest.mark.parametrize("reader", ["open({name}).read()", "Path({name}).open().read()"])
def test_numeric_filename_reader_remains_visible(gate, tmp_path, filename, reader):
    report = report_for(gate, tmp_path, reader.format(name=repr(filename)) + "\n")
    assert filename in unwritten(report)
    assert report.unresolvable == 0


@pytest.mark.parametrize(
    "writer",
    [
        "open('3', 'w').write('{}')",
        "Path('3').open('w').write('{}')",
        "name = '3'\nopen(name, 'w').write('{}')",
    ],
)
def test_numeric_filename_writer_is_not_a_descriptor(gate, tmp_path, writer):
    report = report_for(gate, tmp_path, writer + "\nPath('3').read_text()\n")
    assert "3" not in unwritten(report)
    accesses, unresolved, _, _ = gate.collect_artifact_accesses(tmp_path)
    assert {access.action for access in accesses if access.pattern == "3" and access.bounded} == {
        "read",
        "write",
    }
    assert unresolved == report.unresolvable == 0


@pytest.mark.parametrize(
    "writer",
    ["open(1 + 2, 'w', closefd=False)", "fd = 1 + 2\nopen(fd, 'w', closefd=False)"],
)
def test_numeric_addition_is_not_string_concatenation(gate, tmp_path, writer):
    report = report_for(gate, tmp_path, writer + "\nPath('12').read_text()\n")
    assert "12" in unwritten(report)
    assert report.unresolvable > 0


@pytest.mark.parametrize(
    ("setup", "expression", "label"),
    [("", "Path(3)", "3"), ("", "Path(True)", "True"), ("fd = 3\n", "Path(fd)", "3")],
)
def test_invalid_scalar_path_constructor_cannot_certify_a_writer(
    gate, tmp_path, setup, expression, label
):
    report = report_for(
        gate,
        tmp_path,
        setup + f"{expression}.open('w').write('{{}}')\nPath({label!r}).read_text()\n",
    )
    assert label in unwritten(report)
    assert report.unresolvable > 0


@pytest.mark.parametrize(
    ("writer", "label"),
    [
        ("open(str(1 + 2), 'w')", "3"),
        ("Path(str(1 + 2)).open('w')", "3"),
        ("name = '1' + '2'\nopen(name, 'w')", "12"),
    ],
)
def test_explicit_scalar_conversion_preserves_the_real_filename(gate, tmp_path, writer, label):
    report = report_for(gate, tmp_path, writer + f"\nPath({label!r}).read_text()\n")
    assert label not in unwritten(report)
    accesses, unresolved, _, _ = gate.collect_artifact_accesses(tmp_path)
    assert {access.action for access in accesses if access.pattern == label and access.bounded} == {
        "read",
        "write",
    }
    assert unresolved == report.unresolvable == 0


# ------------------------------------------------------------------------------------------
# Four report-level boundaries, all confirmed against the frozen original as well: none of them
# is a regression from the scalar round. Each is paired with the neighbouring case that must keep
# working, because every one of these repairs is a WITHHOLD or a re-spelling, and a withhold that
# is one case too wide loses a real writer.
# ------------------------------------------------------------------------------------------


def _bounded_writers(gate, tmp_path):
    accesses, _, _, _ = gate.collect_artifact_accesses(tmp_path)
    return {access.pattern for access in accesses if access.action == "write" and access.bounded}


def test_the_symbolic_home_has_no_known_parent(gate, tmp_path):
    """`Path.home().with_name(...)` named the filesystem root's child.

    The home is a symbol: this scanner does not know whose home it is, so it does not know the
    home's parent either. Taking the sentinel's `PurePosixPath` parent produced `/state.json` — a
    bounded writer at a path the code never touches, which then silenced the real reader's orphan.
    """

    report = report_for(
        gate,
        tmp_path,
        "Path.home().with_name('state.json').write_text('{}')\nPath('/state.json').read_text()\n",
    )
    assert "/state.json" in unwritten(report)
    assert "/state.json" not in _bounded_writers(gate, tmp_path)
    assert report.unresolvable > 0


@pytest.mark.parametrize(
    ("writer", "reader"),
    [
        ("(Path.home() / 'old.json').with_name('state.json')", "Path.home() / 'state.json'"),
        ("Path('/home/reviewer').with_name('state.json')", "Path('/home/state.json')"),
    ],
    ids=["home-child", "literal-absolute"],
)
def test_a_known_parent_still_supports_with_name(gate, tmp_path, writer, reader):
    """The companion: a home CHILD has a known parent — the home — and a literal absolute path
    has one too. Withholding those as well would have cost two correct writers."""

    report = report_for(gate, tmp_path, f"{writer}.write_text('{{}}')\n({reader}).read_text()\n")
    assert not unwritten(report)
    assert report.unresolvable == 0


@pytest.mark.parametrize(
    ("returned", "label"),
    [("True", "True"), ("3", "3"), ("1 + 2", "3")],
)
def test_a_returned_scalar_keeps_its_type_across_the_call(gate, tmp_path, returned, label):
    """`def descriptor(): return True` then `open(descriptor(), 'w')` certified a file named
    `True`. A value does not stop being an integer by being returned, and descriptor identity is
    a property of the value rather than of where it was written down."""

    report = report_for(
        gate,
        tmp_path,
        f"def descriptor():\n    return {returned}\n"
        f"open(descriptor(), 'w', closefd=False)\nPath({label!r}).read_text()\n",
    )
    assert label in unwritten(report)
    assert label not in _bounded_writers(gate, tmp_path)
    assert report.unresolvable > 0


@pytest.mark.parametrize("returned", ["'3'", "str(True)", "'state.json'"])
def test_a_returned_string_is_still_a_filename(gate, tmp_path, returned):
    """The companion: a helper returning a STRING names a real file, including a string that
    merely looks numeric. Folding by spelling instead of by type is what this replaces."""

    report = report_for(
        gate,
        tmp_path,
        f"def filename():\n    return {returned}\nopen(filename(), 'w')\n",
    )
    assert _bounded_writers(gate, tmp_path), returned
    assert report.unresolvable == 0


@pytest.mark.parametrize("empty", ["str()", "''", "str('')"], ids=["call", "literal", "explicit"])
def test_a_known_empty_interpolation_is_exact_not_a_wildcard(gate, tmp_path, empty):
    """`Path(f'artifacts/{str()}state.json')` widened to `artifacts/*state.json` and bounded it,
    which silenced the orphan for a genuinely different reader. The constant channel did not know
    `str()` even though the path resolver did; the literal twin already behaved correctly."""

    report = report_for(
        gate,
        tmp_path,
        f"Path(f'artifacts/{{{empty}}}state.json').write_text('{{}}')\n"
        "Path('artifacts/alienstate.json').read_text()\n",
    )
    assert "artifacts/alienstate.json" in unwritten(report)
    assert _bounded_writers(gate, tmp_path) == {"artifacts/state.json"}


@pytest.mark.parametrize(
    ("returned", "label"),
    [("True", "True"), ("3", "3")],
)
def test_a_returned_scalar_survives_an_assignment(gate, tmp_path, returned, label):
    """The binding kept the helper's resolved TEXT and dropped its type.

    `fd = descriptor()` then `open(fd, 'w')` certified a file named `True` where Python opens
    descriptor 1. The previous round covered the direct call and stopped at the assignment
    immediately beside it — which is this file's recurring shape, not a new one.
    """

    report = report_for(
        gate,
        tmp_path,
        f"def descriptor():\n    return {returned}\nfd = descriptor()\n"
        f"open(fd, 'w', closefd=False)\nPath({label!r}).read_text()\n",
    )
    assert label in unwritten(report)
    assert label not in _bounded_writers(gate, tmp_path)
    assert report.unresolvable > 0


def test_an_assigned_returned_filename_is_still_a_filename(gate, tmp_path):
    """The companion: a helper returning a string, through a binding, still names a real file."""

    report = report_for(
        gate,
        tmp_path,
        "def filename():\n    return '3'\nname = filename()\nopen(name, 'w')\n",
    )
    assert _bounded_writers(gate, tmp_path) == {"3"}
    assert report.unresolvable == 0


RETURN_TRANSFER_SHAPES = {
    "literal": "def value():\n    return {scalar}\n",
    "local": "def value():\n    held = {scalar}\n    return held\n",
    "parameter": "def value(held):\n    return held\n",
    "assigned-call": "def value():\n    return {scalar}\n",
}


def _transfer_body(shape, scalar, call_and_use):
    definition = RETURN_TRANSFER_SHAPES[shape].format(scalar=scalar)
    call = f"value({scalar})" if shape == "parameter" else "value()"
    if shape == "assigned-call":
        return definition + f"held = {call}\n" + call_and_use.format(call="held")
    return definition + call_and_use.format(call=call)


@pytest.mark.parametrize("shape", sorted(RETURN_TRANSFER_SHAPES))
def test_every_supported_return_transfer_shape_keeps_the_scalar_type(gate, tmp_path, shape):
    """The transfer shapes, enumerated instead of discovered one reviewer at a time.

    Three consecutive rounds each closed the shape they were shown — a literal return, then the
    assignment beside it — and left the next one certifying a wrong filename. The supported set is
    now written down in `_returned_constant` and asserted here as a set: a helper's own constant
    bindings and the argument a call actually passes both carry the type, and everything past that
    is honestly "not established" rather than quietly a filename.
    """

    report = report_for(
        gate,
        tmp_path,
        _transfer_body(shape, "3", "open({call}, 'w', closefd=False)\nPath('3').read_text()\n"),
    )
    assert "3" in unwritten(report), shape
    assert "3" not in _bounded_writers(gate, tmp_path), shape
    assert report.unresolvable > 0, shape


@pytest.mark.parametrize("shape", sorted(RETURN_TRANSFER_SHAPES))
def test_every_supported_return_transfer_shape_keeps_a_string_a_filename(gate, tmp_path, shape):
    """The companion for each shape. A withhold one case too wide loses a real writer, and these
    four are the cases the withhold above runs closest to."""

    report = report_for(
        gate, tmp_path, _transfer_body(shape, "'3'", "open({call}, 'w')\nPath('3').read_text()\n")
    )
    assert "3" not in unwritten(report), shape
    assert _bounded_writers(gate, tmp_path) == {"3"}, shape
    assert report.unresolvable == 0, shape


CHAINED_TRANSFER_SHAPES = {
    "chained-call": "def inner():\n    return {scalar}\ndef value():\n    return inner()\n",
    "chained-argument": ("def inner():\n    return {scalar}\ndef value(held):\n    return held\n"),
    "arithmetic-parameter": "def value(held):\n    return held + {tail}\n",
}


def _chained_body(shape, scalar, tail, call_and_use):
    definition = CHAINED_TRANSFER_SHAPES[shape].format(scalar=scalar, tail=tail)
    call = {
        "chained-call": "value()",
        "chained-argument": "value(inner())",
        "arithmetic-parameter": f"value({scalar})",
    }[shape]
    return definition + f"held = {call}\n" + call_and_use


@pytest.mark.parametrize("shape", sorted(CHAINED_TRANSFER_SHAPES))
def test_a_scalar_survives_one_call_deeper(gate, tmp_path, shape):
    """The chain rows: `return inner()`, a call as an argument, arithmetic over a parameter.

    Naming these as unsupported in a docstring did not close them — the resolver kept following
    the chain and kept producing a bounded writer, so the limit lived in prose while the report
    made the wrong claim (root, 2026-09-07). The folding goes one call deeper instead, bounded, and
    a self-recursive helper still terminates.
    """

    report = report_for(
        gate,
        tmp_path,
        _chained_body(shape, "3", "1", "open(held, 'w', closefd=False)\nPath('31').read_text()\n"),
    )
    assert not _bounded_writers(gate, tmp_path), shape
    assert report.unresolvable > 0, shape


@pytest.mark.parametrize("shape", sorted(CHAINED_TRANSFER_SHAPES))
def test_a_chained_string_is_still_a_filename(gate, tmp_path, shape):
    """The companion for each chain row: a string through the same shapes still names its file."""

    report = report_for(gate, tmp_path, _chained_body(shape, "'3'", "'1'", "open(held, 'w')\n"))
    assert _bounded_writers(gate, tmp_path), shape
    assert report.unresolvable == 0, shape


@pytest.mark.parametrize(
    ("body", "argument", "descriptor"),
    [
        ("    held = 3\n    return held\n", "'3'", True),
        ("    held = '3'\n    return held\n", "3", False),
        ("    held = 3\n    return held\n    held = '3'\n", None, True),
        ("    held = '3'\n    return held\n    held = 3\n", None, False),
    ],
    ids=["parameter-rebound-int", "parameter-rebound-str", "unreachable-int", "unreachable-str"],
)
def test_the_helper_scope_follows_execution_order(gate, tmp_path, body, argument, descriptor):
    """Order is the difference between a descriptor and a filename.

    A hand-rolled scope applied every body assignment and then overlaid the parameters, which
    reverses execution order — `def f(held): held = 3; return held` called with `'3'` returned the
    ARGUMENT — and it visited assignments *after* the return, so a dead rebinding decided the type
    (review findings, root, 2026-09-07, in both directions). The scope is now built with the same
    machinery the path resolver uses and walked to the return, rather than a second approximation
    of Python.

    Both directions matter: reversing the order does not merely miss a descriptor, it also
    withholds a real filename.
    """

    header = "def value(held):\n" if argument is not None else "def value():\n"
    call = f"value({argument})" if argument is not None else "value()"
    mode = "'w', closefd=False" if descriptor else "'w'"
    report = report_for(
        gate, tmp_path, header + body + f"open({call}, {mode})\nPath('3').read_text()\n"
    )

    if descriptor:
        assert "3" in unwritten(report)
        assert "3" not in _bounded_writers(gate, tmp_path)
        assert report.unresolvable > 0
    else:
        assert "3" not in unwritten(report)
        assert _bounded_writers(gate, tmp_path) == {"3"}
        assert report.unresolvable == 0


def test_a_self_recursive_helper_terminates(gate, tmp_path):
    """Depth is bounded because depth is not evidence — and because a helper returning its own
    call would otherwise not terminate. It certifies nothing, which is the right answer."""

    report = report_for(gate, tmp_path, "def loop():\n    return loop()\nopen(loop(), 'w')\n")
    assert not _bounded_writers(gate, tmp_path)
    assert report.unresolvable > 0


def test_an_unestablished_return_is_not_silently_a_filename(gate, tmp_path):
    """Past the enumerated shapes the answer is "not established", and the boundary treats that as
    it always has. Naming the limit is the point: the table above is a claim about what IS covered,
    so it needs a row that is deliberately outside it."""

    report = report_for(
        gate,
        tmp_path,
        "def value(held):\n    return held\nopen(value(input()), 'w')\n",
    )
    assert not _bounded_writers(gate, tmp_path)
    assert report.unresolvable > 0


def test_a_glob_error_reaches_the_durable_report(gate, tmp_path):
    """The console said [REPORT-ERROR] and the JSON said `status=complete, errors=[]`.

    `_report_glob_error` only printed and updated a process-wide dedup set, so the artifact a
    later reader consumes carried a completeness claim the run had already contradicted — and the
    status field is computed from `report.errors`, so the claim was not merely missing detail, it
    was wrong. The second analysis matters too: the translator is memoised, so a run after the
    first would have produced an error-free report for the same defect.
    """

    (tmp_path / "shared").mkdir()
    (tmp_path / "shared/example.py").write_text(
        "from pathlib import Path\n"
        "Path('cache/a.json').write_text('{}')\n"
        "Path('cache').glob('[z-a].json')\n"
    )

    for attempt in (1, 2):
        report = gate.analyse_consumer_side(tmp_path, [])
        assert report.errors, f"analysis {attempt} lost the glob error"
        assert any("[z-a]" in error for error in report.errors), attempt


def test_a_shadowed_str_is_not_the_builtin(gate, tmp_path):
    """Folding `str` by its spelling certified a file Python never writes.

    `def str(value): return 'actual'` makes `f'{str(1)}'` produce `actual`, and the constant
    channel folded the raw name — a defect I introduced one round earlier while teaching it the
    builtin. The resolver canonicalises names through the function table for exactly this reason;
    the constant channel now asks the same table before folding.
    """

    report = report_for(
        gate,
        tmp_path,
        "def str(value):\n    return 'actual'\n"
        "Path(f'artifacts/{str(1)}.json').write_text('{}')\n"
        "Path('artifacts/1.json').read_text()\n",
    )
    assert "artifacts/1.json" in unwritten(report)
    assert "artifacts/1.json" not in _bounded_writers(gate, tmp_path)


@pytest.mark.parametrize("shape", ["tilde", "absolute-home"])
def test_a_home_rooted_declaration_binds_home_rooted_accesses(gate, tmp_path, shape):
    """A producer declared under the home bound none of the home paths it selects.

    Accesses keep the home SYMBOLIC, because this scanner does not know whose home a path will be
    resolved against. The declaration was expanded against the scanner host's home instead, so the
    two representations could never meet and a scope-exited producer produced no warning at all.
    Both spellings of the same declaration must bind; the repository-rooted twin below is the
    control that this did not simply make everything match.
    """

    import json

    import yaml

    (tmp_path / "shared").mkdir()
    (tmp_path / "shared/example.py").write_text(
        "from pathlib import Path\n"
        "(Path.home() / '.cache/hapax/state.json').write_text('{}')\n"
        "(Path.home() / '.cache/hapax/state.json').read_text()\n"
    )
    declared = "~/.cache/hapax" if shape == "tilde" else str(Path.home() / ".cache/hapax")
    mass = tmp_path / "mass.yaml"
    mass.write_text(
        yaml.safe_dump(
            {
                "members": [
                    {
                        "id": "synthetic-producer",
                        "location": {"path": declared, "patterns": ["*.json"]},
                    }
                ]
            }
        )
    )
    frame = tmp_path / "elements.json"
    frame.write_text(
        json.dumps(
            [
                {
                    "id": "frame:relevance-report",
                    "kind": "relevance_report",
                    "payload": {
                        "verdicts": [
                            {
                                "subject": {"member_id": "synthetic-producer"},
                                "relation": "scope_exited",
                                "verdict": "TRUE",
                            }
                        ]
                    },
                }
            ]
        )
    )

    report = gate.analyse_consumer_side(tmp_path, [], frame_path=frame, mass_path=mass)
    assert "consumer-reads-decayed-producer" in {finding.kind for finding in report.findings}


def test_an_unknown_interpolation_stays_unbounded(gate, tmp_path):
    """The companion, and the one I wrongly alleged was a certification defect: an unknown
    component still widens to a wildcard, and that wildcard is **unbounded**, so it certifies
    nothing and the reader keeps its orphan. Do not collapse empty into unknown, or upgrade
    unknown into a bounded pattern."""

    report = report_for(
        gate,
        tmp_path,
        "x = input()\nPath(f'{x}/a.json').write_text('{}')\nPath('anything/a.json').read_text()\n",
    )
    # The interpolated write IS located — it just cannot be resolved to a path, so it stays
    # unbounded and the reader is orphaned under the located-writer sentence, not the absent one.
    assert "anything/a.json" in unwritten(report, UNRESOLVED_WRITER)
    assert "*/a.json" not in _bounded_writers(gate, tmp_path)
    assert report.unresolvable > 0


def test_a_lone_walrus_return_is_its_value_not_its_targets_old_binding(gate, tmp_path):
    """`(x := v)` IS `v`, and the target still held its previous value when the summary ran.

    All three resolvers read `NamedExpr.target`, which works only once the walker has applied the
    binding — and a return statement is summarised before that happens. So this helper's returned
    name was certified as `artifacts/lexical.json`, a file the code never writes, with nothing
    unresolved to show for it (review finding, codex, 2026-09-07, `check-producer-consumers.py`
    :4454; reproduced identically at `54b818b93`, so it predates the shared-walk adoption).

    The control below is the same helper without the walrus: it certified the right name before
    and after, which is what makes the pair a measurement of the assignment expression rather than
    of returning a constant.
    """

    report = report_for(
        gate,
        tmp_path,
        "def value():\n"
        "    name = 'artifacts/lexical.json'\n"
        "    return (name := 'artifacts/walrus.json')\n"
        "open(value(), 'w').close()\n"
        "Path('artifacts/walrus.json').read_text()\n"
        "Path('artifacts/lexical.json').read_text()\n",
    )
    writers = _bounded_writers(gate, tmp_path)
    assert "artifacts/walrus.json" in writers, "the walrus's value is what the helper returns"
    assert "artifacts/lexical.json" not in writers, "the target's stale binding is not written"
    assert "artifacts/lexical.json" in unwritten(report), "so its reader keeps its orphan"


def test_the_plain_return_beside_it_is_unchanged(gate, tmp_path):
    """The twin of the row above: no assignment expression, same shape, same two readers."""

    report = report_for(
        gate,
        tmp_path,
        "def value():\n"
        "    name = 'artifacts/lexical.json'\n"
        "    return 'artifacts/plain.json'\n"
        "open(value(), 'w').close()\n"
        "Path('artifacts/plain.json').read_text()\n"
        "Path('artifacts/lexical.json').read_text()\n",
    )
    assert "artifacts/plain.json" in _bounded_writers(gate, tmp_path)
    assert "artifacts/lexical.json" in unwritten(report)


@pytest.mark.parametrize(
    ("body", "truth"),
    [
        ("return f'{x}{(x := \"actual\")}'", "wrongactual"),
        ("return f'{(x := \"actual\")}{x}'", "actualactual"),
        ("return (x := 'actual') + x", "actualactual"),
    ],
    ids=["read-then-assign", "assign-then-read", "addition-form"],
)
def test_an_order_dependent_walrus_certifies_what_python_builds(gate, tmp_path, body, truth):
    """One expression that both assigns a name and reads it: operands are folded in order.

    Python evaluates operands left to right, so these three build `wrongactual`, `actualactual`
    and `actualactual`. Folding every operand against one binding snapshot certified `wrongwrong`
    for all three at `54b818b93` and `858e387bd` alike — four wrong filenames across the
    coordinator's twelve helper cases (2026-09-07 12:18), pre-existing rather than introduced by
    the shared-walk adoption.

    **A guard I wrote for these was withdrawn before it shipped.** Recognising "assigns a name and
    reads it" syntactically and withholding everywhere broke three committed controls — the nested
    receiver operands and the callee-identity capture — which are the same syntax and which this
    module *already resolves correctly*, by freezing an operand's value before a later operand
    rebinds its source. Refusing to model evaluation order was not available as a policy while the
    module already modelled it where it mattered; a rule that cannot tell those apart is the wrong
    rule, and "certify nothing" would have been a loss of precision sold as safety.

    `_published_bindings` extends the freezing the call path already does to the two places that
    fold a *sequence* of operands: an earlier interpolation's or operand's `:=` is visible to the
    later ones and to nothing before it. Reading the assignment's value rather than its target is
    the other half, and neither half alone gets all four cases right.
    """

    report = report_for(
        gate,
        tmp_path,
        f"def value(x):\n    {body}\nopen(value('wrong'), 'w').close()\n"
        f"Path({truth!r}).read_text()\n",
    )
    assert [
        pattern
        for pattern in _bounded_writers(gate, tmp_path)
        if pattern.startswith(("wrong", "actual"))
    ] == [truth], "the certified writer is the string Python actually builds"
    assert truth not in unwritten(report), "so the reader of that file is not an orphan"


@pytest.mark.parametrize(
    ("body", "truth"),
    [
        ('return f\'{(x := "a") + (x := x + "b")}{x}\'', "aabab"),
        ('return f\'{(x := (x := "a") + "b")}{x}\'', "abab"),
    ],
    ids=["a-sibling-rebinds-what-the-next-operand-reads", "an-inner-binding-completes-first"],
)
def test_nested_assignment_expressions_publish_in_completion_order(gate, tmp_path, body, truth):
    """Two assignment expressions in one interpolation, and both orderings were wrong.

    Publishing each `:=` against the scope its OPERAND started in read `x` at its entry value, so
    `(x := "a") + (x := x + "b")` certified `aabwrongb` where Python builds `aabab`. And walking
    with `ast.walk` is breadth-first, which reaches an outer assignment before the one nested
    inside it — the reverse of the order they complete — so `(x := (x := "a") + "b")` published
    the inner binding last and certified `aba` where Python builds `abab`. Both reproduce at
    `529e625c3` and at `858e387bd` (root, 2026-09-07), so they are the module's boundary rather
    than a regression the ordered publication introduced.

    Folding each binding against what has been published so far, in completion order, is one
    change answering both: it is what "left to right, innermost first" means when the thing being
    threaded is a scope.
    """

    report = report_for(
        gate,
        tmp_path,
        f"def value(x):\n    {body}\nopen(value('wrong'), 'w').close()\n"
        f"Path({truth!r}).read_text()\n",
    )
    assert [
        pattern
        for pattern in _bounded_writers(gate, tmp_path)
        if pattern.startswith(("a", "wrong"))
    ] == [truth], "nested bindings resolve to the string Python actually builds"
    assert truth not in unwritten(report)
