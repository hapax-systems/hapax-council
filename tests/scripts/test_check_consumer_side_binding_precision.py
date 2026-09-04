"""Precision canaries for the consumer-side scanner (sixth review round of #4626).

All three families found the same four defects: read sites resolved against assignments that
occur later in the scope; file-backed APIs the scanner does not model vanished without even an
unresolvable count; relative and ``from pkg import module`` imports never established the
producer's module name; and a repository-global helper table keyed by bare function name let one
module's ``artifact_path`` answer for another's.
"""

from __future__ import annotations

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


def _unwritten(report) -> dict[tuple[Path, str], int]:
    counts: dict[tuple[Path, str], int] = {}
    for finding in report.findings:
        if finding.kind == "consumer-reads-unwritten-artifact":
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
    unwritten = _unwritten(report)
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
    assert (Path("shared/consumer.py"), "artifacts/later.json") not in _unwritten(report)


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
    assert (Path("shared/consumer.py"), "artifacts/first.json") not in _unwritten(report)


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
    assert _unwritten(report).get((Path("shared/consumer.py"), "artifacts/blocky.json")) == 1


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
    ) in _unwritten(report)


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
    unwritten = _unwritten(report)
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
    unwritten = _unwritten(report)
    assert (Path("shared/consumer.py"), "artifacts/shared.json") in unwritten
    assert (Path("shared/consumer.py"), "artifacts/other.json") not in unwritten
