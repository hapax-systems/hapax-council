"""shared/frame_verdicts.py — the frame's verdicts read at a work-selection point."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from shared import frame_verdicts as fv
from tests.frame_verdict_helpers import git_checkout, latest_epoch_dir, producer_glob_bytes

NOW = datetime(2026, 9, 3, 22, 30, tzinfo=UTC)


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
        result = fv.scope_within_decayed(
            [f"{location}/{name}"], verdicts, council_root=tmp_path, vault_root=tmp_path
        )
        assert result.all_inside == (name in selected), (patterns, name, selected, result)


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
        {"roots": ["podium:store"]},
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
def test_invalid_calendar_epoch_refuses_with_the_producer_remedy(
    tmp_path: Path, stamp: str
) -> None:
    name = f"{stamp}-deadbeef"
    epoch = tmp_path / "_runs/epochs" / name
    epoch.mkdir(parents=True)
    (tmp_path / "_runs/current").symlink_to(Path("epochs") / name)

    for read in (fv.current_epoch_dir, fv.load_frame_verdicts):
        with pytest.raises(fv.FrameVerdictsUnavailable, match="names invalid epoch") as caught:
            read(tmp_path)
        assert name in caught.value.reason
        assert caught.value.remedy == fv.PRODUCER_REMEDY
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


def test_epoch_older_than_two_cadences_refuses_and_younger_does_not(tmp_path: Path) -> None:
    limit = timedelta(seconds=fv.FRAME_EPOCH_MAX_AGE_S)
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
    assert "the producer has stopped" in excinfo.value.reason


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
    # Broad directory and wildcard refs also name non-.py files, so they are only partly inside.
    assert scope("legacy/**").outside == ("legacy/**",)
    assert scope("legacy/**/*.py").outside == ("legacy/**/*.py",)
    assert scope("legacy/sub/").outside == ("legacy/sub/",)
    # partly inside: admitted (moving things out of a decayed member is legitimate work)
    mixed = scope("legacy/a.py", "scripts/live.py")
    assert not mixed.all_inside and mixed.outside == ("scripts/live.py",)
    assert len(mixed.matches) == 1
    # nothing declared: nothing to judge
    empty = scope("", "  ")
    assert not empty.all_inside and empty.matches == () and empty.outside == ()
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
    ("probe", "pattern"), [("is_dir", "a*"), ("is_file", "a*"), ("is_dir", "[a]wk")]
)
def test_scope_expansion_file_type_failure_has_remedy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: str, pattern: str
) -> None:
    target, alias = tmp_path / "gawk", tmp_path / "awk"
    target.touch()
    alias.symlink_to(target.name)
    member = fv.DecayedMember("m", "scope_exited", (tmp_path,), ("gawk",), ())
    original = getattr(Path, probe)

    def denied(path, *args, **kwargs):
        if path == alias:
            raise PermissionError(13, "fixture stat denied", str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, probe, denied)
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
    read = producer_glob_bytes(root, ["bin/gawk"], monkeypatch)
    assert read == {selected: selected.read_bytes()}
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
        assert error.remedy == fv.PRODUCER_REMEDY
        reasons.append(error.reason)
    assert reasons[0] != reasons[1]
