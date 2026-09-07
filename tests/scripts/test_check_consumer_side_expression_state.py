"""What a returned expression IS, checked against Python rather than against my expectations.

Every row here compiles the helper, runs it, and asserts the scanner's certified writer equals the
string Python actually built. The oracle is the language, not a hand-written table — which matters
because the hand-written tables were wrong three times in a row on these same shapes: reading
`NamedExpr.target` instead of its value, folding operands against one scope snapshot, and walking
breadth-first so an inner binding published after the outer one that contained it.

Transposed without changing its oracle from the coordinator's
`coordination-20260904/test_scanner_expression_state_root.py`, which qualified the shared
expression-state candidate this module now guards (2026-09-07). The withheld rows are withheld
because the branch that assigns is not the branch that runs, is a lambda body that never runs at
all, or is a shape the scanner does not model; those are limits, named rather than silently
passing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check-producer-consumers.py"

# The scanner must certify NOTHING for these: an assignment the taken branch never reaches, and a
# lambda body that is compiled here and called nowhere.
WITHHELD = {
    "unselected_assignment",
    "selected_assignment",
    "unselected_lambda",
    # Subscripting a dict display is not modelled, so these certify nothing on either side of the
    # evaluation-order question. They are here as the BOUNDARY, measured: four families report a
    # dict-order shape that certifies a wrong file, and I could not construct one — so what these
    # rows pin is that these particular dict shapes certify nothing at all, which a future change
    # that starts certifying them wrongly would break.
    "dict_value_assigns",
    "dict_value_assigns_read_before",
    "dict_key_read_before_its_value",
    "dict_second_pair_reads_first",
}

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
    # Dict displays evaluate key1, value1, key2, value2 — each key before its own value, in
    # source order — while `ast.Dict` stores keys and values as two separate lists, so a walk over
    # `ast.iter_child_nodes` yields every key and then every value. Four families reported that
    # order producing a wrong certified filename (2026-09-07) and glm's minor recorded these
    # shapes as missing from this matrix.
    #
    # **These four rows do not reproduce that report.** Measured at `93ac1ef0a` and with a
    # corrected walk: both certify NOTHING here, because subscripting a dict display is not a
    # modelled path — so the rows are in WITHHELD, pinning the boundary they actually establish
    # rather than the defect they were written to catch. The reviewers' failing shape is asked
    # for rather than guessed at; a repair with no reproducing case is how the last two withdrawn
    # guards were written.
    ("dict_value_assigns", "f\"{ {'k': (x := 'a')}['k'] }{x}\""),
    ("dict_value_assigns_read_before", "f'{x}'+f\"{ {'k': (x := 'a')}['k'] }\""),
    ("dict_key_read_before_its_value", "f\"{ {x: (x := 'a')}['wrong'] }{x}\""),
    ("dict_second_pair_reads_first", "f\"{ {(x := 'a'): 'v', x: 'w'}['a'] }{x}\""),
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


# A dict display evaluates key1, value1, key2, value2 — each key before its OWN value, in source
# order — and `**` unpacking evaluates only its value. `ast.Dict` declares `keys` then `values` as
# two lists, so any walk over `ast.iter_child_nodes` sees every key and then every value.
#
# The shapes above could not show this, because they read the dict back by subscript and that is
# not a modelled path. These return the BINDING after the display instead (coordinator, 2026-09-07,
# supplying the shape after mine failed to reach it), which is what makes the ordering observable.
DICT_ORDER = (
    # Discriminating: an assignment in a VALUE precedes one in a later KEY, so a keys-then-values
    # walk lets the earlier assignment land last.
    ("value_then_key_assign", "d = {'first': (x := 'actual'), (x := 'final'): 0}"),
    ("value_then_key_then_plain", "d = {'a': (x := 'first'), (x := 'final'): 0, 'c': 1}"),
    ("unpacked_value_then_later_key", "d = {**{'a': (x := 'first')}, (x := 'final'): 0}"),
    ("pair_assigns_both_then_key", "d = {(x := 'k1'): (x := 'v1'), (x := 'final'): 0}"),
    # Already correct before the repair, and must stay so: the last assignment in source order is
    # also the last one a keys-then-values walk reaches.
    ("key_then_value_assign", "d = {(x := 'first'): 0, 'k': (x := 'final')}"),
    ("both_keys_assign", "d = {(x := 'first'): 0, (x := 'final'): 1}"),
    ("both_values_assign", "d = {'a': (x := 'first'), 'b': (x := 'final')}"),
    ("unpack_after_assigning_key", "d = {(x := 'final'): 0, **{'a': 1}}"),
    ("value_assigns_key_reads_later", "d = {'a': (x := 'final'), x: 0}"),
    ("control_no_assignment", "d = {'a': 0, 'b': 1}\n    x = 'final'"),
)


@pytest.mark.parametrize(("name", "body"), DICT_ORDER, ids=[row[0] for row in DICT_ORDER])
def test_dict_displays_are_walked_in_evaluation_order(gate, tmp_path, name, body):
    """The certified writer is the binding Python leaves behind, not the one the walk saw last.

    Every row starts `x = 'wrong'` and ends `return x`, so the answer is entirely decided by which
    assignment inside the display ran last. Four families reported the wrong filename this
    produces; the executed helper is the oracle, so no row here encodes my reading of the order.
    """

    helper = f"def value():\n    x = 'wrong'\n    {body}\n    return x\n"
    namespace: dict = {"__builtins__": {}}
    exec(compile(helper, "<dict-order-oracle>", "exec"), namespace)  # noqa: S102
    actual = namespace["value"]()
    assert isinstance(actual, str)

    writers, orphans = observed(
        gate,
        tmp_path,
        helper + f"open(value(), 'w', closefd=False)\nPath({actual!r}).read_text()",
    )
    assert writers == {actual}, f"{name}: the writer is the binding Python actually leaves"
    assert actual not in orphans
