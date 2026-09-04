"""shared/frame_verdicts.py — the frame's verdicts read at a work-selection point."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from shared import frame_verdicts as fv

NOW = datetime(2026, 9, 3, 22, 30, tzinfo=UTC)


def _stamp(at: datetime) -> str:
    return at.strftime("%Y%m%dT%H%M%SZ")


def _procedure_root(
    root: Path,
    *,
    members: list[dict[str, object]],
    verdicts: list[dict[str, object]],
    at: datetime = NOW,
    epoch_suffix: str = "d693f20c",
) -> Path:
    epoch = root / "_runs" / "epochs" / f"{_stamp(at)}-{epoch_suffix}"
    epoch.mkdir(parents=True, exist_ok=True)
    (epoch / "elements.json").write_text(
        json.dumps(
            [
                {"id": "accountability:x", "kind": "accountability_rollup", "payload": {"n": 1}},
                {
                    "id": "frame:relevance-report",
                    "kind": "relevance_report",
                    "payload": {"verdicts": verdicts},
                },
            ]
        ),
        encoding="utf-8",
    )
    (root / "declaration").mkdir(exist_ok=True)
    (root / "declaration" / "mass.yaml").write_text(
        yaml.safe_dump({"members": members}), encoding="utf-8"
    )
    return root


def _verdict(member_id: str, relation: str, verdict: object = True) -> dict[str, object]:
    return {
        "subject": {"member_id": member_id},
        "relation": relation,
        "verdict": verdict,
        "projection": "frame-reduction",
    }


def test_latest_epoch_is_the_newest_parseable_dir_that_carries_elements(tmp_path: Path) -> None:
    epochs = tmp_path / "_runs" / "epochs"
    (epochs / "20260903T112609Z-0c5d7a85").mkdir(parents=True)
    (epochs / "20260903T112609Z-0c5d7a85" / "elements.json").write_text("[]")
    (epochs / "20260903T204725Z-d693f20c").mkdir()
    (epochs / "20260903T204725Z-d693f20c" / "elements.json").write_text("[]")
    (epochs / "20260903T230000Z-ffffffff").mkdir()  # newest, but no elements yet (in flight)
    (epochs / "notes").mkdir()
    (epochs / "notes" / "elements.json").write_text("[]")

    chosen = fv.latest_epoch_dir(tmp_path)

    assert chosen is not None and chosen.name == "20260903T204725Z-d693f20c"
    assert fv.epoch_produced_at(chosen.name) == datetime(2026, 9, 3, 20, 47, 25, tzinfo=UTC)


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
    epoch = fv.latest_epoch_dir(root)
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
            {"relation": "scope_exited", "verdict": True},  # no subject: ignored
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


def test_non_filesystem_and_undeclared_members_are_reported_unmatchable(tmp_path: Path) -> None:
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
            _verdict("vanished", "scope_exited"),  # decayed, but no longer in the mass
        ],
    )

    verdicts = fv.load_frame_verdicts(root, now=NOW)

    assert verdicts.unmatchable == ("prs", "podium-arm", "vanished")
    mixed = [m for m in verdicts.decayed if m.member_id == "mixed"]
    assert mixed and mixed[0].roots == ((tmp_path / "mixed").absolute(),)
    assert not any(
        m.roots or m.files for m in verdicts.decayed if m.member_id in ("prs", "podium-arm")
    ), "a member with no filesystem location can match no ref"


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

    inside = scope("legacy/a.py", "legacy/**", "30-areas/old/x.md", "config/dead.yaml")
    assert inside.all_inside
    assert [(m.member_id, m.relation) for m in inside.matches] == [
        ("legacy-code", "scope_exited"),
        ("legacy-code", "scope_exited"),
        ("old-notes", "superseded"),
        ("one-file", "discharged"),
    ]

    # a non-.py file under legacy/ is not the member's declared surface
    assert scope("legacy/README.md").outside == ("legacy/README.md",)
    # a directory-like ref under a patterned member counts (the surface lives under it)
    assert scope("legacy/sub/").all_inside
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
    assert path == (council / "scripts" / "x.py").absolute() and not dirlike
    path, dirlike = fv.resolve_scope_ref("30-areas/**/*.md", council_root=council, vault_root=vault)
    assert path == (vault / "30-areas").absolute() and dirlike
    path, dirlike = fv.resolve_scope_ref("scripts", council_root=council, vault_root=vault)
    assert path == (council / "scripts").absolute() and dirlike
    path, _ = fv.resolve_scope_ref("nowhere/y.py", council_root=council, vault_root=vault)
    assert path == (council / "nowhere" / "y.py").absolute()
