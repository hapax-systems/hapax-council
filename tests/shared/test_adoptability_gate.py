"""Adoptability teeth — every refusal, its trigger, and its absence (§7 of the determination).

Each test names the refusal it pins. The mutation battery in
tests/mutation/adoptability_teeth_mutations.sh removes one check at a time and
expects the matching test here to red.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from shared import adoptability_gate as gate
from shared import public_gate_receipts as pgr

SECRET = "adoptability-test-secret"  # pragma: allowlist secret
INSTALL_LINE = "curl -fsSL https://example.org/tool/install.sh | sh"
REPO = "acme/tool"


def _row(
    *,
    tags: list[str] | str = ("cc-task", "garage-door"),
    stage: str = "S1_OFFERED",
    status: str = "offered",
    kind: str = "engineering",
    block: dict | None = None,
    extra: str = "",
) -> str:
    front: dict = {
        "type": "cc-task",
        "task_id": "gd-001",
        "title": "Fixture",
        "status": status,
        "assigned_to": "unassigned",
        "kind": kind,
        "stage": stage,
        "tags": list(tags) if not isinstance(tags, str) else tags,
    }
    if block is not None:
        front["adoptability"] = block
    text = "---\n" + yaml.safe_dump(front, sort_keys=False) + extra + "---\n\n## Session log\n"
    return text


def _block(**overrides) -> dict:
    block = {
        "prior_art_receipt": "receipts/prior-art.yaml",
        "demand_receipt": "receipts/demand.yaml",
        "install_line": INSTALL_LINE,
        "platforms": ["linux", "macos"],
        "zero_config": True,
        "ttfv_seconds": 41,
        "replaces_nothing": True,
        "api": "cli + unix socket",
        "licence": "Apache-2.0",
        "repo_open": REPO,
        "release_notes": "https://github.com/acme/tool/releases",
        "compare_page": "https://example.org/tool/compare",
        "operator_voice_post": "https://example.org/weblog/why-tool",
        "receipt": "receipts/adoptability.json",
    }
    block.update(overrides)
    return block


def _prior_art(verdict: str = "UNBACKED", **overrides) -> dict:
    receipt = {
        "search_shapes": [
            {"shape": "github_code_search", "query": "hook lifecycle idle working blocked"},
            {"shape": "package_registry", "query": "claude-code status reporter"},
        ],
        "verdict": verdict,
    }
    if verdict == "BACKED":
        receipt.update({"tier": "1", "source": "daocoding/herdr-claude-lifecycle", "usable": True})
    receipt.update(overrides)
    return receipt


def _demand() -> dict:
    return {"asked_by": ["issue #12 (two tmux users)", "operator directive 2026-09-16"]}


def _write_receipts(root: Path, *, prior_art: dict | None, demand: dict | None) -> None:
    (root / "receipts").mkdir(parents=True, exist_ok=True)
    if prior_art is not None:
        (root / "receipts" / "prior-art.yaml").write_text(yaml.safe_dump(prior_art))
    if demand is not None:
        (root / "receipts" / "demand.yaml").write_text(yaml.safe_dump(demand))


def _signed_receipt(**overrides) -> dict:
    receipt = {
        "gate": "adoptability",
        "artifact_id": "tool",
        "repo": REPO,
        "install_line_sha256": gate.install_line_digest(INSTALL_LINE),
        "observed_at": "2026-09-16T09:00:00Z",
        "stale_after": "2026-09-17T09:00:00Z",
        "checks": {
            "install": {"passed": True},
            "zero_config": {"passed": True},
            "ttfv": {"passed": True, "seconds": 41},
            "licence": {"passed": True},
            "repo_open": {"passed": True},
            "release_notes": {"passed": True},
            "compare_page": {"passed": True},
        },
        "outcome": "pass",
        "authority_issuer": "review-team:hapax-adoptability-receipt",
    }
    receipt.update(overrides)
    receipt["authority_signature"] = pgr.public_gate_authority_signature(receipt, SECRET)
    return receipt


NOW = 1789552800.0  # 2026-09-16T10:00:00Z; fixtures observed 09:00Z, stale 09:00Z next day


# ── vocabulary ───────────────────────────────────────────────────────────────


def test_refusal_vocabulary_is_closed_and_exact() -> None:
    assert (
        frozenset(
            {
                "row_refused:adoptability_block_missing",
                "row_refused:adoptability_field_missing",
                "row_refused:frontmatter_unparseable",
                "stage_refused:prior_art_receipt_absent",
                "stage_refused:demand_receipt_absent",
                "stage_refused:garage_door_tag_removed",
                "row_converted:contribution",
                "release_refused:adoptability_receipt_absent",
                "release_refused:adoptability_receipt_unsigned",
                "release_refused:adoptability_receipt_stale",
                "release_refused:adoptability_receipt_mismatch",
                "release_refused:adoptability_failed",
                "release_refused:estate_binding_in_install_surface",
            }
        )
        == gate.REFUSAL_VOCABULARY
    )


# ── lint (A5) ────────────────────────────────────────────────────────────────


def test_lint_unparseable_yaml_is_a_refusal_not_a_skip() -> None:
    text = "---\ntitle: [unclosed\nstatus: offered\n---\nbody\n"
    frontmatter, refusals = gate.lint_frontmatter_text(text)
    assert frontmatter is None
    assert refusals == ["row_refused:frontmatter_unparseable:yaml_error"]


def test_lint_missing_frontmatter_is_named() -> None:
    _, refusals = gate.lint_frontmatter_text("# just a heading\n")
    assert refusals == ["row_refused:frontmatter_unparseable:missing_frontmatter"]


def test_lint_unquoted_key_value_inside_list_item_is_refused() -> None:
    # The six rows found by hand on 2026-09-16: an unquoted `key: value` inside a
    # block sequence parses as a one-key mapping, which the autoqueue then skips.
    text = _row(
        tags=["cc-task"], extra="mutation_scope_refs:\n  - scripts/x.py\n  - config/: row schema\n"
    )
    frontmatter, refusals = gate.lint_frontmatter_text(text)
    assert frontmatter is not None
    assert refusals == ["row_refused:frontmatter_unparseable:mutation_scope_refs"]


def test_lint_structured_list_fields_are_design_not_accidents() -> None:
    # Measured 2026-09-16: 1,522 identifier-keyed mapping items across the vault (required_tools,
    # refusal_history, source_touch_conflicts, research_refs, …) — none is the accident.
    text = _row(
        tags=["cc-task"],
        extra=(
            "required_tools:\n  - {tool_id: filesystem, required: true, authority_use: write}\n"
            "source_touch_conflicts:\n  - {pr: 4453, state: draft_parked, task: some-task}\n"
            "research_refs:\n  - official: https://example.org/docs\n"
        ),
    )
    _, refusals = gate.lint_frontmatter_text(text)
    assert refusals == []


def test_lint_one_key_non_identifier_item_is_the_accident_in_any_list() -> None:
    text = _row(tags=["cc-task"], extra="research_refs:\n  - docs/ (see: the runbook)\n")
    _, refusals = gate.lint_frontmatter_text(text)
    assert refusals == ["row_refused:frontmatter_unparseable:research_refs"]


def test_lint_scalar_list_fields_refuse_any_mapping() -> None:
    text = _row(tags=["cc-task"], extra="depends_on:\n  - reins: main\n")
    _, refusals = gate.lint_frontmatter_text(text)
    assert refusals == ["row_refused:frontmatter_unparseable:depends_on"]
    assert gate.list_item_is_accident("tags", {"a": 1}) is True
    assert gate.list_item_is_accident("free_form", {"a": 1}) is False
    assert gate.list_item_is_accident("free_form", {"a b": 1}) is True
    assert gate.list_item_is_accident("free_form", "scalar") is False


def test_lint_plain_row_is_clean() -> None:
    _, refusals = gate.lint_frontmatter_text(_row(tags=["cc-task", "p1"]))
    assert refusals == []


def test_lint_garage_door_row_without_block_is_refused() -> None:
    _, refusals = gate.lint_frontmatter_text(_row())
    assert refusals == ["row_refused:adoptability_block_missing"]


def test_lint_garage_door_row_names_every_missing_field() -> None:
    _, refusals = gate.lint_frontmatter_text(
        _row(block={"install_line": INSTALL_LINE, "licence": ""})
    )
    missing = {r.rsplit(":", 1)[1] for r in refusals}
    assert all(r.startswith("row_refused:adoptability_field_missing:") for r in refusals)
    assert missing == set(gate.RECEIPT_FIELDS) | (set(gate.ACCEPTANCE_FIELDS) - {"install_line"})


def test_lint_garage_door_row_with_full_block_is_clean() -> None:
    _, refusals = gate.lint_frontmatter_text(_row(block=_block()))
    assert refusals == []


def test_lint_row_unreadable_file_is_unparseable(tmp_path: Path) -> None:
    assert gate.lint_row(tmp_path / "missing.md") == [
        "row_refused:frontmatter_unparseable:read_error:FileNotFoundError"
    ]


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        (["cc-task", "garage-door"], True),
        ("cc-task, Garage-Door", True),
        (["cc-task", "garage-door-teeth"], False),
        (["cc-task"], False),
        (None, False),
    ],
)
def test_is_garage_door_matches_the_tag_exactly(tags, expected) -> None:
    assert gate.is_garage_door({"tags": tags}) is expected


# ── receipts ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("receipt", "status"),
    [
        (None, "absent"),
        ({"verdict": "UNBACKED"}, "invalid"),
        ({"search_shapes": [{"shape": "grep", "query": "x"}], "verdict": "UNBACKED"}, "invalid"),
        (
            {
                "search_shapes": [{"shape": "grep", "query": "x"}, {"shape": "grep", "query": "y"}],
                "verdict": "UNBACKED",
            },
            "invalid",
        ),
        (_prior_art(verdict="MAYBE"), "invalid"),
        (_prior_art("UNBACKED"), "unbacked"),
        (_prior_art("BACKED", tier=""), "invalid"),
        (_prior_art("BACKED", usable="yes"), "invalid"),
        (_prior_art("BACKED"), "backed_usable"),
        (_prior_art("BACKED", usable=False), "backed_unusable"),
    ],
)
def test_prior_art_receipt_status(receipt, status) -> None:
    assert gate.prior_art_receipt_status(receipt) == status


@pytest.mark.parametrize(
    ("receipt", "status"),
    [
        (None, "absent"),
        ({}, "absent"),
        ({"asked_by": []}, "absent"),
        ({"asked_by": ["  "]}, "absent"),
        (_demand(), "present"),
        ({"probe": {"asked": 5, "answers": ["keep", "keep", "drop", "keep", "keep"]}}, "present"),
        ({"probe": {"asked": 5, "answers": []}}, "absent"),
        ({"probe": {"asked": 0, "answers": ["x"]}}, "absent"),
    ],
)
def test_demand_receipt_status(receipt, status) -> None:
    assert gate.demand_receipt_status(receipt) == status


def test_resolve_receipt_path_relative_under_root(tmp_path: Path) -> None:
    _write_receipts(tmp_path, prior_art=_prior_art(), demand=None)
    assert gate.resolve_receipt_path("receipts/prior-art.yaml", roots=[tmp_path]) == (
        tmp_path / "receipts" / "prior-art.yaml"
    )


def test_resolve_receipt_path_refuses_escapes_and_foreign_paths(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside.yaml"
    root.mkdir()
    outside.write_text("verdict: BACKED\n")
    (root / "notes.txt").write_text("x")
    assert gate.resolve_receipt_path("../outside.yaml", roots=[root]) is None
    assert gate.resolve_receipt_path(str(outside), roots=[root]) is None
    assert gate.resolve_receipt_path("notes.txt", roots=[root]) is None
    assert gate.resolve_receipt_path("", roots=[root]) is None
    assert gate.resolve_receipt_path(None, roots=[root]) is None


def test_receipt_roots_come_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(gate.RECEIPT_ROOTS_ENV, str(tmp_path))
    assert gate.receipt_roots() == (tmp_path,)
    monkeypatch.delenv(gate.RECEIPT_ROOTS_ENV)
    assert gate.receipt_roots() == gate.DEFAULT_RECEIPT_ROOTS


# ── stage gate (A2) ──────────────────────────────────────────────────────────


def _fm(text: str) -> dict:
    frontmatter, _ = gate.lint_frontmatter_text(text)
    assert frontmatter is not None
    return frontmatter


def test_stage_non_garage_door_row_is_never_judged(tmp_path: Path) -> None:
    fm = _fm(_row(tags=["cc-task"]))
    assert gate.stage_advance_refusals(fm, to_stage="S6_IMPLEMENTATION", roots=[tmp_path]) == []


def test_stage_staying_in_offered_is_not_a_transition(tmp_path: Path) -> None:
    fm = _fm(_row())
    assert gate.stage_advance_refusals(fm, to_stage="S1_OFFERED", roots=[tmp_path]) == []
    assert gate.stage_advance_refusals(fm, to_status="ready", roots=[tmp_path]) == []


def test_stage_leaving_offered_without_receipts_is_refused(tmp_path: Path) -> None:
    fm = _fm(_row())
    refusals = gate.stage_advance_refusals(fm, to_stage="S2_CLAIMED", roots=[tmp_path])
    assert refusals == [
        "row_refused:adoptability_block_missing",
        "stage_refused:prior_art_receipt_absent",
        "stage_refused:demand_receipt_absent",
    ]


def test_stage_claim_transition_is_leaving_offered(tmp_path: Path) -> None:
    fm = _fm(_row(block=_block()))
    refusals = gate.stage_advance_refusals(fm, to_status="claimed", roots=[tmp_path])
    assert "stage_refused:prior_art_receipt_absent" in refusals
    assert "stage_refused:demand_receipt_absent" in refusals


def test_stage_demand_receipt_absent_alone(tmp_path: Path) -> None:
    _write_receipts(tmp_path, prior_art=_prior_art(), demand=None)
    fm = _fm(_row(block=_block()))
    assert gate.stage_advance_refusals(fm, to_stage="S2", roots=[tmp_path]) == [
        "stage_refused:demand_receipt_absent"
    ]


def test_stage_prior_art_receipt_invalid_reads_as_absent(tmp_path: Path) -> None:
    _write_receipts(tmp_path, prior_art={"verdict": "UNBACKED"}, demand=_demand())
    fm = _fm(_row(block=_block()))
    assert gate.stage_advance_refusals(fm, to_stage="S2", roots=[tmp_path]) == [
        "stage_refused:prior_art_receipt_absent"
    ]


def test_stage_with_both_receipts_advances(tmp_path: Path) -> None:
    _write_receipts(tmp_path, prior_art=_prior_art(), demand=_demand())
    fm = _fm(_row(block=_block()))
    assert gate.stage_advance_refusals(fm, to_stage="S6_IMPLEMENTATION", roots=[tmp_path]) == []


def test_stage_backed_usable_prior_art_converts_the_row(tmp_path: Path) -> None:
    _write_receipts(tmp_path, prior_art=_prior_art("BACKED"), demand=_demand())
    fm = _fm(_row(block=_block()))
    assert gate.stage_advance_refusals(fm, to_stage="S2", roots=[tmp_path]) == [
        "row_converted:contribution"
    ]
    fm_contribution = _fm(_row(block=_block(), kind="contribution"))
    assert gate.stage_advance_refusals(fm_contribution, to_stage="S2", roots=[tmp_path]) == []


def test_stage_backed_unusable_prior_art_does_not_convert(tmp_path: Path) -> None:
    _write_receipts(tmp_path, prior_art=_prior_art("BACKED", usable=False), demand=_demand())
    fm = _fm(_row(block=_block()))
    assert gate.stage_advance_refusals(fm, to_stage="S2", roots=[tmp_path]) == []


def test_stage_row_that_already_left_offered_is_not_rejudged(tmp_path: Path) -> None:
    fm = _fm(_row(status="claimed", stage="S2_CLAIMED"))
    assert gate.stage_advance_refusals(fm, to_stage="S6_IMPLEMENTATION", roots=[tmp_path]) == []
    fm_blank_stage = _fm(_row(status="in_progress", stage=""))
    assert gate.stage_advance_refusals(fm_blank_stage, to_stage="S7", roots=[tmp_path]) == []


def test_convert_to_contribution_rewrites_kind_and_logs() -> None:
    converted = gate.convert_to_contribution(_row(), actor="zeta", now="2026-09-16T10:00:00Z")
    frontmatter, _ = gate.lint_frontmatter_text(converted)
    assert frontmatter is not None and frontmatter["kind"] == "contribution"
    assert (
        converted.rstrip()
        .splitlines()[-1]
        .startswith("- 2026-09-16T10:00:00Z zeta: row_converted:contribution")
    )


def test_convert_to_contribution_adds_kind_when_absent() -> None:
    text = "---\ntitle: x\ntags: [garage-door]\n---\nbody\n"
    frontmatter, _ = gate.lint_frontmatter_text(
        gate.convert_to_contribution(text, actor="a", now="t")
    )
    assert frontmatter is not None and frontmatter["kind"] == "contribution"
    with pytest.raises(ValueError):
        gate.convert_to_contribution("no frontmatter", actor="a", now="t")


# ── hook post-condition ──────────────────────────────────────────────────────


def test_apply_tool_edit_shapes() -> None:
    assert gate.apply_tool_edit("abc", "Write", {"content": "xyz"}) == "xyz"
    assert gate.apply_tool_edit("a-b-b", "Edit", {"old_string": "b", "new_string": "c"}) == "a-c-b"
    assert (
        gate.apply_tool_edit(
            "a-b-b", "Edit", {"old_string": "b", "new_string": "c", "replace_all": True}
        )
        == "a-c-c"
    )
    assert (
        gate.apply_tool_edit(
            "a-b",
            "MultiEdit",
            {
                "edits": [
                    {"old_string": "a", "new_string": "x"},
                    {"old_string": "b", "new_string": "y"},
                ]
            },
        )
        == "x-y"
    )
    assert gate.apply_tool_edit("abc", "NotebookEdit", {}) is None
    assert gate.apply_tool_edit("abc", "Edit", {"old_string": "", "new_string": "q"}) == "abc"


def test_hook_edit_removing_the_tag_is_refused(tmp_path: Path) -> None:
    current = _row()
    proposed = _row(tags=["cc-task"])
    assert gate.hook_edit_refusals(current, proposed, roots=[tmp_path]) == [
        "stage_refused:garage_door_tag_removed"
    ]


def test_hook_edit_moving_stage_off_s1_without_receipts_is_refused(tmp_path: Path) -> None:
    current = _row(block=_block())
    proposed = _row(block=_block(), stage="S6_IMPLEMENTATION")
    assert gate.hook_edit_refusals(current, proposed, roots=[tmp_path]) == [
        "stage_refused:prior_art_receipt_absent",
        "stage_refused:demand_receipt_absent",
    ]


def test_hook_edit_claiming_by_hand_is_refused(tmp_path: Path) -> None:
    current = _row(block=_block())
    proposed = _row(block=_block(), status="claimed")
    refusals = gate.hook_edit_refusals(current, proposed, roots=[tmp_path])
    assert "stage_refused:prior_art_receipt_absent" in refusals


def test_hook_edit_receipts_added_in_the_same_edit_count(tmp_path: Path) -> None:
    _write_receipts(tmp_path, prior_art=_prior_art(), demand=_demand())
    current = _row()
    proposed = _row(block=_block(), stage="S2_CLAIMED", status="claimed")
    assert gate.hook_edit_refusals(current, proposed, roots=[tmp_path]) == []


def test_hook_edit_non_garage_door_rows_pass(tmp_path: Path) -> None:
    assert (
        gate.hook_edit_refusals(
            _row(tags=["cc-task"]), _row(tags=["cc-task"], stage="S6"), roots=[tmp_path]
        )
        == []
    )


def test_hook_edit_new_garage_door_row_written_past_s1_is_refused(tmp_path: Path) -> None:
    proposed = _row(block=_block(), stage="S6_IMPLEMENTATION", status="in_progress")
    refusals = gate.hook_edit_refusals("", proposed, roots=[tmp_path])
    assert "stage_refused:prior_art_receipt_absent" in refusals


def test_hook_edit_unparseable_result_is_refused(tmp_path: Path) -> None:
    assert gate.hook_edit_refusals(_row(), "---\ntags: [garage-door\n---\n", roots=[tmp_path]) == [
        "row_refused:frontmatter_unparseable:yaml_error"
    ]


# ── release gate (A1 / A3 / A4) ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("surface", "label"),
    [
        ("cp ~/Documents/Personal/x .", "vault_path"),
        ("ln -s ~/hapax-cc-tasks/active .", "cc_task_rows"),
        ("cc-claim my-row && make", "cc_task_tooling"),
        ("reins doctor", "reins"),
        ("git clone https://github.com/hapax-systems/hapax-council", "hapax_council_checkout"),
        ("cat ~/.cache/hapax/relay/x.yaml", "hapax_cache"),
        ("write to lanebus/cx-blue", "lanebus"),
        ("HAPAX_AGENT_NAME=zeta tool", "hapax_env"),
        ("hapax-secret get key", "hapax_secret"),
        ("scripts/hapax-methodology-dispatch --task x", "methodology_dispatch"),
    ],
)
def test_estate_bindings_name_each_noun(surface: str, label: str) -> None:
    fm = {"tags": ["garage-door"], "adoptability": {"install_line": surface}}
    assert label in gate.estate_bindings(fm)


def test_estate_bindings_respect_word_boundaries_and_clean_surfaces() -> None:
    clean = {
        "tags": ["garage-door"],
        "adoptability": _block(install_line="brew reinstall tool", api="unix socket + CLI"),
    }
    assert gate.estate_bindings(clean) == []
    assert (
        gate.estate_bindings(
            {"tags": ["garage-door"], "adoptability": {"platforms": ["linux", "reins-free"]}}
        )
        == []
    )


def test_release_non_garage_door_row_has_no_adoptability_blockers(tmp_path: Path) -> None:
    fm = _fm(_row(tags=["cc-task", "adoptability", "teeth"]))
    assert gate.release_refusals(fm, now=NOW, roots=[tmp_path], secret=SECRET) == []


def test_release_receipt_absent(tmp_path: Path) -> None:
    fm = _fm(_row(block=_block()))
    assert gate.release_refusals(fm, now=NOW, roots=[tmp_path], secret=SECRET) == [
        "release_refused:adoptability_receipt_absent"
    ]


def _write_adoptability_receipt(root: Path, receipt: dict) -> None:
    (root / "receipts").mkdir(parents=True, exist_ok=True)
    (root / "receipts" / "adoptability.json").write_text(json.dumps(receipt))


def test_release_passing_signed_fresh_receipt_clears(tmp_path: Path) -> None:
    _write_adoptability_receipt(tmp_path, _signed_receipt())
    fm = _fm(_row(block=_block()))
    assert gate.release_refusals(fm, now=NOW, roots=[tmp_path], secret=SECRET) == []


def test_release_receipt_signed_with_another_key_is_unsigned(tmp_path: Path) -> None:
    _write_adoptability_receipt(tmp_path, _signed_receipt())
    fm = _fm(_row(block=_block()))
    other_key = "other"  # pragma: allowlist secret
    assert gate.release_refusals(fm, now=NOW, roots=[tmp_path], secret=other_key) == [
        "release_refused:adoptability_receipt_unsigned"
    ]


def test_release_receipt_without_trusted_issuer_is_unsigned(tmp_path: Path) -> None:
    receipt = _signed_receipt(authority_issuer="self")
    _write_adoptability_receipt(tmp_path, receipt)
    fm = _fm(_row(block=_block()))
    assert gate.release_refusals(fm, now=NOW, roots=[tmp_path], secret=SECRET) == [
        "release_refused:adoptability_receipt_unsigned"
    ]


def test_release_receipt_past_stale_after_is_stale(tmp_path: Path) -> None:
    _write_adoptability_receipt(tmp_path, _signed_receipt(stale_after="2026-09-16T09:30:00Z"))
    fm = _fm(_row(block=_block()))
    assert gate.release_refusals(fm, now=NOW, roots=[tmp_path], secret=SECRET) == [
        "release_refused:adoptability_receipt_stale"
    ]


def test_release_receipt_without_stale_after_uses_observed_at_ttl(tmp_path: Path) -> None:
    receipt = _signed_receipt(stale_after=None)
    receipt.pop("stale_after")
    receipt["authority_signature"] = pgr.public_gate_authority_signature(receipt, SECRET)
    _write_adoptability_receipt(tmp_path, receipt)
    fm = _fm(_row(block=_block()))
    assert gate.release_refusals(fm, now=NOW, roots=[tmp_path], secret=SECRET) == []
    late = NOW + gate.DEFAULT_RECEIPT_TTL_SECONDS
    assert gate.release_refusals(fm, now=late, roots=[tmp_path], secret=SECRET) == [
        "release_refused:adoptability_receipt_stale"
    ]


@pytest.mark.parametrize(
    "overrides",
    [
        {"repo": "someone/else"},
        {"install_line_sha256": "0" * 64},
        {"gate": "public"},
    ],
)
def test_release_receipt_for_another_artifact_is_a_mismatch(
    tmp_path: Path, overrides: dict
) -> None:
    _write_adoptability_receipt(tmp_path, _signed_receipt(**overrides))
    fm = _fm(_row(block=_block()))
    assert gate.release_refusals(fm, now=NOW, roots=[tmp_path], secret=SECRET) == [
        "release_refused:adoptability_receipt_mismatch"
    ]


def test_release_each_failed_check_is_named(tmp_path: Path) -> None:
    receipt = _signed_receipt()
    receipt["checks"]["licence"] = {"passed": False, "detail": "GPL-3.0"}
    receipt["checks"]["ttfv"] = {"passed": False, "seconds": 93}
    receipt["outcome"] = "fail"
    receipt["authority_signature"] = pgr.public_gate_authority_signature(receipt, SECRET)
    _write_adoptability_receipt(tmp_path, receipt)
    fm = _fm(_row(block=_block()))
    assert gate.release_refusals(fm, now=NOW, roots=[tmp_path], secret=SECRET) == [
        "release_refused:adoptability_failed:ttfv",
        "release_refused:adoptability_failed:licence",
    ]


def test_release_receipt_with_no_checks_fails(tmp_path: Path) -> None:
    _write_adoptability_receipt(tmp_path, _signed_receipt(checks={}))
    fm = _fm(_row(block=_block()))
    assert gate.release_refusals(fm, now=NOW, roots=[tmp_path], secret=SECRET) == [
        "release_refused:adoptability_failed:no_checks"
    ]


def test_release_estate_binding_is_independent_of_the_receipt(tmp_path: Path) -> None:
    _write_adoptability_receipt(tmp_path, _signed_receipt())
    fm = _fm(_row(block=_block(api="reads ~/.cache/hapax/relay")))
    assert gate.release_refusals(fm, now=NOW, roots=[tmp_path], secret=SECRET) == [
        "release_refused:estate_binding_in_install_surface"
    ]


def test_release_secret_defaults_to_the_public_gate_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_adoptability_receipt(tmp_path, _signed_receipt())
    fm = _fm(_row(block=_block()))
    monkeypatch.setenv(pgr.PUBLIC_GATE_AUTHORITY_SECRET_ENV, SECRET)
    monkeypatch.setenv(gate.RECEIPT_ROOTS_ENV, str(tmp_path))
    assert gate.adoptability_release_blockers(fm, now=NOW) == []
    monkeypatch.setenv(pgr.PUBLIC_GATE_AUTHORITY_SECRET_ENV, "")
    assert gate.adoptability_release_blockers(fm, now=NOW) == [
        "release_refused:adoptability_receipt_unsigned"
    ]


# ── killswitch ───────────────────────────────────────────────────────────────


def _engage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str = "1") -> Path:
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv(gate.ADOPTABILITY_TEETH_OFF_ENV, value)
    monkeypatch.setenv(gate.METHODOLOGY_LEDGER_ENV, str(ledger))
    monkeypatch.setenv("HAPAX_AGENT_ROLE", "alpha")
    return ledger


def test_killswitch_empties_stage_hook_and_release_refusals_and_ledgers_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = _engage(tmp_path, monkeypatch)
    fm = _fm(_row(block=_block()))
    assert gate.stage_advance_refusals(fm, to_stage="S2_CLAIMED", roots=[tmp_path]) == []
    assert gate.hook_edit_refusals(_row(), _row(tags=["cc-task"]), roots=[tmp_path]) == []
    assert gate.release_refusals(fm, now=NOW, roots=[tmp_path], secret=SECRET) == []
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [row["kind"] for row in rows] == [gate.KILLSWITCH_LEDGER_KIND] * 3
    assert {row["surface"] for row in rows} == {"stage", "hook-edit", "release"}
    assert all(row["role"] == "alpha" for row in rows)
    err = capsys.readouterr().err
    assert err.count("LEDGERED") == 3
    assert "coord-grant-mint --scope adoptability-teeth" in err


def test_killswitch_engages_only_on_exactly_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _engage(tmp_path, monkeypatch, value="true")
    fm = _fm(_row(block=_block()))
    assert gate.stage_advance_refusals(fm, to_stage="S2_CLAIMED", roots=[tmp_path]) != []
    assert not (tmp_path / "ledger.jsonl").exists()


def test_killswitch_does_not_touch_the_lint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _engage(tmp_path, monkeypatch)
    _, refusals = gate.lint_frontmatter_text(_row())
    assert refusals == ["row_refused:adoptability_block_missing"]


def test_killswitch_unwritable_ledger_is_loud_not_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(gate.ADOPTABILITY_TEETH_OFF_ENV, "1")
    monkeypatch.setenv(
        gate.METHODOLOGY_LEDGER_ENV, str(tmp_path / "not-a-dir.txt" / "ledger.jsonl")
    )
    (tmp_path / "not-a-dir.txt").write_text("file, not a directory")
    fm = _fm(_row(block=_block()))
    assert gate.release_refusals(fm, now=NOW, roots=[tmp_path], secret=SECRET) == []
    assert "LEDGER UNWRITABLE" in capsys.readouterr().err


# ── CLI ──────────────────────────────────────────────────────────────────────


def test_cli_lint_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = tmp_path / "rows"
    rows.mkdir()
    (rows / "clean.md").write_text(_row(tags=["cc-task"]))
    assert gate.main(["lint", str(rows)]) == 0
    (rows / "gd.md").write_text(_row())
    assert gate.main(["lint", str(rows)]) == 2
    assert "gd.md: row_refused:adoptability_block_missing" in capsys.readouterr().err
    assert gate.main([]) == 3
    assert gate.main(["bogus"]) == 3


def test_cli_stage_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(gate.RECEIPT_ROOTS_ENV, str(tmp_path))
    note = tmp_path / "row.md"
    note.write_text(_row(block=_block()))
    assert gate.main(["stage-check", str(note), "--to-stage", "S1_OFFERED"]) == 0
    assert gate.main(["stage-check", str(note), "--to-stage", "S2_CLAIMED"]) == 2
    assert gate.main(["stage-check", str(note), "--to-status", "claimed"]) == 2
    assert gate.main(["stage-check", str(tmp_path / "nope.md")]) == 3


def test_cli_hook_edit_reads_tool_input_from_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import io

    monkeypatch.setenv(gate.RECEIPT_ROOTS_ENV, str(tmp_path))
    note = tmp_path / "row.md"
    note.write_text(_row(block=_block()))
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(note),
            "old_string": "stage: S1_OFFERED",
            "new_string": "stage: S6_IMPLEMENTATION",
        },
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert gate.main(["hook-edit", str(note)]) == 2
    assert "stage_refused:prior_art_receipt_absent" in capsys.readouterr().err
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert gate.main(["hook-edit", str(note)]) == 3
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}))
    )
    assert gate.main(["hook-edit", str(note)]) == 0


def test_cli_release_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(gate.RECEIPT_ROOTS_ENV, str(tmp_path))
    monkeypatch.setenv(pgr.PUBLIC_GATE_AUTHORITY_SECRET_ENV, SECRET)
    note = tmp_path / "row.md"
    note.write_text(_row(block=_block(install_line="reins install tool")))
    assert gate.main(["release-check", str(note)]) == 2
    err = capsys.readouterr().err
    assert "estate noun in install surface: reins" in err
    assert "release_refused:estate_binding_in_install_surface" in err
    assert gate.main(["release-check", str(tmp_path / "nope.md")]) == 3
