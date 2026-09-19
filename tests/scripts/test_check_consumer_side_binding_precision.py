"""Precision canaries for the consumer-side scanner (sixth review round of #4626).

All three families found the same four defects: read sites resolved against assignments that
occur later in the scope; file-backed APIs the scanner does not model vanished without even an
unresolvable count; relative and ``from pkg import module`` imports never established the
producer's module name; and a repository-global helper table keyed by bare function name let one
module's ``artifact_path`` answer for another's.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check-producer-consumers.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_consumer_side_precision", SCRIPT_PATH)
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


#: Readers surfaced as having no ESTABLISHED producer, counted per reader — one kind at a time,
#: because which of the two the report chose IS the discrimination. An absent write is
#: `consumer-reads-unwritten-artifact`; a located write whose execution is undetermined is
#: `consumer-reads-artifact-with-unresolved-writer`. Every row below names the one it means.
ABSENT_WRITER = "consumer-reads-unwritten-artifact"
UNRESOLVED_WRITER = "consumer-reads-artifact-with-unresolved-writer"


def _orphaned(report, kind: str = ABSENT_WRITER) -> dict[tuple[Path, str], int]:
    counts: dict[tuple[Path, str], int] = {}
    for finding in report.findings:
        if finding.kind == kind:
            key = (finding.reader.path, finding.reader.pattern)
            counts[key] = counts.get(key, 0) + 1
    return counts


def test_a_read_sees_the_assignment_above_it_not_the_one_below(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def load_state():\n"
        "    artifact = Path('artifacts/orphan.json')\n"
        "    first = artifact.read_text()\n"
        "    artifact = Path('artifacts/second.json')\n"
        "    return first + artifact.read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    unwritten = _orphaned(report)
    assert (Path("shared/consumer.py"), "artifacts/orphan.json") in unwritten
    assert (Path("shared/consumer.py"), "artifacts/second.json") in unwritten


def test_a_read_before_any_assignment_is_unresolvable_not_borrowed(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def load_state():\n"
        "    first = artifact.read_text()\n"
        "    artifact = Path('artifacts/later.json')\n"
        "    return first\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert report.unresolvable == 1
    assert (Path("shared/consumer.py"), "artifacts/later.json") not in _orphaned(report)


def test_a_rebinding_to_an_unresolvable_value_forgets_the_old_path(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def load_state(choose):\n"
        "    artifact = Path('artifacts/first.json')\n"
        "    artifact = choose()\n"
        "    return artifact.read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert report.unresolvable == 1
    assert (Path("shared/consumer.py"), "artifacts/first.json") not in _orphaned(report)


def test_reads_inside_with_and_try_blocks_are_seen_once(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "ARTIFACT = Path('artifacts/blocky.json')\n"
        "def load_state():\n"
        "    try:\n"
        "        with open(ARTIFACT) as handle:\n"
        "            return handle.read()\n"
        "    except OSError:\n"
        "        return ARTIFACT.read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report).get((Path("shared/consumer.py"), "artifacts/blocky.json")) == 1


def test_sqlite_connect_is_a_modelled_read(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "import sqlite3\n"
        "from pathlib import Path\n"
        "DB = Path('cache/state.db')\n"
        "def load_rows():\n"
        "    return sqlite3.connect(DB)\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    matches = [
        finding
        for finding in report.findings
        if finding.reader.pattern == "cache/state.db"
        and finding.reader.operation == "sqlite3.connect"
    ]
    assert matches, [finding.reader for finding in report.findings]
    assert report.unrecognised_path_calls == {}


def test_an_unmodelled_callee_handed_a_path_is_reported_and_compared(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "import custom\n"
        "STATE = Path('cache/state.bin')\n"
        "def load_state():\n"
        "    return custom.load_blob(STATE)\n",
    )
    _write(
        tmp_path,
        "shared/writer.py",
        "from pathlib import Path\n"
        "STATE = Path('cache/state.bin')\n"
        "def save_state():\n"
        "    STATE.write_bytes(b'data')\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    # This used to assert that the resolved path was absent. That contradicted the scanner's
    # no-silent-read contract: an unknown callee must retain the pattern and producer comparison.
    assert report.unrecognised_path_calls == {"custom.load_blob": 1}
    matches = [
        finding
        for finding in report.findings
        if finding.reader.pattern == "cache/state.bin"
        and finding.kind == "consumer-reads-through-unmodelled-api"
    ]
    assert len(matches) == 1
    assert matches[0].reader.modelled is False
    assert matches[0].writers[0].path == Path("shared/writer.py")
    assert "producer-match=yes" in matches[0].detail


def test_unmodelled_file_api_detection_does_not_match_substrings_in_object_names(gate) -> None:
    assert gate._looks_like_file_api("custom.load_blob") is True
    assert gate._looks_like_file_reader("custom.load_blob") is True
    assert gate._looks_like_file_reader("custom.save_blob") is False
    assert gate._looks_like_file_api("payload.get") is False
    assert gate._looks_like_file_api("threading.Thread") is False
    assert gate._looks_like_file_api("parser.add_argument") is False
    assert gate._looks_like_file_api("json.loads") is False


def test_unmodelled_read_without_a_writer_is_reported_once_under_its_own_kind(
    gate, tmp_path: Path
) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "import custom\n"
        "STATE = Path('cache/orphan.bin')\n"
        "def load_state():\n"
        "    return custom.load_blob(STATE)\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    matches = [
        finding for finding in report.findings if finding.reader.pattern == "cache/orphan.bin"
    ]
    assert [finding.kind for finding in matches] == ["consumer-reads-through-unmodelled-api"]
    assert matches[0].reader_count == 1
    assert "producer-match=no" in matches[0].detail


@pytest.mark.parametrize(
    ("imports", "statement", "operation", "action"),
    [
        ("import io", "io.open('artifacts/data.json')", "io.open", "read"),
        (
            "from io import open as open_file",
            "open_file('artifacts/data.json')",
            "io.open",
            "read",
        ),
        (
            "import arbitrary_module",
            "arbitrary_module.open(Path('artifacts/data.json'))",
            "arbitrary_module.open",
            "read",
        ),
        ("", "Path('artifacts/data.json').open('w')", "Path.open", "write"),
    ],
)
def test_open_uses_the_mode_position_for_the_kind_of_callee(
    gate,
    tmp_path: Path,
    imports: str,
    statement: str,
    operation: str,
    action: str,
) -> None:
    _write(
        tmp_path,
        "shared/opening.py",
        f"from pathlib import Path\n{imports}\ndef use_artifact():\n    return {statement}\n",
    )
    accesses, unresolved, _imports, _unrecognised = gate.collect_artifact_accesses(tmp_path)
    matches = [
        access
        for access in accesses
        if access.pattern == "artifacts/data.json" and access.operation == operation
    ]
    assert [(access.action, access.pattern) for access in matches] == [
        (action, "artifacts/data.json")
    ]
    assert unresolved == 0


def test_or_path_expression_keeps_every_resolvable_branch(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "import os\n"
        "from pathlib import Path\n"
        "def load_state():\n"
        "    artifact = Path(os.getenv('ARTIFACT', 'artifacts/custom.json') "
        "or 'artifacts/default.json')\n"
        "    return artifact.read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert {
        "artifacts/custom.json",
        "artifacts/default.json",
    } <= {
        finding.reader.pattern
        for finding in report.findings
        if finding.kind == "consumer-reads-unwritten-artifact"
    }


@pytest.mark.parametrize(
    "statement",
    [
        "os.replace(SOURCE, DESTINATION)",
        "os.rename(SOURCE, DESTINATION)",
        "SOURCE.replace(DESTINATION)",
        "SOURCE.rename(DESTINATION)",
        "shutil.copy2(SOURCE, DESTINATION)",
    ],
)
def test_copy_and_rename_record_source_reads_and_destination_writes(
    gate, tmp_path: Path, statement: str
) -> None:
    _write(
        tmp_path,
        "shared/transfer.py",
        "import os, shutil\n"
        "from pathlib import Path\n"
        "SOURCE = Path('artifacts/unwritten-source.bin')\n"
        "DESTINATION = Path('artifacts/copied-output.bin')\n"
        f"def transfer():\n    {statement}\n",
    )
    accesses, unresolved, _imports, _unrecognised = gate.collect_artifact_accesses(tmp_path)
    effects = {(access.action, access.pattern) for access in accesses}
    assert ("read", "artifacts/unwritten-source.bin") in effects
    assert ("write", "artifacts/copied-output.bin") in effects
    assert unresolved == 0
    report = gate.analyse_consumer_side(tmp_path, [])
    source_findings = [
        finding
        for finding in report.findings
        if finding.reader.pattern == "artifacts/unwritten-source.bin"
    ]
    assert [finding.kind for finding in source_findings] == ["consumer-reads-unwritten-artifact"]


@pytest.mark.parametrize(
    ("import_statement", "call"),
    [
        ("from shutil import copy2", "copy2(SOURCE, DESTINATION)"),
        ("from shutil import copy as duplicate", "duplicate(SOURCE, DESTINATION)"),
        ("from os import replace", "replace(SOURCE, DESTINATION)"),
        ("from os import rename as move", "move(SOURCE, DESTINATION)"),
        ("import shutil as transfer", "transfer.copyfile(SOURCE, DESTINATION)"),
    ],
)
def test_imported_transfer_aliases_record_both_effects(
    gate, tmp_path: Path, import_statement: str, call: str
) -> None:
    _write(
        tmp_path,
        "shared/transfer.py",
        f"{import_statement}\n"
        "from pathlib import Path\n"
        "SOURCE = Path('artifacts/unwritten-source.bin')\n"
        "DESTINATION = Path('artifacts/copied-output.bin')\n"
        f"def transfer_artifact():\n    {call}\n",
    )
    accesses, unresolved, _imports, _unrecognised = gate.collect_artifact_accesses(tmp_path)
    effects = {(access.action, access.pattern) for access in accesses}
    assert ("read", "artifacts/unwritten-source.bin") in effects
    assert ("write", "artifacts/copied-output.bin") in effects
    assert unresolved == 0


def test_function_local_transfer_alias_does_not_leak_to_a_sibling_scope(
    gate, tmp_path: Path
) -> None:
    _write(
        tmp_path,
        "shared/transfer.py",
        "from pathlib import Path\n"
        "SOURCE = Path('artifacts/unwritten-source.bin')\n"
        "DESTINATION = Path('artifacts/copied-output.bin')\n"
        "def transfer_artifact():\n"
        "    from shutil import copy2 as duplicate\n"
        "    duplicate(SOURCE, DESTINATION)\n"
        "def duplicate(source, destination):\n"
        "    return None\n"
        "def unrelated():\n"
        "    duplicate(SOURCE, Path('artifacts/not-an-output.bin'))\n",
    )
    accesses, unresolved, _imports, _unrecognised = gate.collect_artifact_accesses(tmp_path)
    effects = {(access.action, access.pattern) for access in accesses}
    assert ("read", "artifacts/unwritten-source.bin") in effects
    assert ("write", "artifacts/copied-output.bin") in effects
    assert ("write", "artifacts/not-an-output.bin") not in effects
    assert unresolved == 0


@pytest.mark.parametrize(
    "statement",
    [
        "os.rename(source, DESTINATION)",
        "source.rename(DESTINATION)",
        "shutil.copy(source, DESTINATION)",
    ],
)
def test_unresolved_copy_and_rename_sources_increment_the_count(
    gate, tmp_path: Path, statement: str
) -> None:
    _write(
        tmp_path,
        "shared/transfer.py",
        "import os, shutil\n"
        "from pathlib import Path\n"
        "DESTINATION = Path('artifacts/copied-output.bin')\n"
        f"def transfer(source: Path):\n    {statement}\n",
    )
    accesses, unresolved, _imports, _unrecognised = gate.collect_artifact_accesses(tmp_path)
    assert unresolved == 1
    assert any(
        access.action == "write" and access.pattern == "artifacts/copied-output.bin"
        for access in accesses
    )


def test_string_replace_never_fabricates_an_artifact_writer(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def rewrite_text(text):\n"
        "    return text.replace('config/orphan.json', 'x')\n"
        "def load_orphan():\n"
        "    return Path('config/orphan.json').read_text()\n",
    )
    accesses, _unresolved, _imports, _unrecognised = gate.collect_artifact_accesses(tmp_path)
    assert not any(
        access.action == "write" and access.operation == "replace" for access in accesses
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (
        Path("shared/consumer.py"),
        "config/orphan.json",
    ) in _orphaned(report)


def test_relative_import_pairs_the_reader_with_its_writer(gate, tmp_path: Path) -> None:
    _write(tmp_path, "pkg/__init__.py", "")
    _write(
        tmp_path,
        "pkg/writer.py",
        "from pathlib import Path\n"
        "ARTIFACT = Path('artifacts/rel-state.json')\n"
        "def write_widget():\n"
        "    ARTIFACT.write_text('{}')\n",
    )
    _write(
        tmp_path,
        "pkg/reader.py",
        "from pathlib import Path\n"
        "from .writer import write_widget\n"
        "ARTIFACT = Path('artifacts/rel-state.json')\n"
        "def load_widget():\n"
        "    return ARTIFACT.read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert any(
        pair.reader.path == Path("pkg/reader.py") and pair.writer.path == Path("pkg/writer.py")
        for pair in report.pairs
    )


def test_from_package_import_submodule_pairs_the_reader_with_its_writer(
    gate, tmp_path: Path
) -> None:
    _write(tmp_path, "pkg/__init__.py", "")
    _write(
        tmp_path,
        "pkg/writer.py",
        "from pathlib import Path\n"
        "ARTIFACT = Path('artifacts/sub-state.json')\n"
        "def write_widget():\n"
        "    ARTIFACT.write_text('{}')\n",
    )
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "from pkg import writer\n"
        "ARTIFACT = Path('artifacts/sub-state.json')\n"
        "def load_widget():\n"
        "    return ARTIFACT.read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert any(
        pair.reader.path == Path("shared/consumer.py") and pair.writer.path == Path("pkg/writer.py")
        for pair in report.pairs
    )


def test_module_imports_resolve_levels_and_names(gate) -> None:
    import ast

    tree = ast.parse("from . import writer\nfrom ..top import helper\nfrom .sub.mod import x\n")
    imports = gate._module_imports(tree, "pkg.inner.reader")
    assert "pkg.inner.writer" in imports
    assert "pkg.top" in imports and "pkg.top.helper" in imports
    assert "pkg.inner.sub.mod" in imports and "pkg.inner.sub.mod.x" in imports
    package_tree = ast.parse("from . import writer\n")
    assert "pkg.writer" in gate._module_imports(package_tree, "pkg", is_package=True)


def test_same_named_path_helpers_stay_with_their_own_modules(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "alpha/paths.py",
        "from pathlib import Path\n"
        "def artifact_path():\n"
        "    return Path('artifacts/alpha.json')\n"
        "def load_alpha():\n"
        "    return artifact_path().read_text()\n",
    )
    _write(
        tmp_path,
        "beta/paths.py",
        "from pathlib import Path\n"
        "def artifact_path():\n"
        "    return Path('artifacts/beta.json')\n"
        "def load_beta():\n"
        "    return artifact_path().read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    unwritten = _orphaned(report)
    assert (Path("alpha/paths.py"), "artifacts/alpha.json") in unwritten
    assert (Path("beta/paths.py"), "artifacts/beta.json") in unwritten
    assert (Path("alpha/paths.py"), "artifacts/beta.json") not in unwritten
    assert (Path("beta/paths.py"), "artifacts/alpha.json") not in unwritten


def test_an_imported_path_helper_resolves_through_the_import(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/paths.py",
        "from pathlib import Path\ndef artifact_path():\n    return Path('artifacts/shared.json')\n",
    )
    _write(
        tmp_path,
        "other/paths.py",
        "from pathlib import Path\ndef artifact_path():\n    return Path('artifacts/other.json')\n",
    )
    _write(
        tmp_path,
        "shared/consumer.py",
        "from shared.paths import artifact_path\n"
        "def load_state():\n"
        "    return artifact_path().read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    unwritten = _orphaned(report)
    assert (Path("shared/consumer.py"), "artifacts/shared.json") in unwritten
    assert (Path("shared/consumer.py"), "artifacts/other.json") not in unwritten


@pytest.mark.parametrize("import_last", [True, False], ids=["import-last", "definition-last"])
def test_current_import_binding_wins_over_an_earlier_definition(
    gate, tmp_path: Path, import_last: bool
) -> None:
    _write(
        tmp_path,
        "shared/writer.py",
        "from pathlib import Path\n"
        "def write_state(target=Path('artifacts/old.json')):\n"
        "    target.write_text('{}')\n",
    )
    definition = "def write_state(target):\n    pass\n"
    imported = "from shared.writer import write_state\n"
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        + (definition + imported if import_last else imported + definition)
        + "write_state(Path('artifacts/new.json'))\n"
        "Path('artifacts/old.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {(a.path, a.pattern) for a in accesses if a.action == "write" and a.bounded} == {
        (Path("shared/writer.py"), f"artifacts/{'new' if import_last else 'old'}.json")
    }
    report = gate.analyse_consumer_side(tmp_path, [])
    assert ((Path("shared/consumer.py"), "artifacts/old.json") in _orphaned(report)) is import_last


@pytest.mark.parametrize("import_last", [True, False], ids=["import-last", "definition-last"])
def test_import_resolution_uses_the_binding_at_each_call(gate, tmp_path: Path, import_last) -> None:
    _write(
        tmp_path,
        "shared/writer.py",
        "def write_state(target):\n    target.write_text('{}')\n",
    )
    definition = "def write_state(target):\n    pass\n"
    imported = "from shared.writer import write_state\n"
    first, second = (definition, imported) if import_last else (imported, definition)
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        + first
        + "write_state(Path('artifacts/before.json'))\n"
        + second
        + "write_state(Path('artifacts/after.json'))\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write" and a.bounded} == {
        f"artifacts/{'after' if import_last else 'before'}.json"
    }


@pytest.mark.parametrize("shape", ["call", "assignment"])
@pytest.mark.parametrize("scope", ["module", "global", "nonlocal"])
def test_class_body_propagates_outer_binding_effects(gate, tmp_path: Path, shape, scope) -> None:
    declaration = "nonlocal" if scope == "nonlocal" else "global"
    body = (
        "ARTIFACT = Path('artifacts/old.json')\n"
        "def configure():\n"
        f"    {declaration} ARTIFACT\n"
        "    ARTIFACT = Path('artifacts/new.json')\n"
        "class Configure:\n"
        + (
            "    configure()\n"
            if shape == "call"
            else f"    {declaration} ARTIFACT\n    ARTIFACT = Path('artifacts/new.json')\n"
        )
        + "ARTIFACT.write_text('{}')\n"
    )
    if scope != "module":
        if scope == "global":
            body = "global ARTIFACT\n" + body
        body = (
            "def run():\n" + "".join("    " + line + "\n" for line in body.splitlines()) + "run()\n"
        )
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n" + body + "Path('artifacts/old.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    bounded_writes = {a.pattern for a in accesses if a.action == "write" and a.bounded}
    assert bounded_writes == ({"artifacts/new.json"} if shape == "assignment" else set())
    report = gate.analyse_consumer_side(tmp_path, [])
    # A class body that CALLS the configurator locates a writer it cannot certify; one that
    # merely assigns leaves nothing writing this reader. Same orphan, two causes.
    assert (Path("shared/consumer.py"), "artifacts/old.json") in _orphaned(
        report, UNRESOLVED_WRITER if shape == "call" else ABSENT_WRITER
    )
    if shape == "call":
        assert report.unresolvable > 0


@pytest.mark.parametrize("wrapped", [False, True], ids=["module", "function"])
def test_class_attributes_do_not_replace_enclosing_bindings(gate, tmp_path: Path, wrapped) -> None:
    body = (
        "ARTIFACT = Path('artifacts/old.json')\n"
        "class Configure:\n    ARTIFACT = Path('artifacts/new.json')\n"
        "ARTIFACT.write_text('{}')\n"
    )
    if wrapped:
        body = (
            "def run():\n" + "".join("    " + line + "\n" for line in body.splitlines()) + "run()\n"
        )
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n" + body + "Path('artifacts/new.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write" and a.bounded} == {
        "artifacts/old.json"
    }
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), "artifacts/new.json") in _orphaned(report)


@pytest.mark.parametrize("scope", ["global", "nonlocal"])
def test_class_attribute_cannot_hide_a_callee_outer_effect(gate, tmp_path: Path, scope) -> None:
    body = (
        "ARTIFACT = Path('artifacts/old.json')\n"
        f"def configure():\n    {scope} ARTIFACT\n"
        "    ARTIFACT = Path('artifacts/new.json')\n"
        "class Configure:\n"
        "    ARTIFACT = Path('artifacts/class.json')\n"
        "    configure()\n"
        "    ARTIFACT = Path('artifacts/class.json')\n"
        "ARTIFACT.write_text('{}')\n"
    )
    if scope == "nonlocal":
        body = (
            "def run():\n" + "".join("    " + line + "\n" for line in body.splitlines()) + "run()\n"
        )
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n" + body + "Path('artifacts/old.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not [a for a in accesses if a.action == "write" and a.bounded]
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), "artifacts/old.json") in _orphaned(
        report, UNRESOLVED_WRITER
    )
    assert report.unresolvable > 0


@pytest.mark.parametrize("assignment", [False, True], ids=["declaration", "assignment"])
def test_class_global_bypasses_an_enclosing_local(gate, tmp_path: Path, assignment) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nARTIFACT = Path('artifacts/module.json')\n"
        "def write_state():\n    ARTIFACT.write_text('{}')\n"
        "def run():\n    ARTIFACT = Path('artifacts/local.json')\n"
        "    class Configure:\n        global ARTIFACT\n"
        + ("        ARTIFACT = Path('artifacts/new.json')\n" if assignment else "")
        + "        ARTIFACT.write_text('{}')\n"
        "    ARTIFACT.write_text('{}')\n    write_state()\nrun()\n"
        "Path('artifacts/module.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    class_write_line = next(
        index
        for index, line in enumerate(
            (tmp_path / "shared/consumer.py").read_text().splitlines(), start=1
        )
        if line == "        ARTIFACT.write_text('{}')"
    )
    assert {
        a.pattern for a in accesses if a.action == "write" and a.lineno == class_write_line
    } == {f"artifacts/{'new' if assignment else 'module'}.json"}
    assert {a.pattern for a in accesses if a.action == "write" and a.bounded} == {
        "artifacts/local.json",
        f"artifacts/{'new' if assignment else 'module'}.json",
    }
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (
        (Path("shared/consumer.py"), "artifacts/module.json") in _orphaned(report)
    ) is assignment


def test_class_global_store_is_an_effect_of_its_enclosing_function(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "def configure():\n    class Configure:\n        global ARTIFACT\n"
        "        ARTIFACT = Path('artifacts/new.json')\n"
        "configure()\nARTIFACT.write_text('{}')\n"
        "Path('artifacts/old.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not [a for a in accesses if a.action == "write" and a.bounded]
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), "artifacts/old.json") in _orphaned(
        report, UNRESOLVED_WRITER
    )
    assert report.unresolvable > 0


def test_class_effect_branch_cap_keeps_the_orphan_reader(gate, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(gate, "_MAX_BRANCH_STATES", 1)
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "def configure():\n    global ARTIFACT\n"
        "    ARTIFACT = Path('artifacts/new.json')\n"
        "class Configure:\n    if flag:\n        configure()\n"
        "ARTIFACT.write_text('{}')\nPath('artifacts/old.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not [a for a in accesses if a.action == "write" and a.bounded]
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), "artifacts/old.json") in _orphaned(
        report, UNRESOLVED_WRITER
    )
    assert report.unresolvable > 0


@pytest.mark.parametrize("enclosing_local", [False, True], ids=["module", "cell"])
@pytest.mark.parametrize("default", [False, True], ids=["method-body", "method-default"])
def test_class_attributes_do_not_become_method_closure_cells(
    gate, tmp_path: Path, enclosing_local, default
) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nARTIFACT = Path('artifacts/module.json')\n"
        "def outer():\n"
        + ("    ARTIFACT = Path('artifacts/cell.json')\n" if enclosing_local else "")
        + "    class Configure:\n        ARTIFACT = Path('artifacts/class.json')\n"
        + (
            "        def write_state(self, target=ARTIFACT):\n            target.write_text('{}')\n"
            if default
            else "        def write_state(self):\n            ARTIFACT.write_text('{}')\n"
        )
        + "Path('artifacts/class.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    expected = "class" if default else "cell" if enclosing_local else "module"
    assert {a.pattern for a in accesses if a.action == "write" and a.bounded} == {
        f"artifacts/{expected}.json"
    }
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (
        (Path("shared/consumer.py"), "artifacts/class.json") in _orphaned(report)
    ) is not default


@pytest.mark.parametrize("imported", [False, True], ids=["local", "imported"])
@pytest.mark.parametrize(
    "call_after", [False, True], ids=["before-redefinition", "after-redefinition"]
)
def test_calls_bind_to_individual_definitions(gate, tmp_path: Path, imported, call_after) -> None:
    first = "def output_path():\n    return Path('artifacts/actual.json')\n"
    if imported:
        _write(tmp_path, "shared/helper.py", "from pathlib import Path\n" + first)
        first = "from shared.helper import output_path\n"
    second = "def output_path():\n    return Path('artifacts/orphan.json')\n"
    call = "destination = output_path()\n"
    orphan = "actual" if call_after else "orphan"
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        + first
        + (second + call if call_after else call + second)
        + "destination.write_text('{}')\n"
        + f"Path('artifacts/{orphan}.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write" and a.bounded} == {
        f"artifacts/{'orphan' if call_after else 'actual'}.json"
    }
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), f"artifacts/{orphan}.json") in _orphaned(report)
    assert report.unresolvable == 0


def test_function_object_alias_keeps_its_definition(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def output_path():\n    return Path('artifacts/actual.json')\n"
        "saved = output_path\n"
        "def output_path():\n    return Path('artifacts/orphan.json')\n"
        "saved().write_text('{}')\nPath('artifacts/orphan.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write" and a.bounded} == {
        "artifacts/actual.json"
    }
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), "artifacts/orphan.json") in _orphaned(report)
    assert report.unresolvable == 0


@pytest.mark.parametrize("configured", [True, False], ids=["configured", "unchanged"])
@pytest.mark.parametrize("wrapped", [False, True], ids=["direct", "transitive"])
@pytest.mark.parametrize("in_function", [False, True], ids=["module", "function"])
def test_imported_global_effect_withholds_stale_writer(
    gate, tmp_path: Path, configured, wrapped, in_function
) -> None:
    _write(
        tmp_path,
        "shared/helper.py",
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "def configure():\n    global ARTIFACT\n"
        "    ARTIFACT = Path('artifacts/new.json')\n"
        "def prepare():\n    configure()\n"
        "def write_state():\n    ARTIFACT.write_text('{}')\n",
    )
    calls = (
        f"helper.{'prepare' if wrapped else 'configure'}()\n" if configured else ""
    ) + "helper.write_state()\nPath('artifacts/old.json').read_text()\n"
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nfrom shared import helper\n"
        + (
            "def consume():\n" + "".join(f"    {line}\n" for line in calls.splitlines())
            if in_function
            else calls
        ),
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    writers = [a for a in accesses if a.action == "write"]
    assert writers and {a.pattern for a in writers} == {"artifacts/old.json"}
    assert all(a.bounded is not configured for a in writers)
    assert (unresolved > 0) is configured
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (report.unresolvable > 0) is configured
    assert (
        (Path("shared/consumer.py"), "artifacts/old.json") in _orphaned(report, UNRESOLVED_WRITER)
    ) is configured
    if not configured:
        assert not report.findings


@pytest.mark.parametrize("branch_cap", [1, 32], ids=["collapsed-branch", "separate-branches"])
def test_imported_global_effect_survives_branch_and_module_hops(
    gate, tmp_path: Path, monkeypatch, branch_cap
) -> None:
    monkeypatch.setattr(gate, "_MAX_BRANCH_STATES", branch_cap)
    _write(
        tmp_path,
        "shared/helper.py",
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "def configure():\n    global ARTIFACT\n"
        "    ARTIFACT = Path('artifacts/new.json')\n"
        "def read_state():\n    return ARTIFACT.read_text()\n",
    )
    _write(
        tmp_path,
        "shared/bridge.py",
        "from shared import helper\ndef read_state():\n    return helper.read_state()\n",
    )
    _write(
        tmp_path,
        "shared/consumer.py",
        "from shared import helper, bridge\n"
        "if condition:\n    helper.configure()\nbridge.read_state()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    readers = [a for a in accesses if a.action == "read" and a.pattern == "artifacts/old.json"]
    assert readers and any(not a.bounded for a in readers)
    assert unresolved > 0
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/helper.py"), "artifacts/old.json") in _orphaned(report)
    assert report.unresolvable > 0


@pytest.mark.parametrize("uncertain", [False, True], ids=["named-effect", "unknown-effect"])
def test_imported_global_effect_limits_certification_to_untouched_names(
    gate, tmp_path: Path, uncertain
) -> None:
    _write(
        tmp_path,
        "shared/helper.py",
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "STABLE = Path('artifacts/stable.json')\n"
        "def configure():\n"
        + (
            "    unseen_effect()\n"
            if uncertain
            else "    global ARTIFACT\n    ARTIFACT = Path('artifacts/new.json')\n"
        )
        + "def write_state():\n    ARTIFACT.write_text('{}')\n"
        "    STABLE.write_text('{}')\n",
    )
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nfrom shared import helper\n"
        "helper.configure()\nhelper.write_state()\n"
        "Path('artifacts/old.json').read_text()\n"
        "Path('artifacts/stable.json').read_text()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write" and a.bounded} == (
        set() if uncertain else {"artifacts/stable.json"}
    )
    assert unresolved > 0
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), "artifacts/old.json") in _orphaned(
        report, UNRESOLVED_WRITER
    )
    # STABLE keeps its own certified writer unless the effect is unknown; when it does become
    # uncertain it is the located-writer sentence, not the absence one.
    assert (
        (Path("shared/consumer.py"), "artifacts/stable.json")
        in _orphaned(report, UNRESOLVED_WRITER)
    ) is uncertain


@pytest.mark.parametrize("kind", ["function", "class"])
def test_decorator_application_propagates_global_assignment(gate, tmp_path: Path, kind) -> None:
    definition = (
        "def configured():\n    pass\n" if kind == "function" else "class Configured:\n    pass\n"
    )
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "def configure(obj):\n    global ARTIFACT\n"
        "    ARTIFACT = Path('artifacts/new.json')\n    return obj\n"
        "@configure\n"
        + definition
        + "ARTIFACT.write_text('{}')\nPath('artifacts/old.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write" and a.bounded} == {
        "artifacts/new.json"
    }
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), "artifacts/old.json") in _orphaned(report)
    assert report.unresolvable == 0


@pytest.mark.parametrize("kind", ["function", "class"])
def test_unseen_decorator_keeps_outer_binding_uncertain(gate, tmp_path: Path, kind) -> None:
    definition = (
        "def configured():\n    pass\n" if kind == "function" else "class Configured:\n    pass\n"
    )
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nfrom unavailable import configure\n"
        "ARTIFACT = Path('artifacts/old.json')\n@configure\n"
        + definition
        + "ARTIFACT.write_text('{}')\nPath('artifacts/old.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not [a for a in accesses if a.action == "write" and a.bounded]
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), "artifacts/old.json") in _orphaned(
        report, UNRESOLVED_WRITER
    )
    assert report.unresolvable > 0


@pytest.mark.parametrize("kind", ["function", "class"])
def test_stacked_decorators_apply_innermost_first(gate, tmp_path: Path, kind) -> None:
    definition = (
        "def configured():\n    pass\n" if kind == "function" else "class Configured:\n    pass\n"
    )
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "def outer(obj):\n    global ARTIFACT\n"
        "    ARTIFACT = Path('artifacts/outer.json')\n    return obj\n"
        "def inner(obj):\n    global ARTIFACT\n"
        "    ARTIFACT = Path('artifacts/inner.json')\n    return obj\n"
        "@outer\n@inner\n"
        + definition
        + "ARTIFACT.write_text('{}')\nPath('artifacts/inner.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write" and a.bounded} == {
        "artifacts/outer.json"
    }
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), "artifacts/inner.json") in _orphaned(report)
    assert report.unresolvable == 0


@pytest.mark.parametrize("writer", [False, True], ids=["unwritten", "certified-writer"])
def test_untracked_result_retains_the_readers_literal_pattern(gate, tmp_path: Path, writer) -> None:
    _write(tmp_path, "shared/helper.py", "def output_name():\n    return 'obsolete'\n")
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def replacement():\n    return 'actual'\n"
        "def load_state():\n    from shared import helper, producer\n"
        "    helper.output_name = replacement\n"
        "    name = helper.output_name()\n"
        "    target = Path('artifacts') / name / 'state.json'\n"
        "    return target.read_text()\nload_state()\n",
    )
    if writer:
        _write(
            tmp_path,
            "shared/producer.py",
            "from pathlib import Path\ndef save_state():\n"
            "    Path('artifacts/actual/state.json').write_text('{}')\n",
        )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert report.unresolvable > 0
    if writer:
        assert not report.findings
        assert any(
            pair.reader.path == Path("shared/consumer.py")
            and pair.reader.pattern == "artifacts/*/state.json"
            and pair.writer.pattern == "artifacts/actual/state.json"
            and pair.writer.bounded
            for pair in report.pairs
        )
    else:
        assert not report.pairs
        assert {finding.kind for finding in report.findings} == {
            "consumer-reads-unwritten-artifact"
        }
        assert (Path("shared/consumer.py"), "artifacts/*/state.json") in _orphaned(report)
        assert not any(finding.writers for finding in report.findings)


def test_visible_source_relative_helper_survives_module_call_effects(gate, tmp_path: Path) -> None:
    # Exercise lexical source identity through module-call effects. Runtime cwd and
    # symlink resolution are not needed to construct this source-relative fixture.
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nimport logging\nLOG = logging.getLogger(__name__)\n"
        "def source_root() -> Path:\n    return Path(__file__).parents[1]\n"
        "def load_state():\n"
        "    root = source_root()\n"
        "    return (root / 'config' / 'literal.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert {finding.kind for finding in report.findings} == {"consumer-reads-unwritten-artifact"}
    assert (Path("shared/consumer.py"), "config/literal.json") in _orphaned(report)
    assert report.unresolvable == 0


@pytest.mark.parametrize("via_helper", [False, True], ids=["binding", "helper-result"])
@pytest.mark.parametrize("branched", [False, True], ids=["straight-line", "branch-cap"])
def test_module_effects_retain_literal_accesses_without_certifying_writers(
    gate, tmp_path: Path, monkeypatch, via_helper, branched
) -> None:
    if branched:
        monkeypatch.setattr(gate, "_MAX_BRANCH_STATES", 1)
    target = "artifact_path()" if via_helper else "ARTIFACT"
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nARTIFACT = Path('artifacts/literal.json')\n"
        + ("if flag:\n    unknown_setup()\n" if branched else "unknown_setup()\n")
        + "def artifact_path() -> Path:\n    return ARTIFACT\n"
        f"def load_state():\n    return {target}.read_text()\n"
        f"def save_state():\n    {target}.write_text('{{}}')\n"
        "Path('artifacts/literal.json').read_text()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert unresolved > 0
    assert {(a.action, a.pattern, a.bounded) for a in accesses if a.family == "state"} == {
        ("read", "artifacts/literal.json", False),
        ("write", "artifacts/literal.json", False),
    }
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), "artifacts/literal.json") in _orphaned(
        report, UNRESOLVED_WRITER
    )
    assert not any(a.bounded for f in report.findings for a in f.writers)


def test_function_attribute_assignment_keeps_result_identity_uncertain(
    gate, tmp_path: Path
) -> None:
    # Attribute assignment of a function object is deliberately not modelled. Its unknown
    # result must not become artifacts/*/state.json and certify the unrelated orphan reader.
    _write(tmp_path, "shared/helper.py", "def output_name():\n    return 'orphan'\n")
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def replacement():\n    return 'actual'\n"
        "def run():\n    from shared import helper\n"
        "    helper.output_name = replacement\n"
        "    name = helper.output_name()\n"
        "    (Path('artifacts') / name / 'state.json').write_text('{}')\nrun()\n"
        "Path('artifacts/orphan/state.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not [a for a in accesses if a.action == "write" and a.bounded]
    writers = [a for a in accesses if a.action == "write"]
    assert {a.pattern for a in writers} == {"artifacts/*/state.json"}
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), "artifacts/orphan/state.json") in _orphaned(
        report, UNRESOLVED_WRITER
    )
    assert report.unresolvable > 0
    assert not report.pairs
    assert any(set(writers) <= set(finding.writers) for finding in report.findings)
    # The uncalled-body fallback consumes the module prepass snapshot, not a discovered
    # invocation. It must carry the same uncertainty as the evaluated call above.
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nfrom shared import helper\n"
        "def replacement():\n    return 'actual'\n"
        "helper.output_name = replacement\nname = helper.output_name()\n"
        "def write_state():\n"
        "    (Path('artifacts') / name / 'state.json').write_text('{}')\n"
        "Path('artifacts/orphan/state.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not [a for a in accesses if a.action == "write" and a.bounded]
    writers = [a for a in accesses if a.action == "write"]
    assert {a.pattern for a in writers} == {"artifacts/*/state.json"}
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), "artifacts/orphan/state.json") in _orphaned(
        report, UNRESOLVED_WRITER
    )
    assert report.unresolvable > 0
    assert not report.pairs
    assert any(set(writers) <= set(finding.writers) for finding in report.findings)


def test_callee_identity_is_captured_before_argument_rebinding(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "def output_path(ignored):\n    return Path('artifacts/actual.json')\n"
        "def replacement(ignored):\n    return Path('artifacts/orphan.json')\n"
        "destination = output_path(output_path := replacement)\n"
        "destination.write_text('{}')\nPath('artifacts/orphan.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write" and a.bounded} == {
        "artifacts/actual.json"
    }
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), "artifacts/orphan.json") in _orphaned(report)
    assert report.unresolvable == 0


def test_decorator_identity_is_captured_before_class_body(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "def configure(obj):\n    global ARTIFACT\n"
        "    ARTIFACT = Path('artifacts/new.json')\n    return obj\n"
        "def replacement(obj):\n    global ARTIFACT\n"
        "    ARTIFACT = Path('artifacts/orphan.json')\n    return obj\n"
        "@configure\nclass Configured:\n    global configure\n    configure = replacement\n"
        "ARTIFACT.write_text('{}')\nPath('artifacts/orphan.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write" and a.bounded} == {
        "artifacts/new.json"
    }
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), "artifacts/orphan.json") in _orphaned(report)
    assert report.unresolvable == 0


@pytest.mark.parametrize("kind", ["function", "class"])
def test_decorator_with_uncertain_effects_keeps_orphan(gate, tmp_path: Path, kind) -> None:
    definition = (
        "def configured():\n    pass\n" if kind == "function" else "class Configured:\n    pass\n"
    )
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "def configure(obj):\n    unseen_effect()\n    return obj\n"
        "@configure\n"
        + definition
        + "ARTIFACT.write_text('{}')\nPath('artifacts/old.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not [a for a in accesses if a.action == "write" and a.bounded]
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), "artifacts/old.json") in _orphaned(
        report, UNRESOLVED_WRITER
    )
    assert report.unresolvable > 0


def test_imported_decorated_helper_cannot_borrow_original_body(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/helper.py",
        "from pathlib import Path\nfrom unavailable import configure\n"
        "@configure\ndef output_path():\n    return Path('artifacts/orphan.json')\n",
    )
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nfrom shared.helper import output_path\n"
        "output_path().write_text('{}')\nPath('artifacts/orphan.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not [a for a in accesses if a.action == "write" and a.bounded]
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), "artifacts/orphan.json") in _orphaned(report)
    assert report.unresolvable > 0


@pytest.mark.parametrize("configured", [True, False], ids=["configured", "unchanged"])
@pytest.mark.parametrize("wrapped", [False, True], ids=["direct", "transitive"])
@pytest.mark.parametrize("in_function", [False, True], ids=["module", "function"])
def test_imported_callable_effect_withholds_obsolete_body(
    gate, tmp_path: Path, configured, wrapped, in_function
) -> None:
    _write(
        tmp_path,
        "shared/helper.py",
        "from pathlib import Path\n"
        "def write_state():\n    Path('artifacts/old.json').write_text('{}')\n"
        "def replacement():\n    Path('artifacts/new.json').write_text('{}')\n"
        "def configure():\n    global write_state\n    write_state = replacement\n"
        "def prepare():\n    configure()\n",
    )
    calls = (
        f"helper.{'prepare' if wrapped else 'configure'}()\n" if configured else ""
    ) + "helper.write_state()\nPath('artifacts/old.json').read_text()\n"
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nfrom shared import helper\n"
        + (
            "def consume():\n" + "".join(f"    {line}\n" for line in calls.splitlines())
            if in_function
            else calls
        ),
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    old_writers = [a for a in accesses if a.action == "write" and a.pattern == "artifacts/old.json"]
    assert old_writers and all(a.bounded is not configured for a in old_writers)
    assert (unresolved > 0) is configured
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (report.unresolvable > 0) is configured
    assert (
        (Path("shared/consumer.py"), "artifacts/old.json") in _orphaned(report, UNRESOLVED_WRITER)
    ) is configured
    if not configured:
        assert not report.findings


@pytest.mark.parametrize("branch_cap", [1, 32], ids=["collapsed-branch", "separate-branches"])
def test_imported_callable_effect_retains_uncertain_reads_across_module_hops(
    gate, tmp_path: Path, monkeypatch, branch_cap
) -> None:
    monkeypatch.setattr(gate, "_MAX_BRANCH_STATES", branch_cap)
    _write(
        tmp_path,
        "shared/helper.py",
        "from pathlib import Path\n"
        "def read_state():\n    return Path('artifacts/old.json').read_text()\n"
        "def replacement():\n    return Path('artifacts/new.json').read_text()\n"
        "def configure():\n    global read_state\n    read_state = replacement\n",
    )
    _write(
        tmp_path,
        "shared/bridge.py",
        "from shared import helper\ndef read_state():\n    return helper.read_state()\n",
    )
    _write(
        tmp_path,
        "shared/consumer.py",
        "from shared import helper, bridge\n"
        "if condition:\n    helper.configure()\nbridge.read_state()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    readers = [a for a in accesses if a.action == "read" and a.pattern == "artifacts/old.json"]
    assert readers and all(not a.bounded for a in readers)
    assert unresolved > 0
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/helper.py"), "artifacts/old.json") in _orphaned(report)
    assert report.unresolvable > 0


@pytest.mark.parametrize("access", ["read_text()", "write_text('{}')"])
def test_rebound_imported_path_helper_keeps_only_uncertain_literal_evidence(
    gate, tmp_path: Path, access
) -> None:
    _write(
        tmp_path,
        "shared/helper.py",
        "from pathlib import Path\n"
        "def artifact_path() -> Path:\n    return Path('artifacts/old.json')\n"
        "def replacement() -> Path:\n    return Path('artifacts/new.json')\n"
        "def configure():\n    global artifact_path\n    artifact_path = replacement\n",
    )
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nfrom shared import helper\n"
        "helper.configure()\n"
        f"helper.artifact_path().{access}\nPath('artifacts/old.json').read_text()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    through_helper = [a for a in accesses if a.path == Path("shared/consumer.py") and a.lineno == 4]
    assert through_helper and all(not a.bounded for a in through_helper)
    assert {a.pattern for a in through_helper} == {"artifacts/old.json"}
    assert unresolved > 0
    report = gate.analyse_consumer_side(tmp_path, [])
    # The two parameters differ in cause, not only in spelling: `write_text` LOCATES a writer
    # through the rebound helper and leaves it uncertain, while `read_text` writes nothing at
    # all, so the reader's absence is decided. Measured per parameter.
    assert (Path("shared/consumer.py"), "artifacts/old.json") in _orphaned(
        report, UNRESOLVED_WRITER if access.startswith("write") else ABSENT_WRITER
    )
    assert report.unresolvable > 0


def test_rebound_imported_callable_withholds_its_fallback_callees(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/helper.py",
        "from pathlib import Path\n"
        "def old_writer():\n    Path('artifacts/old.json').write_text('{}')\n"
        "def write_state():\n    old_writer()\n"
        "def replacement():\n    Path('artifacts/new.json').write_text('{}')\n"
        "def configure():\n    global write_state\n    write_state = replacement\n",
    )
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nfrom shared import helper\n"
        "helper.configure()\nhelper.write_state()\nPath('artifacts/old.json').read_text()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    writers = [a for a in accesses if a.action == "write" and a.pattern == "artifacts/old.json"]
    assert writers and all(not a.bounded for a in writers)
    assert unresolved > 0
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), "artifacts/old.json") in _orphaned(
        report, UNRESOLVED_WRITER
    )


@pytest.mark.parametrize(
    "opening",
    [
        "open('artifacts/state.json', MODE)",
        "io.open('artifacts/state.json', mode=MODE)",
        "Path('artifacts/state.json').open(MODE)",
        "Path('artifacts/state.json').open(mode=MODE)",
        "tarfile.open('artifacts/state.json', MODE)",
        "zipfile.ZipFile('artifacts/state.json', mode=MODE)",
    ],
)
@pytest.mark.parametrize("mode", ["mode", "'r'", "'w'"], ids=["nonliteral", "read", "write"])
def test_nonliteral_open_mode_withholds_access_certification(
    gate, tmp_path: Path, opening, mode
) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "import io, tarfile, zipfile\nfrom pathlib import Path\n"
        "def use_state(mode):\n    " + opening.replace("MODE", mode) + "\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert len(accesses) == 1
    access = accesses[0]
    assert access.pattern == "artifacts/state.json"
    assert access.action == ("write" if mode == "'w'" else "read")
    assert access.bounded is (mode != "mode")
    assert unresolved == (1 if mode == "mode" else 0)
    report = gate.analyse_consumer_side(tmp_path, [])
    assert report.unresolvable == unresolved
    if mode == "mode":
        assert (Path("shared/consumer.py"), "artifacts/state.json") in _orphaned(report)


@pytest.mark.parametrize("uncertain", [True, False], ids=["uncertain", "bounded"])
@pytest.mark.parametrize("divergent", [False, True], ids=["same-path", "different-path"])
def test_path_mismatch_requires_established_divergent_paths(
    gate, tmp_path: Path, uncertain, divergent
) -> None:
    writer = "artifacts/state.yaml" if divergent else "artifacts/state.json"
    _write(
        tmp_path,
        "shared/producer.py",
        "from pathlib import Path\n"
        f"ARTIFACT = Path('{writer}')\n"
        + ("unknown_setup()\n" if uncertain else "")
        + "def write_state():\n    ARTIFACT.write_text('{}')\n",
    )
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nfrom shared import producer\n"
        "def read_state():\n    return Path('artifacts/state.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    mismatches = [f for f in report.findings if f.kind == "consumer-producer-path-mismatch"]
    assert bool(mismatches) is (divergent and not uncertain)
    assert (report.unresolvable > 0) is uncertain
    # Orphaned for two different reasons across the grid: a DIVERGENT path means nothing writes
    # this reader at all, while the same path left uncertain means the writer is located and
    # not established. Only the second is the unresolved-writer sentence.
    assert (
        (Path("shared/consumer.py"), "artifacts/state.json")
        in _orphaned(report, UNRESOLVED_WRITER if uncertain and not divergent else ABSENT_WRITER)
    ) is (uncertain or divergent)
    if mismatches:
        assert {a.pattern for f in mismatches for a in f.writers} == {writer}


@pytest.mark.parametrize("api", ["os.getenv", "os.environ.get"])
@pytest.mark.parametrize("assigned", [False, True], ids=["inline", "assigned"])
@pytest.mark.parametrize("keyword", [False, True], ids=["positional", "keyword"])
def test_environment_default_writer_is_not_established(
    gate, tmp_path: Path, api, assigned, keyword
) -> None:
    default = "default='artifacts/old.json'" if keyword else "'artifacts/old.json'"
    expression = f"Path({api}('ARTIFACT', {default}))"
    statement = f"artifact = {expression}\nartifact" if assigned else expression
    _write(
        tmp_path,
        "shared/consumer.py",
        "import os\nfrom pathlib import Path\n"
        + statement
        + ".write_text('{}')\nPath('artifacts/old.json').read_text()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    writers = [a for a in accesses if a.action == "write"]
    assert [(a.pattern, a.bounded) for a in writers] == [("artifacts/old.json", False)]
    assert unresolved > 0
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), "artifacts/old.json") in _orphaned(
        report, UNRESOLVED_WRITER
    )
    assert report.unresolvable > 0


@pytest.mark.parametrize(
    "expression,pattern",
    [
        ("Path('artifacts/old.json')", "artifacts/old.json"),
        ("Path.home() / 'artifacts/old.json'", "~/artifacts/old.json"),
    ],
    ids=["literal", "symbolic-home"],
)
def test_established_path_writer_still_pairs(gate, tmp_path: Path, expression, pattern) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        f"from pathlib import Path\n({expression}).write_text('{{}}')\n"
        f"({expression}).read_text()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {(a.action, a.pattern, a.bounded) for a in accesses} == {
        ("write", pattern, True),
        ("read", pattern, True),
    }
    assert unresolved == 0
    assert not gate.analyse_consumer_side(tmp_path, []).findings


@pytest.mark.parametrize("assigned", [False, True], ids=["inline", "assigned"])
def test_literal_tilde_writer_does_not_certify_home_reader(gate, tmp_path: Path, assigned) -> None:
    statement = (
        "artifact = Path('~/artifacts/old.json')\nartifact"
        if assigned
        else ("Path('~/artifacts/old.json')")
    )
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n" + statement + ".write_text('{}')\n"
        "(Path.home() / 'artifacts/old.json').read_text()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {(a.action, a.pattern, a.bounded) for a in accesses} == {
        ("write", "./~/artifacts/old.json", True),
        ("read", "~/artifacts/old.json", True),
    }
    assert unresolved == 0
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), "~/artifacts/old.json") in _orphaned(report)


@pytest.mark.parametrize("expanded", [False, True], ids=["literal", "expanduser"])
def test_expanduser_writer_does_not_certify_literal_tilde_reader(
    gate, tmp_path: Path, expanded
) -> None:
    operation = ".expanduser()" if expanded else ""
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        f"Path('~/artifacts/old.json'){operation}.write_text('{{}}')\n"
        "Path('~/artifacts/old.json').read_text()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert any(a.action == "read" and a.pattern == "./~/artifacts/old.json" for a in accesses)
    assert any(a.action == "write" and a.bounded for a in accesses) is not expanded
    assert (unresolved > 0) is expanded
    report = gate.analyse_consumer_side(tmp_path, [])
    assert ((Path("shared/consumer.py"), "./~/artifacts/old.json") in _orphaned(report)) is expanded
    assert (report.unresolvable > 0) is expanded
    if not expanded:
        assert not report.findings


def test_symbolic_home_parent_is_not_a_modelled_layout(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "(Path.home().parent / 'artifacts/old.json').write_text('{}')\n"
        "Path('/artifacts/old.json').read_text()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not any(a.action == "write" and a.bounded for a in accesses)
    assert unresolved > 0
    assert (Path("shared/consumer.py"), "/artifacts/old.json") in _orphaned(
        gate.analyse_consumer_side(tmp_path, []), UNRESOLVED_WRITER
    )


def test_literal_tilde_globs_keep_relative_identity(gate) -> None:
    assert not gate._patterns_match("./~/artifacts/*.json", "~/artifacts/*.json")
    assert gate._patterns_match("./~/artifacts/*.json", "./~/artifacts/old.json")


@pytest.mark.parametrize(
    "root", ["Path(os.getenv('ARTIFACT', 'artifacts'))", "Path('~').expanduser()"]
)
def test_unestablished_root_keeps_suffix_uncertain(gate, tmp_path: Path, root) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "import os\nfrom pathlib import Path\n"
        f"({root} / 'old.json').write_text('{{}}')\n"
        "Path('artifacts/old.json').read_text()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not any(a.action == "write" and a.bounded for a in accesses)
    assert unresolved > 0
    assert (Path("shared/consumer.py"), "artifacts/old.json") in _orphaned(
        gate.analyse_consumer_side(tmp_path, []), UNRESOLVED_WRITER
    )


@pytest.mark.parametrize(
    "writer,reader,writer_pattern,reader_pattern",
    [
        (
            "Path('$HOME/artifacts/old.json')",
            "Path('~/artifacts/old.json')",
            "$HOME/artifacts/old.json",
            "./~/artifacts/old.json",
        ),
        (
            "Path('$HOME/artifacts/old.json')",
            "Path.home() / 'artifacts/old.json'",
            "$HOME/artifacts/old.json",
            "~/artifacts/old.json",
        ),
        (
            "Path('~/artifacts/old.json')",
            "Path.home() / 'artifacts/old.json'",
            "./~/artifacts/old.json",
            "~/artifacts/old.json",
        ),
    ],
    ids=["dollar-home-vs-tilde", "dollar-home-vs-home", "tilde-vs-home"],
)
@pytest.mark.parametrize("reverse", [False, True], ids=["forward", "reverse"])
def test_python_home_identities_do_not_pair(
    gate, tmp_path: Path, writer, reader, writer_pattern, reader_pattern, reverse
) -> None:
    if reverse:
        writer, reader = reader, writer
        writer_pattern, reader_pattern = reader_pattern, writer_pattern
    _write(
        tmp_path,
        "shared/consumer.py",
        f"from pathlib import Path\n({writer}).write_text('{{}}')\n({reader}).read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), reader_pattern) in _orphaned(report)
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {(a.action, a.pattern, a.bounded) for a in accesses} == {
        ("write", writer_pattern, True),
        ("read", reader_pattern, True),
    }
    assert unresolved == report.unresolvable == 0


@pytest.mark.parametrize(
    "expression,expected",
    [
        (
            "Path('wrong') / (Path('/review-fixture') / 'artifacts/old.json')",
            "/review-fixture/artifacts/old.json",
        ),
        ("Path('a') / '/b'", "/b"),
    ],
    ids=["codex-exact-nested", "plain"],
)
def test_absolute_rhs_discards_left_before_repo_normalisation(gate, expression, expected) -> None:
    root = Path("/review-fixture")
    assert (
        gate._resolve_path_expr(
            ast.parse(expression, mode="eval").body, {}, root / "consumer.py", root, {}
        )
        == expected
    )


@pytest.mark.parametrize("assigned", [False, True], ids=["inline", "assigned"])
@pytest.mark.parametrize("root_kind", ["codex-exact", "repository"])
def test_nested_absolute_join_does_not_certify_left_relative_reader(
    gate, tmp_path: Path, assigned, root_kind
) -> None:
    root = "/review-fixture" if root_kind == "codex-exact" else tmp_path.as_posix()
    inner = f"Path({root!r}) / 'artifacts/old.json'"
    setup = f"target = {inner}\n" if assigned else ""
    expression = "Path('wrong') / " + ("target" if assigned else f"({inner})")
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n" + setup + f"({expression}).write_text('{{}}')\n"
        "Path('wrong/artifacts/old.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert (Path("shared/consumer.py"), "wrong/artifacts/old.json") in _orphaned(report)
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    expected = (
        "/review-fixture/artifacts/old.json" if root_kind == "codex-exact" else "artifacts/old.json"
    )
    assert [(a.pattern, a.bounded) for a in accesses if a.action == "write"] == [(expected, True)]
    assert unresolved == report.unresolvable == 0


def test_genuine_relative_join_still_pairs(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\n"
        "(Path('wrong') / (Path('artifacts') / 'old.json')).write_text('{}')\n"
        "Path('wrong/artifacts/old.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert not report.findings
    assert report.unresolvable == 0


@pytest.fixture
def synthetic_repo(gate, monkeypatch):
    """Keep the exact review root without creating /review-fixture on the host."""
    root = Path("/review-fixture")
    relative = Path("shared/consumer.py")
    monkeypatch.setattr(gate, "_iter_python_sources", lambda *_a, **_kw: [root / relative])
    monkeypatch.setattr(
        gate, "_git_tracking", lambda _root: gate.GitTracking(frozenset({str(relative)}), True)
    )

    def analyse(source):
        monkeypatch.setattr(gate, "_read", lambda *_a, **_kw: source)
        return gate.analyse_consumer_side(root, []), gate.collect_artifact_accesses(root)

    return analyse


@pytest.mark.parametrize(
    "inner",
    [
        "Path('/review-fixture/artifacts/placeholder').parent",
        "Path('/review-fixture/' + 'artifacts')",
        "Path(f\"/review-fixture/{'artifacts'}\")",
    ],
    ids=["parent", "addition", "fstring"],
)
@pytest.mark.parametrize("assigned", [False, True], ids=["inline", "assigned"])
def test_composed_absolute_identity_survives_expression_evaluation(
    synthetic_repo, inner, assigned
) -> None:
    setup = f"target = {inner}\n" if assigned else ""
    operand = "target" if assigned else inner
    report, (accesses, unresolved, *_) = synthetic_repo(
        "from pathlib import Path\n"
        + setup
        + f"(Path('wrong') / {operand} / 'old.json').write_text('{{}}')\n"
        "Path('wrong/artifacts/old.json').read_text()\n"
    )
    # The inline parent case is codex-1's exact composed expression and repo_root.
    assert (Path("shared/consumer.py"), "wrong/artifacts/old.json") in _orphaned(report)
    assert {(a.action, a.pattern, a.bounded) for a in accesses} == {
        ("write", "artifacts/old.json", True),
        ("read", "wrong/artifacts/old.json", True),
    }
    assert unresolved == report.unresolvable == 0


@pytest.mark.parametrize("reverse", [False, True], ids=["codex-exact", "reverse"])
def test_posix_backslash_and_slash_filenames_do_not_pair(synthetic_repo, reverse) -> None:
    writer = "Path(r'$HOME\\artifacts/old.json')"
    reader = "Path('$HOME/artifacts/old.json')"
    writer_pattern = r"$HOME\artifacts/old.json"
    reader_pattern = "$HOME/artifacts/old.json"
    if reverse:
        writer, reader = reader, writer
        writer_pattern, reader_pattern = reader_pattern, writer_pattern
    report, (accesses, unresolved, *_) = synthetic_repo(
        f"from pathlib import Path\n{writer}.write_text('{{}}')\n{reader}.read_text()\n"
    )
    assert (Path("shared/consumer.py"), reader_pattern) in _orphaned(report)
    assert {(a.action, a.pattern, a.bounded) for a in accesses} == {
        ("write", writer_pattern, True),
        ("read", reader_pattern, True),
    }
    assert unresolved == report.unresolvable == 0


@pytest.mark.parametrize("conversion", ["r", "a"])
def test_formatted_backslashes_are_runtime_filename_characters(synthetic_repo, conversion) -> None:
    # _format_constant applies repr/ascii just as Python does. These backslashes
    # belong to the resulting filename; decoding them again would change it.
    value = "\\é"
    converted = repr(value) if conversion == "r" else ascii(value)
    expected = "$HOME" + converted + "/old.json"
    slash_pattern = Path(expected.replace("\\", "/")).as_posix()
    expression = f'Path(f"$HOME{{value!{conversion}}}/old.json")'
    report, (accesses, unresolved, *_) = synthetic_repo(
        f"from pathlib import Path\nvalue = {value!r}\n"
        f"{expression}.write_text('{{}}')\nPath({expected!r}).read_text()\n"
        f"Path({slash_pattern!r}).read_text()\n"
    )
    assert (Path("shared/consumer.py"), slash_pattern) in _orphaned(report)
    assert (Path("shared/consumer.py"), expected) not in _orphaned(report)
    assert [(a.pattern, a.bounded) for a in accesses if a.action == "write"] == [(expected, True)]
    assert unresolved == report.unresolvable == 0


@pytest.mark.parametrize("assigned", [False, True], ids=["codex-exact", "assigned"])
def test_absolute_writer_does_not_certify_wrong_prefix_reader(synthetic_repo, assigned) -> None:
    setup = "target = Path('artifacts/old.json').absolute()\n" if assigned else ""
    operand = "target" if assigned else "Path('artifacts/old.json').absolute()"
    report, (accesses, unresolved, *_) = synthetic_repo(
        "from pathlib import Path\n" + setup + f"(Path('/wrong') / {operand}).write_text('{{}}')\n"
        "Path('/wrong/artifacts/old.json').read_text()\n"
    )
    assert (Path("shared/consumer.py"), "/wrong/artifacts/old.json") in _orphaned(report)
    assert [(a.pattern, a.bounded) for a in accesses if a.action == "write"] == [
        ("/wrong/*", False)
    ]
    assert unresolved == report.unresolvable == 1
    if not assigned:
        # The literal remains visible evidence in the unresolved expression, not
        # a claimed result of absolute() or an assumed cwd in the writer pattern.
        assert any(
            "Path('artifacts/old.json').absolute()" in site for site in report.unresolved_paths
        )


@pytest.mark.parametrize("operation", ["read_text()", "write_text('{}')"])
def test_standalone_absolute_retains_literal_as_unresolved_evidence(
    synthetic_repo, operation
) -> None:
    report, (accesses, unresolved, *_) = synthetic_repo(
        "from pathlib import Path\n" + f"Path('artifacts/old.json').absolute().{operation}\n"
    )
    assert not any(a.bounded for a in accesses)
    assert unresolved == report.unresolvable == 1
    assert any("Path('artifacts/old.json').absolute()" in site for site in report.unresolved_paths)


@pytest.mark.parametrize("assigned", [False, True], ids=["reviewer-join", "assigned"])
def test_resolve_writer_does_not_certify_wrong_prefix_reader(synthetic_repo, assigned) -> None:
    setup = "target = Path('artifacts/old.json').resolve()\n" if assigned else ""
    operand = "target" if assigned else "Path('artifacts/old.json').resolve()"
    report, (accesses, unresolved, *_) = synthetic_repo(
        "from pathlib import Path\n" + setup + f"(Path('/wrong') / {operand}).write_text('{{}}')\n"
        "Path('/wrong/artifacts/old.json').read_text()\n"
    )
    # A resolved operand is absolute and discards /wrong; its actual root and
    # symlink targets cannot be established from this source.
    assert (Path("shared/consumer.py"), "/wrong/artifacts/old.json") in _orphaned(report)
    assert [(a.pattern, a.bounded) for a in accesses if a.action == "write"] == [
        ("/wrong/*", False)
    ]
    assert unresolved == report.unresolvable == 1
    if not assigned:
        assert any(
            "Path('artifacts/old.json').resolve()" in site for site in report.unresolved_paths
        )


@pytest.mark.parametrize("operation", ["read_text()", "write_text('{}')"])
def test_standalone_resolve_retains_literal_as_unresolved_evidence(
    synthetic_repo, operation
) -> None:
    report, (accesses, unresolved, *_) = synthetic_repo(
        "from pathlib import Path\n" + f"Path('artifacts/old.json').resolve().{operation}\n"
    )
    assert not any(a.bounded for a in accesses)
    assert unresolved == report.unresolvable == 1
    assert any("Path('artifacts/old.json').resolve()" in site for site in report.unresolved_paths)


# An argument supplied inside a region whose reachability is not established used to certify the
# callee's write, because demotion rewrites the ACCESS list and the callee's parameters are
# resolved in a different scope walk from a binding the demotion never touched. Reported as a
# critical at `:4359` independently by two reviewer families.
#
# The rows pair every withholding with the control that must NOT withhold. `bounded` is what
# certification means here, so a row expecting `True` is asserting that the repair left a real
# writer alone — withholding everything would satisfy the finding and destroy the report.
_HELPER = (
    "import json\nimport os\n\n\n"
    "def unresolved():\n    return os.environ.get('SOURCE', '')\n\n\n"
    "def emit(path):\n    with open(path, 'w') as handle:\n        json.dump({}, handle)\n"
)
_RELAY = "\n\ndef relay(path):\n    emit(path)\n"
_UNREACHED = "\n[emit('artifacts/a.json') for _ in unresolved()]\n"


def _certified_writes(accesses) -> dict[str, bool]:
    """Whether each written pattern has AT LEAST ONE certified writer.

    Two call sites can resolve to the same path and be scanned as two invocation states, so a
    pattern carries both a certified row from the reached site and a withheld one from the
    unreached site. "One reached caller is enough" is therefore `any(bounded)`, and reading the
    last row instead silently reported whichever state happened to be scanned second.
    """
    flags: dict[str, set[bool]] = {}
    for access in accesses:
        if access.action == "write":
            flags.setdefault(access.pattern, set()).add(access.bounded)
    return {pattern: any(seen) for pattern, seen in flags.items()}


@pytest.mark.parametrize(
    ("suffix", "expected"),
    [
        (_UNREACHED, {"artifacts/a.json": False}),
        # One reached call site is enough: withholding here would assert that the reached
        # caller does not exist, which is the over-reach demotion itself avoids.
        (_UNREACHED + "emit('artifacts/a.json')\n", {"artifacts/a.json": True}),
        (
            _UNREACHED + "emit('artifacts/b.json')\n",
            {"artifacts/a.json": False, "artifacts/b.json": True},
        ),
        (
            _UNREACHED + "\n\ndef caller():\n    emit('artifacts/a.json')\n\n\ncaller()\n",
            {"artifacts/a.json": True},
        ),
    ],
    ids=["unreached-only", "same-state-also-reached", "different-states", "reached-via-caller"],
)
def test_an_argument_from_an_unreached_region_does_not_certify_the_callees_write(
    synthetic_repo, suffix, expected
) -> None:
    _report, (accesses, *_rest) = synthetic_repo(_HELPER + suffix)
    assert _certified_writes(accesses) == expected


@pytest.mark.parametrize(
    ("suffix", "expected"),
    [
        ("\n[relay('artifacts/a.json') for _ in unresolved()]\n", {"artifacts/a.json": False}),
        (
            "\n[relay('artifacts/a.json') for _ in unresolved()]\nrelay('artifacts/a.json')\n",
            {"artifacts/a.json": True},
        ),
    ],
    ids=["relay-unreached-only", "relay-also-reached"],
)
def test_uncertainty_reaches_the_callee_of_the_callee(synthetic_repo, suffix, expected) -> None:
    """A relay must not launder the doubt.

    The callee is scanned in its own walk, so a body reached only through an unreached region
    would otherwise record its own calls as ordinary observations and re-certify one hop down.
    """
    _report, (accesses, *_rest) = synthetic_repo(_HELPER + _RELAY + suffix)
    assert _certified_writes(accesses) == expected


@pytest.mark.parametrize(
    "form",
    [
        "[configure() for artifact in [1]]",
        "{configure() for artifact in [1]}",
        "{artifact: configure() for artifact in [1]}",
        "list(configure() for artifact in [1])",
    ],
    ids=["list", "set", "dict", "consumed-generator"],
)
def test_a_callees_global_mutation_survives_a_comprehension_target_of_the_same_name(
    synthetic_repo, form
) -> None:
    """A name collision is not ownership.

    The comprehension target is local; the callee rebinds the GLOBAL. Subtracting target names
    from the callee's effect names discarded that mutation because the spellings matched, and once
    the enclosing invalidation was removed the result was a CERTIFIED writer for
    `artifacts/old.json` — which Python never writes — absorbing the real orphan reader entirely
    (review critical, codex).

    Python writes `artifacts/new.json` only, in all four forms.
    """
    report, (accesses, unresolved, *_rest) = synthetic_repo(
        "from pathlib import Path\n"
        "artifact = Path('artifacts/old.json')\n"
        "def configure():\n"
        "    global artifact\n"
        "    artifact = Path('artifacts/new.json')\n"
        f"{form}\n"
        "artifact.write_text('{}')\n"
        "Path('artifacts/old.json').read_text()\n"
    )
    assert not [a for a in accesses if a.action == "write" and a.bounded]
    assert unresolved == 1
    # The reader must SURVIVE. A phantom producer that absorbs its orphan is the failure this
    # row exists for, so asserting the writer alone would not catch a regression.
    assert (Path("shared/consumer.py"), "artifacts/old.json") in _orphaned(
        report, UNRESOLVED_WRITER
    )


def test_a_reached_call_is_not_demoted_by_a_later_undecided_region(synthetic_repo) -> None:
    """The two channels a region demotes into do not advance together.

    A call resolving entirely in its callee appends no access here, so its ledger entry shared the
    access position of whatever followed — and an unrelated undecided operand region beginning at
    the same access count demoted a call that had already run (review finding, codex). Python
    writes `a.json` unconditionally; the later condition cannot reach back.
    """
    _report, (accesses, *_rest) = synthetic_repo(
        "from pathlib import Path\n"
        "def emit(path): open(path, 'w')\n"
        "def condition(): return not False\n"
        "emit('artifacts/a.json')\n"
        "condition() and 0\n"
        "Path('artifacts/a.json').read_text()\n"
    )
    assert _certified_writes(accesses) == {"artifacts/a.json": True}


def test_a_well_formed_consumer_side_entry_actually_suppresses_its_finding(
    gate, tmp_path: Path
) -> None:
    """The allowlist's positive direction, which nothing in the tree exercised.

    `producer-consumer-allowlist.json` ships `"entries": []`, so its documented key shape — the
    `kind=consumer_side` requirement and the `<finding kind>:<read pattern>` spelling — had no
    live entry demonstrating it, and the only covering control pinned the CROSS-DOMAIN refusal:
    that a consumer_side entry cannot exempt a producer finding (review finding, claude). This is
    the other half, and it is the half that would notice the key shape drifting.
    """
    _write(
        tmp_path,
        "shared/consumer.py",
        "from pathlib import Path\nPath('artifacts/orphan.json').read_text()\n",
    )
    plain = gate.analyse_consumer_side(tmp_path, [])
    orphan = next(f for f in plain.findings if f.reader.pattern == "artifacts/orphan.json")
    assert orphan.kind == "consumer-reads-unwritten-artifact"
    assert orphan.key == f"{orphan.kind}:artifacts/orphan.json"

    entry = gate.AllowlistEntry(
        orphan.key, "worked example for the documented key shape", "consumer_side"
    )
    exempted = gate.analyse_consumer_side(tmp_path, [entry])
    assert [f.reader.pattern for f in exempted.findings] == []
    assert [(f.reader.pattern, e.reason) for f, e in exempted.allowlisted] == [
        ("artifacts/orphan.json", "worked example for the documented key shape")
    ]

    # And the kind really is load-bearing: the same pattern without `kind=consumer_side` does
    # not suppress it, which is what makes the cross-domain control above meaningful.
    untyped = gate.AllowlistEntry(orphan.key, "no kind declared", None)
    assert [f.reader.pattern for f in gate.analyse_consumer_side(tmp_path, [untyped]).findings] == [
        "artifacts/orphan.json"
    ]
