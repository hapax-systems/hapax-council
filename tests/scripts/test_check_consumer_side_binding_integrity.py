"""Static evidence is preserved across scan failures, binding scopes, and expansion caps."""

from __future__ import annotations

import importlib.util
import itertools
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check-producer-consumers.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_consumer_side_integrity", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(repo: Path, source: str) -> Path:
    path = repo / "shared" / "consumer.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _unwritten(report) -> set[str]:
    return {
        finding.reader.pattern
        for finding in report.findings
        if finding.kind == "consumer-reads-unwritten-artifact"
    }


@pytest.mark.parametrize("failure", ["PermissionError", "UnicodeDecodeError", "SyntaxError"])
def test_source_gap_is_named_in_text_json_and_exit_status(
    gate, tmp_path: Path, monkeypatch, capsys, failure: str
) -> None:
    broken = _write(tmp_path, "open('artifacts/hidden.json').read()\n")
    if failure == "PermissionError":
        broken.chmod(0)
    elif failure == "UnicodeDecodeError":
        broken.write_bytes(b"\xff\xfe\x80")
    else:
        broken.write_text("def broken(:\n", encoding="utf-8")
    good = tmp_path / "shared" / "good.py"
    good.write_text("open('artifacts/visible.json').read()\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "reports"))
    try:
        args = gate.build_parser().parse_args(["--consumer-side"])
        assert gate.run_consumer_side(args) == 0
        output = capsys.readouterr().out
        assert "[REPORT-ERROR]" in output
        assert "status=incomplete" in output
        assert "REPORT-ONLY" in output
        assert "shared/consumer.py" in output and failure in output
        payload = json.loads((tmp_path / "reports/consumer-side-report.json").read_text())
        assert payload["summary"]["status"] == "incomplete"
        assert payload["summary"]["report_only"] is True
        assert payload["source_gaps"] == [
            {
                "path": "shared/consumer.py",
                "operation": "parse" if failure == "SyntaxError" else "read",
                "error_class": failure,
            }
        ]
        assert "artifacts/visible.json" in {f["read_pattern"] for f in payload["findings"]}
    finally:
        broken.chmod(0o600)


def test_main_keeps_invalid_source_report_only(gate, tmp_path: Path, monkeypatch, capsys) -> None:
    _write(tmp_path, "def broken(:\n")
    monkeypatch.chdir(tmp_path)
    destination = tmp_path / "reports/consumer-side-report.json"
    assert gate.main(["--consumer-side", "--report-json", str(destination)]) == 0
    output = capsys.readouterr().out
    assert "REPORT-ONLY" in output and "[REPORT-ERROR]" in output
    assert "shared/consumer.py" in output and "SyntaxError" in output
    payload = json.loads(destination.read_text())
    assert payload["summary"]["status"] == "incomplete"
    assert payload["errors"] == ["shared/consumer.py: parse failed (SyntaxError)"]


@pytest.mark.parametrize(
    ("operation", "action"),
    [("open().read()", "read"), ("open('w').write('{}')", "write")],
)
def test_assigned_path_open_receiver_keeps_access(
    gate, tmp_path: Path, operation: str, action: str
) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\np = Path('artifacts/orphan.json')\n" + f"p.{operation}\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {(item.action, item.pattern, item.operation) for item in accesses} == {
        (action, "artifacts/orphan.json", "Path.open")
    }
    assert unresolved == 0
    if action == "read":
        assert _unwritten(gate.analyse_consumer_side(tmp_path, [])) == {"artifacts/orphan.json"}


@pytest.mark.parametrize("receiver", ["choose()", "'artifacts/orphan.json'"])
@pytest.mark.parametrize(
    "operation", ["open().read()", "open('w').write('{}')", "open(mode='w').write('{}')"]
)
def test_assigned_unknown_open_receiver_is_counted(
    gate, tmp_path: Path, operation: str, receiver: str
) -> None:
    _write(tmp_path, f"p = {receiver}\np.{operation}\n")
    accesses, unresolved, _imports, unrecognised = gate.collect_artifact_accesses(tmp_path)
    assert accesses == []
    assert unresolved == 1
    assert unrecognised == {"p.open": 1}


@pytest.mark.parametrize("nested", ["def", "async def", "lambda"])
@pytest.mark.parametrize("rebinding", ["after_definition", "loop", "between_calls"])
def test_rebound_closure_never_invents_an_obsolete_writer(
    gate, tmp_path: Path, capsys, nested: str, rebinding: str
) -> None:
    definition = (
        f"    {nested} inner():\n        artifact.write_text('{{}}')\n"
        if nested != "lambda"
        else "    inner = lambda: artifact.write_text('{}')\n"
    )
    mutation = "    artifact = Path('artifacts/new.json')\n"
    if rebinding == "loop":
        mutation = "    for _ in range(2):\n    " + mutation
    call = "    await inner()\n" if nested == "async def" else "    inner()\n"
    before = call if rebinding == "between_calls" else ""
    outer = "async def outer():\n" if nested == "async def" else "def outer():\n"
    invoke = "import asyncio\nasyncio.run(outer())\n" if nested == "async def" else "outer()\n"
    _write(
        tmp_path,
        "from pathlib import Path\n"
        + outer
        + "    artifact = Path('artifacts/old.json')\n"
        + definition
        + before
        + mutation
        + call
        + invoke
        + "Path('artifacts/old.json').read_text()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    writers = {item.pattern for item in accesses if item.action == "write"}
    assert writers != {"artifacts/old.json"}, "definition-time snapshot fabricated the only writer"
    # This analysis cannot bound callback invocation, so rebinding must remain a named gap.
    assert writers == set()
    assert unresolved == 1
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "artifacts/old.json" in _unwritten(report)
    payload = gate._report_json(report)
    assert payload["unresolved_closures"] == [
        "shared/consumer.py:4: closure binding artifact may change after definition"
    ]
    gate.print_consumer_side_report(report, tmp_path / "report.json")
    assert "[UNRESOLVED] " + payload["unresolved_closures"][0] in capsys.readouterr().out


@pytest.mark.parametrize(
    "body",
    [
        "        return artifact.read_text()\n",
        "        return artifact.open().read()\n",
        "        artifact.open('w').write('{}')\n",
        "        Path(f'{artifact}/state.json').write_text('{}')\n",
        "        target = artifact\n        Path(f'{target}/state.json').write_text('{}')\n",
    ],
)
def test_rebound_closure_access_is_unresolved_even_through_formatting(
    gate, tmp_path: Path, body: str
) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\ndef outer():\n    artifact = Path('artifacts/old')\n"
        "    def inner():\n" + body + "    artifact = choose()\n    return inner\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert accesses == []
    assert unresolved == 1
    assert gate.analyse_consumer_side(tmp_path, []).unresolved_closures


def test_closure_rebinding_clears_all_branch_alternatives(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\ndef outer(flag):\n"
        "    artifact = Path('artifacts/a.json') if flag else Path('artifacts/b.json')\n"
        "    def inner():\n        artifact.write_text('{}')\n"
        "    artifact = Path('artifacts/new.json')\n    inner()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert accesses == []
    assert unresolved == 1


def test_closure_in_loop_cannot_keep_a_previous_iteration_binding(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\ndef outer(items):\n"
        "    for item in items:\n"
        "        artifact = Path('artifacts/old.json') if item else Path('artifacts/new.json')\n"
        "        def inner():\n            artifact.write_text('{}')\n"
        "        callbacks.append(inner)\n    for callback in callbacks:\n        callback()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert accesses == []
    assert unresolved == 1


def test_later_rebinding_does_not_change_a_frozen_default(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\ndef outer():\n    artifact = Path('artifacts/frozen.json')\n"
        "    def inner(saved=artifact):\n        saved.write_text('{}')\n"
        "    artifact = Path('artifacts/new.json')\n    inner()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {(item.action, item.pattern) for item in accesses} == {
        ("write", "artifacts/frozen.json")
    }
    assert unresolved == 0
    assert gate.analyse_consumer_side(tmp_path, []).unresolved_closures == ()


def test_nonlocal_rebinding_cannot_leave_a_snapshot_writer(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\ndef outer():\n    artifact = Path('artifacts/old.json')\n"
        "    def inner():\n        artifact.write_text('{}')\n"
        "    def rebind():\n        nonlocal artifact\n"
        "        artifact = Path('artifacts/new.json')\n    rebind()\n    inner()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert accesses == []
    assert unresolved == 1


def test_redefined_outer_scopes_keep_their_own_closure_evidence(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\ndef outer():\n    artifact = Path('artifacts/stable.json')\n"
        "    def inner():\n        artifact.read_text()\n"
        "outer()\ndef outer():\n    artifact = Path('artifacts/old.json')\n"
        "    def inner():\n        artifact.write_text('{}')\n"
        "    artifact = Path('artifacts/new.json')\n    inner()\nouter()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {(item.action, item.pattern) for item in accesses} == {("read", "artifacts/stable.json")}
    assert unresolved == 1


def test_all_source_gaps_are_retained(gate, tmp_path: Path) -> None:
    _write(tmp_path, "def broken(:\n")
    (tmp_path / "shared/binary.py").write_bytes(b"\xff")
    report = gate.analyse_consumer_side(tmp_path, [])
    assert {(str(gap.path), gap.error_class) for gap in report.source_gaps} == {
        ("shared/consumer.py", "SyntaxError"),
        ("shared/binary.py", "UnicodeDecodeError"),
    }


def _conditional(leaves: list[str]) -> str:
    result = leaves[-1]
    for i, leaf in reversed(list(enumerate(leaves[:-1]))):
        result = f"({leaf} if flags[{i}] else {result})"
    return result


@pytest.mark.parametrize("shape", ["conditional", "or", "product"])
@pytest.mark.parametrize("assigned", [False, True])
def test_expression_cap_preserves_every_pattern(
    gate, tmp_path: Path, shape: str, assigned: bool
) -> None:
    count = gate._MAX_PATH_EXPR_VARIANTS + 4
    expected = {f"artifacts/branch-{i}.json" for i in range(count)}
    leaves = [f"Path('artifacts/branch-{i}.json')" for i in range(count)]
    if shape == "conditional":
        expression = _conditional(leaves)
    elif shape == "or":
        expression = "(" + " or ".join(leaves) + ")"
    else:
        roots = [f"Path('artifacts/root-{i}')" for i in range(4)]
        names = [f"'branch-{i}.json'" for i in range(4)]
        expression = f"({_conditional(roots)} / {_conditional(names)})"
        expected = {
            f"artifacts/root-{i}/branch-{j}.json" for i, j in itertools.product(range(4), repeat=2)
        }
    body = (
        f"    artifact = {expression}\n    return artifact.read_text()\n"
        if assigned
        else f"    return ({expression}).read_text()\n"
    )
    _write(tmp_path, "from pathlib import Path\ndef load(flags):\n" + body)
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _unwritten(report) == expected
    assert report.unresolvable == 0
    payload = gate._report_json(report)
    assert payload["capped_expressions"]
    assert all(site.startswith("shared/consumer.py:") for site in payload["capped_expressions"])


@pytest.mark.parametrize(
    ("imports", "definition"),
    [
        ("import shutil", "def use(shutil):\n    shutil.copy2(SRC, DEST)"),
        ("import os", "def use(os):\n    os.replace(SRC, DEST)"),
        ("", "def use(open):\n    open(DEST, 'w')"),
        ("", "def use(callback):\n    open = callback\n    open(DEST, 'w')"),
        ("from shutil import copy2 as duplicate", "def use(duplicate):\n    duplicate(SRC, DEST)"),
        (
            "from shutil import copy2 as duplicate",
            "def use(*, duplicate):\n    duplicate(SRC, DEST)",
        ),
        ("import io", "def use(io):\n    io.open(DEST, 'w')"),
    ],
)
def test_shadowed_callee_cannot_supply_a_writer(
    gate, tmp_path: Path, imports: str, definition: str
) -> None:
    _write(
        tmp_path,
        f"from pathlib import Path\n{imports}\nSRC = Path('artifacts/source.json')\nDEST = Path('artifacts/destination.json')\n{definition}\nDEST.read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not [access for access in accesses if access.action == "write"]
    assert "artifacts/destination.json" in _unwritten(gate.analyse_consumer_side(tmp_path, []))


@pytest.mark.parametrize("nested", ["def inner():", "async def inner():", "lambda"])
@pytest.mark.parametrize("operation", ["read_text()", "write_text('{}')"])
def test_nested_scope_inherits_enclosing_path(
    gate, tmp_path: Path, nested: str, operation: str
) -> None:
    body = (
        f"    {nested}\n        artifact.{operation}\n"
        if nested != "lambda"
        else f"    inner = lambda: artifact.{operation}\n"
    )
    _write(
        tmp_path,
        "from pathlib import Path\ndef outer():\n    artifact = Path('artifacts/closure.json')\n"
        + body,
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {(access.action, access.pattern) for access in accesses} == {
        ("read" if operation.startswith("read") else "write", "artifacts/closure.json")
    }
    assert unresolved == 0


def test_nested_scope_keeps_all_enclosing_branch_values(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\ndef outer(flag):\n    if flag:\n        artifact = Path('artifacts/a.json')\n    else:\n        artifact = Path('artifacts/b.json')\n    def inner():\n        return artifact.read_text()\n",
    )
    assert _unwritten(gate.analyse_consumer_side(tmp_path, [])) == {
        "artifacts/a.json",
        "artifacts/b.json",
    }


def test_definition_expressions_use_enclosing_bindings(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\ndef outer():\n    artifact = Path('artifacts/definition.json')\n    @decorate(artifact.read_text())\n    def inner(artifact=open(artifact), *, other=open('artifacts/keyword-default.json')):\n        pass\n",
    )
    assert _unwritten(gate.analyse_consumer_side(tmp_path, [])) == {
        "artifacts/definition.json",
        "artifacts/keyword-default.json",
    }


@pytest.mark.parametrize("cap", [1, 2, 3])
@pytest.mark.parametrize("shape", ["if", "if_else", "try", "loop", "match"])
def test_generated_branch_corpus_preserves_concrete_union(
    gate, tmp_path: Path, monkeypatch, cap: int, shape: str
) -> None:
    monkeypatch.setattr(gate, "_MAX_BRANCH_STATES", cap)
    count = cap + 3
    source = (
        "from pathlib import Path\ndef load(flags):\n    artifact = Path('artifacts/start.json')\n"
    )
    expected = {"artifacts/start.json"}
    for i in range(count):
        path = f"artifacts/branch-{i}.json"
        assignment = f"artifact = Path('{path}')"
        expected.add(path)
        if shape == "if":
            source += f"    if flags[{i}]:\n        {assignment}\n"
        elif shape == "if_else":
            source += f"    if flags[{i}]:\n        {assignment}\n    else:\n        artifact = artifact\n"
        elif shape == "try":
            source += f"    try:\n        might_raise()\n        {assignment}\n    except OSError:\n        pass\n"
        elif shape == "loop":
            source += f"    for item in flags:\n        {assignment}\n"
        else:
            source += f"    match flags[{i}]:\n        case True:\n            {assignment}\n"
    _write(tmp_path, source + "    return artifact.read_text()\n")
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _unwritten(report) == expected
    assert report.unresolvable == 0


def test_json_failure_remedy_is_an_accepted_and_effective_option(
    gate, tmp_path: Path, monkeypatch, capsys
) -> None:
    _write(tmp_path, "open('artifacts/orphan.json')\n")
    blocked = tmp_path / "blocked"
    blocked.write_text("file, not directory", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RUNNER_TEMP", str(blocked))
    parser = gate.build_parser()
    gate.run_consumer_side(parser.parse_args(["--consumer-side"]))
    output = capsys.readouterr().out
    remedy = next(line for line in output.splitlines() if "[REPORT-ERROR]" in line)
    flags = set(re.findall(r"--[a-z][a-z-]+", remedy))
    option_set = {option for action in parser._actions for option in action.option_strings}
    assert flags and flags <= option_set
    assert "--report-json" in flags
    destination = tmp_path / "recovered/report.json"
    assert (
        gate.run_consumer_side(
            parser.parse_args(["--consumer-side", "--report-json", str(destination)])
        )
        == 0
    )
    assert json.loads(destination.read_text())["summary"]["findings"] == 1


@pytest.mark.parametrize(
    "definition",
    [
        "def use(Path):\n    Path('artifacts/destination.json').write_text('{}')",
        "def use(callback):\n    open(DEST, 'w')\n    open = callback",
        "def open(*args):\n    return None\ndef use():\n    open(DEST, 'w')",
        "def artifact_path():\n    return DEST\ndef use(artifact_path):\n    artifact_path().write_text('{}')",
    ],
)
def test_shadowed_constructor_or_helper_cannot_supply_a_writer(
    gate, tmp_path: Path, definition: str
) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\nDEST = Path('artifacts/destination.json')\n"
        + definition
        + "\nDEST.read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not [access for access in accesses if access.action == "write"]
    report = gate.analyse_consumer_side(tmp_path, [])
    assert any(
        finding.reader.pattern == "artifacts/destination.json"
        and (
            finding.kind == "consumer-reads-unwritten-artifact"
            or "producer-match=no" in finding.detail
        )
        for finding in report.findings
    )


def test_module_assignment_preserves_capped_union_for_function_reads(gate, tmp_path: Path) -> None:
    count = gate._MAX_PATH_EXPR_VARIANTS + 4
    leaves = [f"Path('artifacts/module-{i}.json')" for i in range(count)]
    _write(
        tmp_path,
        "from pathlib import Path\nartifact = "
        + _conditional(leaves)
        + "\ndef load():\n    return artifact.read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _unwritten(report) == {f"artifacts/module-{i}.json" for i in range(count)}
    assert report.unresolvable == 0


def test_unreadable_source_directory_is_a_named_gap(gate, tmp_path: Path) -> None:
    directory = _write(tmp_path, "open('artifacts/hidden.json')\n").parent
    directory.chmod(0)
    try:
        report = gate.analyse_consumer_side(tmp_path, [])
        assert {(str(gap.path), gap.error_class) for gap in report.source_gaps} == {
            ("shared", "PermissionError")
        }
    finally:
        directory.chmod(0o700)


def test_script_decode_failure_is_reported_but_excluded_bytecode_is_not(
    gate, tmp_path: Path
) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "unreadable-command").write_bytes(b"\xff")
    excluded = scripts / "__pycache__"
    excluded.mkdir()
    (excluded / "cached.pyc").write_bytes(b"\xff")
    report = gate.analyse_consumer_side(tmp_path, [])
    assert {(str(gap.path), gap.error_class) for gap in report.source_gaps} == {
        ("scripts/unreadable-command", "UnicodeDecodeError")
    }
