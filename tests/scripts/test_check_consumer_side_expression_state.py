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

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check-producer-consumers.py"

# The scanner must certify NOTHING for these: an assignment the taken branch never reaches, and a
# lambda body that is compiled here and called nowhere.
WITHHELD = {
    # All three `IfExp` rows that used to sit here — `unselected_lambda`,
    # `unselected_assignment` and `selected_assignment` — moved OUT once reachability was
    # decided in one place and consulted by the walker as well as by path expansion. Each has a
    # constant test, so only the taken arm is evaluated, and each now certifies exactly what the
    # executed helper builds: `prefixwrong`, `prefixwrong` and `actualactual`. This block's own
    # note says the danger is a change that starts certifying these *wrongly*; certifying
    # correctly retires the boundary rather than breaching it, and outside this set the rows are
    # stronger, asserting a file instead of the absence of one.
    #
    # I had written here that `unselected_assignment` would stay, on the reasoning that the
    # walker's `IfExp` fork "only withholds, and withholding is the safe direction". That was
    # wrong twice over: an unreachable arm can carry an EFFECT, not merely a binding — codex's
    # `open('never.json','w') if False else None` certified a phantom producer — and once the
    # walker honours the test, the binding resolves too.
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


def reported_readers(gate, tmp_path: Path, body: str) -> set[str]:
    """Readers that survive into ANY consumer-side finding, whatever its kind.

    `observed` reads only `consumer-reads-unwritten-artifact`, which is the right question for a
    decided absence and the wrong one for a site whose execution is merely undetermined — those
    now report `consumer-reads-artifact-with-unresolved-writer`. The rows below care that the
    reader survived at all; `REPORT_BOUNDARY` is where WHICH kind it gets is pinned. Keeping the
    two questions in two helpers is what stops the second from being blurred into the first.
    """

    # `exist_ok` so a row may ask BOTH questions of one arrangement — `observed` for what was
    # certified, this for whether the reader survived — without a second temporary tree whose
    # only difference would be its name.
    shared = tmp_path / "shared"
    shared.mkdir(exist_ok=True)
    (shared / "example.py").write_text("from pathlib import Path\n" + body + "\n")
    gate.collect_artifact_accesses(tmp_path)
    report = gate.analyse_consumer_side(tmp_path, [])
    return {reader.pattern for finding in report.findings for reader in finding.readers}


def recorded(gate, tmp_path: Path, body: str) -> list:
    """Every access as recorded, `bounded` included — not just the certified ones.

    `observed` filters on `bounded`, which is the right question for certification and the wrong
    one for "did this site survive at all". The distinction is the whole point of the rows below:
    a site can be present-and-uncertain, and that is a different answer from absent.
    """

    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "example.py").write_text("from pathlib import Path\n" + body + "\n")
    accesses, _, _, _ = gate.collect_artifact_accesses(tmp_path)
    return list(accesses)


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
        # **"Keeps its orphan" is a claim about the READER surviving, not about which absence
        # kind it survives under.** These rows read the orphan set from `observed`, which
        # collects only `consumer-reads-unwritten-artifact`; once the report learned to tell a
        # decided absence from an undetermined execution, four of them — the dict-display rows,
        # whose writers are unbounded — moved to the weaker kind and failed while measuring
        # nothing that had changed (review finding, codex, at `9f8f9d192`, run against the
        # pinned tests with in-memory fixture I/O, which is the run I could not do).
        #
        # Asserted through `reported_readers` for the same reason the comprehension rows are:
        # survival here, classification in `REPORT_BOUNDARY`. Two helpers, two questions.
        assert str(actual) in reported_readers(
            gate,
            tmp_path,
            helper
            + f"open(value({argument!r}), 'w', closefd=False)\nPath({str(actual)!r}).read_text()",
        ), f"{name}: the reader keeps its orphan"
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
    # TIGHTENED 2026-09-08. This row used to assert only `writers != {"artifacts/wrong.json"}`,
    # which PERMITS `{wrong, actual}` — and all four reviewer families reported that as still
    # allowing the phantom the row was written to forbid. They were right, and the harm is
    # measurable rather than theoretical: with a reader of `wrong.json` present, certifying it
    # suppressed the `consumer-reads-unwritten-artifact` finding entirely, so a real orphan
    # disappeared behind a file nothing writes.
    #
    # The old reasoning — that a shadowed call is unknowable, so both keeping both arms and
    # withholding were acceptable — is superseded, not overruled by preference. The scanner now
    # RESOLVES this case through the existing helper-summary machinery: `set` is uniquely bound
    # here and returns a constant, so the walrus provably runs. Measured across all four cells
    # of module/function scope x wrong-path/written-path reader.
    #
    # Withholding was not the safe direction either. At function scope it certified nothing, so
    # `actual.json` — a file the program really does write — was reported as an orphan: a
    # fabricated finding, which is the same defect pointed the other way.
    assert "artifacts/wrong.json" not in writers, (
        "certified a phantom writer; with a reader present it suppresses that reader's genuine "
        "consumer-reads-unwritten-artifact finding"
    )
    assert actual in writers, (
        "the arm Python takes is decidable here — `set` is uniquely bound with a constant "
        "return — and withholding it fabricates an orphan for a file that IS written"
    )
    assert actual not in orphans


def test_an_unreachable_conditional_arm_cannot_carry_an_effect(gate, tmp_path):
    """An arm a constant test rules out must not be SCANNED, never mind certified.

    I argued the walker's `IfExp` fork only blurred bindings, so withholding made it safe to
    leave. That reasoning missed the case codex reported at `45a37aeda`: an unreachable arm can
    hold a call with an effect, and scanning it classifies that call. `open(...) if False else
    None` therefore certified a producer for a file the program never opens, and absorbed the
    orphan reader that would have shown it.
    """

    writers, orphans = observed(
        gate,
        tmp_path,
        "open('artifacts/never.json', 'w', closefd=False) if False else None\n"
        "Path('artifacts/never.json').read_text()\n",
    )
    assert writers == set(), "certified a writer inside an arm the test rules out"
    assert "artifacts/never.json" in orphans, "the orphan reader must survive"


def test_a_reachable_conditional_arm_still_carries_its_effect(gate, tmp_path):
    """The twin: the arm that IS taken must keep being certified."""

    writers, orphans = observed(
        gate,
        tmp_path,
        "open('artifacts/actual.json', 'w', closefd=False) if True else None\n"
        "Path('artifacts/never.json').read_text()\n",
    )
    assert writers == {"artifacts/actual.json"}
    assert "artifacts/never.json" in orphans


@pytest.mark.parametrize("operands", [7, 8], ids=["under_the_cap", "over_the_cap"])
def test_reachability_survives_the_variant_cap(gate, tmp_path, operands):
    """The capped fallback re-expands the node, and used to re-expand what was filtered out.

    codex's boundary, verbatim: seven empty operands stay under the variant cap and certified
    only `actual.json`; eight tripped it, `_expand_conditional_union` derived the arms again
    without reachability, and both filenames became bounded writers while a reader of
    `never.json` disappeared. Both sides are pinned so the cap cannot silently become a bypass.
    """

    assigns = "".join(f"x{index} = ''\n" for index in range(operands))
    chain = " or ".join(f"x{index}" for index in range(operands))
    tail = "('artifacts/actual.json' if True else 'artifacts/never.json')"

    writers, orphans = observed(
        gate,
        tmp_path,
        assigns
        + f"open({chain} or {tail}, 'w', closefd=False)\n"
        + "Path('artifacts/never.json').read_text()\n",
    )
    assert writers == {"artifacts/actual.json"}, f"{operands} operands: unreachable arm restored"
    assert "artifacts/never.json" in orphans, f"{operands} operands: orphan reader must survive"


# A comprehension body that never runs was the FIFTH place deciding reachability blind, after
# the walker's BoolOp/Compare/IfExp, path expansion and the capped union. Reported critical by
# glm at `455612d07`: `[open('artifacts/never.json','w') for _ in []]`, a `if False` filter and
# an unexecuted generator each certified a produced artifact and absorbed its orphan reader,
# with no recorded uncertainty, while Python wrote nothing.
COMPREHENSION_NEVER_RUNS = (
    ("empty_list_iterable", "[open('artifacts/never.json', 'w', closefd=False) for _ in []]"),
    ("empty_tuple_iterable", "[open('artifacts/never.json', 'w', closefd=False) for _ in ()]"),
    ("empty_string_iterable", "[open('artifacts/never.json', 'w', closefd=False) for _ in '']"),
    ("false_filter", "[open('artifacts/never.json', 'w', closefd=False) for _ in [1] if False]"),
    ("generator_never_iterated", "(open('artifacts/never.json', 'w', closefd=False) for _ in [])"),
    # codex's three remaining shapes at `07757da06`, each reproduced certifying a phantom AND
    # absorbing its orphan reader. The first repair stopped at the comprehension BODY; these are
    # the clauses around it, which were still scanned unconditionally.
    #
    # A filter AFTER a constant-false one never evaluates — Python stops at the first false.
    (
        "filter_after_a_false_filter",
        "[x for x in [1] if False if open('artifacts/never.json', 'w', closefd=False)]",
    ),
    # The SECOND generator's iterable never evaluates when the first yields nothing.
    (
        "iterable_after_an_empty_generator",
        "[y for x in [] for y in [open('artifacts/never.json', 'w', closefd=False)]]",
    ),
    # A generator BOUND but never consumed runs no body. Distinct from `generator_never_iterated`
    # above, whose iterable is empty: this one's iterable is non-empty, so only consumption
    # decides it, and nothing here consumes `g`.
    (
        "generator_bound_but_unconsumed",
        "g = (open('artifacts/never.json', 'w', closefd=False) for _ in [1])",
    ),
    # Root readback 2026-09-08. Passing a generator to a call was treated as PROOF of
    # consumption, which certified the body of one handed to a callee that never iterates it
    # and absorbed the real orphan. Measured against Python: none of these four runs the body.
    # `list`/`sorted`/`join` do, and stay in the twin table below — the repair is a table of
    # proven consumers, not a reversal.
    (
        "generator_to_an_identity_helper",
        "def keep(g):\n"
        "    return g\n"
        "keep(open('artifacts/never.json', 'w', closefd=False) for _ in [1])",
    ),
    (
        "generator_to_enumerate",
        "enumerate(open('artifacts/never.json', 'w', closefd=False) for _ in [1])",
    ),
    ("generator_to_zip", "zip(open('artifacts/never.json', 'w', closefd=False) for _ in [1])"),
    ("generator_to_iter", "iter(open('artifacts/never.json', 'w', closefd=False) for _ in [1])"),
    # Root readback 2026-09-08, second pass. The proven-consumer table matched on the NAME, so
    # a locally shadowed builtin and an arbitrary method spelled `join` were both spent as
    # proof. Python writes nothing in either. The same fold on a bare name was corrected for
    # `str` a round earlier in `_builtin_str_call`; this is that defect in a second channel.
    (
        "shadowed_list_identity",
        "def list(g):\n"
        "    return g\n"
        "list(open('artifacts/never.json', 'w', closefd=False) for _ in [1])",
    ),
    (
        "shadowed_sum_identity",
        "def sum(g):\n"
        "    return g\n"
        "sum(open('artifacts/never.json', 'w', closefd=False) for _ in [1])",
    ),
    (
        "arbitrary_receiver_join",
        "class Holder:\n"
        "    def join(self, g):\n"
        "        return g\n"
        "Holder().join(open('artifacts/never.json', 'w', closefd=False) for _ in [1])",
    ),
    (
        "arbitrary_receiver_writelines",
        "class Holder:\n"
        "    def writelines(self, g):\n"
        "        return g\n"
        "Holder().writelines(open('artifacts/never.json', 'w', closefd=False) for _ in [1])",
    ),
    # A PROVEN consumer still does not make the whole body reachable: the body has its own
    # short-circuit, and the element the iterable yields decides it. `any`/`all` really do run
    # the body — these are not iteration-stop cases — so certifying the consumption and then
    # certifying every call inside it are two separate steps, and the second was missing.
    (
        "consumed_body_short_circuits_or",
        "any(x or open('artifacts/never.json', 'w', closefd=False) for x in [True])",
    ),
    (
        "consumed_body_short_circuits_and",
        "all(x and open('artifacts/never.json', 'w', closefd=False) for x in [False])",
    ),
    # The conditional-expression twin of the same binding. Kept because the substitution was
    # written for `BoolOp` and the arm-selection site is a different handler: a rule that holds
    # in one operator and not its neighbour is a rule stated at the wrong level.
    (
        "consumed_body_conditional_arm",
        "[open('artifacts/never.json', 'w', closefd=False) if x else None for x in [False]]",
    ),
    # `shadow is None` means NOT ESTABLISHED. The function table answers about DEFINITIONS, so a
    # rebinding by import alias or plain assignment left the name looking unshadowed and the
    # predicate spent that as proof. Neither of these defines a function anywhere.
    (
        "consumer_name_rebound_by_import_alias",
        "from builtins import iter as list\n"
        "list(open('artifacts/never.json', 'w', closefd=False) for _ in [1])",
    ),
    (
        "consumer_name_rebound_by_assignment",
        "list = iter\nlist(open('artifacts/never.json', 'w', closefd=False) for _ in [1])",
    ),
    # The call FORM matters as well as the callee and the slot: `max` with two positionals
    # compares the objects and iterates neither.
    (
        "max_compares_two_generators_without_iterating",
        "max((open('artifacts/never.json', 'w', closefd=False) for _ in [1]), "
        "(x for x in [1]), key=id)",
    ),
    # The rule names TWO callees and only one was pinned. A guard written as `{"min", "max"}` with
    # a control for `max` alone is the same one-site-current shape this file keeps repairing, one
    # level down: nothing would have caught `min` being dropped from the set.
    (
        "min_compares_two_generators_without_iterating",
        "min((open('artifacts/never.json', 'w', closefd=False) for _ in [1]), "
        "(x for x in [1]), key=id)",
    ),
    # POSITION, not just callee. A proven consumer iterates its FIRST POSITIONAL argument and
    # nothing else, so neither of these iterates anything — and neither shadows a builtin, which
    # is what makes them independent of the shadowing rows above.
    (
        "proven_consumer_keyword_argument",
        "dict(payload=(open('artifacts/never.json', 'w', closefd=False) for _ in [1]))",
    ),
    (
        "proven_consumer_default_keyword",
        "max([1], default=(open('artifacts/never.json', 'w', closefd=False) for _ in [1]))",
    ),
    # The three shapes the clause handlers could decide and were not being given the means to.
    # Distinct from the literal `False` and literal-empty rows above: here the constant arrives
    # through a uniquely bound helper or a comparison, and the handler was told not to look.
    (
        "filter_from_a_constant_helper",
        "def stop():\n"
        "    return False\n"
        "[open('artifacts/never.json', 'w', closefd=False) for _ in [1] if stop()]",
    ),
    (
        "filter_from_a_comparison",
        "[open('artifacts/never.json', 'w', closefd=False) for _ in [1] if 1 == 2]",
    ),
    # The three shapes that were carried as a strict xfail one commit ago, now closed by
    # withholding rather than by resolving each one. They differ in WHY the clause could not be
    # decided — a list-returning helper the constant channel does not carry, a name bound to an
    # empty literal, and a helper whose `not True` is a UnaryOp nothing folds — and that is the
    # point: three separate resolution gaps, one rule. **Unresolved is not permission.**
    (
        "iterable_from_a_constant_helper",
        "def empty():\n"
        "    return []\n"
        "[open('artifacts/never.json', 'w', closefd=False) for _ in empty()]",
    ),
    (
        "iterable_from_a_bound_empty_name",
        "items = []\n[open('artifacts/never.json', 'w', closefd=False) for _ in items]",
    ),
    # A literal binding is only a proof while NOTHING can have changed it. Each of these leaves
    # the name denoting something other than the literal it was assigned, and the stateful
    # version kept vouching for the original — ten measured ways, of which these are five.
    # Python writes in none of them, because in every one the iterable is empty by the time the
    # comprehension runs.
    (
        "literal_binding_mutated_in_place",
        "items = [1]\nitems.clear()\n"
        "[open('artifacts/never.json', 'w', closefd=False) for _ in items]",
    ),
    (
        "literal_binding_mutated_through_an_alias",
        "items = [1]\nalias = items\nalias.clear()\n"
        "[open('artifacts/never.json', 'w', closefd=False) for _ in items]",
    ),
    (
        "literal_binding_emptied_by_augmented_assignment",
        "items = [1]\nitems *= 0\n"
        "[open('artifacts/never.json', 'w', closefd=False) for _ in items]",
    ),
    (
        "literal_binding_emptied_by_slice_delete",
        "items = [1]\ndel items[:]\n"
        "[open('artifacts/never.json', 'w', closefd=False) for _ in items]",
    ),
    # ESCAPE routes, which the first version of the predicate missed while its prose claimed
    # them. Neither hands the name to an attribute or a bare-name assignment, and both let the
    # object be emptied out of sight — a callee that clears it, and a container alias.
    (
        "literal_binding_passed_to_a_mutating_callee",
        "items = [1]\ndef empty(value):\n    value.clear()\nempty(items)\n"
        "[open('artifacts/never.json', 'w', closefd=False) for _ in items]",
    ),
    (
        "literal_binding_escaped_through_a_container",
        "items = [1]\nholder = [items]\nholder[0].clear()\n"
        "[open('artifacts/never.json', 'w', closefd=False) for _ in items]",
    ),
    # MULTI-ELEMENT literals. Refusing to guess which element binds the target is right;
    # letting the body certify anyway while refusing is not. Every element short-circuits in
    # both of these and Python opens nothing.
    (
        "multi_element_literal_every_element_short_circuits",
        "[x or open('artifacts/never.json', 'w', closefd=False) for x in [True, True]]",
    ),
    (
        "multi_element_literal_under_a_consuming_builtin",
        "any(x or open('artifacts/never.json', 'w', closefd=False) for x in [True, False])",
    ),
    # The SPELLINGS the first version missed, because it keyed the element count on
    # `ast.List`/`ast.Tuple` syntax while the value channel resolves a wider domain. Every one
    # of these short-circuits for every element and Python opens nothing.
    (
        "named_single_element_list",
        "items = [True]\n[x or open('artifacts/never.json', 'w', closefd=False) for x in items]",
    ),
    (
        "named_multi_element_list",
        "items = [True, True]\n"
        "[x or open('artifacts/never.json', 'w', closefd=False) for x in items]",
    ),
    (
        "named_tuple",
        "items = (True, True)\n"
        "[x or open('artifacts/never.json', 'w', closefd=False) for x in items]",
    ),
    (
        "inline_set",
        "[x or open('artifacts/never.json', 'w', closefd=False) for x in {1, 2}]",
    ),
    (
        "inline_dict",
        "[x or open('artifacts/never.json', 'w', closefd=False) for x in {1: 0, 2: 0}]",
    ),
    (
        "inline_str",
        "[x or open('artifacts/never.json', 'w', closefd=False) for x in 'ab']",
    ),
    (
        "inline_bytes",
        "[x or open('artifacts/never.json', 'w', closefd=False) for x in b'ab']",
    ),
    # The target is in scope for every clause DOWNSTREAM of its own generator, not just for its
    # filters and the final element. Checking only the near clauses left the outer target
    # unknown while the next iterable certified its conditional call.
    (
        "later_generator_iterable_reads_the_target",
        "[y for x in [True, True] for y in [x or open('artifacts/never.json', 'w', closefd=False)]]",
    ),
    (
        "later_generator_filter_reads_the_target",
        "[y for x in [True, True] for y in [1] "
        "if x or open('artifacts/never.json', 'w', closefd=False)]",
    ),
    (
        "literal_binding_rebound_in_an_untaken_branch",
        "items = [1]\nif not True:\n    items = [2]\nelse:\n    items = []\n"
        "[open('artifacts/never.json', 'w', closefd=False) for _ in items]",
    ),
    (
        "filter_from_a_helper_returning_not_true",
        "def stop():\n"
        "    return not True\n"
        "[open('artifacts/never.json', 'w', closefd=False) for _ in [1] if stop()]",
    ),
    # RESOLVING A VALUE IS NOT REACHING ITS BODY. Every one of these sources is a constant this
    # scanner reads perfectly, and none of them is something Python can iterate: `iter()` raises
    # TypeError before the first element, so the body runs zero times. The handler had one
    # boolean where the domain has three cases — enumerable, not iterable, undecided — and read
    # "I cannot count this" as "I cannot count this yet", then certified (review finding, root,
    # at `120d38d9b`, 36 counterexamples with a runtime oracle recording zero opens).
    #
    # Six values because six TYPES fail differently in principle and identically in fact:
    # `None`, a bool, a zero and a non-zero int, a float and a complex. Truthiness is not the
    # question here — `3` and `1.25` are truthy and still never yield an element.
    (
        "noniterable_none",
        "[open('artifacts/never.json', 'w', closefd=False) for _ in None]",
    ),
    (
        "noniterable_bool",
        "[open('artifacts/never.json', 'w', closefd=False) for _ in True]",
    ),
    (
        "noniterable_zero",
        "[open('artifacts/never.json', 'w', closefd=False) for _ in 0]",
    ),
    (
        "noniterable_truthy_int",
        "[open('artifacts/never.json', 'w', closefd=False) for _ in 3]",
    ),
    (
        "noniterable_float",
        "[open('artifacts/never.json', 'w', closefd=False) for _ in 1.25]",
    ),
    (
        "noniterable_complex",
        "[open('artifacts/never.json', 'w', closefd=False) for _ in 2j]",
    ),
    # The same value arriving by the two other roads the source resolver already travels: a name
    # bound once to a literal, and a uniquely bound helper's constant return.
    (
        "noniterable_from_a_bound_name",
        "items = None\n[open('artifacts/never.json', 'w', closefd=False) for _ in items]",
    ),
    (
        "noniterable_from_a_constant_helper",
        "def source():\n"
        "    return 0\n"
        "[open('artifacts/never.json', 'w', closefd=False) for _ in source()]",
    ),
    # The other comprehension kinds and the eager-consumer shape, because one handler serves all
    # four and a repair that only covered the list form would look complete.
    (
        "noniterable_under_a_consuming_builtin",
        "any(open('artifacts/never.json', 'w', closefd=False) for _ in None)",
    ),
    (
        "noniterable_dict_comprehension",
        "{_: open('artifacts/never.json', 'w', closefd=False) for _ in 3}",
    ),
    (
        "noniterable_set_comprehension",
        "{open('artifacts/never.json', 'w', closefd=False) for _ in 1.25}",
    ),
    # Not only the first clause: the chain stops at whichever source cannot be iterated, and the
    # filter after it is never evaluated either.
    (
        "noniterable_second_generator_clause",
        "[y for x in [1] for y in None if open('artifacts/never.json', 'w', closefd=False)]",
    ),
)


@pytest.mark.parametrize(
    ("name", "body"), COMPREHENSION_NEVER_RUNS, ids=[row[0] for row in COMPREHENSION_NEVER_RUNS]
)
def test_a_comprehension_body_that_never_runs_certifies_nothing(gate, tmp_path, name, body):
    """Both halves, because certifying a phantom producer also swallows the orphan.

    The reader is asserted through `reported_readers` rather than the unwritten kind alone: this
    table mixes decided-dead rows with undecided-element ones, and since the report learned to
    tell those apart the second group reports the weaker kind. The claim here has always been
    that the reader SURVIVES; which classification it survives under is `REPORT_BOUNDARY`'s.
    """

    writers, _ = observed(gate, tmp_path, f"{body}\nPath('artifacts/never.json').read_text()\n")
    assert writers == set(), f"{name}: certified a writer whose comprehension body never runs"


@pytest.mark.parametrize(
    ("name", "body"), COMPREHENSION_NEVER_RUNS, ids=[row[0] for row in COMPREHENSION_NEVER_RUNS]
)
def test_a_comprehension_body_that_never_runs_keeps_its_reader(gate, tmp_path, name, body):
    readers = reported_readers(
        gate, tmp_path, f"{body}\nPath('artifacts/never.json').read_text()\n"
    )
    assert "artifacts/never.json" in readers, f"{name}: the orphan reader must survive"


COMPREHENSION_RUNS = (
    ("nonempty_iterable", "[open('artifacts/actual.json', 'w', closefd=False) for _ in [1]]"),
    ("true_filter", "[open('artifacts/actual.json', 'w', closefd=False) for _ in [1] if True]"),
    # The twin that matters most: an iterable the scanner cannot evaluate must keep certifying,
    # so this repair stays a constant-decided one and does not become a blanket refusal.
    (
        "dynamic_iterable",
        "items = [1]\n[open('artifacts/actual.json', 'w', closefd=False) for _ in items]",
    ),
    # The twins for the deferred-generator repair, and they are what keep it from becoming
    # "generators never certify". A CONSUMED generator does run its body, so withholding here
    # would fabricate an orphan for a file that really is written — the same defect pointed the
    # other way, which is exactly how the earlier function-scope withholding went wrong.
    (
        "generator_consumed_by_list",
        "list(open('artifacts/actual.json', 'w', closefd=False) for _ in [1])",
    ),
    (
        "generator_consumed_by_for",
        "for _h in (open('artifacts/actual.json', 'w', closefd=False) for _ in [1]):\n    pass",
    ),
    (
        "generator_consumed_by_a_comprehension",
        "[v for v in (open('artifacts/actual.json', 'w', closefd=False) for _ in [1])]",
    ),
    # Root readback 2026-09-08, the half pointed the other way. **A generator's OUTERMOST
    # iterable is evaluated when the generator is CREATED**, so a writer there runs even though
    # nothing ever consumes `g`. Skipping the whole clause chain for a deferred generator
    # dropped it and reported the reader as an orphan.
    (
        "unconsumed_generator_first_iterable",
        "g = (x for x in [open('artifacts/actual.json', 'w', closefd=False)])",
    ),
    # The nested case named in the same readback: eager construction, deferred iteration. The
    # INNER generator is created eagerly as the outer's first iterable, and creating it in turn
    # evaluates ITS first iterable — so the writer runs at two removes from anything consumed.
    (
        "unconsumed_generator_nested_source",
        "g = (x for x in (y for y in [open('artifacts/actual.json', 'w', closefd=False)]))",
    ),
    # The other side of the proven-consumer table: these two do drive the body, so narrowing
    # call consumption must not cost them their certification.
    (
        "generator_consumed_by_sorted",
        "sorted(str(open('artifacts/actual.json', 'w', closefd=False)) for _ in [1])",
    ),
    (
        "generator_consumed_by_join",
        "''.join(str(open('artifacts/actual.json', 'w', closefd=False)) for _ in [1])",
    ),
    # The twin for the multi-element withholding: when the target is NEVER READ, the elements
    # cannot change what runs, so this still certifies. Without this row the withholding would
    # look correct while quietly costing every ordinary `for _ in [a, b]` producer.
    (
        "multi_element_literal_whose_target_is_never_read",
        "[open('artifacts/actual.json', 'w', closefd=False) for _ in [1, 2]]",
    ),
    # The twins for the non-iterable refusal. A string and a bytes object are ITERABLE, and both
    # were already in the enumerable set — so a refusal keyed on "has no length I recognise", or
    # on truthiness, or on "is not a container", would redden these while the non-iterable rows
    # above stayed green. They are what makes that refusal a discrimination rather than a
    # blanket.
    (
        "single_character_string_source",
        "[open('artifacts/actual.json', 'w', closefd=False) for _ in 'a']",
    ),
    (
        "single_byte_source",
        "[open('artifacts/actual.json', 'w', closefd=False) for _ in b'a']",
    ),
)


@pytest.mark.parametrize(
    ("name", "body"), COMPREHENSION_RUNS, ids=[row[0] for row in COMPREHENSION_RUNS]
)
def test_a_comprehension_body_that_does_run_still_certifies(gate, tmp_path, name, body):
    writers, orphans = observed(
        gate, tmp_path, f"{body}\nPath('artifacts/never.json').read_text()\n"
    )
    assert writers == {"artifacts/actual.json"}, f"{name}: lost a producer that really runs"
    assert "artifacts/never.json" in orphans


# The SAME defect at the statement boundary. It was found in the comprehension handler and was
# present here too, in all three spellings — inline, through a bound name, and through a helper's
# constant return. Closing only the boundary the finding named is the shape that has cost this
# work a whole day: one defect, reported closed, found again next door.
LOOP_STATEMENT_NEVER_RUNS = (
    ("noniterable_loop_inline", "for _ in None:\n    {write}\n"),
    ("noniterable_loop_bound_name", "items = 0\nfor _ in items:\n    {write}\n"),
    (
        "noniterable_loop_constant_helper",
        "def source():\n    return None\nfor _ in source():\n    {write}\n",
    ),
    # `for ... else` runs its `else` when the loop finishes — and this loop never starts, so the
    # `else` is as unreached as the body. Modelling a non-iterable as merely EMPTY would leave
    # this half certified.
    ("noniterable_loop_else_clause", "for _ in 2j:\n    pass\nelse:\n    {write}\n"),
    ("noniterable_async_loop", "async def run():\n    async for _ in None:\n        {write}\n"),
)


@pytest.mark.parametrize(
    ("name", "body"), LOOP_STATEMENT_NEVER_RUNS, ids=[row[0] for row in LOOP_STATEMENT_NEVER_RUNS]
)
def test_a_loop_statement_that_never_runs_certifies_nothing(gate, tmp_path, name, body):
    write = "open('artifacts/never.json', 'w', closefd=False)"
    writers, orphans = observed(
        gate,
        tmp_path,
        body.format(write=write) + "Path('artifacts/never.json').read_text()\n",
    )
    assert writers == set(), f"{name}: certified a writer whose loop body never runs"
    assert "artifacts/never.json" in orphans, f"{name}: the orphan reader must survive"


LOOP_STATEMENT_RUNS = (
    ("literal_loop", "for _ in [1]:\n    {write}\n"),
    ("bound_literal_loop", "items = [1]\nfor _ in items:\n    {write}\n"),
    # An UNRESOLVED source keeps its body scanned. The statement boundary does not withhold on
    # unknown the way the comprehension boundary does, and that asymmetry is deliberate: nearly
    # every real producer in this estate writes inside a loop over a value no scanner can see.
    # The repair added a decided negative; it did not add a withholding here.
    ("unresolved_source_loop", "import os\nfor _ in os.listdir('.'):\n    {write}\n"),
    ("loop_else_after_a_real_iterable", "for _ in [1]:\n    pass\nelse:\n    {write}\n"),
)


@pytest.mark.parametrize(
    ("name", "body"), LOOP_STATEMENT_RUNS, ids=[row[0] for row in LOOP_STATEMENT_RUNS]
)
def test_a_loop_statement_that_does_run_still_certifies(gate, tmp_path, name, body):
    write = "open('artifacts/actual.json', 'w', closefd=False)"
    writers, orphans = observed(
        gate,
        tmp_path,
        body.format(write=write) + "Path('artifacts/never.json').read_text()\n",
    )
    assert writers == {"artifacts/actual.json"}, f"{name}: lost a producer that really runs"
    assert "artifacts/never.json" in orphans


# ONE QUESTION — "is this condition constantly false?" — was answered by four code paths at three
# capability levels. The comprehension filter decided literals, comparisons and helper returns;
# the `if` statement decided literals only; the `while` statement decided NOTHING; BoolOp and
# IfExp decided literals only. Every row here opened a file Python never opens.
#
# The rule now lives under `_literal_operand` instead of beside one of its callers, so a widening
# reaches all of them at once. That is the repair; these are what say it happened.
CONSTANT_CONDITION_NEVER_RUNS = (
    ("boolop_and_false_comparison", "(1 == 2) and {write}"),
    ("boolop_or_true_comparison", "(1 == 1) or {write}"),
    ("ifexp_false_comparison", "{write} if 1 == 2 else 'n'"),
    # A CHAIN, which the single-operator fallback this replaces could not decide at all.
    ("boolop_chained_comparison", "(1 < 0 < 5) and {write}"),
    ("if_statement_false_comparison", "if 1 == 2:\n    {write}\n"),
    # The `if` handler inlined its own copy of the call refusal and `literal_eval`, so it never
    # received the uniquely-bound-helper resolver either.
    ("if_statement_constant_helper", "def stop():\n    return False\nif stop():\n    {write}\n"),
    ("if_statement_name_bound_to_comparison", "x = 1 == 2\nif x:\n    {write}\n"),
    # The `while` handler had no constant check of any kind — not even for a plain literal.
    ("while_literal_false", "while False:\n    {write}\n"),
    ("while_zero", "while 0:\n    {write}\n"),
    ("while_empty_container", "while []:\n    {write}\n"),
    ("while_none", "while None:\n    {write}\n"),
    ("while_false_comparison", "while 1 == 2:\n    {write}\n"),
    (
        "while_constant_helper",
        "def stop():\n    return False\nwhile stop():\n    {write}\n",
    ),
)


@pytest.mark.parametrize(
    ("name", "body"),
    CONSTANT_CONDITION_NEVER_RUNS,
    ids=[row[0] for row in CONSTANT_CONDITION_NEVER_RUNS],
)
def test_a_constantly_false_condition_certifies_nothing(gate, tmp_path, name, body):
    write = "open('artifacts/never.json', 'w', closefd=False)"
    writers, orphans = observed(
        gate,
        tmp_path,
        body.format(write=write) + "\nPath('artifacts/never.json').read_text()\n",
    )
    assert writers == set(), f"{name}: certified a writer behind a decided-false condition"
    assert "artifacts/never.json" in orphans, f"{name}: the orphan reader must survive"


CONSTANT_CONDITION_RUNS = (
    ("if_true_comparison_chain", "if 1 < 2 < 3:\n    {write}\n"),
    ("boolop_true_comparison", "(1 == 1) and {write}"),
    # The branch that IS taken must still be scanned — deciding a condition narrows which branch
    # runs, it does not drop the statement.
    ("if_false_comparison_runs_its_else", "if 1 == 2:\n    pass\nelse:\n    {write}\n"),
    # A `while` whose condition is false still runs its `else`, which is why the falsy case
    # returns the `orelse` scan rather than the entry states.
    ("while_false_runs_its_else", "while False:\n    pass\nelse:\n    {write}\n"),
    # A constant-TRUTHY loop is an infinite one whose body does run. Deliberately not modelled,
    # and this row is what keeps the falsy repair from quietly growing into the truthy case.
    ("while_true_with_break", "while True:\n    {write}\n    break\n"),
)


@pytest.mark.parametrize(
    ("name", "body"), CONSTANT_CONDITION_RUNS, ids=[row[0] for row in CONSTANT_CONDITION_RUNS]
)
def test_a_decided_condition_still_certifies_the_branch_that_runs(gate, tmp_path, name, body):
    write = "open('artifacts/actual.json', 'w', closefd=False)"
    writers, orphans = observed(
        gate,
        tmp_path,
        body.format(write=write) + "\nPath('artifacts/never.json').read_text()\n",
    )
    assert writers == {"artifacts/actual.json"}, f"{name}: lost a producer that really runs"
    assert "artifacts/never.json" in orphans


# **The FILTERS were the half the earlier repair missed.** Making the two unresolved branches
# scan-and-demote instead of skip fixed the body and the later clauses and left the sibling
# filters behind a `continue` and a `break` respectively — so a reader in a filter still vanished
# while the identical reader one line further into the body survived. Each row below executes its
# reader at runtime.
UNRESOLVED_CLAUSE_FILTER_READERS = (
    # The undecided SOURCE branch `continue`d past `generator.ifs`. An unresolved source may still
    # yield elements — `def src(): return [1]` does — so its filters may run.
    (
        "undecided_source_reader_in_its_own_filter",
        "def src():\n    return [1]\n[1 for _ in src() if Path('artifacts/reader.json').read_text()]",
    ),
    # The undecided FILTER branch `break`s, taking the filters after it with the one it could not
    # decide.
    (
        "undecided_filter_reader_in_a_later_filter",
        "def go():\n    return not False\n"
        "[1 for _ in [1] if go() if Path('artifacts/reader.json').read_text()]",
    ),
    # The twin one line over, which already worked: without it these rows could pass on a repair
    # that scanned filters and stopped scanning bodies.
    (
        "undecided_source_reader_in_the_body",
        "def src():\n    return [1]\n[Path('artifacts/reader.json').read_text() for _ in src()]",
    ),
)


@pytest.mark.parametrize(
    ("name", "body"),
    UNRESOLVED_CLAUSE_FILTER_READERS,
    ids=[row[0] for row in UNRESOLVED_CLAUSE_FILTER_READERS],
)
def test_an_unresolved_clause_keeps_the_readers_in_its_filters(gate, tmp_path, name, body):
    reads = [
        access
        for access in recorded(gate, tmp_path, body)
        if access.action == "read" and access.pattern == "artifacts/reader.json"
    ]
    assert reads, (
        f"{name}: a reader that runs must not vanish with the clause that could not be decided"
    )


def test_a_writer_in_a_later_filter_is_evidence_and_not_a_certification(gate, tmp_path):
    """The other side of the same repair: scanning the filters must not certify through them."""

    writes = [
        access
        for access in recorded(
            gate,
            tmp_path,
            "def go():\n    return not False\n"
            "[1 for _ in [1] if go() if open('artifacts/actual.json', 'w', closefd=False)]",
        )
        if access.action == "write" and access.pattern == "artifacts/actual.json"
    ]
    assert writes, "the write site must survive as evidence"
    assert all(not access.bounded for access in writes), (
        "an undecided guard must not certify the writer behind it"
    )


# The multi-element withholding stopped scanning, not just stopped certifying, and a reader in
# the body went with the writer. Python executes each of these readers twice.
WITHHELD_REGION_READERS = (
    (
        "element_expression",
        "[x or Path('artifacts/reader.json').read_text() for x in [False, False]]",
    ),
    ("filter", "[x for x in [False, False] if x or Path('artifacts/reader.json').read_text()]"),
    (
        "later_clause_iterable",
        "[y for x in [False, False] for y in [x or Path('artifacts/reader.json').read_text()]]",
    ),
)


@pytest.mark.parametrize(
    ("name", "body"), WITHHELD_REGION_READERS, ids=[row[0] for row in WITHHELD_REGION_READERS]
)
def test_a_reader_in_an_unreached_region_survives_as_evidence(gate, tmp_path, name, body):
    """A reader Python really runs must not disappear because a WRITER could not be decided."""

    reads = [
        access
        for access in recorded(gate, tmp_path, body)
        if access.action == "read" and access.pattern == "artifacts/reader.json"
    ]
    assert reads, f"{name}: the reader vanished with the withheld writer"


def test_an_undecided_writer_is_recorded_uncertain_rather_than_dropped(gate, tmp_path):
    """Withholding a producer is defensible; asserting no producer exists is not.

    `[x or open(...) for x in [True, False]]` opens the file once at runtime — the second element
    is falsy, so `or` evaluates its right operand. The scanner cannot pick an element, so it must
    not certify; what it must also not do is leave no trace, which is what a skipped body did.
    """

    accesses = recorded(
        gate,
        tmp_path,
        "[x or open('artifacts/actual.json', 'w', closefd=False) for x in [True, False]]",
    )
    writes = [
        access
        for access in accesses
        if access.action == "write" and access.pattern == "artifacts/actual.json"
    ]
    assert writes, "the write site must survive as evidence"
    assert all(not access.bounded for access in writes), (
        "an undecided element must not certify the writer"
    )


def test_a_decided_multi_element_body_still_certifies(gate, tmp_path):
    """The twin: withholding must stay confined to the case where the target is consulted."""

    writers, orphans = observed(
        gate,
        tmp_path,
        "[open('artifacts/actual.json', 'w', closefd=False) for _ in [1, 2]]\n"
        "Path('artifacts/never.json').read_text()",
    )
    assert writers == {"artifacts/actual.json"}
    assert "artifacts/never.json" in orphans


# A chain evaluates left to right and stops at its first false link, so the FIRST link that is
# not a decided true ends the reading. The distinction that matters is between the two things
# `_comparison_outcome` returns `None` for: an operand it cannot resolve, and an ill-typed
# comparison that RAISES. A chain whose first link may raise has no truth value at all, and a
# later decided-false link does not supply one — which is why `missing < 1 < 0` is undecided even
# though both of its branches would evaluate to False if nothing raised.
#
# The first version of the helper stated exactly that rule in its docstring and did not implement
# it: it tracked the undecided case in a variable and then returned False unconditionally on a
# later false link.
COMPARISON_CHAINS = (
    ("unknown_then_false_name", "missing < 1 < 0", None),
    ("unknown_then_false_illtyped", "None < 1 < 0", None),
    # A decided false genuinely stops the chain, so what follows is never evaluated and an
    # unresolvable operand after it costs nothing.
    ("false_then_unknown", "2 < 1 < missing", False),
    ("false_then_illtyped", "2 < 1 < None", False),
    ("true_then_unknown", "1 < 2 < missing", None),
    ("all_true", "1 < 2 < 3", True),
    ("first_false", "1 < 0 < 5", False),
    ("single_false", "1 == 2", False),
    ("single_true", "1 == 1", True),
    ("single_unknown", "missing == 1", None),
    # Longer chains, because "first link that is not a decided true" is a claim about ORDER and
    # two links cannot tell a left-to-right reading from a scan of the whole list.
    ("true_true_false", "1 < 2 < 3 < 0", False),
    ("true_unknown_false", "1 < 2 < missing < 0", None),
    ("false_unknown_unknown", "2 < 1 < missing < other", False),
)


@pytest.mark.parametrize(
    ("name", "source", "expected"), COMPARISON_CHAINS, ids=[row[0] for row in COMPARISON_CHAINS]
)
def test_a_comparison_chain_is_read_left_to_right(gate, name, source, expected):
    node = ast.parse(source, mode="eval").body
    assert gate._decided_comparison(node) is expected, name  # noqa: SLF001


def test_an_ill_typed_comparison_really_does_raise(gate):
    """The oracle for the rows above: `None < 1` is not merely unresolvable, it raises.

    Without this, "undecided" reads as excess caution about a comparison whose value is plainly
    False in both branches. It is not caution — the expression has no value.
    """

    with pytest.raises(TypeError):
        None < 1  # noqa: B015


# THE REPORT BOUNDARY, held as a fixture rather than as prose. Each row is what the REPORT says
# about `artifacts/actual.json` for one kind of write site, and the runtime column is what Python
# does. The report used to say "unwritten" for an artifact whose writer it had located precisely
# and then declined to certify — an unqualified absence asserted on top of a recorded doubt.
#
# Three dispositions, and the rows are arranged so that collapsing any two of them reddens
# something:
#   bounded write   -> matched, no finding at all
#   absent write    -> `consumer-reads-unwritten-artifact`, the decided absence
#   unbounded write -> `consumer-reads-artifact-with-unresolved-writer`, the recorded doubt
W_ACTUAL = "open('artifacts/actual.json', 'w', closefd=False)"
HELPER_ACTUAL = "def helper():\n    return open('artifacts/actual.json', 'w', closefd=False)\n"

REPORT_BOUNDARY = (
    # A static site satisfies the static check, including one with no call anywhere here: an
    # external importer may call it, so no module-level call does not prove dead code.
    ("definition_only", HELPER_ACTUAL, ""),
    ("definition_and_call", HELPER_ACTUAL + "helper()\n", ""),
    ("inline_reached", W_ACTUAL, ""),
    # Decided absences. Nothing runs, so the reader really does read an unwritten artifact.
    ("dead_empty_source", f"[{W_ACTUAL} for _ in []]", "consumer-reads-unwritten-artifact"),
    (
        "dead_false_filter",
        f"[{W_ACTUAL} for _ in [1] if False]",
        "consumer-reads-unwritten-artifact",
    ),
    ("dead_condition", f"if 1 == 2:\n    {W_ACTUAL}\n", "consumer-reads-unwritten-artifact"),
    ("dead_non_iterable", f"[{W_ACTUAL} for _ in None]", "consumer-reads-unwritten-artifact"),
    # Recorded doubt. The site is located and its execution is undetermined.
    (
        "undecided_guard",
        "def go():\n    return not True\n" + f"[{W_ACTUAL} for _ in [1] if go()]",
        "consumer-reads-artifact-with-unresolved-writer",
    ),
    (
        "undecided_operand",
        "def f():\n    return not True\n" + f"f() and {W_ACTUAL}",
        "consumer-reads-artifact-with-unresolved-writer",
    ),
    (
        "undecided_chain_link",
        "def size():\n    return 5\n" + f"size() < 1 < {W_ACTUAL}",
        "consumer-reads-artifact-with-unresolved-writer",
    ),
    (
        "undecided_element",
        f"[x or {W_ACTUAL} for x in [True, True]]",
        "consumer-reads-artifact-with-unresolved-writer",
    ),
    # **The control that keeps the weak kind from becoming a basename test.** An uncertain writer
    # at a DIFFERENT root must not clear a definite unmatched reader that merely shares a
    # basename — the reader is still reading something nothing writes.
    (
        "uncertain_writer_at_another_root",
        "[x or open('artifacts/other/actual.json', 'w', closefd=False) for x in [True, True]]",
        "consumer-reads-unwritten-artifact",
    ),
    # And no writer of any kind: the absence verdict must survive the new classification.
    ("no_writer_at_all", "pass", "consumer-reads-unwritten-artifact"),
)


@pytest.mark.parametrize(
    ("name", "body", "expected_kind"), REPORT_BOUNDARY, ids=[row[0] for row in REPORT_BOUNDARY]
)
def test_the_report_distinguishes_absence_from_undetermined_execution(
    gate, tmp_path, name, body, expected_kind
):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "example.py").write_text(
        "from pathlib import Path\n" + body + "\nPath('artifacts/actual.json').read_text()\n"
    )
    gate.collect_artifact_accesses(tmp_path)
    result = gate.analyse_consumer_side(tmp_path, [])
    kinds = {
        finding.kind
        for finding in result.findings
        for reader in finding.readers
        if reader.pattern == "artifacts/actual.json"
    }
    assert kinds == ({expected_kind} if expected_kind else set()), name


def test_the_rendered_line_does_not_contradict_its_own_diagnosis(gate, tmp_path):
    """The RENDERED line, not the detail field — which is where the contradiction was.

    The detail said the writer was located and its execution undetermined; the line then ended
    `next-action=bind the consumer to a live producer output`, the one instruction ruled out for
    this kind, because the producer already exists and is printed in the same line under
    `nearest-writers`. My controls read the detail and the finding kind and never the rendered
    output, so nothing caught it (review finding, root, at `7a4b8ceaf`).
    """

    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "example.py").write_text(
        "from pathlib import Path\n"
        f"[x or {W_ACTUAL} for x in [True, True]]\n"
        "Path('artifacts/actual.json').read_text()\n"
    )
    gate.collect_artifact_accesses(tmp_path)
    report = gate.analyse_consumer_side(tmp_path, [])
    finding = next(
        item
        for item in report.findings
        if item.kind == "consumer-reads-artifact-with-unresolved-writer"
    )

    line = gate._finding_line(finding)  # noqa: SLF001
    assert "bind the consumer to a live producer output" not in line, (
        "the weaker finding must not be told to add a producer it has just named"
    )
    assert "next-action=" in line and "undetermined" in line
    # The named candidate must survive into the rendered line as well as the object, since the
    # next action tells the reader to look at it.
    assert "example.py:2" in line


def test_the_weaker_finding_names_its_candidate_writers_and_keeps_the_reader(gate, tmp_path):
    """Not a suppression: readers, their count, and the ACTUAL candidate sites all survive.

    A weaker classification that dropped the reader would trade one wrong verdict for another,
    and one that pointed at a nearest-by-distance guess would waste the fact that these writers
    are known exactly.
    """

    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "example.py").write_text(
        "from pathlib import Path\n"
        f"[x or {W_ACTUAL} for x in [True, True]]\n"
        "Path('artifacts/actual.json').read_text()\n"
    )
    accesses, _, _, _ = gate.collect_artifact_accesses(tmp_path)
    result = gate.analyse_consumer_side(tmp_path, [])

    finding = next(
        item
        for item in result.findings
        if item.kind == "consumer-reads-artifact-with-unresolved-writer"
    )
    assert finding.reader_total >= 1, "the reader count must survive the weaker classification"
    assert finding.readers, "the reader evidence must survive"
    assert finding.writers, "the candidate writer sites must be named"
    assert all(not writer.bounded for writer in finding.writers), (
        "a candidate is an uncertain site; naming a bounded one would imply a pair"
    )
    assert not any(access.action == "write" and access.bounded for access in accesses), (
        "the weaker finding must not certify production"
    )


@pytest.mark.parametrize(
    ("entry_kind", "expect_exempt"),
    (
        # An exemption written for the OLD kind must not reach the new one.
        ("consumer-reads-unwritten-artifact", False),
        # And the twin, without which the row above would pass on a broken filter: the exemption
        # written for the NEW kind must actually take effect.
        ("consumer-reads-artifact-with-unresolved-writer", True),
    ),
    ids=["old_kind_entry_does_not_exempt", "new_kind_entry_does_exempt"],
)
def test_the_new_kind_has_its_own_allowlist_domain(gate, tmp_path, entry_kind, expect_exempt):
    """Through the real filter, not through two strings I typed.

    The first version of this row asserted that two hardcoded keys differ, which is a fact about
    my typing and not about `is_allowlisted` — it would have passed against any filter, including
    one that ignored the kind entirely (review finding, root, at `7a4b8ceaf`). It now runs
    `analyse_consumer_side` with a real entry and reads which side of the report the finding
    lands on, and the parametrised twin is what keeps it from passing on a filter that exempts
    nothing at all.
    """

    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "example.py").write_text(
        "from pathlib import Path\n"
        f"[x or {W_ACTUAL} for x in [True, True]]\n"
        "Path('artifacts/actual.json').read_text()\n"
    )
    gate.collect_artifact_accesses(tmp_path)
    allowlist = [
        gate.AllowlistEntry(f"{entry_kind}:artifacts/actual.json", "control", "consumer_side")
    ]
    report = gate.analyse_consumer_side(tmp_path, allowlist)

    reported = {
        finding.kind
        for finding in report.findings
        for reader in finding.readers
        if reader.pattern == "artifacts/actual.json"
    }
    exempted = {
        finding.kind
        for finding, _entry in report.allowlisted
        if finding.reader.pattern == "artifacts/actual.json"
    }
    target = "consumer-reads-artifact-with-unresolved-writer"
    if expect_exempt:
        assert target in exempted and target not in reported
    else:
        assert target in reported and target not in exempted


class _LegacyIterable:
    """Iterable through the OLD protocol only: `iter()` accepts it, `__iter__` is absent."""

    def __getitem__(self, index: int) -> int:
        if index > 0:
            raise IndexError
        return 1


ITERATION_DOMAIN = (
    # Unresolved stays unresolved: the value channel cannot answer what the resolver could not.
    ("unresolved", False, None, "SOURCE_UNDECIDED"),
    # The enumerable set, one per spelling the element count is read from.
    ("list", True, [1], "SOURCE_ENUMERABLE"),
    ("tuple", True, (1,), "SOURCE_ENUMERABLE"),
    ("set", True, {1}, "SOURCE_ENUMERABLE"),
    ("dict", True, {1: 0}, "SOURCE_ENUMERABLE"),
    ("str", True, "ab", "SOURCE_ENUMERABLE"),
    ("bytes", True, b"ab", "SOURCE_ENUMERABLE"),
    # Decided negatives. `iter()` raises on each, so the body runs zero times.
    ("none", True, None, "SOURCE_NOT_ITERABLE"),
    ("bool", True, True, "SOURCE_NOT_ITERABLE"),
    ("int", True, 3, "SOURCE_NOT_ITERABLE"),
    ("float", True, 1.25, "SOURCE_NOT_ITERABLE"),
    ("complex", True, 2j, "SOURCE_NOT_ITERABLE"),
    ("ellipsis", True, ..., "SOURCE_NOT_ITERABLE"),
    # ITERABLE but not enumerable here. These are the rows that make the predicate a THREE-way
    # answer rather than "enumerable or dead": calling them non-iterable would deny a body that
    # really runs. `range` has `__iter__`; the legacy object has only `__getitem__`, which is
    # exactly what a check written against `__iter__` alone would get wrong.
    ("range", True, range(3), "SOURCE_UNDECIDED"),
    ("generator", True, (n for n in [1]), "SOURCE_UNDECIDED"),
    ("legacy_getitem_protocol", True, _LegacyIterable(), "SOURCE_UNDECIDED"),
)


@pytest.mark.parametrize(
    ("name", "known", "constant", "expected"),
    ITERATION_DOMAIN,
    ids=[row[0] for row in ITERATION_DOMAIN],
)
def test_iteration_domain_separates_all_three_cases(gate, name, known, constant, expected):
    """The predicate at its own boundary, because two of its three answers have no source road.

    `_literal_operand` resolves only what `ast.literal_eval` accepts, so no comprehension or loop
    in any estate file can hand it a `range`, a generator or a legacy-protocol object today. The
    arm is still the difference between refusing a live body and refusing a dead one, so it is
    pinned where it is reachable — here — and reported as unit-pinned rather than claimed to be
    exercised end to end.
    """

    assert gate._iteration_domain(known, constant) == getattr(gate, expected), name
    # Iterability is the question, and the runtime is the oracle for it.
    if expected != "SOURCE_UNDECIDED" or not known:
        return
    iter(constant)


@pytest.mark.parametrize(
    ("name", "known", "constant", "expected"),
    [row for row in ITERATION_DOMAIN if row[3] == "SOURCE_NOT_ITERABLE"],
    ids=[row[0] for row in ITERATION_DOMAIN if row[3] == "SOURCE_NOT_ITERABLE"],
)
def test_a_decided_negative_is_one_python_agrees_with(gate, name, known, constant, expected):
    """Never assert a value is un-iterable without asking the interpreter."""

    with pytest.raises(TypeError):
        iter(constant)
    assert gate._iteration_domain(known, constant) == gate.SOURCE_NOT_ITERABLE, name


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
