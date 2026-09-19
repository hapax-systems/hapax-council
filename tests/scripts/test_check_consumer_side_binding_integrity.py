"""Static evidence is preserved across scan failures, binding scopes, and expansion caps."""

from __future__ import annotations

import ast
import importlib.util
import itertools
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import replace
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


#: Readers surfaced as having no ESTABLISHED producer, which the report now says two ways: an
#: absent write is `consumer-reads-unwritten-artifact`, and a located write whose execution is
#: undetermined is `consumer-reads-artifact-with-unresolved-writer`. These tests are about binding
#: precision and effect propagation — every one of them asks whether the reader survives a
#: withheld writer, not which of the two sentences the report chose. WHICH kind fires is pinned
#: where it belongs, in `test_check_consumer_side_expression_state.py`'s `REPORT_BOUNDARY` rows.
#:
#: Named `_unwritten` while only one kind existed; 66 cases here then asserted a kind name where
#: they meant the concept, and stayed red across three published heads.
#: The report says "this reader has no ESTABLISHED producer" two ways, and which one it says is
#: the discrimination — so each helper reads exactly one kind and every row names the one it
#: means. Measured across both binding files at `b88696a85`: 569 orphan findings, no test case
#: emitting both kinds, and every one of the 72 unresolved-writer findings carrying at least one
#: located writer with none of them bounded. A helper reading both would have hidden all of that.
ABSENT_WRITER = "consumer-reads-unwritten-artifact"
UNRESOLVED_WRITER = "consumer-reads-artifact-with-unresolved-writer"


def _orphaned(report, kind: str = ABSENT_WRITER) -> set[str]:
    return {finding.reader.pattern for finding in report.findings if finding.kind == kind}


@pytest.mark.parametrize("indirect", [False, True], ids=["direct", "indirect"])
def test_round_nine_direct_indirect_outer_effects(gate, tmp_path, indirect):
    _write(
        tmp_path,
        "from pathlib import Path\n\nARTIFACT = Path('artifacts/old.json')\n\n\n"
        + ("def change_path():\n" if indirect else "def configure():\n")
        + "    global ARTIFACT\n    ARTIFACT = Path('artifacts/new.json')\n"
        + ("\n\ndef configure():\n    change_path()\n" if indirect else "")
        + "\n\nconfigure()\nARTIFACT.write_text('{}')\n"
        "Path('artifacts/old.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    bounded_writes = {a.pattern for a in accesses if a.action == "write" and a.bounded}
    assert "artifacts/old.json" not in bounded_writes, bounded_writes
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report, UNRESOLVED_WRITER) == {"artifacts/old.json"}
    assert report.unresolvable > 0 or bounded_writes == {"artifacts/new.json"}
    if not indirect:
        assert report.unresolvable > 0


@pytest.mark.parametrize("aliased", [False, True], ids=["chain", "alias"])
@pytest.mark.parametrize("wrapped", [False, True], ids=["module", "invocation-globals"])
def test_round_nine_three_level_outer_effects(gate, tmp_path, aliased, wrapped):
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "def change_path():\n    global ARTIFACT\n"
        "    ARTIFACT = Path('artifacts/new.json')\n"
        "def middle():\n"
        + ("    update = change_path\n    update()\n" if aliased else "    change_path()\n")
        + "def configure():\n    middle()\n"
        + (
            "def write_state():\n    ARTIFACT.write_text('{}')\n"
            "def run():\n    ARTIFACT = Path('artifacts/local.json')\n"
            "    configure()\n    ARTIFACT.write_text('{}')\n    write_state()\nrun()\n"
            if wrapped
            else "configure()\nARTIFACT.write_text('{}')\n"
        )
        + "Path('artifacts/old.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write" and a.bounded} == (
        {"artifacts/local.json"} if wrapped else set()
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report, UNRESOLVED_WRITER) == {"artifacts/old.json"}
    assert report.unresolvable > 0
    assert not report.unresolved_closures


def test_round_nine_recursive_outer_effects_are_unresolved(tmp_path):
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "def a():\n    b()\n"
        "def b():\n    global ARTIFACT\n    ARTIFACT = Path('artifacts/new.json')\n    a()\n"
        "a()\nARTIFACT.write_text('{}')\nPath('artifacts/old.json').read_text()\n",
    )
    # The source is data for the production parser. A subprocess bounds even a mutation
    # that removes the cycle guard and loops in effect closure construction.
    driver = """
import importlib.util, json, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("recursive_scanner", sys.argv[1])
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)
repo = Path(sys.argv[2])
accesses, *_ = gate.collect_artifact_accesses(repo)
report = gate.analyse_consumer_side(repo, [])
print(json.dumps({"writes": [a.pattern for a in accesses if a.action == "write" and a.bounded],
                  "unresolvable": report.unresolvable,
                  "unresolved_closures": report.unresolved_closures}))
"""
    result = subprocess.run(
        [sys.executable, "-c", driver, str(SCRIPT_PATH), str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    measured = json.loads(result.stdout)
    assert measured["writes"] == [], measured
    assert measured["unresolvable"] > 0
    assert any("recursive outer effect cycle" in site for site in measured["unresolved_closures"])


@pytest.mark.parametrize("unbounded", ["target", "cap"])
def test_round_nine_unbounded_outer_effects_are_named(gate, tmp_path, monkeypatch, unbounded):
    if unbounded == "cap":
        monkeypatch.setattr(gate, "_MAX_BINDING_STATES", 1)
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "def configure(flag):\n"
        + (
            "    pass\n"
            if unbounded == "cap"
            else "    unknown_callback()\n    ARTIFACT.write_text('{}')\n"
        )
        + "def run():\n    configure(1)\n"
        + ("    configure(2)\n" if unbounded == "cap" else "")
        + "Path('artifacts/old.json').read_text()\nrun()\nARTIFACT.write_text('{}')\n"
        "(ARTIFACT / 'nested.json').write_text('{}')\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not [a for a in accesses if a.action == "write" and a.bounded], accesses
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report, UNRESOLVED_WRITER) == {"artifacts/old.json"}
    assert report.unresolvable > 0
    assert any(
        "outer effects" in site and "UNRESOLVED" in site for site in report.unresolved_closures
    )
    assert any(
        "outer effects" in site
        and ("binding state cap" if unbounded == "cap" else "unresolved call target") in site
        for site in report.unresolved_closures
    )


def test_round_nine_transitive_nonlocal_keeps_lexical_owner(gate, tmp_path):
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT = Path('artifacts/module.json')\n"
        "def run():\n    ARTIFACT = Path('artifacts/old.json')\n"
        "    def configure():\n"
        "        def change_path():\n            nonlocal ARTIFACT\n"
        "            ARTIFACT = Path('artifacts/new.json')\n"
        "        change_path()\n"
        "    configure()\n    ARTIFACT.write_text('{}')\n"
        "run()\nARTIFACT.write_text('{}')\nPath('artifacts/old.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write" and a.bounded} == {
        "artifacts/module.json"
    }
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report, UNRESOLVED_WRITER) == {"artifacts/old.json"}
    assert report.unresolvable > 0


@pytest.mark.parametrize(
    "store, wrapped",
    [
        ("global", False),
        ("globals", False),
        ("nonlocal", False),
        ("global", True),
        ("globals", True),
    ],
)
def test_round_eight_callee_mutations_invalidate_caller(gate, tmp_path, store, wrapped):
    if store == "nonlocal":
        source = (
            "def run():\n"
            "    ARTIFACT = Path('artifacts/old.json')\n"
            "    def configure():\n"
            "        nonlocal ARTIFACT\n"
            "        ARTIFACT = Path('artifacts/new.json')\n"
            "    configure()\n"
            "    ARTIFACT.write_text('{}')\n"
            "run()\n"
        )
    else:
        source = (
            "ARTIFACT = Path('artifacts/old.json')\n"
            "def configure():\n"
            + (
                "    global ARTIFACT\n    ARTIFACT = Path('artifacts/new.json')\n"
                if store == "global"
                else "    globals()['ARTIFACT'] = Path('artifacts/new.json')\n"
            )
            + (
                "def run():\n    configure()\n    ARTIFACT.write_text('{}')\nrun()\n"
                if wrapped
                else "configure()\nARTIFACT.write_text('{}')\n"
            )
        )
    _write(
        tmp_path,
        "from pathlib import Path\n" + source + "Path('artifacts/old.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not [a for a in accesses if a.action == "write" and a.bounded], accesses
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report, UNRESOLVED_WRITER) == {"artifacts/old.json"}
    assert report.unresolvable > 0
    assert any("ARTIFACT" in site for site in report.unresolved_paths)


def test_round_eight_augassign_freezes_target_before_walrus(gate, tmp_path):
    _write(
        tmp_path,
        "from pathlib import Path\nartifact = Path('artifacts/old')\n"
        "artifact /= str(artifact := Path('new.json'))\n"
        "artifact.write_text('{}')\nPath('new.json/new.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write"} == {"artifacts/old/new.json"}
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report) == {"new.json/new.json"}
    assert report.unresolvable == 0


@pytest.mark.parametrize("artifact", ["state.json", "nested/state.json", "a/b/state.json"])
def test_round_eight_recursive_glob_includes_zero_directories(gate, tmp_path, artifact):
    _write(
        tmp_path,
        "from pathlib import Path\n"
        f"Path('artifacts/{artifact}').write_text('{{}}')\n"
        "list(Path('artifacts').rglob('*.json'))\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert report.findings == []
    assert report.unresolvable == 0


@pytest.mark.parametrize("cap_route", ["calls", "scope", "module"])
def test_round_eight_binding_cap_is_reported_as_uncertainty(
    gate, tmp_path, monkeypatch, capsys, cap_route
):
    monkeypatch.setattr(gate, "_MAX_BINDING_STATES", 0 if cap_route == "module" else 1)
    calls = (
        "read_state(Path('artifacts/a.json'))\nread_state(Path('artifacts/b.json'))\n"
        if cap_route == "calls"
        else "read_state(Path('artifacts/a.json'))\n"
    )
    _write(
        tmp_path,
        "from pathlib import Path\ndef read_state(artifact):\n    artifact.read_text()\n" + calls,
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert report.unresolvable > 0
    assert any("binding state cap" in site for site in report.capped_expressions)
    assert any("shared/consumer.py:" in site for site in report.capped_expressions)
    gate.print_consumer_side_report(report, tmp_path / "unused.json")
    assert "[CAPPED] shared/consumer.py:" in capsys.readouterr().out


def test_round_eight_report_error_with_findings_stays_report_only(tmp_path):
    _write(tmp_path, "from pathlib import Path\nPath('artifacts/orphan.json').read_text()\n")
    # A directory is an invalid report file even when this canary runs as root.
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--consumer-side", "--report-json", str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"[REPORT-ERROR] {tmp_path}:" in result.stdout
    assert "[REPORT] consumer-reads-unwritten-artifact" in result.stdout
    assert "read=artifacts/orphan.json" in result.stdout
    assert "consumer-side gate is REPORT-ONLY" in result.stdout


@pytest.mark.parametrize("caller_first", [False, True])
@pytest.mark.parametrize("imported", [False, True])
@pytest.mark.parametrize("arguments", [("new",), ("new", "other"), (None,), ("new", None)])
def test_round_seven_call_bindings_precede_body_accesses(
    gate, tmp_path, caller_first, imported, arguments
):
    writer = (
        "def write_state(artifact=Path('artifacts/old.json')):\n    artifact.write_text('{}')\n"
    )
    calls = "".join(
        f"    write_state(Path('artifacts/{name}.json'))\n"
        if name is not None
        else "    write_state(choose())\n"
        for name in arguments
    )
    caller = "def run():\n" + calls
    if imported:
        writer_path = tmp_path / "shared" / ("a_writer.py" if caller_first else "z_writer.py")
        writer_path.parent.mkdir(parents=True, exist_ok=True)
        writer_path.write_text("from pathlib import Path\n" + writer)
        definitions = f"from shared.{writer_path.stem} import write_state\n" + caller
    else:
        definitions = caller + writer if caller_first else writer + caller
    _write(
        tmp_path,
        "from pathlib import Path\n" + definitions + "run()\n"
        "Path('artifacts/old.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write" and a.bounded} == {
        f"artifacts/{name}.json" for name in arguments if name is not None
    }
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report) == {"artifacts/old.json"}
    assert report.unresolvable == (1 if None in arguments else 0)
    assert bool(report.unresolved_paths) == (None in arguments)


@pytest.mark.parametrize(
    "before, after, expected",
    [(True, False, {"old"}), (True, True, {"old", "new"}), (False, True, {"new"})],
)
@pytest.mark.parametrize("wrapped", [False, True])
def test_round_seven_function_globals_at_call(gate, tmp_path, before, after, expected, wrapped):
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "def write_state():\n    ARTIFACT.write_text('{}')\n"
        + ("def run():\n    write_state()\n" if wrapped else "")
        + (("run()\n" if wrapped else "write_state()\n") if before else "")
        + "ARTIFACT = Path('artifacts/new.json')\n"
        + (("run()\n" if wrapped else "write_state()\n") if after else "")
        + "Path('artifacts/new.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write"} == {
        f"artifacts/{name}.json" for name in expected
    }
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report) == (set() if "new" in expected else {"artifacts/new.json"})
    assert report.unresolvable == 0


@pytest.mark.parametrize(
    "receiver, initial, expected",
    [
        ("artifact", "old.json", "old.json"),
        ("artifact.parent", "old.json/child", "old.json"),
        ("artifact.parents[0]", "old.json/child", "old.json"),
        ("artifact.with_suffix('.json')", "old.txt", "old.json"),
    ],
)
@pytest.mark.parametrize("nested", [False, True])
def test_round_seven_receiver_precedes_argument_rebinding(
    gate, tmp_path, receiver, initial, expected, nested
):
    write = f"{receiver}.write_text(str(artifact := Path('artifacts/new.json')))"
    _write(
        tmp_path,
        f"from pathlib import Path\nartifact = Path('artifacts/{initial}')\n"
        + (f"str({write})\n" if nested else f"{write}\n")
        + "artifact.read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write"} == {f"artifacts/{expected}"}
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report) == {"artifacts/new.json"}
    assert report.unresolvable == 0


@pytest.mark.parametrize("argument", ["artifact, later=", "artifact=artifact, later="])
def test_round_seven_arguments_keep_their_evaluation_state(gate, tmp_path, argument):
    _write(
        tmp_path,
        "from pathlib import Path\nartifact = Path('artifacts/old.json')\n"
        "def write_state(artifact, later):\n    artifact.write_text('{}')\n"
        f"write_state({argument}(artifact := Path('artifacts/new.json')))\n"
        "artifact.read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write"} == {"artifacts/old.json"}
    assert _orphaned(gate.analyse_consumer_side(tmp_path, [])) == {"artifacts/new.json"}


def test_round_seven_unknown_receiver_cannot_borrow_argument_binding(gate, tmp_path):
    _write(
        tmp_path,
        "from pathlib import Path\nartifact = choose()\n"
        "artifact.write_text(str(artifact := Path('artifacts/new.json')))\n"
        "artifact.read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not [a for a in accesses if a.action == "write" and a.bounded]
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report) == {"artifacts/new.json"}
    assert report.unresolvable == 1
    assert any("path=artifact" in site for site in report.unresolved_paths)


def test_round_seven_unknown_call_globals_are_named(gate, tmp_path):
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT = choose()\n"
        "def write_state():\n    ARTIFACT.write_text('{}')\n"
        "write_state()\nARTIFACT = Path('artifacts/new.json')\nARTIFACT.read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report) == {"artifacts/new.json"}
    assert report.unresolvable == 1
    assert any("path=ARTIFACT" in site for site in report.unresolved_paths)


def test_round_seven_caller_locals_cannot_replace_callee_globals(gate, tmp_path):
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "def write_state():\n    ARTIFACT.write_text('{}')\n"
        "def run(ARTIFACT):\n    write_state()\n"
        "run(Path('artifacts/new.json'))\nPath('artifacts/new.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write"} == {"artifacts/old.json"}
    assert _orphaned(gate.analyse_consumer_side(tmp_path, [])) == {"artifacts/new.json"}


def test_round_seven_many_call_states_retain_the_union(gate, tmp_path):
    _write(
        tmp_path,
        "from pathlib import Path\ndef write_state():\n    ARTIFACT.write_text('{}')\n"
        + "".join(f"ARTIFACT = Path('artifacts/{i}.json')\nwrite_state()\n" for i in range(12)),
    )
    accesses, count, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write"} == {
        f"artifacts/{i}.json" for i in range(12)
    }
    assert count == 0


@pytest.mark.parametrize("reverse", [False, True])
def test_round_seven_call_state_cap_is_named_without_guessing(gate, tmp_path, reverse):
    calls = [f"write_state(Path('artifacts/{index}.json'))\n" for index in range(40)]
    _write(
        tmp_path,
        "from pathlib import Path\n"
        "def write_state(artifact):\n    artifact.write_text('{}')\n"
        + "".join(reversed(calls) if reverse else calls)
        + "Path('artifacts/39.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert report.unresolvable > 0
    assert any(
        "binding state cap" in site and "write_state" in site for site in report.unresolved_paths
    )
    assert _orphaned(report) == {"artifacts/39.json"}
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not [access for access in accesses if access.action == "write" and access.bounded]


@pytest.mark.parametrize("caller_first", [False, True])
def test_round_seven_state_cap_preserves_unresolved_read_evidence(gate, tmp_path, caller_first):
    reader = "def read_binding(root: Path, key):\n    (root / f'binding-{key}.json').read_text()\n"
    caller = "def callers():\n" + "".join(
        f"    read_binding(Path('artifacts/{index}'), choose_key())\n" for index in range(40)
    )
    _write(
        tmp_path,
        "from pathlib import Path\n"
        + (caller + reader if caller_first else reader + caller)
        + "callers()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert unresolved > 0
    assert any(
        access.action == "read" and not access.bounded and "binding-" in access.pattern
        for access in accesses
    )


def test_round_seven_fixpoint_iteration_cap_is_named(gate, tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "_MAX_BINDING_ROUNDS", 3)
    _write(
        tmp_path,
        "from pathlib import Path\n"
        "def write_state(artifact):\n    artifact.write_text('{}')\n"
        + "".join(
            f"def step_{n}(artifact):\n"
            f"    {'write_state' if n == 0 else f'step_{n - 1}'}(artifact)\n"
            for n in range(6)
        )
        + "step_5(Path('artifacts/new.json'))\n"
        "Path('artifacts/new.json').read_text()\n"
        "Path('artifacts/stable.json').write_text('{}')\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert report.unresolvable > 0
    assert any("did not converge" in site for site in report.unresolved_paths)
    assert _orphaned(report) == {"artifacts/new.json"}
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {access.pattern for access in accesses if access.action == "write"} == {
        "artifacts/stable.json"
    }


def test_round_seven_mixed_read_bounds_keep_only_unresolved_pairs(gate, tmp_path, monkeypatch):
    # This is the mixed group collected at sdlc_claim.py:4089/4152 in the real tree:
    # identical displayed pattern and glob, with both bounded and unresolved reads.
    pattern = "*/cc-claim-dispatch-*.json"
    dynamic = gate.ArtifactAccess(
        "read",
        pattern,
        Path("shared/reader.py"),
        1,
        "claim_dispatch_binding",
        "load_claim_dispatch_binding",
        bounded=False,
        glob_pattern=pattern,
    )
    literal = replace(dynamic, lineno=2, bounded=True)
    writer = replace(
        dynamic,
        action="write",
        path=Path("shared/writer.py"),
        operation="write_claim_dispatch_binding",
    )
    monkeypatch.setattr(
        gate,
        "collect_artifact_accesses",
        lambda *_args, **_kwargs: (
            [dynamic, literal, writer],
            2,
            {dynamic.path: frozenset({"shared.writer"})},
            {},
        ),
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert len(report.pairs) == 1
    assert report.pairs[0].reader == dynamic
    assert report.pairs[0].writer == writer
    assert pattern in _orphaned(report, UNRESOLVED_WRITER)


def test_round_seven_imported_callers_share_equal_global_states(gate, tmp_path):
    _write(
        tmp_path,
        "from shared import writer\n" + "".join(f"writer.run_{index}()\n" for index in range(24)),
    )
    (tmp_path / "shared/writer.py").write_text(
        "from pathlib import Path\nARTIFACT = Path('artifacts/shared.json')\n"
        "def write_state():\n    ARTIFACT.write_text('{}')\n"
        + "".join(f"def run_{index}():\n    write_state()\n" for index in range(24))
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert unresolved == 0
    assert {access.pattern for access in accesses if access.action == "write"} == {
        "artifacts/shared.json"
    }


def test_round_seven_repeated_calls_do_not_exhaust_state_cap(gate, tmp_path):
    _write(
        tmp_path,
        "from pathlib import Path\n"
        "def write_state(artifact):\n    artifact.write_text('{}')\n"
        + "write_state(Path('artifacts/stable.json'))\n"
        * 80,
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert unresolved == 0
    assert {access.pattern for access in accesses if access.action == "write"} == {
        "artifacts/stable.json"
    }


def test_round_seven_repeated_glob_matches_reuse_compilation(gate, monkeypatch):
    compiled = []
    original = gate.re.compile

    def counted(pattern, *args, **kwargs):
        compiled.append(pattern)
        return original(pattern, *args, **kwargs)

    monkeypatch.setattr(gate.re, "compile", counted)
    tracked = frozenset(f"config/unrelated-{index}.txt" for index in range(200))
    for _ in range(10):
        assert not gate._pattern_is_committed("artifacts/fixpoint-resource/*.json", tracked)
    assert gate._pattern_is_committed("config/unrelated-0.txt", tracked)
    assert not gate._pattern_is_committed("config/unrelated-0.txt.extra", tracked)
    assert len(compiled) == 1


def test_round_seven_fixpoint_resource_bounds(tmp_path):
    # Several imported call chains require repeated binding discovery. Compare isolated
    # processes so peak RSS is not inherited from earlier tests; a single sweep is the
    # synthetic baseline, with the same parse/registration and report work in both runs.
    # Large module constants expose duplicated global snapshots; VmHWM belongs to the
    # child address space, unlike ru_maxrss which can retain the pytest parent's peak.
    module_count = 80
    for index in range(module_count):
        module = tmp_path / "shared" / f"writer_{index}.py"
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text(
            "from pathlib import Path\n"
            + "".join(f"CONSTANT_{n} = {str(n).ljust(2048, chr(120))!r}\n" for n in range(64))
            + "def write_state(artifact=Path('artifacts/old.json')):\n"
            "    artifact.write_text('{}')\n"
            + "".join(
                f"def step_{n}(artifact):\n"
                f"    {'write_state' if n == 0 else f'step_{n - 1}'}(artifact)\n"
                for n in range(6)
            )
        )
    _write(
        tmp_path,
        "from pathlib import Path\n"
        + "".join(
            f"from shared.writer_{index} import step_5 as run_{index}\n"
            f"run_{index}(Path('artifacts/{index}.json'))\n"
            for index in range(module_count)
        ),
    )
    driver = """
import importlib.util, json, sys, time
from pathlib import Path
spec = importlib.util.spec_from_file_location("measured_scanner", sys.argv[1])
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)
if sys.argv[3] == "single":
    gate._MAX_BINDING_ROUNDS = 1
started = time.monotonic()
accesses, unresolved, *_ = gate.collect_artifact_accesses(Path(sys.argv[2]))
print(json.dumps({"seconds": time.monotonic() - started,
                  "rss": int(next(line.split()[1] for line in Path('/proc/self/status').read_text().splitlines()
                                  if line.startswith('VmHWM:'))),
                  "writers": sorted({a.pattern for a in accesses if a.action == "write"}),
                  "unresolved": unresolved}))
"""
    measured = {}
    for mode in ("single", "fixpoint"):
        result = subprocess.run(
            [sys.executable, "-c", driver, str(SCRIPT_PATH), str(tmp_path), mode],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        measured[mode] = json.loads(result.stdout)
    baseline, fixed = measured["single"], measured["fixpoint"]
    metrics = {
        mode: {key: result[key] for key in ("seconds", "rss")} for mode, result in measured.items()
    }
    print(f"synthetic binding resource measurements: {metrics}")
    assert fixed["writers"] == [
        f"artifacts/{index}.json" for index in sorted(range(module_count), key=str)
    ]
    assert fixed["unresolved"] == 0
    assert fixed["rss"] <= 2 * baseline["rss"], measured
    assert fixed["seconds"] <= 2 * baseline["seconds"], measured


def test_round_seven_recursive_binding_growth_is_named(gate, tmp_path):
    _write(
        tmp_path,
        "from pathlib import Path\ndef write_state(artifact):\n"
        "    artifact.write_text('{}')\n    write_state(artifact / 'next')\n"
        "def write_stable():\n    Path('artifacts/stable.json').write_text('{}')\n"
        "write_stable()\n"
        "write_state(Path('artifacts/root'))\nPath('artifacts/root/next').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report) == {"artifacts/root/next"}
    assert report.unresolvable > 0
    assert any(
        "call bindings for write_state did not converge" in site for site in report.unresolved_paths
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write"} == {"artifacts/stable.json"}


@pytest.mark.parametrize(
    "expression, expected",
    [
        ("artifact.with_name(str(artifact := Path('new.json')))", "artifacts/old.json/new.json"),
        ("artifact.parents[(index := 0)]", "artifacts/old.json"),
        ("artifact / str(artifact := Path('new.json'))", "artifacts/old.json/child/new.json"),
    ],
)
def test_round_seven_nested_receiver_operands(gate, tmp_path, expression, expected):
    _write(
        tmp_path,
        "from pathlib import Path\nartifact = Path('artifacts/old.json/child')\n"
        f"({expression}).write_text('{{}}')\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write"} == {expected}


@pytest.mark.parametrize("declared_global", [False, True])
@pytest.mark.parametrize("helper", [False, True])
def test_round_seven_nested_call_separates_cells_from_globals(
    gate, tmp_path, declared_global, helper
):
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "def outer():\n    ARTIFACT = Path('artifacts/cell.json')\n"
        "    def inner():\n"
        + ("        global ARTIFACT\n" if declared_global else "")
        + ("        return ARTIFACT\n" if helper else "        ARTIFACT.write_text('{}')\n")
        + ("    inner().write_text('{}')\n" if helper else "    inner()\n")
        + "outer()\nARTIFACT = Path('artifacts/new.json')\nARTIFACT.read_text()\n"
        "Path('artifacts/cell.json').read_text()\nPath('artifacts/old.json').read_text()\n",
    )
    expected = "old" if declared_global else "cell"
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write"} == {f"artifacts/{expected}.json"}
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report) == {
        f"artifacts/{name}.json" for name in {"old", "cell", "new"} - {expected}
    }
    assert report.unresolvable == 0


@pytest.mark.parametrize("caller_first", [False, True])
def test_round_seven_transitive_calls_keep_explicit_bindings(gate, tmp_path, caller_first):
    definitions = [
        "def write_state(artifact=Path('artifacts/old.json')):\n    artifact.write_text('{}')\n",
        *[
            f"def step_{index}(artifact):\n"
            f"    {'write_state' if index == 0 else f'step_{index - 1}'}(artifact)\n"
            for index in range(6)
        ],
    ]
    _write(
        tmp_path,
        "from pathlib import Path\n"
        + "".join(reversed(definitions) if caller_first else definitions)
        + "step_5(Path('artifacts/new.json'))\nPath('artifacts/old.json').read_text()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write"} == {"artifacts/new.json"}
    assert unresolved == 0
    assert _orphaned(gate.analyse_consumer_side(tmp_path, [])) == {"artifacts/old.json"}


@pytest.mark.parametrize(
    "source, orphan",
    [
        (
            "def write_state(artifact=Path('artifacts/old.json')):\n"
            "    artifact.write_text('{}')\n"
            "def run():\n    write_state(Path('artifacts/new.json'))\nrun()\n",
            "old",
        ),
        (
            "ARTIFACT = Path('artifacts/old.json')\n"
            "def write_state():\n    ARTIFACT.write_text('{}')\nwrite_state()\n"
            "ARTIFACT = Path('artifacts/new.json')\n",
            "new",
        ),
        (
            "artifact = Path('artifacts/old.json')\n"
            "artifact.write_text(str(artifact := Path('artifacts/new.json')))\n",
            "new",
        ),
    ],
    ids=["definition-order", "call-globals", "receiver-order"],
)
def test_round_seven_report_arm_keeps_orphan_visible(
    gate, tmp_path, monkeypatch, capsys, source, orphan
):
    _write(
        tmp_path,
        "from pathlib import Path\n" + source + f"Path('artifacts/{orphan}.json').read_text()\n",
    )
    monkeypatch.chdir(tmp_path)
    report_path = tmp_path / "report.json"
    assert gate.main(["--consumer-side", "--report-json", str(report_path)]) == 0
    output = capsys.readouterr().out
    assert "consumer-reads-unwritten-artifact=1" in output
    assert f"artifacts/{orphan}.json" in output
    assert "REPORT-ONLY" in output
    report = json.loads(report_path.read_text())
    assert report["summary"]["unresolvable"] == 0
    assert report["summary"]["report_only"] is True
    assert {finding["read_pattern"] for finding in report["findings"]} == {
        f"artifacts/{orphan}.json"
    }


@pytest.mark.parametrize("terminator", ["break", "continue", "return", "raise RuntimeError"])
def test_round_six_unreachable_accesses_after_terminator(gate, tmp_path, terminator):
    _write(
        tmp_path,
        "from pathlib import Path\ndef run():\n    for item in [1]:\n"
        f"        {terminator}\n"
        "        Path('artifacts/missing.json').write_text('{}')\n"
        "        Path('artifacts/unreachable.json').read_text()\n"
        "Path('artifacts/missing.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report) == {"artifacts/missing.json"}
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert [(a.action, a.pattern) for a in accesses] == [("read", "artifacts/missing.json")]


@pytest.mark.parametrize("terminator", ["break", "continue"])
def test_round_six_loop_exit_preserves_bindings_and_runs_finally(gate, tmp_path, terminator):
    _write(
        tmp_path,
        "from pathlib import Path\nartifact = Path('artifacts/before.json')\n"
        "for item in [1]:\n    try:\n        artifact = Path('artifacts/exit.json')\n"
        f"        {terminator}\n"
        "        artifact = Path('artifacts/unreachable.json')\n"
        "    finally:\n        artifact.read_text()\n"
        "else:\n    Path('artifacts/else.json').read_text()\n"
        "artifact.read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report) == {"artifacts/exit.json"} | (
        {"artifacts/else.json"} if terminator == "continue" else set()
    )


@pytest.mark.parametrize("signature", ["artifact=ARTIFACT", "*, artifact=ARTIFACT"])
def test_round_six_module_default_is_frozen(gate, tmp_path, signature):
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        f"def write_state({signature}):\n    artifact.write_text('{{}}')\n"
        "ARTIFACT = Path('artifacts/new.json')\nwrite_state()\n"
        "Path('artifacts/new.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write"} == {"artifacts/old.json"}
    assert _orphaned(gate.analyse_consumer_side(tmp_path, [])) == {"artifacts/new.json"}


@pytest.mark.parametrize(
    "argument, expected",
    [
        ("", "old"),
        ("Path('artifacts/explicit.json')", "explicit"),
        ("artifact=Path('artifacts/explicit.json')", "explicit"),
    ],
)
def test_round_six_helper_default_and_explicit_argument(gate, tmp_path, argument, expected):
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "def artifact_path(artifact=ARTIFACT):\n    return artifact\n"
        "ARTIFACT = Path('artifacts/new.json')\n"
        f"artifact_path({argument}).write_text('{{}}')\n"
        "Path('artifacts/new.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write"} == {f"artifacts/{expected}.json"}
    assert _orphaned(gate.analyse_consumer_side(tmp_path, [])) == {"artifacts/new.json"}


def test_round_six_unknown_definition_default_stays_unresolved(gate, tmp_path):
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT = choose()\n"
        "def write_state(artifact=ARTIFACT):\n    artifact.write_text('{}')\n"
        "ARTIFACT = Path('artifacts/new.json')\nwrite_state()\n"
        "Path('artifacts/new.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report) == {"artifacts/new.json"}
    assert report.unresolvable == 1
    assert len(report.unresolved_paths) == 1
    assert "path=artifact" in report.unresolved_paths[0]


@pytest.mark.parametrize(
    "argument", ["Path('artifacts/explicit.json')", "artifact=Path('artifacts/explicit.json')"]
)
def test_round_six_explicit_writer_argument_wins(gate, tmp_path, argument):
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "def write_state(artifact=ARTIFACT):\n    artifact.write_text('{}')\n"
        "ARTIFACT = Path('artifacts/new.json')\n"
        f"write_state({argument})\nPath('artifacts/old.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write"} == {"artifacts/explicit.json"}
    assert _orphaned(gate.analyse_consumer_side(tmp_path, [])) == {"artifacts/old.json"}


@pytest.mark.parametrize("argument", ["choose()", "*options", "**options"])
def test_round_six_unknown_writer_argument_cannot_reuse_default(gate, tmp_path, argument):
    _write(
        tmp_path,
        "from pathlib import Path\ndef write_state(artifact=Path('artifacts/old.json')):\n"
        "    artifact.write_text('{}')\n"
        f"write_state({argument})\nPath('artifacts/old.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report) == {"artifacts/old.json"}
    assert report.unresolvable == 1
    assert len(report.unresolved_paths) == 1


@pytest.mark.parametrize(
    "default", ["ARTIFACT, later=(ARTIFACT := Path('artifacts/new.json'))", "helper()"]
)
def test_round_six_defaults_use_definition_expression_order(gate, tmp_path, default):
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "def helper():\n    return ARTIFACT\n"
        f"def write_state(artifact={default}):\n    artifact.write_text('{{}}')\n"
        "ARTIFACT = Path('artifacts/new.json')\nwrite_state()\n"
        "Path('artifacts/new.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write"} == {"artifacts/old.json"}


@pytest.mark.parametrize(
    "literal, other",
    [
        ("state[1].json", "state1.json"),
        ("state].json", "state.json"),
        ("*.json", "missing.json"),
        ("state?.json", "state1.json"),
    ],
)
@pytest.mark.parametrize("indirect", [False, True])
def test_round_six_literal_filename_is_not_a_glob(gate, tmp_path, literal, other, indirect):
    expression = f"Path('artifacts/{literal}')"
    _write(
        tmp_path,
        "from pathlib import Path\n"
        + (
            f"artifact = {expression}\nartifact.write_text('{{}}')\n"
            if indirect
            else f"{expression}.write_text('{{}}')\n"
        )
        + f"Path('artifacts/{other}').read_text()\n{expression}.read_text()\n",
    )
    assert _orphaned(gate.analyse_consumer_side(tmp_path, [])) == {f"artifacts/{other}"}
    accesses, count, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {(a.action, a.pattern) for a in accesses} == {
        ("write", f"artifacts/{literal}"),
        ("read", f"artifacts/{literal}"),
        ("read", f"artifacts/{other}"),
    }
    assert count == 0


@pytest.mark.parametrize("directory", ["state[1]", "state*", "state?", "state]"])
def test_round_six_glob_escapes_literal_parent(gate, tmp_path, directory):
    _write(
        tmp_path,
        "from pathlib import Path\nPath('artifacts/state1/present.json').write_text('{}')\n"
        f"Path('artifacts/{directory}').glob('*.json')\n",
    )
    assert _orphaned(gate.analyse_consumer_side(tmp_path, [])) == {f"artifacts/{directory}/*.json"}


@pytest.mark.parametrize(
    "statement",
    [
        "slots[Path('artifacts/missing.json').read_text()] = 1",
        "Path('artifacts/missing.json').read_text().attribute = 1",
        "with manager() as slots[Path('artifacts/missing.json').read_text()]:\n    pass",
        "with manager() as Path('artifacts/missing.json').read_text().attribute:\n    pass",
        "slots[Path('artifacts/missing.json').read_text()]: int = 1",
        "slots[Path('artifacts/missing.json').read_text()] += 1",
        "del slots[Path('artifacts/missing.json').read_text()]",
    ],
    ids=[
        "subscript",
        "attribute",
        "with-subscript",
        "with-attribute",
        "annotated",
        "augmented",
        "delete",
    ],
)
def test_round_six_store_target_reads_are_scanned(gate, tmp_path, statement):
    _write(tmp_path, "from pathlib import Path\nslots = {}\n" + statement + "\n")
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report) == {"artifacts/missing.json"}
    assert report.unresolvable == 0


@pytest.mark.parametrize("store", ["=", "+="])
def test_round_six_target_and_rhs_evaluation_order(gate, tmp_path, store):
    _write(
        tmp_path,
        "from pathlib import Path\nslots = {}\nartifact = Path('artifacts/old.json')\n"
        f"slots[artifact.read_text()] {store} (artifact := Path('artifacts/new.json'))\n",
    )
    expected = "old" if store == "+=" else "new"
    assert _orphaned(gate.analyse_consumer_side(tmp_path, [])) == {f"artifacts/{expected}.json"}


@pytest.mark.parametrize(
    "statement",
    [
        "artifact = slots[artifact.read_text()] = Path('artifacts/new.json')",
        "artifact, slots[artifact.read_text()] = Path('artifacts/new.json'), 1",
        "with Path('artifacts/new.json') as artifact, manager() as slots[artifact.read_text()]:\n    pass",
    ],
    ids=["chained", "unpacked", "with-items"],
)
def test_round_six_target_stores_execute_left_to_right(gate, tmp_path, statement):
    _write(
        tmp_path,
        "from pathlib import Path\nslots = {}\nartifact = Path('artifacts/old.json')\n"
        # This pin isolates target order; an unresolved manager can also rebind globals.
        "def manager():\n    pass\n" + statement + "\n",
    )
    assert _orphaned(gate.analyse_consumer_side(tmp_path, [])) == {"artifacts/new.json"}


@pytest.mark.parametrize("terminator", ["break", "continue", "return", "raise RuntimeError"])
def test_round_six_conditional_exit_keeps_reachable_branch(gate, tmp_path, terminator):
    _write(
        tmp_path,
        "from pathlib import Path\ndef run(flag):\n    for item in [1]:\n"
        f"        if flag:\n            {terminator}\n"
        "        Path('artifacts/reachable.json').write_text('{}')\n"
        "Path('artifacts/reachable.json').read_text()\n",
    )
    assert _orphaned(gate.analyse_consumer_side(tmp_path, [])) == set()


@pytest.mark.parametrize("terminator", ["break", "continue"])
def test_round_six_unreachable_definition_cannot_supply_writer(gate, tmp_path, terminator):
    _write(
        tmp_path,
        "from pathlib import Path\nfor item in [1]:\n"
        f"    {terminator}\n    def write_state():\n"
        "        Path('artifacts/missing.json').write_text('{}')\n"
        "Path('artifacts/missing.json').read_text()\n",
    )
    assert _orphaned(gate.analyse_consumer_side(tmp_path, [])) == {"artifacts/missing.json"}


@pytest.mark.parametrize("terminator", ["break", "continue"])
def test_round_six_unreachable_helper_cannot_supply_writer(gate, tmp_path, terminator):
    _write(
        tmp_path,
        "from pathlib import Path\nfor item in [1]:\n"
        f"    {terminator}\n    def artifact_path():\n"
        "        return Path('artifacts/missing.json')\n"
        "artifact_path().write_text('{}')\nPath('artifacts/missing.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report) == {"artifacts/missing.json"}
    assert report.unresolvable == 1
    assert len(report.unresolved_paths) == 1


@pytest.mark.parametrize("literal", ["state[1].json", "state].json", "*.json", "state?.json"])
def test_round_six_real_glob_matches_literal_filename(gate, tmp_path, literal):
    _write(
        tmp_path,
        "from pathlib import Path\n"
        f"Path('artifacts/{literal}').write_text('{{}}')\n"
        "Path('artifacts').glob('*.json')\n",
    )
    assert _orphaned(gate.analyse_consumer_side(tmp_path, [])) == set()


@pytest.mark.parametrize("transform", ["f'{name}'", "Path(name)", "helper(name)"])
def test_round_six_literal_provenance_survives_path_construction(gate, tmp_path, transform):
    _write(
        tmp_path,
        "from pathlib import Path\ndef helper(name):\n    return Path(name)\n"
        "name = 'artifacts/state[1].json'\n"
        f"Path({transform}).write_text('{{}}')\n"
        "Path('artifacts/state1.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report) == {"artifacts/state1.json"}
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write"} == {"artifacts/state[1].json"}


def test_round_six_invalid_literal_cannot_forge_provenance(gate, tmp_path):
    _write(
        tmp_path,
        "from pathlib import Path\nPath('artifacts/\\0star.json').write_text('{}')\n"
        "Path('artifacts/*.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report) == {"artifacts/*.json"}
    assert report.unresolvable == 1
    assert len(report.unresolved_paths) == 1


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
        assert _orphaned(gate.analyse_consumer_side(tmp_path, [])) == {"artifacts/orphan.json"}


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
    assert "artifacts/old.json" in _orphaned(report)
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


def test_provenance_names_the_sources_git_does_not_track(gate, tmp_path: Path) -> None:
    """A report cannot say the tree was clean while measuring a file in no commit.

    git status is asked with --untracked-files=no, and the scan walks the filesystem, so an
    untracked .py file was read like any other and its findings appeared beside dirty=false. A
    later reader checking out that head measures a different tree than the report describes
    (review finding, codex, 2026-09-07).

    The committed twin is what keeps this from being a blanket dirty flag: a tree whose measured
    sources are all tracked still reports clean, and the untracked list stays empty.
    """

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    _write(tmp_path, "value = 1\n")
    git("init", "-q")
    git("-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")

    clean = gate.analyse_consumer_side(tmp_path, []).measured
    assert clean["dirty"] is False
    assert clean["untracked_sources"] == []

    (tmp_path / "shared" / "untracked.py").write_text(
        "from pathlib import Path\nPath('artifacts/uncommitted.json').read_text()\n"
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "artifacts/uncommitted.json" in {
        finding.reader.pattern
        for finding in report.findings
        if finding.kind == "consumer-reads-unwritten-artifact"
    }, "the untracked file is measured"
    assert report.measured["untracked_sources"] == ["shared/untracked.py"]
    assert report.measured["dirty"] is True, "so the head does not describe what was measured"


def test_a_commit_that_tracks_nothing_is_still_a_checkout(gate, tmp_path: Path) -> None:
    """An empty tracked set is a fact about the commit, not about there being no commit.

    The first repair guarded on a non-empty tracked set, which is what `_non_python_source_paths`
    asks for a different purpose. A repository whose commit tracks nothing is still a repository:
    its untracked source was reported as `dirty: false` with an empty list beside a real HEAD
    (review finding, cx-blue, 2026-09-07).

    Both neighbours are pinned here so the fix cannot drift into either: the same empty commit
    with nothing untracked still reports clean, and a directory that is no checkout claims nothing
    rather than calling every file untracked.
    """

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "empty")

    clean = gate.analyse_consumer_side(tmp_path, []).measured
    assert clean["head"] is not None
    assert clean["dirty"] is False
    assert clean["untracked_sources"] == []

    _write(tmp_path, "value = 1\n")
    measured = gate.analyse_consumer_side(tmp_path, []).measured
    assert measured["head"] == clean["head"]
    assert measured["untracked_sources"] == ["shared/consumer.py"]
    assert measured["dirty"] is True


def test_an_enumeration_that_failed_is_unknown_not_a_clean_measurement(
    gate, tmp_path: Path, monkeypatch
) -> None:
    """A `git ls-files` that could not run must not become a list of untracked files.

    The repair above answered the empty-commit case by asking whether a head resolves — which
    assumes a resolvable head proves the index was read. It does not. Injecting exit 128 over a
    genuinely clean tracked fixture had the report name a **tracked** file as untracked with
    `dirty: true` (review finding, cx-blue, 2026-09-07, against that repair).

    So the outcome travels with the result of the same acquisition rather than being inferred
    from a second one — a later success cannot certify an earlier empty set, and an earlier
    success cannot license a later failure. Unknown is `null`: not `[]`, which would read as a
    clean measurement, and not a fabricated list.

    **`dirty` is unknown here too, and this row asserted otherwise until the coordinator caught
    it.** It required `False`, on the reasoning that an unreadable index should not upgrade into
    dirty — which is the day's own defect written into a test. `dirty` describes the measurement,
    and the measurement has two inputs; with one of them unreadable, `False` is a claim of
    cleanliness that nothing supports. The row below asserts `None`, and the tracked-modified
    case keeps its `True` because a known-dirty status is sufficient on its own.
    """

    _write(tmp_path, "value = 1\n")
    monkeypatch.setattr(gate, "_git_tracking", lambda _root: gate.NO_GIT_TRACKING)
    monkeypatch.setattr(gate, "_git_head", lambda _root: ("a" * 40, False))

    measured = gate.analyse_consumer_side(tmp_path, []).measured
    assert measured["head"] == "a" * 40, "the head is known and says so"
    assert measured["untracked_sources"] is None, "the enumeration is not"
    assert measured["dirty"] is None, (
        "one unreadable observation leaves the measurement unknown, not clean"
    )


def test_a_modified_tracked_file_is_dirty_even_when_enumeration_fails(
    gate, tmp_path: Path, monkeypatch
) -> None:
    """The twin: either observation alone is enough for dirty, only both agreeing give clean.

    A `git status` that reports modifications establishes a dirty measurement whatever happened to
    `ls-files`, so this must not fall back to unknown along with its neighbour.
    """

    _write(tmp_path, "value = 1\n")
    monkeypatch.setattr(gate, "_git_tracking", lambda _root: gate.NO_GIT_TRACKING)
    monkeypatch.setattr(gate, "_git_head", lambda _root: ("b" * 40, True))

    measured = gate.analyse_consumer_side(tmp_path, []).measured
    assert measured["dirty"] is True
    assert measured["untracked_sources"] is None, "still unknown, and still says so"


def test_a_directory_that_is_no_checkout_claims_nothing(gate, tmp_path: Path) -> None:
    """The twin of the two rows above: no head, so no untracked claim about anything."""

    _write(tmp_path, "value = 1\n")
    measured = gate.analyse_consumer_side(tmp_path, []).measured
    assert measured["head"] is None
    assert measured["dirty"] is None
    assert measured["untracked_sources"] is None


def test_a_walk_error_from_outside_the_tree_is_recorded_not_raised(gate, tmp_path: Path) -> None:
    """`os.walk` does not catch what its `onerror` callback raises.

    The callback exists to RECORD an unreadable directory, and it called `relative_to`, which
    raises `ValueError` for any path the OS reports from outside the root. Nothing promises the
    error's filename is under the tree being walked — that is a fact about the OS's report, not
    about our arguments — so the scanner died exactly where it was written to describe a gap
    (review finding, gemini, 2026-09-07). A failure path that fails is worse than the gap it was
    meant to name.

    The ordinary in-tree case below is the twin: it must keep its relative path and its class.
    """

    _write(tmp_path, "value = 1\n")
    blocked = tmp_path / "shared" / "locked"
    blocked.mkdir()
    os.chmod(blocked, 0o000)
    try:
        report = gate.analyse_consumer_side(tmp_path, [])
        assert ("shared/locked", "PermissionError") in {
            (str(gap.path), gap.error_class) for gap in report.source_gaps
        }
    finally:
        os.chmod(blocked, 0o700)

    foreign = PermissionError(13, "denied")
    foreign.filename = "/proc/1/root/elsewhere"
    real_walk = gate.os.walk

    def one_foreign_error(top, onerror=None, **kwargs):
        if onerror is not None:
            onerror(foreign)
        return iter(())

    gate.os.walk = one_foreign_error
    try:
        gaps: list = []
        gate._iter_python_sources(tmp_path, source_gaps=gaps)
    finally:
        gate.os.walk = real_walk
    assert [(str(gap.path), gap.error_class) for gap in gaps] == [
        ("/proc/1/root/elsewhere", "PermissionError")
    ], "a path that cannot be made relative is recorded absolute, never dropped and never raised"


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
    assert _orphaned(report) == expected
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
    assert "artifacts/destination.json" in _orphaned(gate.analyse_consumer_side(tmp_path, []))


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
    assert _orphaned(gate.analyse_consumer_side(tmp_path, [])) == {
        "artifacts/a.json",
        "artifacts/b.json",
    }


def test_definition_expressions_use_enclosing_bindings(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\ndef outer():\n    artifact = Path('artifacts/definition.json')\n    @decorate(artifact.read_text())\n    def inner(artifact=open(artifact), *, other=open('artifacts/keyword-default.json')):\n        pass\n",
    )
    assert _orphaned(gate.analyse_consumer_side(tmp_path, [])) == {
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
    assert _orphaned(report) == expected
    if shape == "loop":
        assert report.unresolvable > 0
    else:
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
    assert _orphaned(report) == {f"artifacts/module-{i}.json" for i in range(count)}
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


def test_multi_component_path_does_not_pair_different_files(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\n"
        "Path('artifacts', 'produced.json').write_text('{}')\n"
        "Path('artifacts', 'missing.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "artifacts/missing.json" in _orphaned(report)
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {(item.action, item.pattern) for item in accesses} == {
        ("write", "artifacts/produced.json"),
        ("read", "artifacts/missing.json"),
    }
    assert unresolved == 0


@pytest.mark.parametrize(
    "component",
    ["{absolute!r}", "Path({absolute!r})", "PurePath({absolute!r})"],
)
def test_multi_component_path_absolute_component_resets_prefix(
    gate, tmp_path: Path, component: str
) -> None:
    absolute = str(tmp_path / "artifacts/reset")
    _write(
        tmp_path,
        "from pathlib import Path, PurePath\n"
        f"Path('wrong', {component.format(absolute=absolute)}, 'missing.json').read_text()\n",
    )
    assert _orphaned(gate.analyse_consumer_side(tmp_path, [])) == {"artifacts/reset/missing.json"}


@pytest.mark.parametrize("constructor", ["Path", "PurePath", "PurePosixPath"])
def test_multi_component_path_joins_nested_components(
    gate, tmp_path: Path, constructor: str
) -> None:
    _write(
        tmp_path,
        "from pathlib import Path, PurePath, PurePosixPath\n"
        f"Path({constructor}('artifacts', 'nested'), Path('missing.json')).read_text()\n",
    )
    assert _orphaned(gate.analyse_consumer_side(tmp_path, [])) == {"artifacts/nested/missing.json"}


@pytest.mark.parametrize("component", ["choose()", "unknown", "f'{unknown}.json'"])
def test_multi_component_path_unknown_component_is_named(
    gate, tmp_path: Path, capsys, component: str
) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\n"
        f"Path('artifacts', {component}).write_text('{{}}')\n"
        "Path('artifacts/missing.json').read_text()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not [item for item in accesses if item.action == "write"]
    assert unresolved == 1
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "artifacts/missing.json" in _orphaned(report)
    sites = gate._report_json(report)["unresolved_paths"]
    assert len(sites) == 1 and "shared/consumer.py:2:" in sites[0]
    assert component in sites[0]
    gate.print_consumer_side_report(report, tmp_path / "unused.json")
    assert "[UNRESOLVED] " + sites[0] in capsys.readouterr().out


@pytest.mark.parametrize("declaration", ["", "    global ARTIFACT\n"])
def test_helper_local_assignments_do_not_borrow_module_writer(
    gate, tmp_path: Path, declaration: str
) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "def artifact_path():\n"
        + declaration
        + "    ARTIFACT = Path('artifacts/intermediate.json')\n"
        "    ARTIFACT = Path('artifacts/new.json')\n    return ARTIFACT\n"
        "artifact_path().write_text('{}')\nPath('artifacts/old.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "artifacts/old.json" in _orphaned(report)
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {item.pattern for item in accesses if item.action == "write"} == {"artifacts/new.json"}
    assert unresolved == 0


@pytest.mark.parametrize(
    "body",
    [
        "    if flag:\n        ARTIFACT = Path('artifacts/new.json')\n",
        "    for ARTIFACT in choices:\n        pass\n",
        "    global ARTIFACT\n    rebind()\n",
        "    global ARTIFACT\n    rebind()\n    saved = ARTIFACT\n",
    ],
)
def test_helper_unbounded_body_cannot_supply_old_writer(gate, tmp_path: Path, body: str) -> None:
    returned = "saved" if "saved =" in body else "ARTIFACT"
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "def rebind():\n    global ARTIFACT\n"
        "    ARTIFACT = Path('artifacts/new.json')\n"
        "def artifact_path():\n" + body + f"    return {returned}\n"
        "artifact_path().write_text('{}')\nPath('artifacts/old.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "artifacts/old.json" in _orphaned(report)
    assert report.unresolvable >= 1
    assert any("artifact_path()" in site for site in report.unresolved_paths)


def test_helper_nonlocal_assignment_uses_enclosing_binding(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "def outer():\n    ARTIFACT = Path('artifacts/enclosing.json')\n"
        "    def artifact_path():\n        nonlocal ARTIFACT\n"
        "        ARTIFACT = Path('artifacts/new.json')\n        return ARTIFACT\n"
        "    artifact_path().write_text('{}')\nPath('artifacts/old.json').read_text()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {item.pattern for item in accesses if item.action == "write"} == {"artifacts/new.json"}
    assert unresolved == 0
    assert "artifacts/old.json" in _orphaned(gate.analyse_consumer_side(tmp_path, []))


def test_helper_return_uses_state_at_return_not_after(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT = Path('artifacts/old.json')\n"
        "def artifact_path():\n    ARTIFACT = Path('artifacts/returned.json')\n"
        "    return ARTIFACT\n    ARTIFACT = Path('artifacts/unreachable.json')\n"
        "artifact_path().read_text()\n",
    )
    assert _orphaned(gate.analyse_consumer_side(tmp_path, [])) == {"artifacts/returned.json"}


def test_helper_guard_raise_preserves_normal_return_binding(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\ndef artifact_path(flag):\n"
        "    if flag:\n        raise ValueError('invalid')\n"
        "    artifact = Path('artifacts/normal.json')\n    return artifact\n"
        "artifact_path(False).read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report) == {"artifacts/normal.json"}
    assert report.unresolvable == 0


@pytest.mark.parametrize(
    ("binding", "expected"),
    [
        pytest.param(
            "artifact, other = Path('artifacts/new.json'), None", "artifacts/new.json", id="tuple"
        ),
        pytest.param(
            "[artifact, other] = [Path('artifacts/new.json'), None]",
            "artifacts/new.json",
            id="list",
        ),
        pytest.param(
            "artifact, (other, label) = Path('artifacts/new.json'), (None, None)",
            "artifacts/new.json",
            id="nested",
        ),
        pytest.param("artifact, other = items", None, id="unknown-unpack"),
        pytest.param(
            "artifact, other = [Path('artifacts/new.json')]", None, id="mismatched-unpack"
        ),
        pytest.param("*artifact, other = [Path('artifacts/new.json'), None]", None, id="starred"),
        pytest.param("artifact /= 'child.json'", "artifacts/old.json/child.json", id="aug-div"),
        pytest.param("artifact += '.new'", "artifacts/old.json.new", id="aug-add"),
        pytest.param("artifact /= unknown", None, id="aug-unknown"),
        pytest.param("artifact *= 2", None, id="aug-unmodelled"),
        pytest.param("with context() as artifact:\n        pass", None, id="with"),
        pytest.param("async with context() as artifact:\n        pass", None, id="async-with"),
        pytest.param(
            "with Path('artifacts/new.json') as artifact:\n        pass",
            "artifacts/new.json",
            id="with-path",
        ),
        pytest.param("del artifact", None, id="del"),
        pytest.param("(artifact := unknown)", None, id="named-expression"),
        pytest.param("artifact.part = unknown", None, id="attribute-store"),
        pytest.param("artifact[0] = unknown", None, id="subscript-store"),
        pytest.param("import other as artifact", None, id="import"),
        pytest.param("def artifact():\n        pass", None, id="function"),
        pytest.param("class artifact:\n        pass", None, id="class"),
        pytest.param(
            "match items:\n        case artifact:\n            artifact.write_text('{}')",
            None,
            id="match",
        ),
        pytest.param(
            "try:\n        raise ValueError()\n    except ValueError as artifact:\n        artifact.write_text('{}')",
            None,
            id="except",
        ),
    ],
)
def test_store_cannot_supply_an_obsolete_producer(gate, tmp_path: Path, binding, expected) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\nasync def use(items):\n"
        "    artifact = Path('artifacts/old.json')\n"
        f"    {binding}\n    artifact.write_text('{{}}')\n"
        "Path('artifacts/old.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "artifacts/old.json" in _orphaned(report)
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write"} == (
        {expected} if expected else set()
    )
    assert (unresolved > 0) == (expected is None)
    if expected is None:
        assert any("artifact" in site for site in report.unresolved_paths)


@pytest.mark.parametrize(
    ("expression", "unresolved_sites"),
    [
        ("[artifact.write_text('{}') for artifact in items]", 2),
        ("{artifact.write_text('{}') for artifact in items}", 2),
        ("{artifact: artifact.write_text('{}') for artifact in items}", 2),
        # A generator's body is not scheduled at the definition site, so its single unresolved
        # site is the deferral itself rather than an iterable plus a target-bound write.
        ("(artifact.write_text('{}') for artifact in items)", 1),
    ],
)
def test_comprehension_targets_do_not_borrow_or_export_producers(
    gate, tmp_path: Path, expression, unresolved_sites
) -> None:
    """A comprehension target neither exports its value NOR disturbs the enclosing binding.

    Only the first half was true here. `for artifact in items` invalidated the enclosing
    `artifact` as well, so the next line's write — which Python performs on `old.json`, the
    comprehension having its own scope — was lost with it. Twelve shapes measured against the
    interpreter, eight of them closed fixtures calling `use([])` or
    `use([Path('artifacts/other.json')])`: Python writes `old.json` in all eight and the scanner
    recorded no writer at all (review finding, root).
    """
    _write(
        tmp_path,
        "from pathlib import Path\ndef use(items):\n"
        "    artifact = Path('artifacts/old.json')\n"
        f"    {expression}\n    artifact.write_text('{{}}')\n"
        "Path('artifacts/old.json').read_text()\n",
    )
    accesses, *_rest = gate.collect_artifact_accesses(tmp_path)
    assert [(a.pattern, a.bounded) for a in accesses if a.action == "write"] == [
        ("artifacts/old.json", True)
    ]
    report = gate.analyse_consumer_side(tmp_path, [])
    # The reader now HAS its producer, so it is orphaned under neither sentence.
    assert _orphaned(report) == set()
    assert _orphaned(report, UNRESOLVED_WRITER) == set()
    # The write THROUGH the target stays unresolved: that one really is bound to an element of
    # an argument, and naming it would need per-element evaluation this arm has not built.
    assert report.unresolvable == unresolved_sites
    assert len(report.unresolved_paths) == unresolved_sites


def test_store_context_inventory_and_fallback(gate, tmp_path: Path) -> None:
    # These are all concrete CPython expression nodes capable of carrying ast.Store.
    contexts = {
        node
        for node in vars(ast).values()
        if isinstance(node, type) and issubclass(node, ast.expr) and "ctx" in node._fields
    }
    assert contexts == {ast.Name, ast.Attribute, ast.Subscript, ast.Starred, ast.List, ast.Tuple}
    scanner = gate._BlockScanner(
        path=Path("shared/consumer.py"),
        repo_root=tmp_path,
        path_functions={},
        accesses=[],
        unresolved=[0],
        unrecognised=gate.Counter(),
        context_family="test",
        nested_scope_values={},
    )
    # An unrecognised statement still exposes its Store expression to the fallback.
    statement = ast.Expr(value=ast.Name(id="artifact", ctx=ast.Store()))
    state = scanner.scan_block([statement], [{"artifact": "artifacts/old.json"}])[0]
    assert state.get("artifact") in (None, "*")


@pytest.mark.parametrize(
    ("key", "field", "expected", "wrong"),
    [
        pytest.param("1", "key:02d", "artifacts/01.json", "artifacts/1.json", id="spec"),
        pytest.param("'word'", "key!r", "artifacts/'word'.json", "artifacts/word.json", id="repr"),
        pytest.param("'é'", "key!a", "artifacts/'\\xe9'.json", "artifacts/é.json", id="ascii"),
        pytest.param("1", "key!s:0>2", "artifacts/01.json", "artifacts/1.json", id="str"),
        pytest.param(
            "123", "key!s:.2", "artifacts/12.json", "artifacts/123.json", id="str-precision"
        ),
        pytest.param("1.25", "key:.1f", "artifacts/1.2.json", "artifacts/1.25.json", id="float"),
        pytest.param("True", "key!s", "artifacts/True.json", "artifacts/1.json", id="bool"),
    ],
)
def test_constant_formatting_cannot_match_a_different_filename(
    gate, tmp_path: Path, key, field, expected, wrong
) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\n" + f"key = {key}\n"
        f"Path(f'artifacts/{{{field}}}.json').write_text('{{}}')\nPath({wrong!r}).read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert wrong in _orphaned(report)
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write"} == {expected}
    assert unresolved == 0


@pytest.mark.parametrize(
    "field", ["key:02d", "key:{width}d", "key!r:bad", "unknown!s", "unknown:02d"]
)
def test_unbounded_or_invalid_formatting_is_named(gate, tmp_path: Path, field) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\nkey = 'word'\nwidth = 2\n"
        f"Path(f'artifacts/{{{field}}}.json').write_text('{{}}')\n"
        "Path('artifacts/word.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "artifacts/word.json" in _orphaned(report)
    assert report.unresolvable == 1
    assert len(report.unresolved_paths) == 1


def test_unresolved_console_summary_first_and_bounded_json_complete(
    gate, tmp_path: Path, capsys
) -> None:
    _write(tmp_path, "def use():\n" + "".join(f"    unknown_{i}.read_text()\n" for i in range(100)))
    report = gate.analyse_consumer_side(tmp_path, [])
    gate.print_consumer_side_report(report, tmp_path / "report.json")
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("consumer-side counts:")
    assert sum(line.startswith("[UNRESOLVED]") for line in lines) == gate.CONSUMER_SIDE_REPORT_LIMIT
    assert any("75 more in JSON" in line for line in lines)
    assert len(lines) <= gate.CONSUMER_SIDE_REPORT_LIMIT + 4
    payload = gate._report_json(report)
    assert payload["summary"]["unresolvable"] == 100
    assert len(payload["unresolved_paths"]) == 100


@pytest.mark.parametrize("assigned", [False, True])
def test_unformatted_dynamic_gap_cannot_prove_a_producer(gate, tmp_path: Path, assigned) -> None:
    writer = (
        "    artifact = Path(f'artifacts/{unknown}.json')\n    artifact.write_text('{}')\n"
        if assigned
        else "    Path(f'artifacts/{unknown}.json').write_text('{}')\n"
    )
    _write(
        tmp_path,
        "from pathlib import Path\ndef use(unknown):\n"
        + writer
        + "Path('artifacts/old.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "artifacts/old.json" in _orphaned(report, UNRESOLVED_WRITER)
    assert report.unresolvable == 1
    assert len(report.unresolved_paths) == 1
    assert not report.pairs


@pytest.mark.parametrize(
    "expression",
    [
        "(artifact := Path('artifacts/a.json')) if flag else (artifact := Path('artifacts/b.json'))",
        "(artifact := Path('artifacts/a.json')) or (artifact := Path('artifacts/b.json'))",
    ],
)
def test_expression_stores_preserve_both_possible_bindings(
    gate, tmp_path: Path, expression
) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\ndef use(flag):\n"
        "    artifact = Path('artifacts/old.json')\n" + f"    {expression}\n"
        "    artifact.read_text()\n",
    )
    assert _orphaned(gate.analyse_consumer_side(tmp_path, [])) == {
        "artifacts/a.json",
        "artifacts/b.json",
    }


def test_unpacking_resolves_all_components_before_storing(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\ndef use():\n"
        "    first = Path('artifacts/first.json')\n    second = Path('artifacts/second.json')\n"
        "    first, second = second, first\n    first.read_text()\n    second.read_text()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert [(a.lineno, a.pattern) for a in accesses] == [
        (6, "artifacts/second.json"),
        (7, "artifacts/first.json"),
    ]
    assert unresolved == 0


def test_formatting_helper_argument_replaces_typed_default(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\ndef artifact_path(key=1):\n"
        "    return Path(f'artifacts/{key:02d}.json')\n"
        "artifact_path(2).write_text('{}')\nPath('artifacts/01.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "artifacts/01.json" in _orphaned(report)
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write"} == {"artifacts/02.json"}
    assert unresolved == 0


def test_lambda_comprehension_has_its_own_target_binding(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\nartifact = Path('artifacts/old.json')\n"
        "use = lambda items: [artifact.write_text('{}') for artifact in items]\n"
        "Path('artifacts/old.json').read_text()\n",
    )
    accesses, *_rest = gate.collect_artifact_accesses(tmp_path)
    # The lambda is never called, and inside it the target SHADOWS the module binding, so the
    # write is on an element of `items` and nothing writes old.json. The reader is genuinely
    # unproduced — the contrast with the function fixture above, where the write is on the line
    # AFTER the comprehension and therefore on the enclosing binding.
    assert not [a for a in accesses if a.action == "write"]
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "artifacts/old.json" in _orphaned(report)
    # Two sites, not one: the unresolvable iterable AND the write through the target. The second
    # only became visible when the comprehension body started being scanned, and this count was
    # never updated — it has been red since.
    assert report.unresolvable == 2
    assert len(report.unresolved_paths) == 2


def test_unmodelled_type_alias_invalidates_store(gate, tmp_path: Path) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\ndef use():\n"
        "    artifact = Path('artifacts/old.json')\n    type artifact = str\n"
        "    artifact.write_text('{}')\nPath('artifacts/old.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "artifacts/old.json" in _orphaned(report)
    assert report.unresolvable == 1


def test_dynamic_helper_pair_is_retained_as_unresolved_evidence(
    gate, tmp_path: Path, capsys
) -> None:
    _write(
        tmp_path,
        "from pathlib import Path\ndef artifact_path(key):\n"
        "    return Path(f'artifacts/widget-{key}.json')\n"
        "def use(key):\n    artifact = artifact_path(key)\n"
        "    artifact.write_text('{}')\n    artifact.read_text()\n"
        "Path('artifacts/widget-old.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert "artifacts/widget-old.json" in _orphaned(report, UNRESOLVED_WRITER)
    assert report.unresolvable == 2
    assert len(report.unresolved_paths) == 2
    payload = gate._report_json(report)
    assert len(payload["pairs"]) == 1
    assert payload["pairs"][0]["status"] == "unresolved"
    assert payload["pairs"][0]["writer"]["bounded"] is False
    gate.print_consumer_side_report(report, tmp_path / "report.json")
    assert (
        "status=unresolved; equal dynamic patterns, possible pairing only"
        in capsys.readouterr().out
    )


def test_round_ten_literal_setup_configure(gate, tmp_path):
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT=Path('artifacts/old.json')\n"
        "def configure():\n    global ARTIFACT\n"
        "    ARTIFACT=Path('artifacts/new.json')\n"
        "def setup():\n    configure()\n"
        "setup()\nARTIFACT.write_text('{}')\n"
        "Path('artifacts/old.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not [a for a in accesses if a.action == "write" and a.bounded]
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report, UNRESOLVED_WRITER) == {"artifacts/old.json"}
    assert report.unresolvable > 0


@pytest.mark.parametrize("factory_parameter", [False, True])
def test_round_ten_attribute_owner_never_borrows_namesake(gate, tmp_path, factory_parameter):
    # The literal dossier is already masked by unknown-call poisoning of Holder.
    # A constructor parameter keeps that independent effect from hiding the fallback.
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT=Path('artifacts/old.json')\n"
        "class Holder:\n    ARTIFACT=Path('artifacts/new.json')\n"
        + (
            "def run(factory):\n    ARTIFACT=Path('artifacts/old.json')\n"
            "    factory().ARTIFACT.write_text('{}')\nrun(Holder)\n"
            if factory_parameter
            else "Holder().ARTIFACT.write_text('{}')\n"
        )
        + "Path('artifacts/old.json').read_text()\n",
    )
    expression = ast.parse("Holder().ARTIFACT", mode="eval").body
    assert (
        gate._resolve_path_expr(
            expression, {"ARTIFACT": "artifacts/old.json"}, Path("shared/consumer.py"), tmp_path, {}
        )
        is None
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert "artifacts/old.json" not in {
        a.pattern for a in accesses if a.action == "write" and a.bounded
    }
    report = gate.analyse_consumer_side(tmp_path, [])
    # The namesake attribute is not borrowed, so no writer is LOCATED for this reader at all —
    # a genuine absence, not a withheld one. Measured for both parameters.
    assert _orphaned(report) == {"artifacts/old.json"}
    assert report.unresolvable > 0


def test_round_ten_literal_loop_composes_iterations(gate, tmp_path):
    _write(
        tmp_path,
        "from pathlib import Path\nartifact=Path('artifacts/start')\n"
        "for piece in ['a','b']:\n    artifact /= piece\n"
        "artifact.write_text('{}')\n"
        "Path('artifacts/start').read_text()\n"
        "Path('artifacts/start/a').read_text()\n"
        "Path('artifacts/start/b').read_text()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write" and a.bounded} == {
        "artifacts/start/a/b"
    }
    assert unresolved == 0
    assert _orphaned(gate.analyse_consumer_side(tmp_path, [])) == {
        "artifacts/start",
        "artifacts/start/a",
        "artifacts/start/b",
    }


def test_round_ten_loop_freezes_iterable_and_handles_empty(gate, tmp_path):
    _write(
        tmp_path,
        "from pathlib import Path\nartifact=Path('artifacts/start')\npiece='a'\n"
        "for suffix in (piece, piece):\n    artifact /= suffix\n    piece='b'\n"
        "for suffix in []:\n    artifact /= 'impossible'\n"
        "artifact.write_text('{}')\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write" and a.bounded} == {
        "artifacts/start/a/a"
    }
    assert unresolved == 0


@pytest.mark.parametrize("iterable", ["pieces", "['a'] * 100", "['a', 'b', 'c']"])
def test_round_ten_uncertain_loop_never_certifies_producers(gate, tmp_path, monkeypatch, iterable):
    monkeypatch.setattr(gate, "_MAX_BINDING_STATES", 2)
    _write(
        tmp_path,
        "from pathlib import Path\nartifact=Path('artifacts/start')\n"
        f"for piece in {iterable}:\n    artifact /= piece\n"
        "artifact.write_text('{}')\nPath('artifacts/start').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not [a for a in accesses if a.action == "write" and a.bounded]
    report = gate.analyse_consumer_side(tmp_path, [])
    # The three parameters do NOT share a causal state, and the report says so. A three-element
    # literal is enumerated exactly, so nothing writes `artifacts/start` and the absence is
    # decided; `['a'] * 100` and the unresolved name leave a located writer whose execution is
    # undetermined. Same expected reader, two different sentences about why it is orphaned.
    exact_literal = iterable == "['a', 'b', 'c']"
    assert "artifacts/start" in _orphaned(
        report, ABSENT_WRITER if exact_literal else UNRESOLVED_WRITER
    )
    assert report.unresolvable > 0
    if exact_literal:
        assert any("literal loop iteration cap" in site for site in report.capped_expressions)


@pytest.mark.parametrize(
    "expression",
    [
        "write_state(ARTIFACT, configure())",
        "ARTIFACT.write_text(configure())",
        "write_state(ARTIFACT, [0 for item in configure()])",
    ],
)
def test_round_ten_ordered_outer_effects_without_walrus(gate, tmp_path, expression):
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT=Path('artifacts/old.json')\n"
        "def configure():\n    global ARTIFACT\n"
        "    ARTIFACT=Path('artifacts/new.json')\n    return []\n"
        + (
            "def write_state(artifact, ignored):\n    artifact.write_text('{}')\n"
            if expression.startswith("write_state")
            else ""
        )
        + f"{expression}\nPath('artifacts/old.json').read_text()\n",
    )
    accesses, unresolved, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write" and a.bounded} == {
        "artifacts/old.json"
    }
    # The comprehension row now carries ONE named uncertainty, and the other two carry none.
    #
    # This clause used to read `unresolved == 0` for all three. That was accurate only while an
    # unresolved comprehension iterable silently permitted certification; three reviewer
    # families independently found that shape admitting phantom writers, and the repair is that
    # an iterable this scanner cannot evaluate withholds and RECORDS why. `configure()` returns
    # a list the constant channel does not carry, so this row's iterable is genuinely
    # unresolved and the scanner now says so instead of proceeding.
    #
    # **The subject of this round-ten control is unaffected**: the ordered outer effect still
    # binds the write to `old.json`, which is what the row exists to pin, and that assertion is
    # untouched above. Only the claim that the scanner had NO gap on this input changed, and it
    # changed because the claim was false.
    expected_unresolved = 1 if expression.startswith("write_state(ARTIFACT, [") else 0
    assert unresolved == expected_unresolved
    assert not _orphaned(gate.analyse_consumer_side(tmp_path, []))


def test_round_ten_comprehension_exports_outer_effects(gate, tmp_path):
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT=Path('artifacts/old.json')\n"
        "def configure():\n    global ARTIFACT\n"
        "    ARTIFACT=Path('artifacts/new.json')\n    return []\n"
        "[0 for item in configure()]\nARTIFACT.write_text('{}')\n"
        "Path('artifacts/old.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not [a for a in accesses if a.action == "write" and a.bounded]
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report, UNRESOLVED_WRITER) == {"artifacts/old.json"}
    assert report.unresolvable > 0


def test_round_ten_reduced_registry_instance(gate, tmp_path):
    # The real canary expects only the unwritten-artifact kind for this path.
    path = tmp_path / "shared" / "platform_capability_registry.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "from pathlib import Path\nimport json\n"
        "REGISTRY_PATH=Path('config/platform-capability-registry.json')\n"
        "def _load_json_object(path):\n"
        "    payload=json.loads(path.read_text(encoding='utf-8'))\n    return payload\n"
        "def load_registry():\n    return _load_json_object(REGISTRY_PATH)\n"
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    registry = [
        item
        for item in report.findings
        if item.reader.pattern == "config/platform-capability-registry.json"
    ]
    assert registry
    assert {item.kind for item in registry} == {"consumer-reads-unwritten-artifact"}


def test_round_ten_reduced_claim_dispatch_instance(gate, tmp_path):
    # Reduced from sdlc_claim._capture_claim_leases and the task-store writer:
    # captured() mentions snapshot, never its caller's binding_path local.
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "sdlc_task_store.py").write_text(
        "from pathlib import Path\nimport os\n"
        "CLAIM_DISPATCH_BINDING_SCHEMA='hapax.claim-dispatch-binding.v1'\n"
        "def claim_dispatch_binding_path(cache_dir: Path, claim_key: str) -> Path:\n"
        "    if not claim_key or '/' in claim_key or claim_key in {'.','..'}:\n"
        "        raise TaskStoreError('claim_dispatch_binding_key_invalid', claim_key)\n"
        "    return cache_dir / f'cc-claim-dispatch-{claim_key}.json'\n"
        "def write_claim_dispatch_binding(cache_dir: Path, claim_key: str, binding):\n"
        "    path=claim_dispatch_binding_path(cache_dir, claim_key)\n"
        "    path.parent.mkdir(parents=True, exist_ok=True)\n"
        "    payload=_canonical_json_bytes(binding.to_record())\n"
        "    temporary=path.parent / f'.{path.name}.{os.getpid()}.tmp'\n"
        "    os.replace(temporary, path)\n    return path\n"
    )
    (shared / "sdlc_claim.py").write_text(
        "from pathlib import Path\n"
        "from shared.sdlc_task_store import claim_dispatch_binding_path\n"
        "def capture_claim(cache: Path, role, snapshot):\n"
        "    def captured(name):\n        return snapshot.observe_file_at(name).captured\n"
        "    binding_path=claim_dispatch_binding_path(cache, role)\n"
        "    binding_file=captured(binding_path.name)\n"
        "    return load_claim_dispatch_binding(binding_path, content=binding_file.content)\n"
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    pairs = [item for item in report.pairs if item.family == "claim_dispatch_binding"]
    assert pairs
    assert all(item.reader.pattern == item.writer.pattern for item in pairs)
    assert any(item.reader.path == Path("shared/sdlc_claim.py") for item in pairs)
    assert any(item.writer.path == Path("shared/sdlc_task_store.py") for item in pairs)


def test_round_ten_unknown_transitive_capture_keeps_its_owner(gate, tmp_path):
    _write(
        tmp_path,
        "from pathlib import Path\n"
        "def run():\n    artifact=Path('artifacts/old.json')\n"
        "    stable=Path('artifacts/stable.json')\n"
        "    def captured():\n        callback(artifact)\n"
        "    def wrapper():\n        captured()\n"
        "    wrapper()\n    artifact.write_text('{}')\n    stable.write_text('{}')\n"
        "run()\nPath('artifacts/old.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert {a.pattern for a in accesses if a.action == "write" and a.bounded} == {
        "artifacts/stable.json"
    }
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report, UNRESOLVED_WRITER) == {"artifacts/old.json"}
    assert report.unresolvable > 0


@pytest.mark.parametrize("limit", ["depth", "summary"])
def test_round_ten_effect_caps_are_named_and_withhold_writers(gate, tmp_path, limit):
    count = (gate._MAX_BINDING_ROUNDS + 2) if limit == "depth" else (gate._MAX_BINDING_STATES + 1)
    definitions = (
        "def leaf():\n    global ARTIFACT\n    ARTIFACT=Path('artifacts/new.json')\n"
        + "".join(
            f"def step_{i}():\n    {f'step_{i - 1}' if i else 'leaf'}()\n" for i in range(count)
        )
        + f"step_{count - 1}()\n"
        if limit == "depth"
        else "".join(
            f"def step_{i}():\n    global ARTIFACT\n    ARTIFACT=Path('artifacts/new.json')\n"
            for i in range(count)
        )
        + "def setup():\n"
        + "".join(f"    step_{i}()\n" for i in range(count))
        + "setup()\n"
    )
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT=Path('artifacts/old.json')\n"
        + definitions
        + "ARTIFACT.write_text('{}')\nPath('artifacts/old.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not [a for a in accesses if a.action == "write" and a.bounded]
    report = gate.analyse_consumer_side(tmp_path, [])
    assert report.unresolvable > 0
    assert any(f"outer effect {limit} cap" in site for site in report.capped_expressions)
    assert _orphaned(report, UNRESOLVED_WRITER) == {"artifacts/old.json"}


def test_round_ten_effect_closure_linear_cost_and_local_cache(gate, monkeypatch):
    # Count construction work, not a timing ratio susceptible to scheduler noise.
    # The chain has shared fan-in at every level; closure must never unfold it per call.
    original_effects = gate._OuterEffects
    original_mutations = gate._scope_outer_mutations
    work = {"summaries": 0, "bodies": 0}

    def effects(*args, **kwargs):
        if args or kwargs:
            work["summaries"] += 1
        return original_effects(*args, **kwargs)

    def mutations(node):
        work["bodies"] += 1
        return original_mutations(node)

    monkeypatch.setattr(gate, "_OuterEffects", effects)
    monkeypatch.setattr(gate, "_scope_outer_mutations", mutations)
    measurements = []
    for count in (200, 400):
        table = gate.PathFunctionTable()
        nodes = ast.parse("".join(f"def step_{i}():\n    pass\n" for i in range(count))).body
        for i, node in enumerate(nodes):
            table.register(
                Path("shared/chain.py"),
                node.name,
                gate.PathFunction((), None, {}, Path("shared/chain.py"), False, (node.name,), node),
            )
            table.scope_results[node] = {}
            table.call_edges[node] = {nodes[i - 1], nodes[0]} if i else set()
        independent = ast.parse("def independent():\n    pass\n").body[0]
        marker = object()
        table.scope_results[independent] = {("cached",): marker}
        before = dict(work)
        started = time.monotonic()
        table.close_outer_effects()
        seconds = time.monotonic() - started
        measured = {key: work[key] - before[key] for key in work}
        assert measured == {"summaries": count, "bodies": count}, measured
        assert seconds < 1.0, seconds
        assert len(table.outer_effects) == count
        assert "depth cap" in table.outer_effects[nodes[-1]].unresolved
        assert table.scope_results[independent] == {("cached",): marker}
        # A second fixpoint reuses direct bodies; summaries are closed once per node again.
        table.close_outer_effects()
        assert work["bodies"] - before["bodies"] == count
        assert work["summaries"] - before["summaries"] == 2 * count
        measurements.append((count, measured, seconds))
    assert measurements[1][1]["summaries"] == 2 * measurements[0][1]["summaries"]
    print(f"outer closure scaling measurements: {measurements}")


def test_round_ten_unknown_loop_outer_effects_are_uncertain(gate, tmp_path):
    _write(
        tmp_path,
        "from pathlib import Path\nARTIFACT=Path('artifacts/old.json')\n"
        "def configure():\n    global ARTIFACT\n"
        "    ARTIFACT=Path('artifacts/new.json')\n"
        "for piece in pieces:\n    configure()\nARTIFACT.write_text('{}')\n"
        "Path('artifacts/old.json').read_text()\n",
    )
    accesses, *_ = gate.collect_artifact_accesses(tmp_path)
    assert not [a for a in accesses if a.action == "write" and a.bounded]
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report, UNRESOLVED_WRITER) == {"artifacts/old.json"}
    assert report.unresolvable > 0


@pytest.mark.parametrize("callee", ["len", "unknown_callback"])
def test_round_twelve_flat_module_binding_lookup_cost(gate, tmp_path, monkeypatch, callee):
    # shared/sdlc_claim.py and shared/coord_projection.py have large module-global
    # maps and flat validation/API call bodies. The real profile spent 122.8s
    # rebuilding aliases and 117.8s freezing operands, rather than in graph closure.
    # Count that work through the production scanner, independently of CPU scheduling.
    measured = {"lookups": 0, "enumerated": 0, "snapshots": 0, "invalidations": 0}
    original_aliases = gate._import_aliases
    original_freeze = gate._BlockScanner._freeze_expression
    original_invalidate = gate._invalidate_names

    class CountedBindings(dict):
        def items(self):
            measured["enumerated"] += len(self)
            return super().items()

        def __iter__(self):
            measured["enumerated"] += len(self)
            return super().__iter__()

        def __getitem__(self, key):
            measured["lookups"] += 1
            return super().__getitem__(key)

        def __contains__(self, key):
            measured["lookups"] += 1
            return super().__contains__(key)

        def get(self, key, default=None):
            measured["lookups"] += 1
            return super().get(key, default)

    def aliases(values):
        return original_aliases(CountedBindings(values))

    def freeze(scanner, node, states):
        measured["snapshots"] += len(states)
        return original_freeze(scanner, node, states)

    def invalidate(values, names):
        measured["invalidations"] += sum(name.startswith("CONSTANT_") for name in names)
        return original_invalidate(values, names)

    monkeypatch.setattr(gate, "_invalidate_names", invalidate)
    monkeypatch.setattr(gate, "_import_aliases", aliases)
    monkeypatch.setattr(gate._BlockScanner, "_freeze_expression", freeze)
    _write(
        tmp_path,
        "from pathlib import Path\n"
        + "".join(f"CONSTANT_{i} = 'metadata-{i}'\n" for i in range(64))
        + "".join(
            f"def validate_{i}(value):\n"
            + f"    {callee}(value)\n" * 20
            + f"    artifact = Path('artifacts/{i}.json')\n"
            "    artifact.read_text()\n"
            for i in range(24)
        ),
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report) == {f"artifacts/{i}.json" for i in range(24)}
    assert measured["enumerated"] == 0, measured
    assert measured["lookups"] > 1000
    assert measured["snapshots"] == 0, measured
    assert measured["invalidations"] <= 4 * 64 * 24, measured
    print(f"flat {callee} binding work: {measured}")


def test_round_twelve_real_claim_capture_survives_callee_cap(gate, tmp_path, monkeypatch):
    # Byte-exact function bodies from the real reader and writer modules, attributed below.
    # The real sdlc_close caller exhausts captured()'s 16 invocation states. A smaller
    # budget reaches the same cap/cache-eviction transition without the rest of that estate.
    # In particular preserve captured()'s observed-file cache, exception branch and the
    # role/session loop: the old reduction omitted all three and never capped captured().
    monkeypatch.setattr(gate, "_MAX_BINDING_STATES", 6)
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "sdlc_claim.py").write_text(
        r"""from pathlib import Path
import os
from shared.sdlc_task_store import claim_dispatch_binding_path, load_claim_dispatch_binding

# shared/sdlc_claim.py:154-155 at bc0a922c2
def _normalized(path: Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


# shared/sdlc_claim.py:4054-4210 at bc0a922c2
def _capture_claim_leases(
    snapshot: ReadOnlyFsSnapshot,
    cache_dir: Path,
    *,
    role: str,
    task_id: str,
    session_id: str | None,
) -> tuple[ClaimLeaseSnapshot, ...]:
    if not role.strip() or role == "unknown":
        raise ClaimPublicationError(
            "claim_identity_missing",
            "bind one real lane identity before lifecycle mutation",
        )
    cache = _normalized(cache_dir)
    try:
        claim_dispatch_binding_path(cache, role)
    except TaskStoreError as exc:
        raise ClaimPublicationError(exc.reason_code, exc.repair_action, exc.detail) from exc
    directory = snapshot.pin_absolute_dir(cache, private_final=False)
    assert directory is not None
    observations: dict[str, CapturedFile | None] = {}

    def captured(name: str, *, reason_code: str) -> CapturedFile:
        if name not in observations:
            observations[name] = snapshot.observe_file_at(
                directory,
                name,
                private=False,
                max_bytes=_CLAIM_SNAPSHOT_MAX_SIDECAR_BYTES,
            ).captured
        value = observations[name]
        if value is None:
            raise ClaimPublicationError(
                reason_code,
                "restore the exact regular claim, epoch, and dispatch-binding sidecars",
                str(cache / name),
            )
        return value

    role_binding_path = claim_dispatch_binding_path(cache, role)
    role_binding_file = captured(
        role_binding_path.name,
        reason_code="claim_dispatch_binding_missing",
    )
    try:
        role_binding = load_claim_dispatch_binding(
            role_binding_path,
            content=role_binding_file.content,
        )
    except TaskStoreError as exc:
        raise ClaimPublicationError(exc.reason_code, exc.repair_action, exc.detail) from exc
    resolved_session = role_binding.session_id if session_id is None else session_id
    if (
        _CLAIM_SESSION_FRAGMENT_RE.fullmatch(resolved_session) is None
        or resolved_session.isdecimal()
        or "/" in resolved_session
    ):
        raise ClaimPublicationError(
            "claim_session_identity_invalid",
            "bind one non-PID claim-keyable harness session before lifecycle mutation",
            resolved_session,
        )
    if session_id is None and (
        role_binding.task_id != task_id
        or role_binding.lane != role
        or not role_binding.session_id.strip()
    ):
        raise ClaimPublicationError(
            "claim_role_binding_mismatch",
            "restore the role binding for this exact task, lane, and claim session",
            role,
        )

    leases: list[ClaimLeaseSnapshot] = []
    for key in (role, f"{role}-{resolved_session}"):
        claim_path = cache / f"cc-active-task-{key}"
        epoch_path = cache / f"cc-claim-epoch-{key}"
        binding_path = claim_dispatch_binding_path(cache, key)
        claim_file = captured(claim_path.name, reason_code="claim_cache_missing")
        epoch_file = captured(epoch_path.name, reason_code="claim_epoch_missing")
        binding_file = captured(
            binding_path.name,
            reason_code="claim_dispatch_binding_missing",
        )
        try:
            claim_task = claim_file.content.decode("utf-8").strip()
        except UnicodeError as exc:
            raise ClaimPublicationError(
                "claim_cache_missing",
                "restore the exact regular claim, epoch, and dispatch-binding sidecars",
                str(claim_path),
            ) from exc
        if claim_task != task_id:
            raise ClaimPublicationError(
                "claim_task_mismatch",
                "bind every current claim cache to the exact task",
                str(claim_path),
            )
        try:
            epoch_text, epoch_task = epoch_file.content.decode("utf-8").split()
            epoch = int(epoch_text)
        except (UnicodeError, ValueError) as exc:
            raise ClaimPublicationError(
                "claim_epoch_malformed",
                "restore the '<epoch> <task_id>' claim epoch sidecar",
                str(epoch_path),
            ) from exc
        try:
            binding = load_claim_dispatch_binding(binding_path, content=binding_file.content)
        except TaskStoreError as exc:
            raise ClaimPublicationError(exc.reason_code, exc.repair_action, exc.detail) from exc
        if (
            epoch <= 0
            or epoch_task != task_id
            or binding.claim_epoch != epoch
            or binding.task_id != task_id
            or binding.lane != role
            or binding.session_id != resolved_session
        ):
            raise ClaimPublicationError(
                "claim_binding_vector_mismatch",
                "reclaim through the exact governed dispatch so all claim sidecars agree",
                key,
            )
        leases.append(
            ClaimLeaseSnapshot(
                claim_key=key,
                claim_path=claim_path,
                claim_content=claim_file.content,
                claim_mode=stat.S_IMODE(claim_file.stamp.mode),
                epoch_path=epoch_path,
                epoch_content=epoch_file.content,
                epoch_mode=stat.S_IMODE(epoch_file.stamp.mode),
                binding_path=binding_path,
                binding_content=binding_file.content,
                binding_mode=stat.S_IMODE(binding_file.stamp.mode),
                binding=binding,
            )
        )
    if any(item.binding != leases[0].binding for item in leases[1:]):
        raise ClaimPublicationError(
            "claim_binding_sidecars_conflict",
            "restore identical role and session claim dispatch bindings",
            role,
        )
    if session_id is None and (
        leases[0].binding_path != role_binding_path
        or leases[0].binding_content != role_binding_file.content
        or leases[0].binding_mode != stat.S_IMODE(role_binding_file.stamp.mode)
        or leases[0].binding != role_binding
    ):
        raise ClaimPublicationError(
            "claim_role_binding_changed_during_resolution",
            "retry after the exact role binding stabilizes",
            role,
        )
    return tuple(leases)
"""
    )
    (shared / "sdlc_task_store.py").write_text(
        r"""from pathlib import Path
import os

# shared/sdlc_task_store.py:177-184 at bc0a922c2
def claim_dispatch_binding_path(cache_dir: Path, claim_key: str) -> Path:
    if not claim_key or "/" in claim_key or claim_key in {".", ".."}:
        raise TaskStoreError(
            "claim_dispatch_binding_key_invalid",
            "use the exact role or role-session claim key",
            claim_key,
        )
    return cache_dir / f"cc-claim-dispatch-{claim_key}.json"


# shared/sdlc_task_store.py:187-209 at bc0a922c2
def write_claim_dispatch_binding(
    cache_dir: Path, claim_key: str, binding: ClaimDispatchBinding
) -> Path:
    path = claim_dispatch_binding_path(cache_dir, claim_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_json_bytes(binding.to_record()) + b"\n"
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


# shared/sdlc_task_store.py:212-314 at bc0a922c2
def load_claim_dispatch_binding(
    path: Path,
    *,
    content: bytes | None = None,
) -> ClaimDispatchBinding:
    def unique_pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        output: dict[str, object] = {}
        for key, value in values:
            if key in output:
                raise TaskStoreError(
                    "claim_dispatch_binding_duplicate_key",
                    "remove duplicate JSON keys from the claim binding",
                    key,
                )
            output[key] = value
        return output

    try:
        payload = (
            content
            if content is not None
            else _regular_file_bytes(
                path,
                reason_code="claim_dispatch_binding_unreadable",
            )[0]
        )
        record = json.loads(payload.decode("ascii"), object_pairs_hook=unique_pairs)
    except TaskStoreError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TaskStoreError(
            "claim_dispatch_binding_unreadable",
            "restore the exact self-hashed claim binding sidecar",
            str(path),
        ) from exc
    exact_keys = {
        "authority_case",
        "binding_hash",
        "claim_epoch",
        "coord_dispatch_idempotency_key",
        "dispatch_message_id",
        "lane",
        "may_authorize",
        "mode",
        "platform",
        "profile",
        "receipt_hash",
        "schema",
        "session_id",
        "task_id",
    }
    if (
        not isinstance(record, dict)
        or set(record) != exact_keys
        or record.get("schema") != CLAIM_DISPATCH_BINDING_SCHEMA
        or record.get("may_authorize") is not False
        or type(record.get("claim_epoch")) is not int
        or any(
            not isinstance(record.get(key), str)
            for key in {
                "authority_case",
                "binding_hash",
                "dispatch_message_id",
                "lane",
                "mode",
                "platform",
                "profile",
                "receipt_hash",
                "session_id",
                "task_id",
            }
        )
        or (
            record.get("coord_dispatch_idempotency_key") is not None
            and not isinstance(record.get("coord_dispatch_idempotency_key"), str)
        )
        or payload != _canonical_json_bytes(record) + b"\n"
    ):
        raise TaskStoreError(
            "claim_dispatch_binding_malformed",
            "restore the exact non-authorizing claim binding schema",
            str(path),
        )
    binding = ClaimDispatchBinding.create(
        task_id=record["task_id"],
        lane=record["lane"],
        session_id=record["session_id"],
        claim_epoch=record["claim_epoch"],
        dispatch_message_id=record["dispatch_message_id"],
        platform=record["platform"],
        mode=record["mode"],
        profile=record["profile"],
        authority_case=record["authority_case"],
        binding_hash=record["binding_hash"],
        coord_dispatch_idempotency_key=record["coord_dispatch_idempotency_key"],
    )
    if record.get("receipt_hash") != binding.receipt_hash:
        raise TaskStoreError(
            "claim_dispatch_binding_receipt_hash_mismatch",
            "restore the exact self-hashed claim binding sidecar",
            str(path),
        )
    return binding
"""
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    pairs = [item for item in report.pairs if item.family == "claim_dispatch_binding"]
    assert pairs
    assert all(
        item.reader.pattern == item.writer.pattern == "*/cc-claim-dispatch-*.json" for item in pairs
    )
    assert any(item.reader.path == Path("shared/sdlc_claim.py") for item in pairs)
    assert any(item.writer.path == Path("shared/sdlc_task_store.py") for item in pairs)
    assert all(not item.reader.bounded and not item.writer.bounded for item in pairs)
    assert report.unresolvable > 0
    assert any(
        "_capture_claim_leases.captured" in site and "binding state cap" in site
        for site in report.capped_expressions
    )


def test_round_twelve_captured_api_name_is_not_an_effect_cap(gate, tmp_path):
    # The real profile reported 'unresolved call target captured.append' as a cap.
    # A diagnostic string containing 'cap' cannot erase an unrelated caller local.
    _write(
        tmp_path,
        "from pathlib import Path\n"
        "def run():\n"
        "    artifact = Path('artifacts/valid.json')\n"
        "    def inspect():\n"
        "        captured = []\n"
        "        captured.append(1)\n"
        "    inspect()\n"
        "    artifact.write_text('{}')\n"
        "run()\nPath('artifacts/valid.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert not report.capped_expressions
    assert not _orphaned(report)


@pytest.mark.parametrize("width", [32, 256])
def test_round_twelve_wide_conditional_payload_copy_bound(gate, tmp_path, monkeypatch, width):
    # The shared-package profile spent 50s deep-copying conditional payloads. Real
    # validation calls pass wide records beside a conditional argument; only
    # the changed expression's ancestors need copying, regardless of record width.
    # Examples: shared/sdlc_claim.py:3562 (267 AST nodes) and
    # shared/content_programme_run_store.py:1032 (621 AST nodes), at bc0a922c2.
    copied = [0]
    original_copy, original_deepcopy = gate.copy.copy, gate.copy.deepcopy

    def shallow(node):
        if isinstance(node, ast.AST):
            copied[0] += 1
        return original_copy(node)

    def deep(node, *args, **kwargs):
        if isinstance(node, ast.AST):
            copied[0] += sum(1 for _ in ast.walk(node))
        return original_deepcopy(node, *args, **kwargs)

    monkeypatch.setattr(gate.copy, "copy", shallow)
    monkeypatch.setattr(gate.copy, "deepcopy", deep)
    _write(
        tmp_path,
        "from pathlib import Path\n"
        "def inspect(flag):\n"
        "    payload = assemble('first' if flag else 'second', {\n"
        + "".join(f"        'metadata_{i}': [{i}, 'schema-field'],\n" for i in range(width))
        + "    })\n"
        "    Path('artifacts/first.json' if flag else 'artifacts/second.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report) == {"artifacts/first.json", "artifacts/second.json"}
    assert 0 < copied[0] <= 64, copied
    print(f"wide payload {width}: copied {copied[0]} AST nodes")


def test_round_twelve_unbounded_helper_keeps_uncertainty_without_snapshots(
    gate, tmp_path, monkeypatch
):
    # Real validation helpers encounter an opaque API before nested formatting calls.
    # Their return summary is then unresolved, while the ordinary scope walker must
    # still report the helper body's independent reads and the caller's unwritten file.
    snapshots = [0]
    original = gate._BlockScanner._freeze_expression

    def freeze(scanner, node, states):
        if isinstance(scanner, gate._PathHelperScanner):
            snapshots[0] += sum(gate._HELPER_EFFECT_KEY in state for state in states)
        return original(scanner, node, states)

    monkeypatch.setattr(gate._BlockScanner, "_freeze_expression", freeze)
    _write(
        tmp_path,
        "from pathlib import Path\n"
        "def normalize(path: Path) -> Path:\n"
        "    opaque_api()\n"
        "    Path('artifacts/inside.json').read_text()\n"
        + "    validate(str(path), encode(path))\n"
        * 20
        + "    return path\n"
        "normalize(Path('artifacts/outside.json')).write_text('{}')\n"
        "Path('artifacts/outside.json').read_text()\n",
    )
    report = gate.analyse_consumer_side(tmp_path, [])
    assert _orphaned(report) == {"artifacts/inside.json", "artifacts/outside.json"}
    assert report.unresolvable > 0
    assert snapshots[0] == 0
