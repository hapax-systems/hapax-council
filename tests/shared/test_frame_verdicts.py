"""shared/frame_verdicts.py — the frame's verdicts read at a work-selection point."""

from __future__ import annotations

import ast
import errno
import fnmatch
import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from shared import frame_verdicts as fv
from tests import frame_verdict_helpers as frame_helpers
from tests.frame_verdict_helpers import git_checkout, latest_epoch_dir


@pytest.mark.parametrize("required", [None, "0", "1"])
@pytest.mark.parametrize("engine", ["python", "rg"])
def test_producer_absence_is_checked_at_each_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, required: str | None, engine: str
) -> None:
    missing = tmp_path / "absent/frame/procedure/builtin.py"
    monkeypatch.setattr(frame_helpers, "PRODUCER_BUILTIN_PATH", missing)
    if required is None:
        monkeypatch.delenv("HAPAX_FRAME_ORACLE_REQUIRED", raising=False)
    else:
        monkeypatch.setenv("HAPAX_FRAME_ORACLE_REQUIRED", required)
    expected = pytest.fail.Exception if required == "1" else pytest.skip.Exception
    for _ in range(2):
        with pytest.raises(expected) as caught:
            frame_helpers.producer_glob_bytes(
                tmp_path, ["*.py"], monkeypatch, content_query="query", query_engine=engine
            )
        assert str(caught.value) == f"FRAME_PRODUCER_ABSENT:{missing}"


@pytest.mark.parametrize("case_insensitive", [False, True])
def test_direct_rg_oracle_never_skips_missing_rg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case_insensitive: bool
) -> None:
    monkeypatch.setattr(frame_helpers.shutil, "which", lambda name: None)
    with pytest.raises(
        pytest.fail.Exception, match="frame content-query rg oracle requires the rg executable"
    ):
        frame_helpers.rg_query_bytes(tmp_path, "query", case_insensitive=case_insensitive)


NOW = datetime(2026, 9, 3, 22, 30, tzinfo=UTC)


def _expected_producer_remedy(root: Path) -> str:
    return (
        f"run the frame producer — verify it targets procedure root {root}, "
        "then `systemctl --user start hapax-frame-iteration.service` — then retry the dispatch"
    )


def _expected_stale_remedy(root: Path) -> str:
    return (
        f"read {root / '_runs/current'}, then the newest retained epoch's publish.json "
        f"under {root / '_runs/epochs'} (swapped and reason fields), then inspect producer "
        "state with `systemctl --user status hapax-frame-iteration.service` before any "
        "restart; distinguish an unadvanced accepted pointer from refused publication, "
        "then retry the dispatch"
    )


def test_producer_remedy_template_requires_named_root_placeholder() -> None:
    assert "{procedure_root}" in fv.PRODUCER_REMEDY_TEMPLATE


def test_the_rootless_producer_remedy_does_not_pretend_to_name_a_path() -> None:
    """The constant is used where no procedure root has been resolved yet.

    It was formatted with the env-var NAME, so nineteen refusals said "verify it targets procedure
    root HAPAX_FRAME_PROCEDURE_ROOT" — a next action whose subject reads as a path and is a
    variable name (review finding, glm). A message written before the read can honestly say which
    variable to consult and what it defaults to, and no more than that.
    """
    remedy = fv.PRODUCER_REMEDY
    # A bare env-var name would be indistinguishable from a path; the sigil is what makes it a
    # reference, and the default is what makes it actionable without one.
    assert f"${fv.FRAME_PROCEDURE_ROOT_ENV}" in remedy
    assert str(fv.DEFAULT_FRAME_PROCEDURE_ROOT) in remedy
    assert f"root {fv.FRAME_PROCEDURE_ROOT_ENV}" not in remedy

    # The call-time twin still binds a real path and says nothing about variables, because there
    # the subject IS known.
    resolved = fv._producer_remedy(Path("/srv/frame/procedure"))  # noqa: SLF001
    assert "procedure root /srv/frame/procedure" in resolved
    assert fv.FRAME_PROCEDURE_ROOT_ENV not in resolved


def test_producer_remedy_renders_resolved_root(tmp_path: Path) -> None:
    root = tmp_path / "actual-procedure"
    alias = tmp_path / "procedure-alias"
    alias.symlink_to(root, target_is_directory=True)

    with pytest.raises(fv.FrameVerdictsUnavailable) as caught:
        fv.load_frame_verdicts(alias, now=NOW)

    remedy = caught.value.remedy
    assert str(root.resolve()) in remedy
    assert str(alias) not in remedy
    assert fv.FRAME_PROCEDURE_ROOT_ENV not in remedy
    assert "{procedure_root}" not in remedy


@pytest.mark.parametrize(
    ("left", "right"),
    [("a.py", "b.py"), ("a*.py", "b*.py"), ("a*.py", "a*.md")],
    ids=["literal-mismatch", "incompatible-prefixes", "incompatible-suffixes"],
)
def test_glob_disjoint_established_returns_true(left: str, right: str) -> None:
    assert fv._glob_disjoint(left, right) is True
    assert fv._glob_disjoint(right, left) is True


@pytest.mark.parametrize(
    ("left", "right"),
    [("a.py", "a.py"), ("a.py", "*.py"), ("a.py", "**/*.py")],
    ids=["identical-literals", "literal-in-wildcard", "globstar-zero-segments"],
)
def test_glob_disjoint_literal_overlap_returns_none(left: str, right: str) -> None:
    assert fv._glob_disjoint(left, right) is None
    assert fv._glob_disjoint(right, left) is None


def test_glob_disjoint_overlapping_wildcards_remain_unknown() -> None:
    left, right = "a*b*c", "a*c*b*c"
    # Both fixed prefixes are 'a' and both suffixes are 'c'. The heuristic does not
    # compare the intervening wildcard languages; it must keep their intersection
    # unknown. This concrete shared member proves that returning True is unsound.
    witness = "acbc"
    assert fnmatch.fnmatchcase(witness, left)
    assert fnmatch.fnmatchcase(witness, right)
    assert fv._glob_disjoint(left, right) is None
    assert fv._glob_disjoint(right, left) is None


@pytest.mark.parametrize(
    "patterns",
    [["*"], ["*.md"], ["file[12].md"], ["session/*.md"], [], ["**"], ["file**.md"], ["."]],
)
def test_ssh_glob_matches_producer_find_name_oracle(tmp_path: Path, patterns: list[str]) -> None:
    """builtin.py:ssh_glob uses find . -type f ( -name PATTERN -o ... ), recursively.

    Execute that selection locally, without SSH, caps or byte transport. Unlike fs_glob,
    ssh_glob never reads skip_dirs or calls ctx.is_excluded: even the declared excluded
    directory remains selected. These nonempty tiny files are below all producer bounds.
    """
    mirror = tmp_path / "remote"
    names = ["file1.md", "session/file2.md", "excluded/file1.md", "session/code.py", ".hidden.md"]
    for name in names:
        file = mirror / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("content")
    expression = []
    for pattern in patterns or ["*"]:
        if expression:
            expression.append("-o")
        expression.extend(["-name", pattern])
    selected = subprocess.run(
        ["find", ".", "-type", "f", "(", *expression, ")", "-print"],
        cwd=mirror,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.splitlines()
    selected = {name.removeprefix("./") for name in selected}
    location = "podium:.local/share/opencode"
    verdicts = fv.load_frame_verdicts(
        _procedure_root(
            tmp_path / "procedure",
            members=[
                {
                    "id": "remote",
                    "reader": {"id": "ssh.glob", "version": "^1.0.0"},
                    "location": {
                        "path": location,
                        "patterns": patterns,
                        "skip_dirs": ["excluded"],
                    },
                }
            ],
            verdicts=[_verdict("remote", "scope_exited")],
            exclusions=[{"id": "excluded", "paths": [str(mirror / "excluded")]}],
        ),
        now=NOW,
    )
    for name in names:
        ref = f"{location}/{name}"
        if name in selected:
            result = fv.scope_within_decayed(
                [ref], verdicts, council_root=tmp_path, vault_root=tmp_path
            )
            assert result.all_inside, (patterns, name, selected, result)
        else:
            # Round 30: find's lexical miss cannot exclude remote path aliases.
            with pytest.raises(
                fv.UndecidableScopeContainment, match="scope_containment_undecidable"
            ):
                fv.scope_within_decayed([ref], verdicts, council_root=tmp_path, vault_root=tmp_path)


def test_ssh_glob_unsupported_filename_syntax_is_undecidable(tmp_path: Path) -> None:
    # find matches a slash inside this negated class; treating every slash as a path
    # separator would incorrectly admit this file as outside the decayed surface.
    (tmp_path / "file.md").write_text("content")
    pattern = "*[!/]md"
    assert (
        subprocess.run(
            ["find", ".", "-type", "f", "-name", pattern],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        == "./file.md\n"
    )
    member = fv.DecayedMember(
        "remote",
        "scope_exited",
        (),
        (pattern,),
        (),
        qualified_roots=(fv._qualified_location("podium:store")[0],),
        reader="ssh.glob",
    )
    with pytest.raises(
        fv.UncontainableMemberLocation, match="ssh.glob filename pattern.*undecidable"
    ):
        fv.qualified_ref_within_member(
            fv._qualified_location("podium:store/file.md")[0], False, member
        )


def _stamp(at: datetime) -> str:
    return at.strftime("%Y%m%dT%H%M%SZ")


def _procedure_root(
    root: Path,
    *,
    members: list[dict[str, object]],
    verdicts: list[dict[str, object]],
    exclusions: list[dict[str, object]] | None = None,
    at: datetime = NOW,
    epoch_suffix: str = "d693f20c",
    make_current: bool = True,
    swapped: bool = True,
) -> Path:
    declared_exclusions = exclusions or []
    epoch = root / "_runs" / "epochs" / f"{_stamp(at)}-{epoch_suffix}"
    epoch.mkdir(parents=True, exist_ok=True)
    complete_verdicts = list(verdicts)
    present = {
        (subject.get("member_id"), row.get("relation"))
        for row in verdicts
        if isinstance(row, dict)
        and isinstance((subject := row.get("subject")), dict)
        and isinstance(subject.get("member_id"), str)
        and isinstance(row.get("relation"), str)
    }
    for member in members:
        member_id = member.get("id") if isinstance(member, dict) else None
        if not isinstance(member_id, str):
            continue
        for relation in sorted(fv.ALL_RELATIONS):
            if (member_id, relation) not in present:
                complete_verdicts.append(_verdict(member_id, relation, "UNKNOWN"))
    (epoch / "elements.json").write_text(
        json.dumps(
            [
                {"id": "accountability:x", "kind": "accountability_rollup", "payload": {"n": 1}},
                {
                    "id": "frame:relevance-report",
                    "kind": "relevance_report",
                    "payload": {"verdicts": complete_verdicts},
                },
            ]
        ),
        encoding="utf-8",
    )
    (root / "declaration").mkdir(exist_ok=True)
    (root / "declaration" / "mass.yaml").write_text(
        yaml.safe_dump(
            {
                "projection": "frame-reduction",
                "members": members,
                "exclusions": declared_exclusions,
            }
        ),
        encoding="utf-8",
    )
    (epoch / "coverage.json").write_text(
        json.dumps(
            [
                {
                    "member_id": member["id"],
                    "member_declaration_identity": fv._member_declaration_identity(
                        member, declared_exclusions
                    ),
                }
                for member in members
                if isinstance(member, dict) and isinstance(member.get("id"), str)
            ]
        ),
        encoding="utf-8",
    )
    (epoch / "publish.json").write_text(
        json.dumps({"epoch": epoch.name, "swapped": swapped, "reason": "test fixture"}),
        encoding="utf-8",
    )
    if make_current:
        (root / "_runs" / "current").symlink_to(Path("epochs") / epoch.name)
    return root


def _verdict(member_id: str, relation: str, verdict: object = True) -> dict[str, object]:
    return {
        "subject": {"member_id": member_id},
        "relation": relation,
        "verdict": verdict,
        "projection": "frame-reduction",
    }


def _content_query_member(
    tmp_path: Path,
    *,
    location: dict[str, object] | None = None,
    max_bytes: int = 128,
    errors: str = "replace",
    exclusions: list[dict[str, object]] | None = None,
) -> tuple[fv.DecayedMember, Path]:
    root = tmp_path / "member"
    root.mkdir(exist_ok=True)
    declaration = {
        "id": "query",
        "reader": {"id": "fs.content_query"},
        "location": {
            "roots": [str(root)],
            "patterns": ["*.py"],
            "query": "def ",
            **(location or {}),
        },
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[declaration],
        verdicts=[_verdict("query", "scope_exited")],
        exclusions=exclusions,
    )
    (procedure / "declaration/params.yaml").write_text(
        yaml.safe_dump(
            {
                "profile_id": "fixture",
                "parameters": {
                    "max_unit_bytes": {"value": max_bytes, "why": "test bound"},
                    "encoding_error_policy": {"value": errors, "why": "test decoding"},
                },
            }
        )
    )
    return fv.load_frame_verdicts(procedure, now=NOW).decayed[0], root


@pytest.mark.parametrize(
    ("location", "blob", "inside"),
    [
        ({}, b"def selected(): pass", True),
        ({}, b"DEF selected(): pass", False),
        ({"case_insensitive": True}, b"DEF selected(): pass", True),
        ({"query": "sced", "match": "word"}, b"sced_jailbreak", True),
        ({"query": "sced", "match": "word"}, b"quiesced", False),
        ({"query": "sced", "match": "word", "case_insensitive": True}, b"SCED-ruler", True),
        ({"query": "sced"}, b"quiesced", True),
        ({"patterns": []}, b"def selected(): pass", False),
        ({"patterns": None}, b"def selected(): pass", True),
        ({"skip_dirs": ["nested"]}, b"def selected(): pass", True),
        ({"patterns": ["nested/**"]}, b"def selected(): pass", False),
    ],
)
def test_content_query_declared_predicate(
    tmp_path: Path, location: dict[str, object], blob: bytes, inside: bool
) -> None:
    member, root = _content_query_member(tmp_path, location=location)
    file = root / "nested/file.py"
    file.parent.mkdir()
    file.write_bytes(blob)
    assert fv.ref_within_member(file, False, member) is inside


def test_content_query_evaluates_current_bytes_and_canonical_alias(tmp_path: Path) -> None:
    member, root = _content_query_member(tmp_path)
    file = root / "file.py"
    alias = root / "alias"
    alias.symlink_to(file)
    for content, inside in [(b"def selected(): pass", True), (b"value = 1", False)]:
        file.write_bytes(content)
        assert fv.ref_within_member(file, False, member) is inside
        assert fv.ref_within_member(alias, False, member) is inside


@pytest.mark.parametrize("spelling", ["bin", "sbin"])
@pytest.mark.parametrize("populated", [False, True], ids=["future", "selected"])
@pytest.mark.parametrize("prefix", ["", "nested"], ids=["root", "recursive"])
def test_content_query_helper_canonical_directory_pattern_bounds_bytes(
    tmp_path: Path, spelling: str, populated: bool, prefix: str
) -> None:
    member, root = _content_query_member(tmp_path, location={"patterns": ["sbin/db5.3/*.py"]})
    root = root / prefix
    directory = root / "bin/db5.3"
    directory.mkdir(parents=True)
    (root / "sbin").symlink_to("bin", target_is_directory=True)
    target = directory / "file.py"
    if populated:
        target.write_bytes(b"def selected(): pass")
    candidate = root / spelling / "db5.3/file.py"
    selected = fv._canonical_member_entries(member)
    if populated:
        assert selected == {root / "sbin/db5.3/file.py": target}
        assert fv._content_query_within_member(candidate, False, member, None, selected)
    else:
        assert selected == {}
        with pytest.raises(fv.UndecidableScopeContainment) as caught:
            fv._content_query_within_member(candidate, False, member, None, selected)
        assert str(target) in str(caught.value)
        assert "max_unit_bytes" in caught.value.remedy


@pytest.mark.parametrize("external", [False, True])
def test_content_query_selected_alias_predicate_uses_target_bytes(
    tmp_path: Path, external: bool
) -> None:
    member, root = _content_query_member(tmp_path, location={"patterns": ["awk"]})
    target = (tmp_path if external else root) / "gawk"
    alias = root / "nested/awk"
    alias.parent.mkdir()
    alias.symlink_to(target)
    for content, inside in [(b"def selected(): pass", True), (b"value = 1", False)]:
        target.write_bytes(content)
        assert fv.ref_within_member(alias, False, member) is inside
        assert fv.ref_within_member(target, False, member) is inside


@pytest.mark.parametrize("spelling", ["[a]lias", "[aa]lias", "[aaa]lias"])
def test_content_query_singleton_glob_alias_selects_external_target(
    tmp_path: Path, spelling: str
) -> None:
    member, root = _content_query_member(tmp_path, location={"patterns": ["selected"]})
    target = tmp_path / "target.py"
    target.write_bytes(b"def selected(): pass")
    (root / "selected").symlink_to(target)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "alias").symlink_to(target)
    assert {entry.resolve() for entry in outside.glob(spelling)} == {target}
    assert fv.ref_within_member(outside, True, member, scope_pattern=spelling)


@pytest.mark.parametrize("spelling", ["[s]bin", "[ss]bin", "[sss]bin"])
def test_glob_singleton_directory_alias_has_canonical_containment(
    tmp_path: Path, spelling: str
) -> None:
    root = tmp_path / "bin/db5.3"
    root.mkdir(parents=True)
    (root / "db_dump").write_bytes(b"selected bytes")
    (tmp_path / "sbin").symlink_to("bin", target_is_directory=True)
    member = fv.DecayedMember("m", "scope_exited", (root,), ("**/*",), ())
    assert {entry.resolve() for entry in tmp_path.glob(spelling + "/db5.3")} == {root}
    assert fv.ref_within_member(tmp_path, True, member, scope_pattern=spelling + "/db5.3")


@pytest.mark.parametrize("kind", ["dangling", "loop"])
def test_content_query_selected_unresolved_alias_has_remedy(tmp_path: Path, kind: str) -> None:
    member, root = _content_query_member(tmp_path, location={"patterns": ["awk"]})
    alias = root / "awk"
    alias.symlink_to(alias.name if kind == "loop" else "missing")
    with pytest.raises(fv.UndecidableScopeContainment) as caught:
        fv.ref_within_member(root / "gawk", False, member)
    assert str(alias) in str(caught.value)
    assert "intended target" in caught.value.remedy


@pytest.mark.parametrize("problem", ["oversize", "zero-bound", "missing", "unreadable", "strict"])
def test_content_query_unreadable_or_unbounded_file_is_undecidable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    member, root = _content_query_member(
        tmp_path,
        max_bytes=0 if problem == "zero-bound" else 4,
        errors="strict" if problem == "strict" else "replace",
        location={"query": "x", "match": "word"},
    )
    file = root / "file.py"
    if problem != "missing":
        file.write_bytes(b"x     " if problem == "oversize" else b"x\xff")
    if problem == "unreadable":
        original = Path.open

        def denied(path, *args, **kwargs):
            if path == file:
                raise PermissionError("fixture read denied")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(fv.UndecidableScopeContainment) as caught:
        fv.ref_within_member(file, False, member)
    assert "fs.content_query" in str(caught.value) and str(file) in str(caught.value)
    assert (
        "max_unit_bytes" in caught.value.remedy and "encoding_error_policy" in caught.value.remedy
    )


@pytest.mark.parametrize(("errors", "inside"), [("replace", True), ("ignore", False)])
def test_content_query_word_predicate_uses_declared_encoding_policy(
    tmp_path: Path, errors: str, inside: bool
) -> None:
    member, root = _content_query_member(
        tmp_path,
        errors=errors,
        location={"query": "sced", "match": "word"},
    )
    file = root / "file.py"
    file.write_bytes(b"sced\xffword")
    assert fv.ref_within_member(file, False, member) is inside


def test_content_query_preserves_declared_exclusions_and_refuses_broad_scopes(
    tmp_path: Path,
) -> None:
    file = tmp_path / "member/file.py"
    member, root = _content_query_member(
        tmp_path,
        exclusions=[{"id": "residue", "paths": [str(file)]}],
    )
    file.write_bytes(b"def selected(): pass")
    assert not fv.ref_within_member(file, False, member)
    with pytest.raises(fv.UndecidableScopeContainment, match="content predicate"):
        fv.ref_within_member(root, True, member, scope_pattern="*.py")


def test_content_query_uses_only_producer_roots(tmp_path: Path) -> None:
    outside = tmp_path / "outside.py"
    outside.write_bytes(b"def selected(): pass")
    member, _ = _content_query_member(
        tmp_path, location={"path": str(tmp_path), "files": [str(outside)]}
    )
    assert not fv.ref_within_member(outside, False, member)


def test_content_query_parameters_match_the_accepted_epoch(tmp_path: Path) -> None:
    _content_query_member(tmp_path)
    procedure = tmp_path / "procedure"
    params = procedure / "declaration/params.yaml"
    profile = yaml.safe_load(params.read_text())
    # ParameterProfile.digest uses this canonical serialization (producer params.py:131-133).
    canonical = json.dumps(profile, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    (procedure / "_runs/current/hypothesis.json").write_text(
        json.dumps(
            {
                "iteration": {
                    "parameter_profile_digest": hashlib.sha256(canonical.encode()).hexdigest()
                },
            }
        )
    )
    assert fv.load_frame_verdicts(procedure, now=NOW).decayed[0].content_query.max_unit_bytes == 128
    profile["parameters"]["max_unit_bytes"]["value"] = 256
    params.write_text(yaml.safe_dump(profile))
    with pytest.raises(fv.FrameVerdictsUnavailable, match="differs from the accepted epoch"):
        fv.load_frame_verdicts(procedure, now=NOW)


def test_content_query_terminal_glob_does_not_read_unselected_files(tmp_path: Path) -> None:
    member, root = _content_query_member(tmp_path, max_bytes=0, location={"patterns": ["**"]})
    file = root / "file.py"
    file.write_bytes(b"def selected(): pass")
    assert not {p for p in root.rglob("**") if p.is_file()}
    assert not fv.ref_within_member(file, False, member)


@pytest.mark.parametrize(
    "location",
    [
        # `{"roots": ["podium:store"]}` used to sit here. It is not an invalid declaration: the
        # local readers give a colon no meaning, so it is a legal relative directory name, and
        # whether it refuses depends entirely on whether an anchor is available. Leaving it in a
        # list of malformed inputs made this test pass or fail on an ambient property of the
        # environment — the presence of a declared-vault fallback — rather than on the
        # declaration. It is pinned deliberately, with both fallback states controlled, in
        # `test_a_colon_bearing_relative_root_anchors_when_a_fallback_exists` below.
        {"roots": []},
        {"query": ""},
        {"query": "two\nlines"},
        {"query": "é", "case_insensitive": True},
        {"match": "regex"},
    ],
)
def test_content_query_invalid_declaration_has_producer_remedy(
    tmp_path: Path, location: dict[str, object]
) -> None:
    with pytest.raises(fv.FrameVerdictsUnavailable) as caught:
        _content_query_member(tmp_path, location=location)
    assert "fs.content_query" in str(caught.value)
    assert "run the frame producer" in caught.value.remedy


def test_a_colon_bearing_relative_root_anchors_when_a_fallback_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A colon is part of the name, so anchoring is the only question — and it is environmental.

    `_producer_working_directory` honours a recorded absolute cwd first and otherwise the
    declared vault binding. With a vault present this legal relative root anchors and nothing
    refuses; with **both** absent it refuses for want of an anchor. Both states are controlled
    here rather than inherited, because inheriting one of them is what made the old
    invalid-declaration case pass in one environment and fail in another.
    """

    vault = tmp_path / "vault"
    (vault / "30-areas" / "hapax").mkdir(parents=True)
    monkeypatch.setenv(fv.FRAME_VAULT_ROOT_ENV, str(vault))

    member, _root = _content_query_member(tmp_path, location={"roots": ["podium:store"]})
    assert member is not None


def test_a_colon_bearing_relative_root_refuses_when_no_anchor_is_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the same contract, with the fallback explicitly absent."""

    monkeypatch.setenv(fv.FRAME_VAULT_ROOT_ENV, str(tmp_path / "no-such-vault"))

    with pytest.raises(fv.FrameVerdictsUnavailable) as caught:
        _content_query_member(tmp_path, location={"roots": ["podium:store"]})

    assert "cannot be anchored" in str(caught.value)
    assert "fs.content_query" in str(caught.value)
    assert "run the frame producer" in caught.value.remedy


# **Last-wins is silent, and the value it keeps is not the safe one.** A decay row carrying
# `"verdict": "TRUE", "verdict": "FALSE"` parses to FALSE under both parsers, so a scope refused at
# exit 10 becomes eligible at exit 0 — and the ambiguity is gone before any validation sees the
# document, so nothing downstream can detect it.
DUPLICATE_KEY_INPUTS = (
    ("json_flat", "json", '{"verdict": "TRUE", "verdict": "FALSE"}'),
    ("json_nested", "json", '{"row": {"verdict": "TRUE", "verdict": "FALSE"}}'),
    ("json_in_a_list", "json", '[{"verdict": "TRUE", "verdict": "FALSE"}]'),
    ("yaml_flat", "yaml", "verdict: TRUE\nverdict: FALSE\n"),
    ("yaml_nested", "yaml", "row:\n  verdict: TRUE\n  verdict: FALSE\n"),
    ("yaml_in_a_list", "yaml", "- verdict: TRUE\n  verdict: FALSE\n"),
)


@pytest.mark.parametrize(
    ("name", "parser", "text"), DUPLICATE_KEY_INPUTS, ids=[row[0] for row in DUPLICATE_KEY_INPUTS]
)
def test_a_governing_document_that_repeats_a_key_is_refused(
    name: str, parser: str, text: str
) -> None:
    """Nesting matters: the hook must see pairs at every depth, not only at the top."""

    load = fv._strict_json if parser == "json" else fv._strict_yaml  # noqa: SLF001
    with pytest.raises(fv.DuplicateGoverningKey):
        load(text)
    # The oracle beside it: the stock parsers accept these and keep the LAST value, which is what
    # makes the refusal necessary rather than fastidious.
    stock = json.loads(text) if parser == "json" else yaml.safe_load(text)
    assert stock is not None, name


@pytest.mark.parametrize(
    ("name", "scalar", "kind"),
    (
        ("date", "2026-09-08", "date"),
        ("timestamp", "2026-09-08 01:02:03", "datetime"),
        ("sexagesimal_like", "2026-09-08T01:02:03Z", "datetime"),
    ),
    ids=["date", "timestamp", "iso-timestamp"],
)
def test_a_yaml_scalar_the_producer_left_unquoted_refuses_instead_of_escaping(
    name: str, scalar: str, kind: str
) -> None:
    """SafeLoader accepts it; the identity hash cannot govern it.

    An unquoted `declared: 2026-09-08` is a `datetime.date`, and canonicalising the declaration
    then raised a bare `TypeError` outside the parsing handler — the dispatcher catches only
    `FrameVerdictsUnavailable`, so it escaped with no refusal, remedy or receipt (review finding,
    codex). Same class as the unhashable-key escape beside it: a value the loader accepts and a
    later stage cannot serialise.

    Coercion is deliberately not the fix. This identity is copied from the producer's own rule and
    a fixture pins byte compatibility, so serialising the date would compute a hash the producer
    does not and the two trees would disagree about which declaration this is.
    """
    member = {"id": "m1", "relation": "scope_exited", "declared": yaml.safe_load(scalar)}
    assert type(member["declared"]).__name__ == kind, name

    with pytest.raises(fv.FrameVerdictsUnavailable) as caught:
        fv._member_declaration_identity(member, ())  # noqa: SLF001
    assert "cannot be canonicalised" in str(caught.value)
    assert "m1" in str(caught.value)
    # The offending FIELD is named, because a member with twenty keys is not repairable from a
    # message saying only that one of them is not serialisable.
    assert "declared=" in str(caught.value)
    assert "quote the affected value" in caught.value.remedy

    # The twin: an all-string member still produces its identity, so the refusal is about the
    # unserialisable value and not about the shape of the member.
    quoted = {"id": "m1", "relation": "scope_exited", "declared": scalar}
    assert fv._member_declaration_identity(quoted, ()).startswith("declaration:")  # noqa: SLF001


#: What SafeLoader really produces for an unquoted `declared: 2026-09-08`, taken from the loader
#: rather than constructed, so these rows describe a document a producer can actually write.
DECL_DATE = yaml.safe_load("2026-09-08")


def _unencodable_at(member: dict[str, object], exclusions: object = ()) -> tuple[str, str]:
    with pytest.raises(fv.FrameVerdictsUnavailable) as caught:
        fv._member_declaration_identity(member, exclusions)  # noqa: SLF001
    return str(caught.value).split("at: ", 1)[-1], caught.value.remedy


@pytest.mark.parametrize(
    ("name", "member", "exclusions", "expected"),
    (
        ("top_level", {"id": "m1", "declared": DECL_DATE}, (), "declared="),
        (
            "nested_mapping",
            {"id": "m1", "location": {"path": "/tmp/x", "declared": DECL_DATE}},
            (),
            "location.declared=",
        ),
        ("inside_list", {"id": "m1", "windows": [{"from": DECL_DATE}]}, (), "windows[0].from="),
        ("in_exclusions", {"id": "m1"}, ({"declared": DECL_DATE},), "exclusions[0].declared="),
    ),
    ids=["top-level", "nested-mapping", "inside-list", "in-exclusions"],
)
def test_the_refusal_names_the_path_to_the_value_not_just_the_member(
    name: str, member: dict[str, object], exclusions: object, expected: str
) -> None:
    """ "Which key do I quote" is most of what this refusal is for.

    The first version inspected top-level member keys only, so a date under `location`, inside a
    window list or in `exclusions` refused with `<not in a top-level member field>` and named
    nothing actionable (review finding, root).
    """
    located, remedy = _unencodable_at(member, exclusions)
    assert located.startswith(expected), name
    assert "quote the affected value" in remedy


#: A lone surrogate, reached the way a producer could: YAML's own escape syntax, not a constructed
#: Python object. It survives `json.dumps(ensure_ascii=False)` and fails only at the digest.
SURROGATE = yaml.safe_load('"\\udcff"')


@pytest.mark.parametrize(
    ("name", "member", "exclusions", "expected"),
    (
        ("value", {"id": "m1", "declared": SURROGATE}, (), "declared="),
        ("nested", {"id": "m1", "location": {"path": SURROGATE}}, (), "location.path="),
        ("key", {"id": "m1", SURROGATE: "x"}, (), "'\\udcff' (key)="),
        ("exclusions", {"id": "m1"}, ({"path": SURROGATE},), "exclusions[0].path="),
    ),
    ids=["value", "nested", "key", "exclusions"],
)
def test_a_surrogate_refuses_and_the_refusal_is_itself_writable(
    name: str, member: dict[str, object], exclusions: object, expected: str
) -> None:
    """The encode was one line below the guard, and the diagnostic had the same problem.

    `json.dumps(ensure_ascii=False)` accepts a lone surrogate and `encode("utf-8")` rejects it, so
    the digest raised `UnicodeEncodeError` — a `ValueError`, which the handler beside it would have
    caught had the call been inside it. Guarding the dumps and leaving the very next operation
    unguarded is the boundary drawn one line too high (review finding, codex).

    The second assertion is the one that came from the reproduction failing rather than from the
    finding: a surrogate used as a mapping KEY was interpolated raw into the path label, so the
    refusal naming it could not be written to stderr or into a receipt — reproducing, at the moment
    of reporting, the failure it was reporting.
    """
    located, remedy = _unencodable_at(member, exclusions)
    assert located.startswith(expected), name
    assert "not encodable as UTF-8" in located
    assert "replace the character that is not encodable as UTF-8" in remedy
    # Neither of the other two repairs, which would send the author after the wrong thing.
    assert "quote the affected value" not in remedy
    assert "self-referencing anchor" not in remedy
    # **The refusal must survive being emitted**, which is the whole point of a governed refusal.
    located.encode("utf-8")
    remedy.encode("utf-8")


def test_valid_non_ascii_still_produces_its_identity_unchanged() -> None:
    """The control the repair must not break: legitimate Unicode still hashes, and hashes the same.

    Moving `encode("utf-8")` inside the handler changes where the bytes are produced and must not
    change what they are — this pins the digest against a fixed member so a future rewrite of that
    boundary cannot quietly renumber every declaration identity in the estate.
    """
    member = {"id": "m1", "declared": "café — ünïcode ✓"}
    identity = fv._member_declaration_identity(member, ())  # noqa: SLF001
    assert identity.startswith("declaration:")
    expected = hashlib.sha256(
        json.dumps(
            {"member": member, "exclusions": ()},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert identity == "declaration:" + expected


def test_a_cyclic_declaration_gets_its_own_repair_and_does_not_hang_the_walker() -> None:
    """A cycle and an unquoted scalar are different repairs.

    `metadata: &loop [*loop]` is accepted by SafeLoader and raises `ValueError` at
    canonicalisation — a different exception AND a different fix, so telling its author to quote
    something would send them after a scalar that is not the problem. Root established this class
    is pre-existing rather than introduced by the date refusal.

    The walker that describes it must also survive it: an identity-guarded recursion, because a
    describer that recurses forever on the document it exists to diagnose is worse than the bare
    exception it replaced.
    """
    loop: list[object] = []
    loop.append(loop)

    located, remedy = _unencodable_at({"id": "m1", "metadata": loop})
    assert "(cycle)" in located
    assert "remove the self-referencing anchor/alias" in remedy
    assert "quote the affected value" not in remedy

    located, remedy = _unencodable_at({"id": "m1"}, loop)
    assert located.startswith("exclusions[0]") and "(cycle)" in located
    assert "remove the self-referencing anchor/alias" in remedy


@pytest.mark.parametrize(
    ("name", "text"),
    (
        ("sequence_key", "? [a, b]\n: c\n"),
        ("mapping_key", "? {a: b}\n: c\n"),
        ("sequence_key_nested", "row:\n  ? [a, b]\n  : c\n"),
    ),
    ids=["sequence_key", "mapping_key", "sequence_key_nested"],
)
def test_an_unhashable_key_keeps_SafeLoaders_actionable_refusal(name: str, text: str) -> None:
    """The duplicate check must not pre-empt the loader's own error with a bare TypeError.

    `key in seen` is set membership, and a YAML complex key — a sequence or mapping used as a key
    — is unhashable, so the guard raised `TypeError` before `SafeLoader.construct_mapping` could
    raise `ConstructorError`. The refusal boundary catches `yaml.YAMLError`; a TypeError escapes
    it with no refusal, remedy or receipt (review finding, codex, at `41be64bde`).

    Duplicate detection is simply not this key's question. SafeLoader already refuses it, and the
    guard now steps aside instead of answering first and wrongly.
    """
    with pytest.raises(yaml.YAMLError) as caught:
        fv._strict_yaml(text)  # noqa: SLF001
    assert "unhashable" in str(caught.value), name
    # The oracle beside it: stock SafeLoader refuses these the same way, so the strict loader is
    # preserving that behaviour rather than inventing one.
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(text)


@pytest.mark.parametrize(
    ("name", "parser", "text"),
    (
        ("json_clean", "json", '{"verdict": "TRUE"}'),
        ("yaml_clean", "yaml", "verdict: TRUE\n"),
        ("json_repeated_across_siblings", "json", '[{"verdict": "TRUE"}, {"verdict": "FALSE"}]'),
        ("yaml_repeated_across_siblings", "yaml", "- verdict: TRUE\n- verdict: FALSE\n"),
    ),
    ids=["json_clean", "yaml_clean", "json_siblings", "yaml_siblings"],
)
def test_a_key_repeated_across_SIBLINGS_is_not_a_duplicate(
    name: str, parser: str, text: str
) -> None:
    """The twin that keeps the refusal from becoming a blanket.

    Two mappings each carrying `verdict` is ordinary and must parse. A check that counted keys
    across the whole document rather than within one mapping would redden these.
    """

    load = fv._strict_json if parser == "json" else fv._strict_yaml  # noqa: SLF001
    assert load(text) is not None, name


def test_the_strict_yaml_loader_still_refuses_an_unsafe_tag() -> None:
    """`yaml.load` with a custom Loader is the dangerous SHAPE, so the safety is asserted.

    `_StrictYAMLLoader` subclasses `SafeLoader` and overrides one constructor, so the reachable
    value domain is unchanged — but that is a claim, and this is the measurement.
    """

    with pytest.raises(yaml.YAMLError):
        fv._strict_yaml("!!python/object:os.system {}")  # noqa: SLF001


def _fault_once(monkeypatch: pytest.MonkeyPatch, operation: str, name: str, index: int) -> dict:
    """Fault `operation` ONCE, at the INDEXth call touching `name`, then let it recover.

    Transient on purpose. A steady fault is caught by the later readability walk, so it cannot
    tell an observed enumeration from an unobserved one — the walk sees the fault because it is
    still there. Only a fault that is gone by then distinguishes them, which is the same sentence
    as "a check of a re-run is not a check of the run".

    Injected at `os.scandir` / `os.stat`, the operations BOTH the suppressing method and the
    unsuppressed classifier reach. Patching `Path.is_file` would measure only the old source and
    would pass vacuously against the repair.
    """

    state = {"count": 0, "seen": 0}
    real = {"scandir": os.scandir, "stat": os.stat}

    def faulted(kind: str, error: OSError):  # noqa: ANN202
        def call(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
            if kind == operation and name in str(path):
                if state["seen"] == index and state["count"] == 0:
                    state["count"] += 1
                    state["seen"] += 1
                    raise error
                state["seen"] += 1
            return real[kind](path, *args, **kwargs)

        return call

    monkeypatch.setattr(
        os, "scandir", faulted("scandir", PermissionError(errno.EACCES, "injected once"))
    )
    monkeypatch.setattr(os, "stat", faulted("stat", OSError(errno.ELOOP, "injected once")))
    return state


# TWO observation boundaries reaching one consequence, and they need separate controls: observing
# the supplying enumeration does not fix the classification suppression, and vice versa. Both were
# reproduced against receipt-only dispatch before this repair — a transient scandir fault and an
# independent transient classification fault each turned a decayed scope into an eligible one.
#
# **The stat index is MEASURED, not guessed.** `alias.txt` is stat'ed four times here —
# `_classified_is_dir`, two `lstat`s from the symlink and resolution checks, then
# `_classified_is_file` — so faulting the first call lands on the DIRECTORY classifier and the
# control passes against the repair for the wrong reason. My first version did exactly that and
# its rollback did not redden it. Index 0 is kept beside index 3 so the pair shows the index is
# what discriminates.
SCOPE_OBSERVATION_FAULTS = (
    ("transient_enumeration", "scandir", "branch", 0),
    ("transient_file_classification", "stat", "alias.txt", 3),
    ("transient_dir_classification", "stat", "alias.txt", 0),
)


@pytest.mark.parametrize(
    ("name", "operation", "target", "index"),
    SCOPE_OBSERVATION_FAULTS,
    ids=[row[0] for row in SCOPE_OBSERVATION_FAULTS],
)
def test_a_transient_scope_fault_refuses_instead_of_shortening_the_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    operation: str,
    target: str,
    index: int,
) -> None:
    """A short scope is not a smaller answer but a wrong one."""

    root = tmp_path / "producer"
    branch = root / "branch"
    branch.mkdir(parents=True)
    alias = branch / "alias.txt"
    alias.write_bytes(b"decayed\n")
    member = fv.DecayedMember("m", "scope_exited", (root,), ("branch/*.txt",), (alias,))

    state = _fault_once(monkeypatch, operation, target, index)
    with pytest.raises(fv.UndecidableScopeContainment) as caught:
        fv._canonical_scope_entries(root, "branch/[a-a]lias.txt", member)  # noqa: SLF001
    assert state["count"] == 1, f"{name}: the fault must actually have fired"
    # **The remedy has to belong to the failure, and the default fires by omission.**
    # `UndecidableScopeContainment` defaults to "use narrower globs", which is right for a scope
    # too broad to decide and actively misleading for one that could not be READ — following it
    # edits the declaration instead of repairing the fault. Raising the class directly inherits
    # that default silently, which is what happened here and what this row now catches.
    assert caught.value.remedy != fv.UndecidableScopeContainment.remedy, (
        f"{name}: an unreadable scope must not be told to narrow its globs"
    )
    # Which remedy replaces the default depends on the boundary, and this row asserted the WRONG
    # one for two of the three. Enumeration failing means the directory could not be walked, and
    # read access is the fix. A classification failing means an entry the walk already yielded
    # could not be resolved — the injected errno here is ELOOP — and there the fix is the
    # declaration's intended target, which is what `test_dispatch_canonical_closure_unresolved_
    # entry_names_remedy` has pinned all along with a real self-referential symlink.
    #
    # I asserted "repair read access" for all three, then changed the source to satisfy it and
    # broke that committed row. The invariant this test actually establishes is the line above:
    # the default must not fire by omission. The specific wording belongs to the boundary.
    expected = (
        "repair read access"
        if operation == "scandir"
        else "repair or re-declare unresolved component"
    )
    assert expected in caught.value.remedy, name


def test_a_healthy_scope_expansion_still_returns_its_entry(tmp_path: Path) -> None:
    """The twin: three refusals beside it mean nothing without one arrangement that succeeds."""

    root = tmp_path / "producer"
    branch = root / "branch"
    branch.mkdir(parents=True)
    alias = branch / "alias.txt"
    alias.write_bytes(b"decayed\n")
    member = fv.DecayedMember("m", "scope_exited", (root,), ("branch/*.txt",), (alias,))

    found = fv._canonical_scope_entries(root, "branch/[a-a]lias.txt", member)  # noqa: SLF001
    assert sorted(path.name for path in found) == ["alias.txt"]


PRODUCER_CWD_ARRANGEMENTS = (
    # Decided negatives. Nothing readable is there, and the declared vault binding is the
    # documented fallback for exactly that case, so each of these must still anchor.
    ("absent", "vault"),
    ("dangling_symlink", "vault"),  # `stat` reports ENOENT for the target: a decided absence
    ("blocked_by_a_file_component", "vault"),  # ENOTDIR, likewise decided
    # UNREADABLE. The file is there and cannot be read, so the recorded working directory is
    # unknown — and substituting the vault base for it resolves every member location below
    # against a root the producer never used.
    ("symlink_loop", "refuse"),
)


@pytest.mark.parametrize(
    ("arrangement", "expected"),
    PRODUCER_CWD_ARRANGEMENTS,
    ids=[row[0] for row in PRODUCER_CWD_ARRANGEMENTS],
)
def test_an_unreadable_hypothesis_refuses_instead_of_redirecting_the_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arrangement: str, expected: str
) -> None:
    """`hypothesis.exists()` answered False for a file that exists and cannot be read.

    Three review families reported this on one line. The fault is injected at the FILESYSTEM —
    a real symlink loop, which is what `Path.exists` suppresses — rather than by patching the
    method, so the control measures the mitigation and not a stand-in for it. The three decided
    negatives beside it are what keeps the refusal a discrimination: a repair that refused for
    every unhappy stat would redden them.
    """

    vault = tmp_path / "vault"
    (vault / "30-areas" / "hapax").mkdir(parents=True)
    monkeypatch.setenv(fv.FRAME_VAULT_ROOT_ENV, str(vault))

    epoch = tmp_path / "epoch"
    epoch.mkdir()
    hypothesis = epoch / "hypothesis.json"
    if arrangement == "dangling_symlink":
        hypothesis.symlink_to(tmp_path / "nowhere")
    elif arrangement == "symlink_loop":
        hypothesis.symlink_to(hypothesis)
    elif arrangement == "blocked_by_a_file_component":
        (epoch / "blocker").write_text("not a directory")
        epoch = epoch / "blocker"

    if expected == "vault":
        assert fv._producer_working_directory(epoch) == (vault / "30-areas/hapax").resolve()  # noqa: SLF001
        return

    with pytest.raises(fv.FrameVerdictsUnavailable) as caught:
        fv._producer_working_directory(epoch)  # noqa: SLF001
    assert "undecidable" in str(caught.value)
    assert "hypothesis.json" in caught.value.remedy


def test_a_recorded_working_directory_still_wins_over_the_vault_binding(tmp_path: Path) -> None:
    """The twin the refusal must not cost: a readable hypothesis is still honoured."""

    epoch = tmp_path / "epoch"
    epoch.mkdir()
    recorded = tmp_path / "recorded"
    recorded.mkdir()
    (epoch / "hypothesis.json").write_text(
        json.dumps({"iteration": {"environment": {"cwd": str(recorded)}}}), encoding="utf-8"
    )

    assert fv._producer_working_directory(epoch) == recorded.resolve()  # noqa: SLF001


def test_latest_epoch_is_the_newest_parseable_dir_that_carries_elements(tmp_path: Path) -> None:
    epochs = tmp_path / "_runs" / "epochs"
    (epochs / "20260903T112609Z-0c5d7a85").mkdir(parents=True)
    (epochs / "20260903T112609Z-0c5d7a85" / "elements.json").write_text("[]")
    (epochs / "20260903T204725Z-d693f20c").mkdir()
    (epochs / "20260903T204725Z-d693f20c" / "elements.json").write_text("[]")
    (epochs / "20260903T230000Z-ffffffff").mkdir()  # newest, but no elements yet (in flight)
    (epochs / "notes").mkdir()
    (epochs / "notes" / "elements.json").write_text("[]")
    (epochs / "20261303T123456Z-deadbeef").mkdir()
    (epochs / "20261303T123456Z-deadbeef" / "elements.json").write_text("[]")

    chosen = latest_epoch_dir(tmp_path)

    assert chosen is not None and chosen.name == "20260903T204725Z-d693f20c"
    assert fv.epoch_produced_at(chosen.name) == datetime(2026, 9, 3, 20, 47, 25, tzinfo=UTC)


@pytest.mark.parametrize(
    "stamp",
    [
        "20261303T123456Z",
        "20260931T123456Z",
        "20260229T123456Z",
        "20260903T243456Z",
        "20260903T126056Z",
        "20260903T123460Z",
    ],
)
@pytest.mark.parametrize("reader", ["current_epoch_dir", "load_frame_verdicts"])
def test_invalid_calendar_epoch_refuses_with_the_producer_remedy(
    tmp_path: Path, stamp: str, reader: str
) -> None:
    name = f"{stamp}-deadbeef"
    epoch = tmp_path / "_runs/epochs" / name
    epoch.mkdir(parents=True)
    (tmp_path / "_runs/current").symlink_to(Path("epochs") / name)

    with pytest.raises(fv.FrameVerdictsUnavailable, match="names invalid epoch") as caught:
        getattr(fv, reader)(tmp_path)
    assert name in caught.value.reason
    assert caught.value.remedy == _expected_producer_remedy(tmp_path.resolve())
    if reader == "load_frame_verdicts":
        assert caught.value.frame_root_resolved == str(tmp_path.resolve())
    assert fv.epoch_produced_at(name) is None


def test_loader_uses_the_accepted_current_epoch_not_a_newer_rejected_attempt(
    tmp_path: Path,
) -> None:
    members = [{"id": "m", "location": {"path": str(tmp_path / "m")}}]
    root = _procedure_root(
        tmp_path,
        members=members,
        verdicts=[_verdict("m", "scope_exited", False)],
        at=NOW - timedelta(minutes=5),
        epoch_suffix="aaaaaaaa",
    )
    accepted = (root / "_runs" / "current").resolve()
    _procedure_root(
        root,
        members=members,
        verdicts=[_verdict("m", "scope_exited", True)],
        at=NOW,
        epoch_suffix="bbbbbbbb",
        make_current=False,
        swapped=False,
    )

    verdicts = fv.load_frame_verdicts(root, now=NOW)

    assert verdicts.epoch == accepted.name
    assert verdicts.decayed == ()


def test_a_fresh_rejected_attempt_does_not_reset_the_current_epochs_freshness(
    tmp_path: Path,
) -> None:
    members = [{"id": "m", "location": {"path": str(tmp_path / "m")}}]
    root = _procedure_root(
        tmp_path,
        members=members,
        verdicts=[],
        at=NOW - timedelta(seconds=fv.FRAME_EPOCH_MAX_AGE_S + 1),
        epoch_suffix="aaaaaaaa",
    )
    _procedure_root(
        root,
        members=members,
        verdicts=[],
        at=NOW,
        epoch_suffix="bbbbbbbb",
        make_current=False,
        swapped=False,
    )

    with pytest.raises(fv.FrameVerdictsUnavailable, match="current frame epoch.*older"):
        fv.load_frame_verdicts(root, now=NOW)


@pytest.mark.parametrize(
    ("receipt", "message"),
    [
        (None, "publish.json is missing"),
        ({"epoch": "wrong", "swapped": True}, "names epoch"),
        ({"epoch": f"{_stamp(NOW)}-d693f20c", "swapped": False}, "was not accepted"),
    ],
    ids=["missing", "wrong-epoch", "not-swapped"],
)
def test_current_epoch_requires_its_acceptance_receipt(
    tmp_path: Path, receipt: dict[str, object] | None, message: str
) -> None:
    members = [{"id": "m", "location": {"path": str(tmp_path / "m")}}]
    root = _procedure_root(tmp_path, members=members, verdicts=[])
    publish_path = root / "_runs" / "current" / "publish.json"
    if receipt is None:
        publish_path.unlink()
    else:
        publish_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(fv.FrameVerdictsUnavailable, match=message):
        fv.load_frame_verdicts(root, now=NOW)


def test_missing_root_or_epoch_refuse_with_the_producer_named(tmp_path: Path) -> None:
    with pytest.raises(fv.FrameVerdictsUnavailable, match="does not exist"):
        fv.load_frame_verdicts(tmp_path / "absent", now=NOW)
    (tmp_path / "_runs" / "epochs").mkdir(parents=True)
    with pytest.raises(fv.FrameVerdictsUnavailable, match="no frame epoch") as excinfo:
        fv.load_frame_verdicts(tmp_path, now=NOW)
    assert "hapax-frame-iteration" in excinfo.value.remedy
    assert "hapax-frame-iteration" in str(excinfo.value)


def test_epoch_age_is_declared_independently_of_cadence() -> None:
    tree = ast.parse(Path(fv.__file__).read_text(encoding="utf-8"))
    assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "FRAME_EPOCH_MAX_AGE_S"
            for target in node.targets
        )
    ]
    assert len(assignments) == 1
    assert isinstance(assignments[0].value, ast.Constant)
    assert assignments[0].value.value == 21600
    assert fv.FRAME_EPOCH_MAX_AGE_S == 21600


@pytest.mark.parametrize("diagnostic", ["reason", "remedy"])
def test_epoch_older_than_accepted_evidence_allowance_refuses_and_younger_does_not(
    tmp_path: Path, diagnostic: str
) -> None:
    limit = timedelta(seconds=21600)
    members = [{"id": "m", "location": {"path": str(tmp_path / "m")}}]

    fresh = _procedure_root(
        tmp_path / "fresh",
        members=members,
        verdicts=[_verdict("m", "scope_exited", False)],
        at=NOW - limit + timedelta(seconds=1),
    )
    assert fv.load_frame_verdicts(fresh, now=NOW).decayed == ()

    stale = _procedure_root(
        tmp_path / "stale",
        members=members,
        verdicts=[_verdict("m", "scope_exited", False)],
        at=NOW - limit - timedelta(seconds=1),
    )
    with pytest.raises(fv.FrameVerdictsUnavailable, match="older than 360 min") as excinfo:
        fv.load_frame_verdicts(stale, now=NOW)
    if diagnostic == "reason":
        epoch = (stale / "_runs/current").resolve().name
        assert excinfo.value.reason == (
            f"current frame epoch {epoch} is 21601.000000 s old, older than 360 min (21600 s); "
            "the accepted pointer may not have been advanced, or the producer's publication "
            f"may have been refused; frame_root_resolved={stale.resolve()}"
        )
    else:
        assert excinfo.value.remedy == _expected_stale_remedy(stale.resolve())


@pytest.mark.parametrize("ahead_s", [1, 86400, 31536000], ids=["one-second", "one-day", "one-year"])
def test_an_epoch_dated_after_the_reading_clock_is_refused(tmp_path: Path, ahead_s: int) -> None:
    """Being impossibly fresh used to pass the freshness bound.

    `age = now - produced_at` is negative for an epoch stamped after `now`, and a negative age is
    not greater than any positive limit — so an epoch dated a YEAR ahead loaded, measured (review
    finding, codex, 2026-09-07). The bound exists to say the accepted pointer is keeping up with
    the producer; two clocks disagreeing establishes nothing about that, and is not a weaker form
    of freshness.

    No skew tolerance is asserted, because any constant here would be a number nothing measured.
    The boundary rows beside this one are unchanged: an epoch exactly at the limit still loads and
    one second past it still refuses, so this refuses a third state rather than moving either edge.
    """

    root = _procedure_root(
        tmp_path,
        members=[{"id": "m", "location": {"path": str(tmp_path / "m")}}],
        verdicts=[_verdict("m", "scope_exited", False)],
        at=NOW + timedelta(seconds=ahead_s),
    )
    with pytest.raises(
        fv.FrameVerdictsUnavailable, match="in the future of the reading clock"
    ) as excinfo:
        fv.load_frame_verdicts(root, now=NOW)
    assert f"{float(ahead_s):.6f} s in the future" in excinfo.value.reason
    assert "compare the producer's clock with this reader's" in excinfo.value.remedy
    assert "older than" not in excinfo.value.reason, (
        "a future epoch is a different fact from a stale one and must not borrow its diagnosis"
    )


@pytest.mark.parametrize("age_s", [21599, 21600, 21601])
def test_default_epoch_age_boundary_is_six_hours(tmp_path: Path, age_s: int) -> None:
    root = _procedure_root(
        tmp_path,
        members=[{"id": "m", "location": {"path": str(tmp_path / "m")}}],
        verdicts=[_verdict("m", "scope_exited", False)],
        at=NOW - timedelta(seconds=age_s),
    )
    if age_s <= 21600:
        assert fv.load_frame_verdicts(root, now=NOW).decayed == ()
    else:
        with pytest.raises(fv.FrameVerdictsUnavailable, match="older than 360 min"):
            fv.load_frame_verdicts(root, now=NOW)


def test_malformed_elements_mass_or_no_verdict_rows_refuse(tmp_path: Path) -> None:
    members = [{"id": "m", "location": {"path": str(tmp_path / "m")}}]
    root = _procedure_root(tmp_path, members=members, verdicts=[_verdict("m", "scope_exited")])
    epoch = latest_epoch_dir(root)
    assert epoch is not None

    (epoch / "elements.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(fv.FrameVerdictsUnavailable, match="unreadable or malformed"):
        fv.load_frame_verdicts(root, now=NOW)

    (epoch / "elements.json").write_text(json.dumps({"elements": []}), encoding="utf-8")
    with pytest.raises(fv.FrameVerdictsUnavailable, match="JSON list"):
        fv.load_frame_verdicts(root, now=NOW)

    (epoch / "elements.json").write_text(
        json.dumps([{"id": "accountability:x", "payload": {}}]), encoding="utf-8"
    )
    with pytest.raises(fv.FrameVerdictsUnavailable, match="no verdict rows"):
        fv.load_frame_verdicts(root, now=NOW)

    (epoch / "elements.json").write_text(
        json.dumps([{"id": "r", "payload": {"verdicts": [_verdict("m", "scope_exited")]}}]),
        encoding="utf-8",
    )
    (root / "declaration" / "mass.yaml").write_text("members: {not: a list}\n", encoding="utf-8")
    with pytest.raises(fv.FrameVerdictsUnavailable, match="members list"):
        fv.load_frame_verdicts(root, now=NOW)


def test_only_true_verdicts_under_decay_relations_decay_a_member(tmp_path: Path) -> None:
    members = [
        {"id": "gone", "location": {"path": str(tmp_path / "gone"), "patterns": ["*.md"]}},
        {"id": "replaced", "location": {"path": str(tmp_path / "replaced")}},
        {"id": "ticking", "location": {"path": str(tmp_path / "ticking")}},
        {"id": "healthy", "location": {"path": str(tmp_path / "healthy")}},
    ]
    root = _procedure_root(
        tmp_path,
        members=members,
        verdicts=[
            _verdict("gone", "scope_exited", True),
            _verdict("replaced", "superseded", "TRUE"),
            _verdict("ticking", "periodic", True),  # a §6 relation, not a decay
            _verdict("healthy", "scope_exited", False),
            _verdict("healthy", "discharged", "false"),
        ],
    )

    verdicts = fv.load_frame_verdicts(root, now=NOW)

    assert [(m.member_id, m.relation) for m in verdicts.decayed] == [
        ("gone", "scope_exited"),
        ("replaced", "superseded"),
    ]
    assert verdicts.decayed[0].patterns == ("*.md",)
    assert verdicts.epoch.startswith(_stamp(NOW))
    assert verdicts.unmatchable == ()


def test_scheme_qualified_members_are_matched_by_uri_containment(tmp_path: Path) -> None:
    members = [
        {"id": "prs", "location": {"path": "gh://hapax-systems", "endpoints": ["x"]}},
        {
            "id": "podium-arm",
            "location": {"path": "podium:.local/share/opencode", "patterns": ["*"]},
        },
        {"id": "mixed", "location": {"roots": ["podium:/x", str(tmp_path / "mixed")]}},
    ]
    root = _procedure_root(
        tmp_path,
        members=members,
        verdicts=[
            _verdict("prs", "discharged"),
            _verdict("podium-arm", "scope_exited"),
            _verdict("mixed", "superseded"),
        ],
    )

    verdicts = fv.load_frame_verdicts(root, now=NOW)

    assert verdicts.unmatchable == ()
    mixed = [m for m in verdicts.decayed if m.member_id == "mixed"]
    assert mixed and mixed[0].roots == ((tmp_path / "mixed").resolve(),)
    council, vault = tmp_path / "council", tmp_path / "vault"
    council.mkdir()
    vault.mkdir()
    podium = fv.scope_within_decayed(
        ["podium:.local/share/opencode/x"],
        verdicts,
        council_root=council,
        vault_root=vault,
    )
    assert podium.all_inside
    assert podium.matches[0].member_id == "podium-arm"
    github = fv.scope_within_decayed(
        ["gh://hapax-systems/frame-consumer"],
        verdicts,
        council_root=council,
        vault_root=vault,
    )
    assert github.all_inside
    assert github.matches[0].member_id == "prs"
    assert not fv.scope_within_decayed(
        ["podium:.local/share/opencode-neighbor/x"],
        verdicts,
        council_root=council,
        vault_root=vault,
    ).all_inside


def test_a_decayed_member_without_a_containable_location_refuses_scope_comparison(
    tmp_path: Path,
) -> None:
    members = [{"id": "mystery", "location": {"endpoints": ["undisclosed"]}}]
    verdicts = fv.load_frame_verdicts(
        _procedure_root(tmp_path, members=members, verdicts=[_verdict("mystery", "scope_exited")]),
        now=NOW,
    )

    assert verdicts.unmatchable == ("mystery",)
    with pytest.raises(fv.NonCanonicalScopeRef, match="mystery.*no containable"):
        fv.scope_within_decayed(
            ["scripts/x.py"],
            verdicts,
            council_root=tmp_path / "council",
            vault_root=tmp_path / "vault",
        )

    # THE BYPASS this guard had (review finding, codex, at `5007ed238`). The refusal above is
    # reached through `if declared_refs and verdicts.unmatchable`, so a scope that TRIMMED away
    # to nothing skipped it and returned an ordinary "not inside" verdict. A whitespace-only
    # name is a legal POSIX filename and must reach the same refusal as any other reference:
    # trimming a name to nothing must never convert a refusal into a verdict.
    for ref in ("  ", " ", "\t"):
        with pytest.raises(fv.NonCanonicalScopeRef, match="mystery.*no containable"):
            fv.scope_within_decayed(
                [ref],
                verdicts,
                council_root=tmp_path / "council",
                vault_root=tmp_path / "vault",
            )


def test_scope_matching_by_containment_patterns_files_and_wildcard_tails(tmp_path: Path) -> None:
    council = tmp_path / "council"
    vault = tmp_path / "vault"
    (council / "legacy").mkdir(parents=True)
    (vault / "30-areas" / "old").mkdir(parents=True)
    members = [
        {"id": "legacy-code", "location": {"path": str(council / "legacy"), "patterns": ["*.py"]}},
        {"id": "old-notes", "location": {"path": str(vault / "30-areas" / "old")}},
        {"id": "one-file", "location": {"files": [str(council / "config" / "dead.yaml")]}},
    ]
    root = _procedure_root(
        tmp_path,
        members=members,
        verdicts=[
            _verdict("legacy-code", "scope_exited"),
            _verdict("old-notes", "superseded"),
            _verdict("one-file", "discharged"),
        ],
    )
    verdicts = fv.load_frame_verdicts(root, now=NOW)

    def scope(*refs: str) -> fv.ScopeVerdict:
        return fv.scope_within_decayed(refs, verdicts, council_root=council, vault_root=vault)

    inside = scope("legacy/a.py", "legacy/*.py", "30-areas/old/x.md", "config/dead.yaml")
    assert inside.all_inside
    assert [(m.member_id, m.relation) for m in inside.matches] == [
        ("legacy-code", "scope_exited"),
        ("legacy-code", "scope_exited"),
        ("old-notes", "superseded"),
        ("one-file", "discharged"),
    ]

    # a non-.py file under legacy/ is not the member's declared surface
    assert scope("legacy/README.md").outside == ("legacy/README.md",)
    # Round 30 repairs round 29's over-refusal: these partial languages include
    # canonical paths outside the selected direct .py files.
    for ref in ("legacy/**", "legacy/**/*.py"):
        assert scope(ref).outside == (ref,)
    assert scope("legacy/sub/").outside == ("legacy/sub/",)
    # partly inside: admitted (moving things out of a decayed member is legitimate work)
    mixed = scope("legacy/a.py", "scripts/live.py")
    assert not mixed.all_inside and mixed.outside == ("scripts/live.py",)
    assert len(mixed.matches) == 1
    # Nothing declared: nothing to judge. This row used to read `scope("", "  ")` with the
    # comment "nothing declared", which conflated two different things and encoded a fail-open
    # (review finding, codex, at `5007ed238`). It entered in this branch's first commit as
    # incidental coverage of what the code did, not as a ratified equivalence, so it is corrected
    # here rather than treated as settled. The two cases are now separated below.
    empty = scope()
    assert not empty.all_inside and empty.matches == () and empty.outside == ()
    # `""` cannot name a surface, so it is UNREPRESENTABLE and refused by name. Dropping it made
    # a declared-but-impossible scope indistinguishable from declaring no scope at all.
    with pytest.raises(fv.NonCanonicalScopeRef, match="empty string"):
        scope("")
    # `"  "` is a legal POSIX filename, so it IS a declaration and gets answered. Here it names
    # nothing in the decayed member, so it is outside — a verdict, not a disappearance.
    spaces = scope("  ")
    assert not spaces.all_inside and spaces.outside == ("  ",)
    # absolute refs resolve as given; a foreign absolute path is outside
    assert scope(str(council / "legacy" / "z.py")).all_inside
    assert scope("/etc/hosts").outside == ("/etc/hosts",)


def test_resolve_scope_ref_prefers_an_existing_council_path_then_the_vault(tmp_path: Path) -> None:
    council = tmp_path / "council"
    vault = tmp_path / "vault"
    (council / "scripts").mkdir(parents=True)
    (vault / "30-areas").mkdir(parents=True)

    path, dirlike = fv.resolve_scope_ref("scripts/x.py", council_root=council, vault_root=vault)
    assert path == (council / "scripts" / "x.py").resolve() and not dirlike
    path, dirlike = fv.resolve_scope_ref("30-areas/**/*.md", council_root=council, vault_root=vault)
    assert path == (vault / "30-areas").resolve() and dirlike
    path, dirlike = fv.resolve_scope_ref("scripts", council_root=council, vault_root=vault)
    assert path == (council / "scripts").resolve() and dirlike
    path, _ = fv.resolve_scope_ref("nowhere/y.py", council_root=council, vault_root=vault)
    assert path == (council / "nowhere" / "y.py").resolve()


# ── Round 2 on #4629: the six criticals four review families raised ──────────────────────────


def test_a_double_star_pattern_does_not_match_every_path_under_the_root(tmp_path: Path) -> None:
    """`**` crosses `/` and `*` does not; the previous implementation returned True for any pattern
    merely containing `**`, so a member declaring `docs/**/*.md` decayed its whole root."""
    root = tmp_path / "m"
    members = [{"id": "docs", "location": {"path": str(root), "patterns": ["docs/**/*.md"]}}]
    verdicts = fv.load_frame_verdicts(
        _procedure_root(tmp_path, members=members, verdicts=[_verdict("docs", "scope_exited")]),
        now=NOW,
    )
    member = verdicts.decayed[0]

    assert fv.ref_within_member(root / "docs" / "a" / "b.md", False, member)
    assert fv.ref_within_member(root / "docs" / "b.md", False, member)
    assert not fv.ref_within_member(root / "scripts" / "x.py", False, member)
    assert not fv.ref_within_member(root / "docs" / "a" / "b.py", False, member)
    # fs.glob uses root.glob(pattern): flat patterns select only direct children.
    flat = fv.DecayedMember("s", "scope_exited", (root,), ("*.md",), ())
    assert fv.ref_within_member(root / "a.md", False, flat)
    assert not fv.ref_within_member(root / "sub" / "a.md", False, flat)
    anchored = fv.DecayedMember("s", "scope_exited", (root,), ("docs/*.md",), ())
    assert fv.ref_within_member(root / "docs" / "a.md", False, anchored)
    assert not fv.ref_within_member(root / "docs" / "sub" / "a.md", False, anchored)


@pytest.mark.parametrize("pattern", ["*.md", "**/*.md"])
def test_member_globs_match_producer_enumeration(tmp_path: Path, pattern: str) -> None:
    root = tmp_path / "member"
    files = [root / "file.md", root / "sub/dir/file.md", root / "sub/dir/file.py"]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    member = fv.DecayedMember("m", "scope_exited", (root,), (pattern,), ())
    # builtin.py:65-68: root.glob(pattern), then keep files.
    enumerated = {path for path in root.glob(pattern) if path.is_file()}
    for path in files:
        assert fv.ref_within_member(path, False, member) == (path in enumerated)


@pytest.mark.parametrize("scope_pattern", ["*.md", "sub/dir/*.md", "**/*.md"])
def test_flat_member_does_not_contain_nested_glob_scopes(
    tmp_path: Path, scope_pattern: str
) -> None:
    member = fv.DecayedMember("m", "scope_exited", (tmp_path,), ("*.md",), ())
    assert fv.ref_within_member(tmp_path, True, member, scope_pattern=scope_pattern) == (
        scope_pattern == "*.md"
    )


@pytest.mark.parametrize("pattern", ["[!a]", "[a!]", "[^a]", "[]a]", "[[]", "[a-c]", "[z-a]"])
def test_glob_classes_match_producer_enumeration(tmp_path: Path, pattern: str) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    paths = [docs / f"{char}.py" for char in "abcz!^[]-"]
    for path in paths:
        path.touch()
    glob = f"docs/{pattern}.py"
    member = fv.DecayedMember("m", "scope_exited", (tmp_path,), (glob,), ())
    enumerated = set(tmp_path.glob(glob))
    for path in paths:
        assert fv.ref_within_member(path, False, member) == (path in enumerated), path.name


def test_patterned_member_requires_the_entire_directory_or_wildcard_scope(tmp_path: Path) -> None:
    """A scope is inside only when every path it can name satisfies a member pattern."""
    council = tmp_path / "council"
    vault = tmp_path / "vault"
    (council / "docs").mkdir(parents=True)
    (council / "scripts").mkdir()
    vault.mkdir()
    members = [
        {
            "id": "docs",
            "location": {"path": str(council), "patterns": ["docs/**/*.md"]},
        }
    ]
    verdicts = fv.load_frame_verdicts(
        _procedure_root(
            tmp_path / "procedure", members=members, verdicts=[_verdict("docs", "scope_exited")]
        ),
        now=NOW,
    )

    def scope(ref: str) -> fv.ScopeVerdict:
        return fv.scope_within_decayed([ref], verdicts, council_root=council, vault_root=vault)

    assert scope("docs/**/*.md").all_inside
    assert scope("docs/guides/*.md").all_inside
    assert scope("scripts/**").outside == ("scripts/**",)
    assert scope("docs/**/*.py").outside == ("docs/**/*.py",)
    # Round 30: a canonical non-.md path proves this directory only partly contained.
    assert scope("docs/").outside == ("docs/",)


@pytest.mark.parametrize("populated", [False, True])
@pytest.mark.parametrize("base_alias", [False, True])
def test_glob_language_uses_the_canonical_root(
    tmp_path: Path, populated: bool, base_alias: bool
) -> None:
    root = tmp_path / "member"
    root.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    if populated:
        (root / "gawk").touch()
    member = fv.DecayedMember("m", "scope_exited", (root,), ("gawk",), ())
    base = alias if base_alias else root
    assert not fv.ref_within_member(base, True, member, scope_pattern="gaw*k")
    assert fv.ref_within_member(base / "gawk", False, member)
    assert fv.ref_within_member(base, True, member, scope_pattern="[g]awk")


@pytest.mark.parametrize(
    ("probe", "pattern", "injected"),
    [
        # EACCES: pathlib PROPAGATES this, so these rows exercise the handler. Kept, because a
        # handler that converts a propagated error into a remedy is a real obligation.
        ("is_dir", "a*", errno.EACCES),
        ("is_file", "a*", errno.EACCES),
        ("is_dir", "[a]wk", errno.EACCES),
        # ELOOP and EBADF: pathlib SUPPRESSES these and answers False, so only these rows
        # discriminate the unsuppressed classifiers. The coordinator caught that my rewrite
        # moved the layer and left the errno at EACCES while my report claimed both had
        # changed — the row could not have distinguished a suppressing classifier from a
        # correct one, which is the whole property it is here to hold.
        ("is_dir", "a*", errno.ELOOP),
        ("is_file", "a*", errno.ELOOP),
        ("is_dir", "[a]wk", errno.ELOOP),
        ("is_dir", "[a]wk", errno.EBADF),
    ],
)
def test_scope_expansion_file_type_failure_has_remedy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: str, pattern: str, injected: int
) -> None:
    target, alias = tmp_path / "gawk", tmp_path / "awk"
    target.touch()
    alias.symlink_to(target.name)
    member = fv.DecayedMember("m", "scope_exited", (tmp_path,), ("gawk",), ())

    # **The fault is injected at `os.stat`, the supplying boundary, not at the `Path` method.**
    # It used to replace `Path.is_dir` / `Path.is_file` directly, which stopped intercepting the
    # moment those calls moved to the unsuppressed classifiers — and, more to the point, was
    # never the layer that matters: those methods swallow the ignorable errnos themselves, so
    # faulting the METHOD exercises the handler while leaving the case where the method silently
    # answers False untested. Same correction as row R5c, which took three tries to discriminate
    # anything (review finding, codex, 2026-09-08). `probe` is kept as the parametrisation label
    # because it still names which classification the pattern reaches.
    original_stat = os.stat

    def denied(path, *args, **kwargs):
        if str(path) == str(alias):
            raise OSError(injected, "fixture stat denied", str(path))
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", denied)
    with pytest.raises(fv.UndecidableScopeContainment) as caught:
        fv.ref_within_member(tmp_path, True, member, scope_pattern=pattern)
    assert "containment is undecidable" in str(caught.value)
    assert ("scope glob expansion" if pattern == "a*" else "scope component") in str(caught.value)
    assert str(alias) in caught.value.remedy


def test_an_undecidable_pattern_union_refuses_instead_of_admitting(tmp_path: Path) -> None:
    council = tmp_path / "council"
    (council / "docs").mkdir(parents=True)
    members = [
        {
            "id": "samples",
            "location": {
                "path": str(council),
                "patterns": ["docs/scope", "docs/scope.py", "docs/scope.md"],
            },
        }
    ]
    verdicts = fv.load_frame_verdicts(
        _procedure_root(
            tmp_path / "procedure",
            members=members,
            verdicts=[_verdict("samples", "scope_exited")],
        ),
        now=NOW,
    )

    with pytest.raises(fv.NonCanonicalScopeRef, match="cannot be decided safely"):
        fv.scope_within_decayed(
            ["docs/*"], verdicts, council_root=council, vault_root=tmp_path / "vault"
        )


def test_mass_exclusions_are_subtracted_from_every_decayed_member(tmp_path: Path) -> None:
    """The consumer uses the producer's effective surface, including exact and prefix exclusions."""
    frame = tmp_path / "frame"
    procedure = frame / "procedure"
    frame.mkdir()
    members = [{"id": "vault-frame", "location": {"path": str(frame), "patterns": ["**/*.md"]}}]
    exclusions = [
        {"id": "coord", "paths": ["../../LOG.md"]},
        {"id": "runs", "paths": ["../_runs*"]},
    ]
    verdicts = fv.load_frame_verdicts(
        _procedure_root(
            procedure,
            members=members,
            verdicts=[_verdict("vault-frame", "scope_exited")],
            exclusions=exclusions,
        ),
        now=NOW,
    )
    council = tmp_path / "council"
    council.mkdir()

    def scope(ref: Path) -> fv.ScopeVerdict:
        return fv.scope_within_decayed(
            [str(ref)], verdicts, council_root=council, vault_root=tmp_path
        )

    assert scope(frame / "MASS.md").all_inside
    assert scope(frame / "LOG.md").outside == (str(frame / "LOG.md"),)
    prefixed = procedure / "_runs-next" / "receipt.md"
    assert scope(prefixed).outside == (str(prefixed),)


def test_skip_dirs_follow_producer_path_part_filtering(tmp_path: Path) -> None:
    root = tmp_path / "member"
    paths = [root / path for path in ("live/a.md", "skip/a.md", "live/skip/a.md", "skipper/a.md")]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    verdicts = fv.load_frame_verdicts(
        _procedure_root(
            tmp_path / "procedure",
            members=[
                {
                    "id": "m",
                    "location": {"path": str(root), "patterns": ["**/*.md"], "skip_dirs": ["skip"]},
                }
            ],
            verdicts=[_verdict("m", "scope_exited")],
        ),
        now=NOW,
    )
    member = verdicts.decayed[0]
    enumerated = {p for p in root.glob("**/*.md") if p.is_file() and "skip" not in p.parts}
    for path in paths:
        assert fv.ref_within_member(path, False, member) == (path in enumerated)
    for pattern, inside in [("**/*.md", False), ("live/*.md", True), ("*/a.md", False)]:
        assert fv.ref_within_member(root, True, member, scope_pattern=pattern) == inside


@pytest.mark.parametrize("kind", ["PROCEDURE", "VAULT"])
@pytest.mark.parametrize("value", [None, "", "  ", " ~/custom-frame-root "])
def test_frame_roots_support_environment_overrides(
    monkeypatch: pytest.MonkeyPatch, kind: str, value: str | None
) -> None:
    env = f"HAPAX_FRAME_{kind}_ROOT"
    if value is None:
        monkeypatch.delenv(env, raising=False)
    else:
        monkeypatch.setenv(env, value)
    get_root = fv.frame_procedure_root if kind == "PROCEDURE" else fv.frame_vault_root
    default = (
        fv.DEFAULT_FRAME_PROCEDURE_ROOT if kind == "PROCEDURE" else fv.DEFAULT_FRAME_VAULT_ROOT
    )
    assert get_root() == (Path(value.strip()) if value and value.strip() else default).expanduser()


def test_frame_fixture_restores_environment_when_teardown_is_interrupted(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.conftest import _frame_verdicts_default_root

    monkeypatch.setenv(fv.FRAME_PROCEDURE_ROOT_ENV, "/prior-procedure")
    fixture = _frame_verdicts_default_root.__wrapped__(tmp_path_factory)
    next(fixture)
    assert fv.frame_procedure_root() != Path("/prior-procedure")
    with pytest.raises(RuntimeError, match="interrupted teardown"):
        fixture.throw(RuntimeError("interrupted teardown"))
    assert fv.frame_procedure_root() == Path("/prior-procedure")


def test_an_unreadable_mass_exclusion_refuses_instead_of_disappearing(tmp_path: Path) -> None:
    members = [{"id": "m", "location": {"path": str(tmp_path / "m")}}]
    root = _procedure_root(
        tmp_path / "procedure",
        members=members,
        verdicts=[_verdict("m", "scope_exited")],
        exclusions=[{"id": "broken", "paths": [7]}],
    )

    with pytest.raises(fv.FrameVerdictsUnavailable, match="effective surface is undecidable"):
        fv.load_frame_verdicts(root, now=NOW)


def test_a_malformed_verdict_row_refuses_instead_of_shrinking_the_decayed_set(
    tmp_path: Path,
) -> None:
    """Skipping an unparseable row empties the decayed set and the guard admits everything —
    failing open at the one point it exists to fail closed."""
    members = [{"id": "m", "location": {"path": str(tmp_path / "m")}}]
    root = _procedure_root(tmp_path, members=members, verdicts=[_verdict("m", "scope_exited")])
    epoch = latest_epoch_dir(root)
    assert epoch is not None
    (epoch / "elements.json").write_text(
        json.dumps(
            [
                {
                    "id": "frame:relevance-report",
                    "payload": {"verdicts": [_verdict("m", "scope_exited"), "not a row"]},
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(fv.FrameVerdictsUnavailable, match="not a JSON object"):
        fv.load_frame_verdicts(root, now=NOW)


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (
            {"relation": "scope_exited", "verdict": True, "projection": "frame-reduction"},
            "subject object",
        ),
        (
            {
                "subject": [],
                "relation": "scope_exited",
                "verdict": True,
                "projection": "frame-reduction",
            },
            "subject object",
        ),
        (
            {
                "subject": {},
                "relation": "scope_exited",
                "verdict": True,
                "projection": "frame-reduction",
            },
            "subject.member_id",
        ),
        (
            {
                "subject": {"member_id": 7},
                "relation": "scope_exited",
                "verdict": True,
                "projection": "frame-reduction",
            },
            "subject.member_id",
        ),
        (
            {
                "subject": {"member_id": "m"},
                "relation": "scope_exited",
                "projection": "frame-reduction",
            },
            "invalid verdict",
        ),
        (
            {
                "subject": {"member_id": "m"},
                "relation": "scope_exited",
                "verdict": "maybe",
                "projection": "frame-reduction",
            },
            "invalid verdict",
        ),
        (
            {
                "subject": {"member_id": "m"},
                "relation": "scope_exited",
                "verdict": True,
            },
            "non-empty projection",
        ),
        (
            {
                "subject": {"member_id": "m"},
                "relation": "scope_exited",
                "verdict": True,
                "projection": "another-purpose",
            },
            "not the current mass projection",
        ),
    ],
    ids=[
        "missing-subject",
        "non-object-subject",
        "missing-member-id",
        "non-string-member-id",
        "missing-verdict",
        "invalid-verdict",
        "missing-projection",
        "wrong-projection",
    ],
)
def test_malformed_verdict_dictionaries_refuse(
    tmp_path: Path, row: dict[str, object], message: str
) -> None:
    members = [{"id": "m", "location": {"path": str(tmp_path / "m")}}]
    root = _procedure_root(tmp_path, members=members, verdicts=[row])

    with pytest.raises(fv.FrameVerdictsUnavailable, match=message):
        fv.load_frame_verdicts(root, now=NOW)


def test_an_incomplete_or_duplicate_verdict_matrix_refuses(tmp_path: Path) -> None:
    members = [{"id": "m", "location": {"path": str(tmp_path / "m")}}]
    root = _procedure_root(tmp_path, members=members, verdicts=[])
    epoch = latest_epoch_dir(root)
    assert epoch is not None
    elements = json.loads((epoch / "elements.json").read_text(encoding="utf-8"))
    rows = elements[1]["payload"]["verdicts"]
    removed = rows.pop()
    (epoch / "elements.json").write_text(json.dumps(elements), encoding="utf-8")

    with pytest.raises(fv.FrameVerdictsUnavailable, match="verdict matrix is incomplete"):
        fv.load_frame_verdicts(root, now=NOW)

    rows.append(removed)
    rows.append(dict(removed))
    (epoch / "elements.json").write_text(json.dumps(elements), encoding="utf-8")
    with pytest.raises(fv.FrameVerdictsUnavailable, match="duplicate verdicts"):
        fv.load_frame_verdicts(root, now=NOW)


@pytest.mark.parametrize("value", [True, False, "UNKNOWN"])
def test_a_verdict_under_an_unknown_relation_refuses(tmp_path: Path, value: object) -> None:
    """The producer's relation set can grow; a reader that silently ignores what it does not
    classify decides accountability by omission."""
    members = [{"id": "m", "location": {"path": str(tmp_path / "m")}}]
    root = _procedure_root(
        tmp_path, members=members, verdicts=[_verdict("m", "invented_relation", value)]
    )

    with pytest.raises(fv.FrameVerdictsUnavailable, match="does not classify"):
        fv.load_frame_verdicts(root, now=NOW)


def test_the_decay_set_is_the_producers_seven_not_a_private_three(tmp_path: Path) -> None:
    assert {
        "superseded",
        "discharged",
        "scope_exited",
        "absorbed",
        "contradicted",
        "context_lost",
        "unconsulted",
    } == fv.DECAY_RELATIONS
    members = [{"id": "m", "location": {"path": str(tmp_path / "m")}}]
    root = _procedure_root(
        tmp_path, members=members, verdicts=[_verdict("m", "context_lost", True)]
    )

    verdicts = fv.load_frame_verdicts(root, now=NOW)

    assert [(m.member_id, m.relation) for m in verdicts.decayed] == [("m", "context_lost")]


def test_a_ref_that_climbs_out_of_its_tree_is_refused(tmp_path: Path) -> None:
    council, vault = tmp_path / "c", tmp_path / "v"
    (council / "scripts").mkdir(parents=True)
    vault.mkdir()

    with pytest.raises(fv.NonCanonicalScopeRef, match=r"\.\."):
        fv.resolve_scope_ref("scripts/../../elsewhere/x.py", council_root=council, vault_root=vault)


def test_a_symlinked_member_root_and_ref_resolve_to_the_same_surface(tmp_path: Path) -> None:
    council, vault = tmp_path / "c", tmp_path / "v"
    real = tmp_path / "outside"
    (real / "deep").mkdir(parents=True)
    council.mkdir()
    vault.mkdir()
    (council / "legacy").symlink_to(real)
    members = [{"id": "legacy", "location": {"path": str(council / "legacy")}}]
    verdicts = fv.load_frame_verdicts(
        _procedure_root(tmp_path, members=members, verdicts=[_verdict("legacy", "scope_exited")]),
        now=NOW,
    )

    scope = fv.scope_within_decayed(
        ["legacy/deep/x.py"], verdicts, council_root=council, vault_root=vault
    )

    assert scope.all_inside, scope
    assert verdicts.decayed[0].roots == (real.resolve(),)


@pytest.mark.parametrize("kind", ["member", "nonmember", "outside"])
def test_validate_task_in_root_alias_uses_canonical_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    from tests.scripts.test_hapax_methodology_dispatch import (
        _dispatcher_module,
        _frame_procedure_root,
        _governed_source_frontmatter,
        _spec,
        _task,
    )

    module = _dispatcher_module()
    root = tmp_path / "member"
    (root / "bin").mkdir(parents=True)
    selected = root / "bin/gawk"
    selected.write_bytes(b"selected bytes\n")
    target = selected if kind == "member" else (root if kind == "nonmember" else tmp_path) / "other"
    if target != selected:
        target.write_bytes(b"accountable bytes\n")
    alias = root / "bin/awk"
    alias.symlink_to(target)
    read = {selected: selected.read_bytes()}
    frame_root = _frame_procedure_root(
        tmp_path / "frame",
        decayed_root=root,
        reader="fs.glob",
        location={"path": str(root), "patterns": ["bin/gawk"]},
    )
    monkeypatch.setenv("HAPAX_FRAME_PROCEDURE_ROOT", str(frame_root))
    for index, path in enumerate((alias, target)):
        task_id = f"alias-{index}"
        _task(
            tmp_path / "tasks",
            task_id,
            _governed_source_frontmatter(
                _spec(tmp_path / "spec.md"), mutation_scope_refs=json.dumps([str(path)])
            ),
        )
        result = module.validate_task(
            task_id=task_id,
            lane="cx-green",
            platform="codex",
            task_root=tmp_path / "tasks",
            strict_worktree=False,
        )
        inside = path.resolve(strict=True) in read
        assert result.ok is (not inside), result.reason
        assert (
            "marks every declared mutation surface out of accountability" in result.reason
        ) is inside


def test_a_symlinked_explicit_member_file_and_ref_resolve_to_the_same_file(tmp_path: Path) -> None:
    council, vault = tmp_path / "c", tmp_path / "v"
    real = tmp_path / "outside" / "real.py"
    real.parent.mkdir(parents=True)
    real.write_text("pass\n", encoding="utf-8")
    council.mkdir()
    vault.mkdir()
    (council / "alias.py").symlink_to(real)
    members = [{"id": "one-file", "location": {"files": [str(council / "alias.py")]}}]
    verdicts = fv.load_frame_verdicts(
        _procedure_root(tmp_path, members=members, verdicts=[_verdict("one-file", "scope_exited")]),
        now=NOW,
    )

    scope = fv.scope_within_decayed(["alias.py"], verdicts, council_root=council, vault_root=vault)

    assert scope.all_inside, scope
    assert verdicts.decayed[0].files == (real.resolve(),)


def test_a_verdict_is_not_applied_to_a_member_redeclared_since_the_epoch(tmp_path: Path) -> None:
    """The verdict was computed against the member as the epoch declared it; applying it to a
    member since re-pointed would decay a surface nobody witnessed."""
    members = [{"id": "m", "location": {"path": str(tmp_path / "m"), "patterns": ["*.py"]}}]
    root = _procedure_root(tmp_path, members=members, verdicts=[_verdict("m", "scope_exited")])
    epoch = latest_epoch_dir(root)
    assert epoch is not None
    matching = fv._member_declaration_identity(members[0], [])
    (epoch / "coverage.json").write_text(
        json.dumps([{"member_id": "m", "member_declaration_identity": matching}]),
        encoding="utf-8",
    )
    assert [m.member_id for m in fv.load_frame_verdicts(root, now=NOW).decayed] == ["m"]

    (root / "declaration" / "mass.yaml").write_text(
        yaml.safe_dump(
            {
                "projection": "frame-reduction",
                "members": [{"id": "m", "location": {"path": str(tmp_path / "elsewhere")}}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(fv.FrameVerdictsUnavailable, match="declaration identity changed.*'m'"):
        fv.load_frame_verdicts(root, now=NOW)


def test_identity_drift_on_a_non_decayed_member_also_refuses(tmp_path: Path) -> None:
    members = [
        {"id": "decayed", "location": {"path": str(tmp_path / "gone")}},
        {"id": "healthy", "location": {"path": str(tmp_path / "live")}},
    ]
    root = _procedure_root(
        tmp_path,
        members=members,
        verdicts=[
            _verdict("decayed", "scope_exited", True),
            _verdict("healthy", "scope_exited", False),
        ],
    )
    members[1]["location"] = {"path": str(tmp_path / "moved")}
    (root / "declaration" / "mass.yaml").write_text(
        yaml.safe_dump({"projection": "frame-reduction", "members": members}), encoding="utf-8"
    )

    with pytest.raises(fv.FrameVerdictsUnavailable, match="declaration identity changed.*healthy"):
        fv.load_frame_verdicts(root, now=NOW)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing-file", "is missing"),
        ("non-list", "must contain a JSON list"),
        ("non-object-row", "row 0 is not a JSON object"),
        ("missing-identity", "has no declaration identity"),
        ("partial", "missing members=.*healthy"),
        ("extra", "undeclared members=.*vanished"),
        ("duplicate", "duplicate bindings"),
    ],
)
def test_coverage_must_bind_every_current_member_exactly_once(
    tmp_path: Path, mutation: str, message: str
) -> None:
    members = [
        {"id": "decayed", "location": {"path": str(tmp_path / "gone")}},
        {"id": "healthy", "location": {"path": str(tmp_path / "live")}},
    ]
    root = _procedure_root(
        tmp_path, members=members, verdicts=[_verdict("decayed", "scope_exited", True)]
    )
    epoch = latest_epoch_dir(root)
    assert epoch is not None
    coverage_path = epoch / "coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    if mutation == "missing-file":
        coverage_path.unlink()
    elif mutation == "non-list":
        coverage_path.write_text(json.dumps({"coverage": coverage}), encoding="utf-8")
    elif mutation == "non-object-row":
        coverage_path.write_text(json.dumps(["bad row", *coverage[1:]]), encoding="utf-8")
    elif mutation == "missing-identity":
        coverage[0].pop("member_declaration_identity")
        coverage_path.write_text(json.dumps(coverage), encoding="utf-8")
    elif mutation == "partial":
        coverage_path.write_text(json.dumps(coverage[:1]), encoding="utf-8")
    elif mutation == "extra":
        coverage.append({"member_id": "vanished", "member_declaration_identity": "declaration:x"})
        coverage_path.write_text(json.dumps(coverage), encoding="utf-8")
    elif mutation == "duplicate":
        coverage.append(dict(coverage[0]))
        coverage_path.write_text(json.dumps(coverage), encoding="utf-8")

    with pytest.raises(fv.FrameVerdictsUnavailable, match=message):
        fv.load_frame_verdicts(root, now=NOW)


def test_member_declaration_identity_matches_a_real_epoch() -> None:
    """The identity is the producer's own rule, copied because the producer lives in another tree.
    This pins that the copy still reproduces a real epoch's recorded value."""
    procedure = Path.home() / "Documents/Personal/30-areas/hapax/frame/procedure"
    coverage_files = (
        sorted((procedure / "_runs" / "epochs").glob("*/coverage.json"), reverse=True)
        if (procedure / "_runs" / "epochs").is_dir()
        else []
    )
    if not coverage_files:
        pytest.skip("no local frame epoch to check the identity rule against")
    rows = json.loads(coverage_files[0].read_text(encoding="utf-8"))
    mass = yaml.safe_load((procedure / "declaration" / "mass.yaml").read_text(encoding="utf-8"))
    by_id = {m["id"]: m for m in mass["members"]}
    exclusions = mass.get("exclusions") or []
    checked = 0
    for row in rows:
        recorded = row.get("member_declaration_identity")
        member = by_id.get(row.get("member_id"))
        if not recorded or member is None:
            continue
        assert fv._member_declaration_identity(member, exclusions) == recorded, row["member_id"]
        checked += 1
    assert checked, "no member could be checked — the coverage rows carry no identities"


def _load_literal_digest(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    digest = lines[0].partition("#")[0].strip()
    assert re.fullmatch(r"[0-9a-f]{64}", digest), path
    return digest


def _strip_json_line_comments(text: str) -> str:
    """Preserve JSON strings and newlines; remove comment separators and line comments."""
    return re.sub(
        r'"(?:\\.|[^"\\])*"|[ \t]*//[^\r\n]*',
        lambda match: match[0] if match[0].startswith('"') else "",
        text,
    )


def _load_verified_jsonc(path: Path) -> dict[str, object]:
    canonical = _strip_json_line_comments(path.read_bytes().decode("utf-8")).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == _load_literal_digest(
        path.with_suffix(".sha256.txt")
    )
    return json.loads(canonical)


def test_json_line_comments_preserve_strings_and_original_line_endings() -> None:
    canonical = r'{"url": "gh://fixture/notes", "escaped": "quote\"//text", "slash": "\\"}'
    for newline in ("\n", "\r\n", ""):
        annotated = canonical + "  // pragma: allowlist secret" + newline
        assert _strip_json_line_comments(annotated) == canonical + newline
        assert json.loads(_strip_json_line_comments(annotated)) == json.loads(canonical)


def test_producer_read_result_fixture_preserves_recorded_bytes() -> None:
    fixture = Path(__file__).parent / "fixtures/frame-producer-identity"
    observed = _load_verified_jsonc(fixture / "read-result.jsonc")
    assert observed["enumerated_units"] == 4
    assert observed["excluded_units"] == 1
    assert observed["bytes_read"] == 9
    assert {
        row["unit_id"]: bytes.fromhex(row["content_hex"]) for row in observed["observations"]
    } == {"nested/two.md": "λ\n".encode(), "one.md": "café\n".encode()}
    assert observed["residue"] == [
        "tree/excluded/generated.md: excluded-by-declaration "
        "(fixture-generated, receipt fixture:generated-residue)"
    ]


def test_member_declaration_identity_matches_literal_producer_fixture() -> None:
    fixture = Path(__file__).parent / "fixtures/frame-producer-identity"
    mass = json.loads((fixture / "mass.json").read_bytes())
    canonical = (fixture / "declaration.canonical.json").read_bytes()
    expected = "declaration:" + _load_literal_digest(fixture / "declaration.digest.txt")
    assert json.loads(canonical) == {"member": mass["members"][0], "exclusions": mass["exclusions"]}
    assert "declaration:" + hashlib.sha256(canonical).hexdigest() == expected
    assert fv._member_declaration_identity(mass["members"][0], mass["exclusions"]) == expected


def test_explicit_file_glob_through_symlinked_parent_retains_round_five_refusal(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    file = target / "dead.yaml"
    file.touch()
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    member = fv.DecayedMember("m", "scope_exited", (), (), (file,))
    with pytest.raises(fv.UndecidableScopeContainment, match="matches declared member file"):
        fv.ref_within_member(alias, True, member, scope_pattern="*.yaml")


@pytest.mark.parametrize("kind", ["escape", "dangling", "loop"])
@pytest.mark.parametrize("ref", ["alias.py", "[a]lias.py", "*.py"])
def test_patterned_symlink_ambiguity_names_the_link_and_target(
    tmp_path: Path, kind: str, ref: str
) -> None:
    council = tmp_path / "council"
    council.mkdir()
    link = council / "alias.py"
    target = link if kind == "loop" else tmp_path / "target"
    if kind == "escape":
        target.touch()
    link.symlink_to(target)
    member = fv.DecayedMember("m", "scope_exited", (council,), ("*.py",), ())
    verdicts = fv.FrameVerdicts("fixture", tmp_path, NOW, (member,), ())
    with pytest.raises(fv.UndecidableScopeContainment) as caught:
        fv.scope_within_decayed([ref], verdicts, council_root=council, vault_root=tmp_path)
    assert str(link) in str(caught.value)
    assert str(target) in str(caught.value)
    assert str(link) in caught.value.remedy
    assert str(target) in caught.value.remedy


def test_recursive_member_pattern_does_not_prove_traversal_of_a_directory_symlink(
    tmp_path: Path,
) -> None:
    (tmp_path / "target").mkdir()
    (tmp_path / "target/old.py").touch()
    (tmp_path / "alias").symlink_to(tmp_path / "target", target_is_directory=True)
    selected = tmp_path / "alias/old.py"
    assert selected in set(tmp_path.glob("alias/*.py"))
    assert selected not in set(tmp_path.glob("**/*.py"))
    member = fv.DecayedMember("m", "scope_exited", (tmp_path,), ("**/*.py",), ())
    with pytest.raises(fv.UndecidableScopeContainment, match="directory symlink"):
        fv.ref_within_member(selected, False, member)


def test_disjoint_alias_checks_the_selected_canonical_surface(tmp_path: Path) -> None:
    root = tmp_path / "member"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file").write_bytes(b"selected bytes")
    (root / "selected").symlink_to(outside, target_is_directory=True)
    alias = root / "alias"
    alias.symlink_to("selected/file")
    member = fv.DecayedMember("m", "scope_exited", (root,), ("selected/*",), ())
    # The lexical alias is disjoint, but its bytes belong to an escaping selection.
    # This guard must inspect that selection itself, before any caller's fallback.
    with pytest.raises(fv.UndecidableScopeContainment, match="escapes member root") as caught:
        fv._check_member_symlinks(alias, root, member, scope_pattern=None)
    assert str(root / "selected") in str(caught.value)


def test_disjoint_alias_checks_canonical_exclusions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, alias = tmp_path / "selected", tmp_path / "alias"
    target.write_bytes(b"selected bytes")
    alias.symlink_to(target.name)
    member = fv.DecayedMember("m", "scope_exited", (tmp_path,), ("selected",), ())
    checked = []
    original = fv._path_is_excluded

    def observe(path, selected_member):
        checked.append(path)
        return original(path, selected_member)

    monkeypatch.setattr(fv, "_path_is_excluded", observe)
    assert not fv._check_member_symlinks(alias, tmp_path, member, scope_pattern=None)
    assert target in checked


def test_disjoint_directory_alias_undecidable_names_component(tmp_path: Path) -> None:
    target, alias = tmp_path / "selected", tmp_path / "alias"
    target.mkdir()
    (target / "sample").write_bytes(b"selected bytes")
    alias.symlink_to(target.name, target_is_directory=True)
    member = fv.DecayedMember("m", "scope_exited", (tmp_path,), ("selected/s*",), ())
    with pytest.raises(fv.UndecidableScopeContainment) as caught:
        fv._check_member_symlinks(alias, tmp_path, member, scope_pattern="*")
    assert str(alias) in str(caught.value)
    assert str(target) in str(caught.value)


def test_canonical_surfaces_contain_only_producer_files(tmp_path: Path) -> None:
    root = tmp_path / "member"
    (root / "selected").mkdir(parents=True)
    (root / "selected/file").write_bytes(b"selected bytes")
    (root / "unrelated").mkdir()
    alias = root / "tools"
    alias.symlink_to("unrelated", target_is_directory=True)
    member = fv.DecayedMember("m", "scope_exited", (root,), ("selected/**/*", "tools"), ())
    assert fv._canonical_member_entries(member) == {root / "selected/file": root / "selected/file"}
    assert fv._canonical_scope_entries(root, "**", member) == {}


@pytest.mark.parametrize("ref", [".venv/bin/python", ".venv/bin/[p]ython"])
def test_disjoint_loop_literal_requires_canonical_resolution(tmp_path: Path, ref: str) -> None:
    (tmp_path / ".venv/bin").mkdir(parents=True)
    link = tmp_path / ".venv/bin/python"
    link.symlink_to(link)
    (tmp_path / "docs").mkdir()
    document = tmp_path / "docs/x.md"
    document.touch()
    pattern = "./docs//**/*.md"
    assert set(tmp_path.glob(pattern)) == {document}
    member = fv.DecayedMember(
        "m",
        "scope_exited",
        (tmp_path,),
        (pattern,),
        (),
        excluded_roots=(tmp_path / "unrelated",),
    )
    verdicts = fv.FrameVerdicts("fixture", tmp_path, NOW, (member,), ())

    # Neither the literal nor the equivalent singleton glob may skip target resolution.
    with pytest.raises(fv.UndecidableScopeContainment) as caught:
        fv.scope_within_decayed([ref], verdicts, council_root=tmp_path, vault_root=tmp_path)
    assert str(link) in str(caught.value)
    assert "cannot resolve scope component" in str(caught.value)
    assert str(link) in caught.value.remedy and "intended target" in caught.value.remedy


@pytest.mark.parametrize(
    ("scope_pattern", "alias"),
    [
        ("**/*.py", False),
        ("**/bin/site_perl/*.py", False),
        ("**/s?in/site_perl/new.py", True),
        ("**/[s-s]bin/site_perl/*.py", True),
        ("s?in/site_perl/**/*.py", True),
        ("[s-s]bin/site_perl/*.py", True),
    ],
)
@pytest.mark.parametrize("relative_base", ["", "local"], ids=["root", "nested-base"])
def test_in_root_recursive_glob_only_resolves_alias_prefixes(
    tmp_path: Path, scope_pattern: str, alias: bool, relative_base: str
) -> None:
    root = tmp_path / "usr"
    base = root / relative_base
    (base / "bin/site_perl").mkdir(parents=True)
    (base / "sbin").symlink_to("bin", target_is_directory=True)
    pattern = (Path(relative_base) / "bin/site_perl/**/*").as_posix()
    member = fv.DecayedMember("m", "scope_exited", (root,), (pattern,), ())
    assert not list(base.glob(scope_pattern))
    if alias:
        with pytest.raises(fv.UndecidableScopeContainment, match="scope_containment_undecidable"):
            fv.ref_within_member(base, True, member, scope_pattern=scope_pattern)
    else:
        # Resolving ordinary directories must not erase the recursive language;
        # these scopes can also select future files outside the declared surface.
        assert not fv.ref_within_member(base, True, member, scope_pattern=scope_pattern)


@pytest.mark.parametrize("skip", ["alias", "target"])
def test_patterned_symlink_skip_dirs_use_lexical_parts(tmp_path: Path, skip: str) -> None:
    (tmp_path / "target").mkdir()
    (tmp_path / "target/old.py").touch()
    (tmp_path / "alias").symlink_to(tmp_path / "target", target_is_directory=True)
    member = fv.DecayedMember(
        "m", "scope_exited", (tmp_path,), ("alias/*.py",), (), skip_dirs=(skip,)
    )
    selected = tmp_path / "alias/old.py"
    assert selected in set(tmp_path.glob("alias/*.py"))
    assert fv.ref_within_member(selected, False, member) is (skip == "target")


def test_patterned_symlink_exclusions_use_the_resolved_target(tmp_path: Path) -> None:
    (tmp_path / "excluded").mkdir()
    target = tmp_path / "excluded/old.py"
    target.touch()
    link = tmp_path / "alias.py"
    link.symlink_to(target)
    member = fv.DecayedMember(
        "m",
        "scope_exited",
        (tmp_path,),
        ("alias.py",),
        (),
        excluded_roots=(tmp_path / "excluded",),
    )
    assert link in set(tmp_path.glob("alias.py"))
    assert not fv.ref_within_member(link, False, member)


@pytest.mark.parametrize("escape", [False, True])
def test_patterned_symlink_in_an_equivalent_checkout_preserves_its_entry(
    tmp_path: Path, escape: bool
) -> None:
    canonical, running = tmp_path / "canonical", tmp_path / "running"
    git_checkout(canonical, history="council")
    git_checkout(running, history="council")
    target = (tmp_path if escape else canonical) / "target"
    target.touch()
    (canonical / "alias.py").symlink_to(target)
    member = fv.DecayedMember("m", "scope_exited", (canonical,), ("alias.py",), ())
    verdicts = fv.FrameVerdicts("fixture", tmp_path, NOW, (member,), ())
    if escape:
        with pytest.raises(fv.UndecidableScopeContainment, match="escapes member root"):
            fv.scope_within_decayed(["alias.py"], verdicts, council_root=running)
    else:
        scope = fv.scope_within_decayed(["alias.py"], verdicts, council_root=running)
        assert scope.all_inside


@pytest.mark.parametrize(
    ("member_dir", "scope_pattern", "overlaps"),
    [
        ("legacy", "[l]egacy/*.py", True),
        ("legacy", "leg?cy/*.py", True),
        ("legacy", "*/old.py", True),
        ("legacy", "**/*.py", True),
        ("legacy", "[l]egacy/**/old.py", True),
        ("legacy", "[l]egacy/[!a].py", True),
        ("archive/legacy", "*/[l]egacy/*.py", True),
        ("archive/legacy", "[a]rchive/leg?cy/*.py", True),
        ("archive/legacy", "**/[l]egacy/*.py", True),
        ("legacy", "[x]egacy/*.py", False),
        ("legacy", "*.py", False),
        ("archive/legacy", "*/[x]egacy/*.py", False),
    ],
)
def test_glob_components_before_member_root_do_not_guess_containment(
    tmp_path: Path, member_dir: str, scope_pattern: str, overlaps: bool
) -> None:
    council = tmp_path / "council"
    member_root = council / member_dir
    member_root.mkdir(parents=True)
    (member_root / "old.py").touch()
    (member_root / "b.py").touch()
    for relative in ("live/old.py", "xegacy/old.py", "archive/xegacy/old.py", "live.py"):
        file = council / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.touch()
    members = [{"id": "legacy", "location": {"path": str(member_root), "patterns": ["**/*.py"]}}]
    verdicts = fv.load_frame_verdicts(
        _procedure_root(
            tmp_path / "procedure", members=members, verdicts=[_verdict("legacy", "scope_exited")]
        ),
        now=NOW,
    )
    # Producer oracle: root.glob(pattern), retaining files, anchored at each root.
    enumerated = {file for file in member_root.glob("**/*.py") if file.is_file()}
    scope_files = {file for file in council.glob(scope_pattern) if file.is_file()}
    assert scope_files
    assert bool(scope_files & enumerated) is overlaps
    assert fv.scope_within_decayed(
        [f"{member_dir}/*.py"], verdicts, council_root=council
    ).all_inside

    if overlaps:
        with pytest.raises(fv.UndecidableScopeContainment) as caught:
            fv.scope_within_decayed([scope_pattern], verdicts, council_root=council)
        assert scope_pattern in str(caught.value)
        assert str(member_root) in str(caught.value)
        assert "explicit file paths or narrower globs" in caught.value.remedy
    else:
        result = fv.scope_within_decayed([scope_pattern], verdicts, council_root=council)
        assert not result.all_inside
        assert result.matches == ()
        assert result.outside == (scope_pattern,)


@pytest.mark.parametrize(
    "ref",
    [
        "podium:.local/share/[x]pencode/x",
        "podium:.local/share/*.py",
        "podium:.local/elsewhere/[o]pencode/x",
        "other:.local/share/[o]pencode/x",
        "podium:/.local/share/[o]pencode/x",
        "podium://host/.local/share/[o]pencode/x",
    ],
)
def test_qualified_globs_disjoint_from_member_roots_are_outside(tmp_path: Path, ref: str) -> None:
    root = _procedure_root(
        tmp_path,
        members=[{"id": "m", "location": {"path": "podium:.local/share/opencode"}}],
        verdicts=[_verdict("m", "scope_exited")],
    )
    result = fv.scope_within_decayed(
        [ref], fv.load_frame_verdicts(root, now=NOW), council_root=tmp_path / "council"
    )
    assert not result.all_inside
    assert result.matches == ()
    assert result.outside == (ref,)


@pytest.mark.parametrize("namespace", ["filesystem", "podium:", "gh://hapax-systems/"])
@pytest.mark.parametrize(
    "pattern", ["config/[l]ive.yaml", "config/*/*.yaml", "[x]onfig/*.yaml", "elsewhere/[d]ead.yaml"]
)
def test_explicit_file_globs_disjoint_by_path_parts_are_outside(
    tmp_path: Path, namespace: str, pattern: str
) -> None:
    council = tmp_path / "council"
    declared = (
        str(council / "config/dead.yaml")
        if namespace == "filesystem"
        else namespace + "config/dead.yaml"
    )
    ref = pattern if namespace == "filesystem" else namespace + pattern
    root = _procedure_root(
        tmp_path,
        members=[{"id": "m", "location": {"files": [declared]}}],
        verdicts=[_verdict("m", "scope_exited")],
    )
    result = fv.scope_within_decayed(
        [ref], fv.load_frame_verdicts(root, now=NOW), council_root=council
    )
    assert not result.all_inside
    assert result.matches == ()
    assert result.outside == (ref,)


@pytest.mark.parametrize(
    "ref",
    [
        "other:config/[d]ead.yaml",
        "podium:/config/[d]ead.yaml",
        "podium://host/config/[d]ead.yaml",
    ],
)
def test_explicit_file_globs_in_other_namespaces_are_outside(tmp_path: Path, ref: str) -> None:
    root = _procedure_root(
        tmp_path,
        members=[{"id": "m", "location": {"files": ["podium:config/dead.yaml"]}}],
        verdicts=[_verdict("m", "scope_exited")],
    )
    result = fv.scope_within_decayed(
        [ref], fv.load_frame_verdicts(root, now=NOW), council_root=tmp_path / "council"
    )
    assert not result.all_inside
    assert result.matches == ()
    assert result.outside == (ref,)


@pytest.mark.parametrize("exclusion", ["skip_dirs", "root", "prefix"])
def test_explicit_file_globs_do_not_include_excluded_files(tmp_path: Path, exclusion: str) -> None:
    council = tmp_path / "council"
    file = council / "config/dead.yaml"
    member = fv.DecayedMember(
        "m",
        "scope_exited",
        (),
        (),
        (file,),
        skip_dirs=("config",) if exclusion == "skip_dirs" else (),
        excluded_roots=(file.parent,) if exclusion == "root" else (),
        excluded_prefixes=(file.parent / "dead",) if exclusion == "prefix" else (),
        lexical_files=(file,),
    )
    assert not fv.ref_within_member(file, False, member)
    assert not fv.ref_within_member(file.parent, True, member, scope_pattern="[d]ead.yaml")


@pytest.mark.parametrize("identity", ["unrelated", "missing", "invalid", "unverified-source"])
def test_repo_relative_scope_does_not_count_an_unverified_repository(
    tmp_path: Path, identity: str
) -> None:
    council = tmp_path / "council"
    unrelated = tmp_path / "unrelated-repo"
    if identity == "unverified-source":
        (council / ".git").mkdir(parents=True)
        git_checkout(unrelated, history="council")
    else:
        git_checkout(council, history="council")
    if identity == "unrelated":
        git_checkout(unrelated, history="unrelated")
    elif identity == "invalid":
        (unrelated / ".git").mkdir(parents=True)
    (council / "docs").mkdir()
    (unrelated / "docs").mkdir(parents=True)
    members = [{"id": "unrelated-docs", "location": {"path": str(unrelated / "docs")}}]
    verdicts = fv.load_frame_verdicts(
        _procedure_root(
            tmp_path / "procedure",
            members=members,
            verdicts=[_verdict("unrelated-docs", "scope_exited")],
        ),
        now=NOW,
    )

    scope = fv.scope_within_decayed(
        ["docs/live.md"], verdicts, council_root=council, vault_root=tmp_path / "vault"
    )

    assert not scope.all_inside
    assert scope.matches == ()
    assert scope.outside == ("docs/live.md",)


def test_a_repo_relative_ref_matches_a_member_declared_at_another_checkout(tmp_path: Path) -> None:
    """In production the dispatcher runs from the activation worktree while the mass declares the
    canonical checkout; a ref resolved only against the running tree could never match, leaving the
    guard inert exactly where it runs."""
    canonical = tmp_path / "projects" / "hapax-council"
    running = tmp_path / "source-activation" / "releases" / "43b8c76a31"  # pragma: allowlist secret
    git_checkout(canonical, history="council")
    git_checkout(running, history="council")
    (canonical / "legacy").mkdir(parents=True)
    (running / "legacy").mkdir(parents=True)
    assert canonical.name != running.name
    members = [{"id": "legacy", "location": {"path": str(canonical / "legacy")}}]
    verdicts = fv.load_frame_verdicts(
        _procedure_root(tmp_path, members=members, verdicts=[_verdict("legacy", "scope_exited")]),
        now=NOW,
    )

    scope = fv.scope_within_decayed(
        ["legacy/old.py"], verdicts, council_root=running, vault_root=tmp_path / "vault"
    )

    assert scope.all_inside, scope
    assert scope.matches[0].member_id == "legacy"


@pytest.mark.parametrize("source", ["explicit", "environment", "default"])
@pytest.mark.parametrize("state", ["stale", "missing-root", "missing-current", "missing-elements"])
def test_unavailable_frame_evidence_binds_resolved_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str, state: str
) -> None:
    reasons = []
    for name in ("frame-a", "frame-b"):
        root = tmp_path / name
        epoch_name = None
        if state in {"stale", "missing-elements"}:
            at = NOW - timedelta(seconds=fv.FRAME_EPOCH_MAX_AGE_S + 1) if state == "stale" else NOW
            _procedure_root(root, members=[], verdicts=[], at=at)
            epoch = (root / "_runs/current").resolve()
            epoch_name = epoch.name
            if state == "missing-elements":
                (epoch / "elements.json").unlink()
        elif state == "missing-current":
            root.mkdir()
        # Resolve a relative symlink, including a dangling one for an absent root.
        alias = tmp_path / (name + "-alias")
        alias.symlink_to(root, target_is_directory=True)
        monkeypatch.chdir(tmp_path)
        relative_alias = Path(alias.name)
        if source == "environment":
            monkeypatch.setenv(fv.FRAME_PROCEDURE_ROOT_ENV, f" {relative_alias} ")
        elif source == "default":
            monkeypatch.delenv(fv.FRAME_PROCEDURE_ROOT_ENV, raising=False)
            monkeypatch.setattr(fv, "DEFAULT_FRAME_PROCEDURE_ROOT", relative_alias)
        else:
            monkeypatch.setenv(fv.FRAME_PROCEDURE_ROOT_ENV, str(tmp_path / "unrelated"))

        with pytest.raises(fv.FrameVerdictsUnavailable) as caught:
            fv.load_frame_verdicts(relative_alias if source == "explicit" else None, now=NOW)

        error = caught.value
        assert error.frame_root_resolved == str(root.resolve())
        assert error.frame_epoch == epoch_name
        assert f"frame_root_resolved={root.resolve()}" in error.reason
        if state == "stale":
            assert error.remedy == _expected_stale_remedy(root.resolve())
        else:
            assert error.remedy == _expected_producer_remedy(root.resolve())
        reasons.append(error.reason)
    assert reasons[0] != reasons[1]
