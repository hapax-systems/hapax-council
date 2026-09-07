"""What a returned expression IS, checked against Python rather than against my expectations.

Every row here compiles the helper, runs it, and asserts the scanner's certified writer equals the
string Python actually built. The oracle is the language, not a hand-written table — which matters
because the hand-written tables were wrong three times in a row on these same shapes: reading
`NamedExpr.target` instead of its value, folding operands against one scope snapshot, and walking
breadth-first so an inner binding published after the outer one that contained it.

Transposed without changing its oracle from the coordinator's
`coordination-20260904/test_scanner_expression_state_root.py`, which qualified the shared
expression-state candidate this module now guards (2026-09-07). The three withheld rows are
withheld because the branch that assigns is not the branch that runs, or is a lambda body that
never runs at all; those are limits, named rather than silently passing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check-producer-consumers.py"

# The scanner must certify NOTHING for these: an assignment the taken branch never reaches, and a
# lambda body that is compiled here and called nowhere.
WITHHELD = {"unselected_assignment", "selected_assignment", "unselected_lambda"}

EXPRESSIONS = (
    ("plain", "x"),
    ("lone", "(x := 'actual')"),
    ("earlier", "f\"{x}{(x := 'actual')}\""),
    ("later", "f\"{(x := 'actual')}{x}\""),
    ("addition", "(x := 'actual') + x"),
    ("unselected_assignment", "f\"{('prefix' if True else (x := 'hidden'))}{x}\""),
    ("selected_assignment", "f\"{((x := 'actual') if True else (x := 'hidden'))}{x}\""),
    ("unselected_lambda", "f\"{('prefix' if True else (lambda: (x := 'hidden')))}{x}\""),
    ("nested_sequential", "f\"{(x := 'a') + (x := x + 'b')}{x}\""),
    ("nested_same_target", "f\"{(x := (x := 'a') + 'b')}{x}\""),
    ("typed_bool", 'f"{(x := True)}{x}"'),
    ("typed_int", 'f"{(x := 3)}{x}"'),
    ("outer_reads_before_inner_write", "f\"{(x := x + (x := 'a'))}{x}\""),
    ("outer_reads_after_inner_write", "f\"{(x := (x := 'a') + x)}{x}\""),
    ("outer_and_inner_read_old_values", "f\"{(x := x + (x := x + 'a'))}{x}\""),
)

MATRIX = [(name, expression, "wrong") for name, expression in EXPRESSIONS] + [
    ("bool_rebind", "(x := True)", "True"),
    ("int_rebind", "(x := 3)", "3"),
    ("string_from_int", "(x := 'actual')", 3),
    ("str_rebind", "str(x := 3)", "wrong"),
    ("format_rebind", "f'{(x := 3)}'", "wrong"),
    ("plain_bool", "True", "True"),
    ("plain_conversion", "str(x)", 3),
]


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_consumer_expression_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def observed(gate, tmp_path: Path, body: str) -> tuple[set[str], set[str]]:
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "example.py").write_text("from pathlib import Path\n" + body + "\n")
    accesses, _, _, _ = gate.collect_artifact_accesses(tmp_path)
    report = gate.analyse_consumer_side(tmp_path, [])
    writers = {row.pattern for row in accesses if row.action == "write" and row.bounded}
    orphans = {
        reader.pattern
        for finding in report.findings
        if finding.kind == "consumer-reads-unwritten-artifact"
        for reader in finding.readers
    }
    return writers, orphans


@pytest.mark.parametrize(("name", "expression", "argument"), MATRIX, ids=[row[0] for row in MATRIX])
def test_expression_result_and_binding_agree(gate, tmp_path, name, expression, argument):
    """The certified writer is what the helper returns when Python runs it.

    Only the helper is executed, and only with `str` in its builtins: it is a pure expression over
    one parameter, hand-authored above. The consumer's `open(...)`/`read_text()` tail is parsed by
    the scanner and never performed.
    """

    helper = f"def value(x):\n    return {expression}\n"
    namespace = {"__builtins__": {"str": str}}
    exec(compile(helper, "<pure-expression-state-oracle>", "exec"), namespace)  # noqa: S102
    actual = namespace["value"](argument)
    assert type(actual) in (str, bool, int), "the oracle only speaks about scalars"

    writers, orphans = observed(
        gate,
        tmp_path,
        helper
        + f"open(value({argument!r}), 'w', closefd=False)\nPath({str(actual)!r}).read_text()",
    )
    if name in WITHHELD or not isinstance(actual, str):
        assert writers == set(), f"{name}: nothing may be certified here"
        assert str(actual) in orphans, f"{name}: the reader keeps its orphan"
    else:
        assert writers == {actual}, f"{name}: the writer is the string Python built"
        assert actual not in orphans
