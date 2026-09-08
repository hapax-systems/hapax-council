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
    # `unselected_lambda` was here, and moved OUT when path expansion learned reachability:
    # `('prefix' if True else (lambda: ...))` has a constant test, so only `'prefix'` is
    # reachable and the row now certifies `prefixwrong` — exactly what the executed helper
    # builds. This block's own note says the danger is a change that starts certifying these
    # "wrongly"; certifying correctly retires the boundary rather than breaching it, and the
    # row is a stronger control outside this set, where it asserts the file rather than the
    # absence of one.
    #
    # `unselected_assignment` stays: its unselected branch holds a walrus, and the expression
    # WALKER still forks both arms of an `IfExp` regardless of a constant test, so the binding
    # is ambiguous and nothing is certified. That is imprecision, not the wrong-certification
    # defect repaired here, and withholding is the safe direction — so it is left alone rather
    # than repaired speculatively.
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
    # WITHIN one pair: the value reads what its own key just bound. Reversing key and value
    # inside the pair changes the answer, which the pair-ordering rows above cannot see — a
    # negative control run against a value-before-key mutation passed all of them.
    ("key_binds_what_its_value_reads", "d = {(x := 'k'): (x := x + '1')}"),
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


# `and`, `or` and CHAINED comparisons stop early. `a < b < c` evaluates `a < b` and, only if that
# is true, `b < c` — so an assignment in a later operand may never run while the walk still reaches
# it. Reported critical by the codex reader at b96341134 with the first row below, where the
# scanner certified `artifacts/actual.json`, a file the program never writes, and then suppressed
# the orphan reader that would have exposed it.
#
# Every row here is decided by CONSTANTS, because only a constant makes one continuation
# unreachable. A dynamic operand leaves both genuinely possible, and both must keep being
# certified — that is the same contract as an if/else binding two different paths, and it is held
# by test_function_inherits_module_post_flow_bindings in the branch module rather than duplicated
# here. Narrowing a dynamic short circuit would break it, which is how a first attempt at this
# repair was caught.
SHORT_CIRCUIT = (
    # Skipped: the assignment never runs, so the earlier binding is what gets written.
    ("codex_chained_comparison", "2 < 1 < (x := 'actual')"),
    ("chain_decided_false_at_second_link", "1 < 2 < 1 < (x := 'actual')"),
    ("and_false_skips", "False and (x := 'actual')"),
    ("or_true_skips", "True or (x := 'actual')"),
    ("zero_is_falsy_and_skips", "0 and (x := 'actual')"),
    # Run: the twins that must KEEP certifying, so the repair cannot be a blanket refusal.
    ("chain_continues", "'a' < 'b' < (x := 'actual')"),
    ("and_true_runs", "True and (x := 'actual')"),
    ("or_false_runs", "False or (x := 'actual')"),
    ("empty_string_is_falsy_so_or_runs", "'' or (x := 'actual')"),
    ("empty_tuple_is_falsy_so_or_runs", "() or (x := 'actual')"),
)


@pytest.mark.parametrize(("name", "body"), SHORT_CIRCUIT, ids=[row[0] for row in SHORT_CIRCUIT])
def test_short_circuited_operands_do_not_certify_a_writer(gate, tmp_path, name, body):
    """The certified writer is the file Python writes, not the one the walk happened to bind.

    Each row starts `x = 'wrong'` and ends `return x`, so the answer is decided entirely by
    whether the short-circuited operand ran. The executed helper is the oracle, so no row
    encodes my reading of Python's evaluation rules — which is the point, because I spent two
    hours probing `BoolOp` shapes for this and the reproducing case was a chained comparison.

    Both halves of the finding are asserted: the writer's identity, and that the reader stays an
    orphan when nothing wrote its file. Certifying a phantom writer is worse than certifying
    none, because it silently removes the orphan that would have shown the gap.
    """

    helper = f"def value():\n    x = 'wrong'\n    {body}\n    return x\n"
    namespace: dict = {"__builtins__": {}}
    exec(compile(helper, "<short-circuit-oracle>", "exec"), namespace)  # noqa: S102
    actual = namespace["value"]()
    assert actual in {"wrong", "actual"}, "the oracle only speaks about these two spellings"
    never_written = "actual" if actual == "wrong" else "wrong"

    writers, orphans = observed(
        gate,
        tmp_path,
        helper + f"open(value(), 'w', closefd=False)\nPath({never_written!r}).read_text()",
    )
    assert writers == {actual}, f"{name}: certified a file the program does not write"
    assert never_written in orphans, f"{name}: the orphan reader must survive"


# Reachability is decided in TWO places, and repairing the expression walker left the other
# one answering the same question the opposite way. Reported critical by codex at `c01c645d2`:
#
#   * PATH EXPANSION expanded every arm of an `or` / `IfExp` regardless of a constant test, so
#     `open('wrong.json' or 'actual.json', 'w')` certified both names and suppressed an orphan
#     reader of the file Python never writes.
#   * `ast.literal_eval` special-cases `set()` — the empty set has no literal spelling — so a
#     module SHADOWING that name had its branch decided by this scanner differently from
#     Python, certifying a file that is never written.
#
# Each row states what Python really writes; the executed helper remains the oracle.
PATH_REACHABILITY = (
    # Decided by a constant, so only one arm can be the path.
    ("or_first_operand_is_truthy", "'artifacts/actual.json' or 'artifacts/never.json'"),
    ("or_first_operand_is_falsy", "'' or 'artifacts/actual.json'"),
    ("ifexp_constant_true", "'artifacts/actual.json' if True else 'artifacts/never.json'"),
    ("ifexp_constant_false", "'artifacts/never.json' if False else 'artifacts/actual.json'"),
    ("or_chain_stops_at_first_truthy", "'' or 'artifacts/actual.json' or 'artifacts/never.json'"),
)


@pytest.mark.parametrize(
    ("name", "expression"), PATH_REACHABILITY, ids=[row[0] for row in PATH_REACHABILITY]
)
def test_path_expansion_respects_reachability(gate, tmp_path, name, expression):
    """The certified writer is the path Python resolves, not every arm the expander can reach.

    The reader below names a file the program never writes, so a run that expands unreachable
    arms both certifies a phantom producer AND silently absorbs this orphan — which is the
    half of the finding that makes a wrong certification worse than no certification.
    """

    helper = f"def value():\n    return {expression}\n"
    namespace: dict = {"__builtins__": {}}
    exec(compile(helper, "<path-reachability-oracle>", "exec"), namespace)  # noqa: S102
    actual = namespace["value"]()
    assert actual == "artifacts/actual.json", f"{name}: oracle disagrees with the row"

    writers, orphans = observed(
        gate,
        tmp_path,
        helper + "open(value(), 'w', closefd=False)\nPath('artifacts/never.json').read_text()",
    )
    assert writers == {actual}, f"{name}: certified an arm Python never evaluates"
    assert "artifacts/never.json" in orphans, f"{name}: the orphan reader must survive"


def test_a_shadowed_set_call_is_not_a_falsy_constant(gate, tmp_path):
    """`ast.literal_eval('set()')` returns an empty set, so a call must be refused outright.

    With `set` shadowed to return a truthy string, Python runs the assignment and writes
    `actual.json`. A scanner that read `set()` as an empty set took the short circuit and
    certified `wrong.json` — a file never written — while suppressing its orphan reader.
    """

    helper = (
        "def set():\n    return 'nonempty'\n"
        "def value():\n"
        "    x = 'artifacts/wrong.json'\n"
        "    set() and (x := 'artifacts/actual.json')\n"
        "    return x\n"
    )
    namespace: dict = {"__builtins__": {}}
    exec(compile(helper, "<shadowed-set-oracle>", "exec"), namespace)  # noqa: S102
    actual = namespace["value"]()
    assert actual == "artifacts/actual.json"

    writers, orphans = observed(
        gate,
        tmp_path,
        helper + "open(value(), 'w', closefd=False)\nPath('artifacts/actual.json').read_text()",
    )
    # The finding is specifically that the scanner certified `wrong.json` — the arm Python does
    # NOT take — and suppressed the orphan reader of the file that really is written. So that is
    # what this forbids, and only that.
    #
    # A shadowed call is genuinely unknowable, so two other outcomes are both acceptable and the
    # scanner produces each depending on scope: keeping both arms (module scope, the estate's
    # ordinary treatment of an undecided condition) or withholding entirely (function scope, the
    # safe direction). Asserting `actual in writers` instead would have demanded a resolution the
    # scanner has no basis for, which is the opposite error.
    assert writers != {"artifacts/wrong.json"}, "certified only the branch Python does not take"
    if not writers:
        assert actual in orphans, "withheld, so the reader of the written file stays an orphan"


def test_a_genuine_falsy_literal_still_short_circuits(gate, tmp_path):
    """The twin: refusing calls must not cost the real constants their decision."""

    helper = (
        "def value():\n"
        "    x = 'artifacts/actual.json'\n"
        "    () and (x := 'artifacts/never.json')\n"
        "    return x\n"
    )
    namespace: dict = {"__builtins__": {}}
    exec(compile(helper, "<falsy-literal-oracle>", "exec"), namespace)  # noqa: S102
    actual = namespace["value"]()
    assert actual == "artifacts/actual.json"

    writers, orphans = observed(
        gate,
        tmp_path,
        helper + "open(value(), 'w', closefd=False)\nPath('artifacts/never.json').read_text()",
    )
    assert writers == {actual}, "a genuine falsy literal must still decide its operator"
    assert "artifacts/never.json" in orphans
