"""Malformed pattern containers must refuse through governed dispatch main()."""

import json
import os
import shutil
import subprocess
import sys

import pytest
import yaml

from shared import frame_verdicts as fv
from tests.frame_verdict_helpers import PRODUCER_BUILTIN_PATH
from tests.scripts.test_hapax_methodology_dispatch import (
    _dispatch_receipt_only_scope,
    _frame_procedure_root,
)


def _pattern_dispatch(
    tmp_path,
    monkeypatch,
    capsys,
    reader,
    location_update,
    *,
    unrelated=False,
    reader_id=None,
    member_update=None,
):
    root = tmp_path / "member"
    root.mkdir()
    candidate = root / "candidate.txt"
    candidate.write_text("NEEDLE\n")
    location = (
        {"roots": [str(root)], "query": "NEEDLE"}
        if reader == "fs.content_query"
        else {"path": str(root)}
    )
    location.update(location_update)
    frame = _frame_procedure_root(
        tmp_path / "frame",
        decayed_root=root,
        reader=reader,
        location=location,
        query_params=reader == "fs.content_query",
    )
    if unrelated:
        # This member is non-decayed and unused for containment. Do not require
        # admission despite a malformed governing member.
        mass_path = frame / "declaration/mass.yaml"
        mass = yaml.safe_load(mass_path.read_text())
        mass["members"][1]["location"]["patterns"] = {"glob": "*"}
        mass_path.write_text(yaml.safe_dump(mass))
        coverage = frame / "_runs/current/coverage.json"
        rows = json.loads(coverage.read_text())
        rows[1]["member_declaration_identity"] = fv._member_declaration_identity(
            mass["members"][1], mass["exclusions"]
        )
        coverage.write_text(json.dumps(rows))
    if member_update is not None:
        mass_path = frame / "declaration/mass.yaml"
        mass = yaml.safe_load(mass_path.read_text())
        mass["members"][0].update(member_update)
        mass_path.write_text(yaml.safe_dump(mass, allow_unicode=True))
        coverage = frame / "_runs/current/coverage.json"
        rows = json.loads(coverage.read_text())
        # Deliberately NOT restating the declaration identity here: the point of these rows is
        # that computing it is what fails, so a fixture that computed it first could not exist.
        coverage.write_text(json.dumps(rows))
    if reader_id is not None:
        # Rewrite the DECAYED member's reader id after the frame is built, then restate its
        # declaration identity so the coverage row still matches — otherwise the dispatch refuses
        # on the identity mismatch and never reaches the reader vocabulary at all.
        mass_path = frame / "declaration/mass.yaml"
        mass = yaml.safe_load(mass_path.read_text())
        mass["members"][0]["reader"] = {"id": reader_id}
        mass_path.write_text(yaml.safe_dump(mass))
        coverage = frame / "_runs/current/coverage.json"
        rows = json.loads(coverage.read_text())
        rows[0]["member_declaration_identity"] = fv._member_declaration_identity(
            mass["members"][0], mass["exclusions"]
        )
        coverage.write_text(json.dumps(rows))
    rc, err = _dispatch_receipt_only_scope(tmp_path, monkeypatch, capsys, frame, candidate)
    return rc, err, root, candidate


@pytest.mark.parametrize("reader", ["fs.content_query", "fs.glob"])
@pytest.mark.parametrize("patterns", ["*", {"glob": "*"}, 3], ids=["scalar", "mapping", "integer"])
def test_main_refuses_malformed_pattern_container(tmp_path, monkeypatch, capsys, reader, patterns):
    rc, err, _, _ = _pattern_dispatch(tmp_path, monkeypatch, capsys, reader, {"patterns": patterns})
    assert rc == 10, "a malformed container must not establish an empty selection"
    assert "legacy-surface" in err
    assert "location.patterns has malformed container" in err, (
        "This pins the strict container contract: wrapping '*' as ['*'] happens to agree "
        "with producer character iteration, but must still refuse the malformed declaration."
    )
    assert type(patterns).__name__ in err
    assert repr(patterns) in err
    assert "expected a list of patterns or absence" in err
    assert "use a list such as ['*'], or omit patterns" in err


@pytest.mark.parametrize("reader", ["fs.content_query", "fs.glob"])
@pytest.mark.parametrize(
    ("location", "query_rc"),
    [({}, 10), ({"patterns": None}, 10), ({"patterns": []}, 0), ({"patterns": ["*"]}, 10)],
    ids=["absent", "null-absence", "empty-list", "list"],
)
def test_main_pattern_absence_and_lists_unchanged(
    tmp_path, monkeypatch, capsys, reader, location, query_rc
):
    rc, err, _, _ = _pattern_dispatch(tmp_path, monkeypatch, capsys, reader, location)
    assert rc == (query_rc if reader == "fs.content_query" else 10)
    assert "malformed container" not in err
    if rc == 10:
        assert "legacy-surface (scope_exited)" in err


def test_main_refuses_a_surrogate_declaration_with_a_receipt(tmp_path, monkeypatch, capsys):
    """The escape end to end, through the governed dispatcher rather than the helper.

    A lone surrogate survives YAML and `json.dumps(ensure_ascii=False)` and fails at the digest.
    Before the boundary was corrected, `UnicodeEncodeError` escaped the typed handler and dispatch
    ended with no next action and no refusal receipt.

    The receipt assertion is the half a unit test cannot make: the refusal has to be *written*, and
    a message that interpolated the surrogate raw would fail at exactly that step — reproducing the
    reported failure at the moment of reporting it.
    """
    rc, err, _root, _candidate = _pattern_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        "fs.glob",
        {"patterns": ["*"]},
        member_update={"declared": yaml.safe_load('"\\udcff"')},
    )
    assert rc == 10
    assert "cannot be canonicalised" in err
    assert "not encodable as UTF-8" in err
    assert "replace the character that is not encodable as UTF-8" in err
    err.encode("utf-8")


@pytest.mark.parametrize(
    ("name", "reader_id"),
    [
        ("list", ["fs.glob"]),
        ("mapping", {"id": "fs.glob"}),
        ("integer", 7),
    ],
    ids=["list", "mapping", "integer"],
)
def test_main_refuses_a_non_string_reader_id_with_a_receipt(
    tmp_path, monkeypatch, capsys, name, reader_id
):
    """`reader.id` reached a set-membership test carrying whatever YAML held.

    A list or a mapping is unhashable, so `reader_id not in {…}` raised `TypeError` before any
    refusal could be built — escaping both the loader's handler and `frame_verdict_refusal`, so
    dispatch terminated with no next action and no refusal receipt (review finding, codex).

    The integer is the row that would not have been written from the finding alone: it is
    hashable, so it never crashed — it reached the membership test and was reported as an
    *unimplemented containment reader 7*, sending the operator to implement containment for a
    number rather than to fix a malformed declaration. Same defect, quieter symptom.
    """
    rc, err, _root, _candidate = _pattern_dispatch(
        tmp_path, monkeypatch, capsys, "fs.glob", {"patterns": ["*"]}, reader_id=reader_id
    )
    assert rc == 10, "a malformed reader id must refuse, not escape"
    assert "non-string reader id" in err
    assert repr(reader_id) in err and type(reader_id).__name__ in err
    assert "declare reader.id as a string" in err
    # The refusal must be the DECLARATION one, not the vocabulary one: telling the operator the
    # reader is unimplemented sends them to implement it.
    assert "unimplemented containment reader" not in err


@pytest.mark.parametrize("reader", ["fs.content_query", "fs.glob"])
@pytest.mark.parametrize(
    "patterns",
    [[None], [7], [{"glob": "*"}], ["*", None], [["*"]]],
    ids=["null", "integer", "mapping", "trailing-null", "nested-list"],
)
def test_main_refuses_a_malformed_pattern_ENTRY_not_only_the_container(
    tmp_path, monkeypatch, capsys, reader, patterns
):
    """The container was checked and its entries were not.

    `str(item)` accepts anything, so a list holding `None`, an integer or a mapping produced a
    selector spelled from `repr` while the installed producer raises on the original entry. The
    consumer then has not established a comparable surface — it has established a different one.
    Reported as a critical by codex at `842ca5937`.

    Sibling contrast, twenty lines below the defect: `location.files` entries ARE type-checked
    before use. The same question was asked at one of the two sites.
    """
    rc, err, _, _ = _pattern_dispatch(tmp_path, monkeypatch, capsys, reader, {"patterns": patterns})
    assert rc == 10, "a pattern entry the producer cannot iterate must not select anything"
    assert "location.patterns has malformed entry" in err
    # The member and the EXACT index, because a list with one bad entry is not repairable from a
    # message naming only the member. Asserting `"index" in err` was the first spelling of this
    # and it passes against an always-zero index — a root oracle caught that where these native
    # rows could not, so the row now names the position it measured.
    position = next(i for i, item in enumerate(patterns) if not isinstance(item, str))
    assert f"index {position}" in err
    bad = patterns[position]
    assert type(bad).__name__ in err
    assert repr(bad) in err


@pytest.mark.parametrize("reader", ["fs.content_query", "fs.glob"])
def test_main_malformed_non_decayed_unrelated_member_unchanged(
    tmp_path, monkeypatch, capsys, reader
):
    rc, err, _, _ = _pattern_dispatch(
        tmp_path, monkeypatch, capsys, reader, {"patterns": ["*.py"]}, unrelated=True
    )
    assert rc == 0
    assert "malformed container" not in err


def test_main_scalar_star_producer_parity(tmp_path, monkeypatch, capsys):
    rc, err, root, candidate = _pattern_dispatch(
        tmp_path, monkeypatch, capsys, "fs.content_query", {"patterns": "*"}
    )
    assert rc == 10, "reviewer's exact scalar '*' scope_exited=TRUE case must refuse"
    assert "location.patterns has malformed container" in err, (
        "This pins the strict container contract: coercing '*' into ['*'] coincides with "
        "the producer's one-character iteration but is not the required declaration refusal."
    )
    # Execute only the installed reader on synthetic files with a read-only host
    # and no network. Absence of this environment is explicitly an unexecuted oracle.
    if not PRODUCER_BUILTIN_PATH.is_file():
        pytest.skip(f"FRAME_PRODUCER_ABSENT:{PRODUCER_BUILTIN_PATH}; parity not executed")
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        pytest.skip("bwrap unavailable; isolated producer parity not executed")
    isolation = [
        bwrap,
        "--ro-bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--unshare-net",
        "--die-with-parent",
    ]
    probe = subprocess.run([*isolation, "/usr/bin/true"], capture_output=True, text=True)
    if probe.returncode:
        pytest.skip(f"isolated producer parity not executed: {probe.stderr.strip()}")
    code = """
import sys
from pathlib import Path
import pytest
from tests.frame_verdict_helpers import producer_glob_bytes
root, candidate = map(Path, sys.argv[1:])
with pytest.MonkeyPatch.context() as mp:
    for patterns in ('*', ['*']):
        selected = producer_glob_bytes(root, patterns, mp, content_query='NEEDLE')
        assert selected == {candidate: b'NEEDLE\\n'}, (patterns, selected)
print('installed fs.content_query selects candidate for both star spellings')
"""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(
        [*isolation, sys.executable, "-c", code, str(root), str(candidate)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == (
        "installed fs.content_query selects candidate for both star spellings"
    )
