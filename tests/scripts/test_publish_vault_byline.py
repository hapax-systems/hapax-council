"""Pin vault publisher CLI input to its actual temporary inbox JSON artifact."""

import json
import logging
from pathlib import Path

import pytest
import yaml

from scripts import publish_vault_artifact as publisher
from shared import co_author_model as authors
from shared.preprint_artifact import PreprintArtifact
from tests.scripts.test_publish_vault_artifact import (
    PUBLIC_GATE_AUTHORITY_BLOCK,
    PUBLICATION_GATE_RECEIPTS,
    _write_public_gate_review_evidence,
)
from tests.scripts.test_publish_vault_artifact import (
    durable_public_gate_receipts as durable_public_gate_receipts,
)

pytestmark = pytest.mark.usefixtures("durable_public_gate_receipts")


def _source_with_receipts(tmp_path, *, entries, expected_authors, byline, include_null=False):
    """Synthetic clearance for a specified artifact, using real receipt validation."""
    body = "# Synthetic draft\n\nFixture body.\n"
    expected = PreprintArtifact(
        slug="synthetic-byline",
        title="Synthetic draft",
        abstract="Fixture body.",
        body_md=body,
        co_authors=expected_authors,
        attribution_block=byline,
        surfaces_targeted=["omg-weblog"],
    )
    bindings = publisher._publication_gate_receipt_bindings(expected)
    root = publisher.PUBLIC_GATE_RECEIPT_ROOTS[0]
    for gate, ref in PUBLICATION_GATE_RECEIPTS.items():
        payload = {
            **yaml.safe_load(PUBLIC_GATE_AUTHORITY_BLOCK),
            **bindings,
            "gate_id": gate,
            "status": "passed",
        }
        (root / f"{ref.removeprefix('public-gate:')}.yaml").write_text(yaml.safe_dump(payload))
    _write_public_gate_review_evidence(
        root,
        gates=tuple(PUBLICATION_GATE_RECEIPTS),
        receipt_refs=tuple(f"{ref}.yaml" for ref in PUBLICATION_GATE_RECEIPTS.values()),
        **bindings,
    )
    frontmatter = {
        "Publication-Allowed": True,
        "title": expected.title,
        "slug": expected.slug,
        "attribution_block": byline,
        "publication_gate_receipts": PUBLICATION_GATE_RECEIPTS,
    }
    if entries is not None or include_null:
        frontmatter["co_authors"] = entries
    source = tmp_path / "synthetic.md"
    source.write_text("---\n" + yaml.safe_dump(frontmatter) + "---\n" + body)
    return source, expected


def _run_publisher(source: Path, state: Path):
    return publisher.main(
        [
            str(source),
            "--state-root",
            str(state),
            "--surfaces",
            "omg-weblog",
            "--approver",
            "operator",
        ]
    )


@pytest.mark.parametrize(
    "entry", ["codex", "Codex (substrate)", {"alias": "codex"}, {"key": "codex"}]
)
def test_publisher_writes_selected_participant_and_byline_to_named_artifact(tmp_path, entry):
    source, expected = _source_with_receipts(
        tmp_path, entries=[entry], expected_authors=[authors.get("codex")], byline="Codex"
    )
    original_source = source.read_bytes()
    state = tmp_path / "isolated-state"

    assert _run_publisher(source, state) == 0

    destination = state / "publish" / "inbox" / "synthetic-byline.json"
    assert sorted(state.rglob("*.json")) == [destination]
    payload = json.loads(destination.read_text())
    assert payload["slug"] == "synthetic-byline"
    assert payload["title"] == "Synthetic draft"
    assert payload["co_authors"] == expected.model_dump(mode="json")["co_authors"]
    assert [author["name"] for author in payload["co_authors"]] == ["Codex"]
    assert payload["attribution_block"] == "Codex"
    assert payload["body_md"] == expected.body_md
    assert payload["surfaces_targeted"] == ["omg-weblog"]
    assert payload["approval"] == "approved"
    assert payload["source_path"] == str(source.resolve())
    assert source.read_bytes() == original_source


def test_publisher_default_participants_and_attribution_are_unchanged(tmp_path):
    expected_authors = [authors.HAPAX, authors.CLAUDE_CODE, authors.get("operator")]
    source, expected = _source_with_receipts(
        tmp_path, entries=None, expected_authors=expected_authors, byline=""
    )
    state = tmp_path / "isolated-state"

    assert _run_publisher(source, state) == 0

    payload = json.loads((state / "publish" / "inbox" / "synthetic-byline.json").read_text())
    assert payload["co_authors"] == expected.model_dump(mode="json")["co_authors"]
    assert payload["attribution_block"] == ""
    assert "Codex" not in [author["name"] for author in payload["co_authors"]]


@pytest.mark.parametrize(
    "unknown", ["unregistered-participant", {"alias": "unregistered-participant"}]
)
@pytest.mark.parametrize("receipt_authors", ["defaults", "survivors"])
def test_publisher_refuses_whole_unknown_list_before_artifact_write(
    tmp_path, caplog, unknown, receipt_authors
):
    # Even valid synthetic clearance for either buggy output cannot authorize
    # substituting the defaults or silently dropping the unrecognized entry.
    expected_authors = (
        [authors.HAPAX, authors.CLAUDE_CODE, authors.get("operator")]
        if receipt_authors == "defaults"
        else [authors.HAPAX]
    )
    source, _ = _source_with_receipts(
        tmp_path,
        entries=["hapax", unknown],
        expected_authors=expected_authors,
        byline="Synthetic attribution",
    )
    original_source = source.read_bytes()
    state = tmp_path / "isolated-state"
    with caplog.at_level(logging.ERROR):
        rc = _run_publisher(source, state)

    assert rc == 1
    assert not state.exists()
    assert source.read_bytes() == original_source
    assert "unrecognized co_authors entry" in caplog.text
    assert "unregistered-participant" in caplog.text
    assert "next action: use a registered key" in caplog.text
    assert "'codex'" in caplog.text
    assert "{'alias': 'codex'}" in caplog.text


@pytest.mark.parametrize("entries", [None, []], ids=["null", "empty-list"])
def test_publisher_null_and_empty_list_retain_default_participants(tmp_path, entries):
    expected_authors = [authors.HAPAX, authors.CLAUDE_CODE, authors.get("operator")]
    source, expected = _source_with_receipts(
        tmp_path, entries=entries, expected_authors=expected_authors, byline="", include_null=True
    )
    original_source = source.read_bytes()
    state = tmp_path / "isolated-state"

    assert _run_publisher(source, state) == 0

    destination = state / "publish" / "inbox" / "synthetic-byline.json"
    assert sorted(state.rglob("*.json")) == [destination]
    payload = json.loads(destination.read_text())
    assert payload["co_authors"] == expected.model_dump(mode="json")["co_authors"]
    assert payload["attribution_block"] == ""
    assert source.read_bytes() == original_source


@pytest.mark.parametrize(
    "entries, shape",
    [
        pytest.param(False, "bool", id="false"),
        pytest.param(0, "int", id="zero"),
        pytest.param("", "str", id="empty-string"),
        pytest.param({}, "dict", id="empty-mapping"),
        pytest.param(3, "int", id="integer"),
        pytest.param({"codex": "unregistered"}, "dict", id="resolvable-mapping-key"),
        pytest.param("codex", "str", id="string"),
        pytest.param(True, "bool", id="true"),
        pytest.param(0.5, "float", id="float"),
    ],
)
def test_publisher_refuses_malformed_container_before_artifact_write(
    tmp_path, caplog, entries, shape
):
    # Clear the buggy output too: an iterable mapping would select its valid key;
    # falsey declarations would activate the constructor's default participants.
    expected_authors = (
        [authors.get("codex")]
        if entries == {"codex": "unregistered"}
        else [authors.HAPAX, authors.CLAUDE_CODE, authors.get("operator")]
    )
    source, _ = _source_with_receipts(
        tmp_path, entries=entries, expected_authors=expected_authors, byline="Synthetic attribution"
    )
    original_source = source.read_bytes()
    state = tmp_path / "isolated-state"
    with caplog.at_level(logging.ERROR):
        rc = _run_publisher(source, state)

    assert rc == 1
    assert not state.exists()
    assert source.read_bytes() == original_source
    assert f"malformed co_authors container: found {shape}" in caplog.text
    assert "next action: declare a list" in caplog.text
    assert "['codex']" in caplog.text
    assert "[{'alias': 'codex'}]" in caplog.text


@pytest.mark.parametrize("receipt_authors", ["defaults", "survivors"])
def test_publisher_refuses_codex_and_unregistered_before_artifact_write(
    tmp_path, caplog, receipt_authors
):
    expected_authors = (
        [authors.HAPAX, authors.CLAUDE_CODE, authors.get("operator")]
        if receipt_authors == "defaults"
        else [authors.get("codex")]
    )
    source, _ = _source_with_receipts(
        tmp_path,
        entries=["codex", "unregistered"],
        expected_authors=expected_authors,
        byline="Synthetic attribution",
    )
    original_source = source.read_bytes()
    state = tmp_path / "isolated-state"
    with caplog.at_level(logging.ERROR):
        rc = _run_publisher(source, state)

    assert rc == 1
    assert not state.exists()
    assert source.read_bytes() == original_source
    assert "unrecognized co_authors entry 'unregistered'" in caplog.text
