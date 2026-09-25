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


# ------------------------------------------------------------------------------------------
# C1 — the THIRD exit channel from an undecided region (codex, #4626, at `8417e866f`).
#
# `_demote_from` covers two channels: the access list, and the invocation ledger for arguments
# resolved in a callee's scope. A NAME bound inside the region left it fully CERTAIN, so a write
# through that name AFTER the region certified a path the program never touches. Isolated by
# moving only the write: inside the region it is already evidence, after it, certified.
#
#     write INSIDE  the undecided region -> ('artifacts/new.json', False)   demotion works
#     write AFTER   the undecided region -> ('artifacts/new.json', True)    certainty escaped
#
# Every defect row is paired with its DECIDED twin, which must keep certifying: this repair is a
# withhold, and a withhold one case too wide loses a real writer. The unchanged-binding, alias
# and ordinary-branch controls below exist because that is exactly how the `_orphaned` attempt
# went wrong — a demotion broad enough to remove the discrimination it existed to make.
# ------------------------------------------------------------------------------------------


def _unbounded_writers(gate, tmp_path):
    """The half `_bounded_writers` cannot see.

    A pattern is reported once per state, so a name certified by ANY surviving alternative shows
    up in `_bounded_writers` even when an over-broad demotion has quietly unbounded it in the
    others. Asserting only membership there is satisfiable by one untouched alternative — which
    is how the first version of the controls below stayed green while the discrimination they
    exist to pin was broken. The two sets together are the assertion; either alone is not.
    """

    accesses, _, _, _ = gate.collect_artifact_accesses(tmp_path)
    return {
        access.pattern for access in accesses if access.action == "write" and not access.bounded
    }


C1_UNDECIDED_REGIONS = [
    pytest.param(
        "def flag():\n    return not True\n",
        "flag() and (target := Path('artifacts/new.json'))\n",
        id="and-operator",
    ),
    pytest.param(
        "def flag():\n    return not False\n",
        "flag() or (target := Path('artifacts/new.json'))\n",
        id="or-operator",
    ),
    pytest.param(
        "def flag():\n    return not True\n",
        "(target := Path('artifacts/new.json')) if flag() else None\n",
        id="conditional-expression",
    ),
    pytest.param(
        "def size():\n    return 5\n",
        "size() < 1 < (target := Path('artifacts/new.json'))\n",
        id="comparison-chain",
    ),
]


@pytest.mark.parametrize("preamble,region", C1_UNDECIDED_REGIONS)
def test_a_name_bound_in_an_undecided_region_is_not_certain_after_it(
    gate, tmp_path: Path, preamble: str, region: str
) -> None:
    """The write is OUTSIDE every region; only the NAME is bound inside one.

    In each row Python writes `artifacts/old.json` — the operand carrying the walrus never runs —
    and reads `artifacts/new.json`, which nothing writes.
    """

    report = report_for(
        gate,
        tmp_path,
        preamble + "target = Path('artifacts/old.json')\n" + region + "target.write_text('{}')\n"
        "Path('artifacts/new.json').read_text()\n",
    )
    assert "artifacts/new.json" not in _bounded_writers(gate, tmp_path)
    # WITHHOLDING IS NOT ASSERTING ABSENCE. The writer was located and its execution is
    # undetermined, so the reader is unresolved — not reported as reading an unwritten artifact,
    # which is the claim this scanner is not entitled to make here.
    assert "artifacts/new.json" not in unwritten(report)
    assert "artifacts/new.json" in unwritten(report, UNRESOLVED_WRITER)


C1_DECIDED_REGIONS = [
    pytest.param("False and (target := Path('artifacts/new.json'))\n", id="and-operator"),
    pytest.param("True or (target := Path('artifacts/new.json'))\n", id="or-operator"),
    pytest.param(
        "(target := Path('artifacts/new.json')) if False else None\n",
        id="conditional-expression",
    ),
    pytest.param("2 < 1 < (target := Path('artifacts/new.json'))\n", id="comparison-chain"),
]


@pytest.mark.parametrize("region", C1_DECIDED_REGIONS)
def test_a_decided_operand_still_certifies_the_binding_it_leaves_standing(
    gate, tmp_path: Path, region: str
) -> None:
    """The twin that must keep working. A decided operand has no undecided region at all.

    `target` is certainly `artifacts/old.json`, so that write stays CERTIFIED. If this row goes
    unbounded the repair has stopped discriminating and is demoting on the shape of the syntax
    rather than on whether reachability was established.
    """

    report = report_for(
        gate,
        tmp_path,
        "target = Path('artifacts/old.json')\n" + region + "target.write_text('{}')\n"
        "Path('artifacts/old.json').read_text()\n",
    )
    assert "artifacts/old.json" in _bounded_writers(gate, tmp_path)
    assert "artifacts/old.json" not in unwritten(report)


def test_an_unchanged_binding_keeps_its_certainty_across_an_undecided_region(
    gate, tmp_path: Path
) -> None:
    """A name the region never touches is not made uncertain by standing next to one.

    The region binds `other`; `keep` is bound before it and never rebound, so the write through
    `keep` is as certain as it was. Demoting by position rather than by binding would fail here.
    """

    report = report_for(
        gate,
        tmp_path,
        "def flag():\n    return not True\n"
        "keep = Path('artifacts/keep.json')\n"
        "flag() and (other := Path('artifacts/new.json'))\n"
        "keep.write_text('{}')\n"
        "Path('artifacts/keep.json').read_text()\n",
    )
    assert "artifacts/keep.json" in _bounded_writers(gate, tmp_path)
    # And in NO state is it evidence-only: a demotion keyed to position rather than to binding
    # marks `keep` in the in-region alternatives while an earlier one still certifies it, which
    # membership above cannot see.
    assert "artifacts/keep.json" not in _unbounded_writers(gate, tmp_path)
    assert "artifacts/keep.json" not in unwritten(report)


def test_an_alias_of_an_unchanged_binding_keeps_its_certainty(gate, tmp_path: Path) -> None:
    """An alias made before the region still names the value it was given.

    Rebinding `base` inside the region does not retroactively change what `alias` holds, so the
    write through `alias` stays certified while the write through `base` does not.
    """

    report = report_for(
        gate,
        tmp_path,
        "def flag():\n    return not True\n"
        "base = Path('artifacts/keep.json')\n"
        "alias = base\n"
        "flag() and (base := Path('artifacts/new.json'))\n"
        "alias.write_text('{}')\n"
        "Path('artifacts/keep.json').read_text()\n",
    )
    assert "artifacts/keep.json" in _bounded_writers(gate, tmp_path)
    assert "artifacts/keep.json" not in _unbounded_writers(gate, tmp_path)
    assert "artifacts/keep.json" not in unwritten(report)


def test_ordinary_branches_keep_certifying_both_arms(gate, tmp_path: Path) -> None:
    """The no-broadening control, and the one most likely to catch an over-wide repair.

    An `if`/`else` under an undecided test is NOT this defect: both arms are reachable and the
    committed contract certifies both. This repair is about a binding made where reachability was
    never established, so this row must be untouched by it.
    """

    report_for(
        gate,
        tmp_path,
        "def flag():\n    return not True\n"
        "if flag():\n"
        "    target = Path('artifacts/a.json')\n"
        "else:\n"
        "    target = Path('artifacts/b.json')\n"
        "target.write_text('{}')\n",
    )
    assert {"artifacts/a.json", "artifacts/b.json"} <= _bounded_writers(gate, tmp_path)
    assert not {"artifacts/a.json", "artifacts/b.json"} & _unbounded_writers(gate, tmp_path)


def test_a_reached_walrus_is_demoted_too_and_that_is_the_accepted_cost(
    gate, tmp_path: Path
) -> None:
    """Stated openly rather than discovered later: this repair demotes a REAL writer.

    Here the operand does run and Python really does write `artifacts/new.json`. The scanner
    cannot decide `flag()`, so it cannot tell this row from the ones above — and the honest
    reading of "reachability not established" demotes it as well. The write is kept as evidence
    and the reader is unresolved, never reported absent; that discrimination is what makes the
    cost acceptable rather than a lost writer.
    """

    report = report_for(
        gate,
        tmp_path,
        "def flag():\n    return not False\n"
        "target = Path('artifacts/old.json')\n"
        "flag() and (target := Path('artifacts/new.json'))\n"
        "target.write_text('{}')\n"
        "Path('artifacts/new.json').read_text()\n",
    )
    assert "artifacts/new.json" not in _bounded_writers(gate, tmp_path)
    assert "artifacts/new.json" not in unwritten(report)
    assert "artifacts/new.json" in unwritten(report, UNRESOLVED_WRITER)


# ------------------------------------------------------------------------------------------
# C2 — an annotation expression that never runs (codex, #4626, at `:5330`).
#
# TWO independent conditions, and a repair keyed to either alone is wrong at four positions:
#
#   PEP 563   `from __future__ import annotations` — nothing annotated evaluates.
#   PEP 526   a variable annotation in a FUNCTION body never evaluates, future import or not.
#             Root's counterexample, and the reason module state is necessary but not sufficient.
#
# A class body is not a function body even nested inside one, so `class_in_function` is the row
# that decides how the predicate is worded rather than merely another position.
#
# These cases cannot use `report_for`: it prepends its own imports, and a `from __future__` line
# after them is a misplaced-future SyntaxError. `_parse` answers a SyntaxError with None and the
# file is skipped in silence — so the postponed rows would pass while measuring nothing at all.
# ------------------------------------------------------------------------------------------

_ANN = "Path('artifacts/ann.json').write_text('{}')"
_VAL = "Path('artifacts/val.json').write_text('{}')"


def _annotation_writers(gate, tmp_path: Path, body: str, *, postponed: bool):
    """(certified, evidence-only) write patterns for one annotated module."""

    _write(
        tmp_path,
        "shared/annotated.py",
        ("from __future__ import annotations\n" if postponed else "")
        + "from pathlib import Path\n"
        + body,
    )
    accesses, _, _, _ = gate.collect_artifact_accesses(tmp_path)
    writes = [access for access in accesses if access.action == "write"]
    return (
        {access.pattern for access in writes if access.bounded},
        {access.pattern for access in writes if not access.bounded},
    )


#: Positions where the annotation DOES evaluate when the module does not defer.
_EVALUATED_POSITIONS = [
    pytest.param("x: " + _ANN + "\n", id="module_annassign"),
    pytest.param("class K:\n    x: " + _ANN + "\n", id="class_attribute"),
    pytest.param("def use(v: " + _ANN + "):\n    return v\n", id="arg_annotation"),
    pytest.param("def use() -> " + _ANN + ":\n    return 1\n", id="return_annotation"),
    pytest.param(
        "def f():\n    class K:\n        x: " + _ANN + "\n    return K\nf()\n",
        id="class_in_function",
    ),
]


@pytest.mark.parametrize("body", _EVALUATED_POSITIONS)
def test_an_evaluated_annotation_still_certifies_its_write(gate, tmp_path: Path, body: str) -> None:
    """The half that must keep working. Without the future import these annotations DO run."""

    certified, evidence = _annotation_writers(gate, tmp_path, body, postponed=False)
    assert "artifacts/ann.json" in certified
    assert "artifacts/ann.json" not in evidence


@pytest.mark.parametrize("body", _EVALUATED_POSITIONS)
def test_a_deferred_annotation_writes_nothing_at_all(gate, tmp_path: Path, body: str) -> None:
    """With PEP 563 the annotation is a string; no write exists to certify OR to keep as evidence.

    Absent rather than unbounded, and the distinction is deliberate: an undecided region withholds
    because reachability is UNKNOWN, while this is decided — the expression provably does not run,
    exactly like a `case` whose guard is constant-false. Recording evidence here would invent an
    unresolved site the program does not have.
    """

    certified, evidence = _annotation_writers(gate, tmp_path, body, postponed=True)
    assert "artifacts/ann.json" not in certified
    assert "artifacts/ann.json" not in evidence


@pytest.mark.parametrize("postponed", [False, True], ids=["eager", "postponed"])
def test_a_function_local_annotation_never_evaluates(gate, tmp_path: Path, postponed: bool) -> None:
    """Root's counterexample: the module does NOT defer, and the annotation still never runs.

    A gate keyed only to the future import cannot express this row — which is why the eager case
    is parametrized here rather than serving as a control that the write survives.
    """

    certified, evidence = _annotation_writers(
        gate, tmp_path, "def f():\n    x: " + _ANN + "\nf()\n", postponed=postponed
    )
    assert "artifacts/ann.json" not in certified
    assert "artifacts/ann.json" not in evidence


@pytest.mark.parametrize("postponed", [False, True], ids=["eager", "postponed"])
def test_the_value_beside_a_dead_annotation_still_runs(
    gate, tmp_path: Path, postponed: bool
) -> None:
    """Suppressing the annotation must not suppress the assignment beside it.

    `x: <annotation> = <value>` in a function body runs the VALUE and not the annotation, in both
    modes. This is the row that catches a repair which skips the whole statement.
    """

    certified, evidence = _annotation_writers(
        gate, tmp_path, "def f():\n    x: " + _ANN + " = " + _VAL + "\nf()\n", postponed=postponed
    )
    assert "artifacts/val.json" in certified
    assert "artifacts/val.json" not in evidence
    assert "artifacts/ann.json" not in certified


def test_a_subscript_target_runs_even_when_its_annotation_does_not(gate, tmp_path: Path) -> None:
    """`d[<target>]: <annotation>` evaluates the target expression whether or not the module defers."""

    body = "d = {}\nd[Path('artifacts/tgt.json').write_text('{}')]: " + _ANN + "\n"
    certified, evidence = _annotation_writers(gate, tmp_path, body, postponed=True)
    assert "artifacts/tgt.json" in certified
    assert "artifacts/tgt.json" not in evidence
    assert "artifacts/ann.json" not in certified


@pytest.mark.parametrize("postponed", [False, True], ids=["eager", "postponed"])
def test_a_parameter_default_is_not_an_annotation(gate, tmp_path: Path, postponed: bool) -> None:
    """Defaults run when the `def` executes, deferred annotations included.

    Correct in both modes today; kept as a regression guard because a gate keyed to the future
    import could plausibly swallow the defaults sitting in the same signature.
    """

    body = "def use(a=Path('artifacts/def.json').write_text('{}')):\n    return a\n"
    certified, evidence = _annotation_writers(gate, tmp_path, body, postponed=postponed)
    assert "artifacts/def.json" in certified
    assert "artifacts/def.json" not in evidence


# ------------------------------------------------------------------------------------------
# C3 — a `case` body that cannot run (codex, #4626, at `:5579`).
#
# The `ast.Match` handler scanned EVERY case body as certainly executed and called
# `_demote_from` nowhere, so it had not one region but none. Two entry conditions, only one of
# which codex named:
#
#   constant-false guard   `case 1 if False:` — the guard runs and selects nothing.
#   pattern cannot match   `match 1: case 2:` — the case is never entered at all.
#
# THREE OUTCOMES, and only one of them removes anything:
#
#   decided dead   skipped entirely — the case, its guard and its body never run.
#   decided live   certified, unchanged. Positive constant and helper cases must survive.
#   undecided      EVIDENCE. Demoted across all three channels — accesses, callee invocation
#                  bindings and escaping name bindings — never certified and never dropped.
#
# Unknown pattern entry governs the GUARD as well as the body, and a decided later case is not
# certainly reached after an undecided earlier one.
#
# My first draft got the undecided outcome backwards: it left unknown cases certified, reasoning
# from `test_check_consumer_side_binding_integrity.py:1682` (`match flags[i]: case True:`, which
# asserts `unresolvable == 0`). That test preserves possible READ identities; it does not license
# certifying unknown WRITES, and the wide reading was intentional. See the conflict note in the
# handoff: the counter assertion is exposed deliberately rather than kept green by exempting
# unknown writes.
# ------------------------------------------------------------------------------------------

_DEAD_CASES = [
    pytest.param("match 1:\n    case 1 if False:\n", id="constant_false_guard"),
    pytest.param("match 1:\n    case 2:\n", id="value_cannot_match"),
    pytest.param("match 1:\n    case True:\n", id="singleton_is_not_equal"),
    pytest.param("match 1:\n    case 2 | 3:\n", id="no_alternative_matches"),
    pytest.param("match 1:\n    case 2 as seen:\n", id="capture_of_a_dead_value"),
    pytest.param("match 1:\n    case 1:\n        pass\n    case 1:\n", id="after_a_certain_match"),
]


@pytest.mark.parametrize("header", _DEAD_CASES)
def test_a_case_that_cannot_run_certifies_nothing(gate, tmp_path: Path, header: str) -> None:
    """Python enters none of these bodies, so none of them may certify a producer."""

    report = report_for(
        gate,
        tmp_path,
        header + "        Path('artifacts/never.json').write_text('{}')\n"
        "Path('artifacts/never.json').read_text()\n",
    )
    assert "artifacts/never.json" not in _bounded_writers(gate, tmp_path)
    # Decided, not unknown: like a constant-false conditional arm, the write is absent rather
    # than withheld, so the reader is genuinely reading an unwritten artifact.
    assert "artifacts/never.json" in unwritten(report)


_LIVE_CASES = [
    pytest.param("match 1:\n    case 1 if True:\n", id="constant_true_guard"),
    pytest.param("match 1:\n    case 1:\n", id="value_matches"),
    pytest.param("match 1:\n    case 1 | 9:\n", id="an_alternative_matches"),
    pytest.param("match 1:\n    case 1 as seen:\n", id="capture_of_a_live_value"),
    pytest.param("match None:\n    case None:\n", id="singleton_matches"),
    pytest.param("match 1:\n    case other:\n", id="bare_capture_always_matches"),
]


@pytest.mark.parametrize("header", _LIVE_CASES)
def test_a_case_that_does_run_still_certifies(gate, tmp_path: Path, header: str) -> None:
    """The twin half. Every row here is entered at runtime and must keep its certification."""

    report = report_for(
        gate,
        tmp_path,
        header + "        Path('artifacts/written.json').write_text('{}')\n"
        "Path('artifacts/written.json').read_text()\n",
    )
    assert "artifacts/written.json" in _bounded_writers(gate, tmp_path)
    assert "artifacts/written.json" not in _unbounded_writers(gate, tmp_path)
    assert "artifacts/written.json" not in unwritten(report)


def test_a_reached_guard_keeps_its_effects(gate, tmp_path: Path) -> None:
    """The guard runs whenever the PATTERN matches, whatever it then evaluates to.

    The pattern here is decided-match, so the guard definitely executes and its write is
    certified — the requirement that this repair must not trade away while removing dead bodies.

    The guard's own OUTCOME is undecided here — a call is not literal-decidable — so the body it
    may select is demoted, and the row below covers that half explicitly. "Guard runs and is
    decided FALSE" remains only constructible with an effect-free guard, which
    `constant_false_guard` covers.
    """

    report = report_for(
        gate,
        tmp_path,
        "match 1:\n"
        "    case 1 if Path('artifacts/guard.json').write_text('{}'):\n"
        "        Path('artifacts/body.json').write_text('{}')\n"
        "Path('artifacts/guard.json').read_text()\n",
    )
    assert "artifacts/guard.json" in _bounded_writers(gate, tmp_path)
    assert "artifacts/guard.json" not in _unbounded_writers(gate, tmp_path)
    assert "artifacts/guard.json" not in unwritten(report)


#: A helper this scanner CANNOT summarise. `return not True` is the established idiom for it in
#: this file; a helper that returns a literal IS resolved by the existing summary, so using one
#: here would have written an "undecided" control that is actually decided — which is exactly the
#: mistake root found in my first draft of these rows.
_OPAQUE_FALSE = "def opaque():\n    return not True\n"

_UNDECIDED_CASES = [
    pytest.param(_OPAQUE_FALSE + "match opaque():\n    case 1:\n", id="unknown_subject"),
    pytest.param(_OPAQUE_FALSE + "match 1:\n    case 1 if opaque():\n", id="unknown_guard"),
    pytest.param("match 1:\n    case [x]:\n", id="sequence_pattern_on_an_int"),
    pytest.param("match 1:\n    case {'k': v}:\n", id="mapping_pattern_on_an_int"),
    pytest.param("match 1:\n    case seen if seen:\n", id="guard_reads_a_capture"),
]


@pytest.mark.parametrize("header", _UNDECIDED_CASES)
def test_an_undecided_case_is_evidence_and_never_certified(
    gate, tmp_path: Path, header: str
) -> None:
    """UNKNOWN IS NOT CERTIFIED, and it is not absent either.

    Each row is a case this scanner cannot decide without a structural pattern evaluator, which
    is out of scope. The write is retained as evidence — the program may perform it — and the
    certification is withheld, the same three-channel demotion the operator and conditional sites
    apply. The sequence and mapping rows are the ones my first draft got backwards: it asserted
    they certify, which certifies a write against an integer subject that cannot match.
    """

    report_for(
        gate,
        tmp_path,
        header + "        Path('artifacts/kept.json').write_text('{}')\n"
        "Path('artifacts/kept.json').read_text()\n",
    )
    assert "artifacts/kept.json" not in _bounded_writers(gate, tmp_path)
    assert "artifacts/kept.json" in _unbounded_writers(gate, tmp_path)


_HELPER_CONSTANT_CASES = [
    pytest.param(
        "def subject():\n    return 1\nmatch subject():\n    case 1:\n", id="helper_subject"
    ),
    pytest.param(
        "def flag():\n    return True\nmatch 1:\n    case 1 if flag():\n", id="helper_guard"
    ),
]


@pytest.mark.parametrize("header", _HELPER_CONSTANT_CASES)
def test_a_helper_returning_a_literal_stays_decided(gate, tmp_path: Path, header: str) -> None:
    """POSITIVE CASES MUST SURVIVE. The existing helper summary resolves literal returns.

    I first filed both of these as "undecided" controls. They are not: the summary resolves them,
    so they are decided-live and must keep certifying. Forcing uncertainty here would be
    perpetual, not honest — root's point, and the reason `_OPAQUE_FALSE` above uses `not True`.
    """

    report = report_for(
        gate,
        tmp_path,
        header + "        Path('artifacts/written.json').write_text('{}')\n"
        "Path('artifacts/written.json').read_text()\n",
    )
    assert "artifacts/written.json" in _bounded_writers(gate, tmp_path)
    assert "artifacts/written.json" not in _unbounded_writers(gate, tmp_path)
    assert "artifacts/written.json" not in unwritten(report)


def test_an_effect_bearing_guard_keeps_its_write_while_its_body_stays_uncertain(
    gate, tmp_path: Path
) -> None:
    """The row I deleted as unconstructible. It is constructible — with an UNDECIDED body.

    `(<write>, False)[1]` is not literal-decidable, so the guard's OUTCOME is unknown. But the
    pattern is decided-match and entry is established, so the guard itself definitely RUNS and
    its write stays certified; only the body it may or may not select is demoted. I had asserted
    the body was absent, which the decision procedure cannot produce, and then concluded the whole
    row was impossible. Uncertainty was the missing third value, not a reason to drop the case.
    """

    report = report_for(
        gate,
        tmp_path,
        "match 1:\n"
        "    case 1 if (Path('artifacts/guard.json').write_text('{}'), False)[1]:\n"
        "        Path('artifacts/body.json').write_text('{}')\n"
        "Path('artifacts/guard.json').read_text()\n",
    )
    assert "artifacts/guard.json" in _bounded_writers(gate, tmp_path)
    assert "artifacts/guard.json" not in _unbounded_writers(gate, tmp_path)
    assert "artifacts/guard.json" not in unwritten(report)
    assert "artifacts/body.json" not in _bounded_writers(gate, tmp_path)
    assert "artifacts/body.json" in _unbounded_writers(gate, tmp_path)


def test_a_guard_under_an_unknown_pattern_is_itself_uncertain(gate, tmp_path: Path) -> None:
    """Unknown pattern ENTRY governs the guard, not only the body.

    The guard runs only if the pattern matches. When the subject cannot be resolved, the guard's
    own write is no better established than the case, so it is evidence rather than certified.
    """

    report_for(
        gate,
        tmp_path,
        _OPAQUE_FALSE + "match opaque():\n"
        "    case 1 if Path('artifacts/guard.json').write_text('{}'):\n"
        "        pass\n",
    )
    assert "artifacts/guard.json" not in _bounded_writers(gate, tmp_path)
    assert "artifacts/guard.json" in _unbounded_writers(gate, tmp_path)


def test_a_decided_case_after_an_undecided_one_is_not_certainly_reached(
    gate, tmp_path: Path
) -> None:
    """A `match` runs the FIRST matching case, so an earlier maybe makes a later certainty a maybe.

    The second case is decided-match with no guard. It is still not certainly reached, because the
    first case may already have selected — the ordering rule that a per-case decision, taken in
    isolation, cannot see.
    """

    report_for(
        gate,
        tmp_path,
        _OPAQUE_FALSE + "match 1:\n"
        "    case 1 if opaque():\n"
        "        Path('artifacts/first.json').write_text('{}')\n"
        "    case 1:\n"
        "        Path('artifacts/second.json').write_text('{}')\n",
    )
    assert "artifacts/second.json" not in _bounded_writers(gate, tmp_path)
    assert "artifacts/second.json" in _unbounded_writers(gate, tmp_path)


def test_a_binding_escaping_an_uncertain_case_does_not_certify_later(gate, tmp_path: Path) -> None:
    """The C1 channel, reached through a `match`.

    The write is outside the statement entirely; only the NAME is bound inside a case whose entry
    is unknown. Certainty must not leave with it, while the binding made before the statement and
    never reassigned stays certified.
    """

    report_for(
        gate,
        tmp_path,
        _OPAQUE_FALSE + "target = Path('artifacts/old.json')\n"
        "match 1:\n"
        "    case 1 if opaque():\n"
        "        target = Path('artifacts/new.json')\n"
        "target.write_text('{}')\n",
    )
    assert "artifacts/new.json" not in _bounded_writers(gate, tmp_path)
    assert "artifacts/new.json" in _unbounded_writers(gate, tmp_path)


# ------------------------------------------------------------------------------------------
# Controls authored 2026-09-09 as proposals, without being run; the rows below still carry that
# "PROPOSED" label. Executed 2026-09-25: all pass. Each root's repair was mutation-verified
# separately:
#   - a never-marked undecided-region binding turns 13 red;
#   - a never-false guard turns 6 red;
#   - an always-eager annotation reading turns 6 red.
# Exact bytes were restored after each.
#
# Three groups, one per defect root reproduced independently:
#
#   capped mixed marker composition   uncertainty must survive the branch-state collapse
#   definite replacement              a certain rebinding must still clear it afterwards
#   reached-guard state               a guard that ran governs selection AND nonselection
# ------------------------------------------------------------------------------------------

_OPAQUE = "def opaque():\n    return not True\n"


def _capped(gate, tmp_path: Path, monkeypatch, source: str, cap: int = 2):
    """Run the collector with the disjunctive-state cap lowered, as the integrity corpus does."""

    monkeypatch.setattr(gate, "_MAX_BRANCH_STATES", cap)
    _write(tmp_path, "shared/capped.py", "from pathlib import Path\n" + source)
    accesses, _, _, _ = gate.collect_artifact_accesses(tmp_path)
    writes = [access for access in accesses if access.action == "write"]
    return (
        {access.pattern for access in writes if access.bounded},
        {access.pattern for access in writes if not access.bounded},
    )


@pytest.mark.parametrize("cap", [1, 2, 3])
def test_uncertainty_survives_the_branch_state_collapse(
    gate, tmp_path: Path, monkeypatch, cap: int
) -> None:
    """PROPOSED. Past the cap, a mixed marker must not be dropped.

    `_merge_states` joins internal keys only when every alternative agrees, so a name marked in
    some merged states and unmarked in others matched no rule and lost its flag entirely — the
    binding regained certainty and later writes through it were certified again. Enough undecided
    cases are generated here to exceed `cap` and force the collapse.
    """

    cases = "".join(
        f"    case {i}:\n        target = Path('artifacts/branch-{i}.json')\n"
        for i in range(cap + 3)
    )
    certified, evidence = _capped(
        gate,
        tmp_path,
        monkeypatch,
        _OPAQUE + "target = Path('artifacts/start.json')\n"
        "match opaque():\n" + cases + "target.write_text('{}')\n",
        cap=cap,
    )
    branches = {f"artifacts/branch-{i}.json" for i in range(cap + 3)}
    assert not (branches & certified), "a collapsed uncertain binding was certified"
    # EVERY enumerated alternative, not merely one of them: the preservation obligation is that
    # collapsing bounds the state count without deleting a statically known pattern, so a rule
    # that kept a single branch and dropped the rest would satisfy an intersection and still be
    # the defect.
    assert branches <= evidence, "a concrete branch alternative was lost, not just uncertified"


@pytest.mark.parametrize("cap", [1, 2, 3])
def test_a_definite_replacement_after_a_collapse_certifies_again(
    gate, tmp_path: Path, monkeypatch, cap: int
) -> None:
    """PROPOSED, and the twin that keeps the rule above from being a blanket withhold.

    The marker is cleared by rebinding — `_apply_assignment` pops the key and re-sets it only
    from the RHS — so a definite literal assignment after the collapse must certify normally.
    Without this row the composition rule could withhold everything downstream and still look
    correct.
    """

    cases = "".join(
        f"    case {i}:\n        target = Path('artifacts/branch-{i}.json')\n"
        for i in range(cap + 3)
    )
    certified, evidence = _capped(
        gate,
        tmp_path,
        monkeypatch,
        _OPAQUE + "target = Path('artifacts/start.json')\n"
        "match opaque():\n" + cases + "target = Path('artifacts/fixed.json')\n"
        "target.write_text('{}')\n",
        cap=cap,
    )
    assert "artifacts/fixed.json" in certified
    assert "artifacts/fixed.json" not in evidence


@pytest.mark.parametrize(
    "guard",
    [
        "(artifact := Path('artifacts/actual.json')) and False",
        "(artifact := Path('artifacts/actual.json')) and True",
        "((artifact := Path('artifacts/actual.json')), False)[1]",
        "((artifact := Path('artifacts/actual.json')), True)[1]",
    ],
    ids=["and_false", "and_true", "tuple_false", "tuple_true"],
)
def test_a_reached_guard_governs_the_state_after_the_match(
    gate, tmp_path: Path, guard: str
) -> None:
    """PROPOSED. A guard that definitely ran must not leave the pre-match binding standing.

    The pattern decides, so entry is established and the guard evaluates whatever it returns. Its
    walrus rebinds `artifact`, and control leaves the statement with that binding — selected or
    not. Re-forking the pre-match state restored `stale.json` and CERTIFIED it, a path the program
    never writes; `pending` now threads the post-guard state through the cases and the
    fall-through instead.

    All four guards are compound and therefore undecided, which is exactly why they exercise the
    threading rather than the decided-false branch.
    """

    report_for(
        gate,
        tmp_path,
        "artifact = Path('artifacts/stale.json')\n"
        f"match 1:\n    case 1 if {guard}:\n        pass\n"
        "artifact.write_text('{}')\n",
    )
    certified = _bounded_writers(gate, tmp_path)
    assert "artifacts/stale.json" not in certified
    assert "artifacts/actual.json" in certified | _unbounded_writers(gate, tmp_path)


def test_an_unentered_case_still_leaves_its_alternative_standing(gate, tmp_path: Path) -> None:
    """PROPOSED, and the boundary of the threading rule.

    When the pattern is NOT decided the case may never be entered, so the pre-match binding is a
    real alternative and must survive beside the post-guard one — while the guard's own binding,
    made where entry was never established, stays evidence rather than being promoted by escaping.
    """

    report_for(
        gate,
        tmp_path,
        _OPAQUE + "artifact = Path('artifacts/before.json')\n"
        "match opaque():\n"
        "    case 1 if (artifact := Path('artifacts/inguard.json')) and False:\n"
        "        pass\n"
        "artifact.write_text('{}')\n",
    )
    assert "artifacts/before.json" in _bounded_writers(gate, tmp_path)
    assert "artifacts/inguard.json" not in _bounded_writers(gate, tmp_path)
    assert "artifacts/inguard.json" in _unbounded_writers(gate, tmp_path)
