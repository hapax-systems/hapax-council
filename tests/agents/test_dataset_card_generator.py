"""Dataset card generator tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.dataset_card_generator import (
    ExportStatus,
    ReleaseVerdict,
    generate_cards,
    load_ledger,
    main,
    render_batch_markdown,
    render_card_markdown,
    scan_text_for_pii,
)


def _minimal_corpus(**overrides: Any) -> dict[str, Any]:
    corpus: dict[str, Any] = {
        "corpus_id": "test_corpus",
        "display_name": "Test Corpus",
        "source_refs": ["tests/fixtures/"],
        "consumer_modes": ["dataset_cards"],
        "default_export_status": "public",
        "field_statuses": [
            {
                "field": "test_field",
                "status": "public",
                "transform": "none",
                "rationale": "Safe for release.",
            },
        ],
        "rights_posture": {
            "rights_class": "operator_controlled",
            "license_basis": "Operator-authored test data.",
            "public_license": "CC-BY-NC-ND-4.0",
            "attribution_required": True,
            "monetization_allowed": False,
            "public_release_allowed": True,
        },
        "automated_test_refs": [
            "legal_name_to_operator_referent",
            "email_address_redaction",
            "secret_value_block",
            "employer_material_path_block",
            "non_operator_person_state_block",
            "private_vault_body_drop",
            "local_path_root_redaction",
        ],
        "release_gate": {
            "recurring_operator_review_required": False,
            "bootstrap_attestation_required": True,
            "bootstrap_attestation_ref": "legal/export-attestation:test",
            "blocks_on_uncertain_fields": True,
        },
        "failure_mode": "block_release",
    }
    corpus.update(overrides)
    return corpus


def _minimal_ledger(**overrides: Any) -> dict[str, Any]:
    ledger: dict[str, Any] = {
        "schema_version": 1,
        "ledger_id": "test_ledger:2026-05-10",
        "global_policy": {
            "single_operator_only": True,
            "fail_closed_on_uncertain_status": True,
            "forbidden_exports": ["credential_values"],
        },
        "corpora": [_minimal_corpus()],
    }
    ledger.update(overrides)
    return ledger


def test_generate_cards_produces_batch() -> None:
    batch = generate_cards(_minimal_ledger())
    assert batch.schema_version == 1
    assert len(batch.cards) == 1
    assert batch.ledger_id == "test_ledger:2026-05-10"


def test_card_has_required_fields() -> None:
    batch = generate_cards(_minimal_ledger())
    card = batch.cards[0]
    assert card.corpus_id == "test_corpus"
    assert card.display_name == "Test Corpus"
    assert card.scope_limits
    assert card.methodology_note
    assert card.intended_use
    assert card.prohibited_use
    assert card.citation_state


def test_card_includes_n1_methodology() -> None:
    batch = generate_cards(_minimal_ledger())
    card = batch.cards[0]
    assert "n=1" in card.scope_limits or "SCED" in card.methodology_note
    assert "single" in card.methodology_note.lower()


def test_card_field_statuses_preserved() -> None:
    batch = generate_cards(_minimal_ledger())
    card = batch.cards[0]
    assert len(card.fields) == 1
    assert card.fields[0].field == "test_field"
    assert card.fields[0].status == ExportStatus.PUBLIC


def test_card_rights_posture_preserved() -> None:
    batch = generate_cards(_minimal_ledger())
    card = batch.cards[0]
    assert card.rights_posture.rights_class == "operator_controlled"
    assert card.rights_posture.public_license == "CC-BY-NC-ND-4.0"
    assert card.rights_posture.attribution_required is True
    assert card.rights_posture.monetization_allowed is False


def test_card_blocked_by_bootstrap_attestation() -> None:
    batch = generate_cards(_minimal_ledger())
    card = batch.cards[0]
    assert card.verdict == ReleaseVerdict.NOT_RELEASABLE_YET
    assert "bootstrap_attestation_not_verified" in card.blockers


def test_card_blocked_by_forbidden_field() -> None:
    corpus = _minimal_corpus(
        field_statuses=[
            {"field": "secrets", "status": "forbidden", "transform": "block", "rationale": "No."},
        ],
    )
    batch = generate_cards(_minimal_ledger(corpora=[corpus]))
    card = batch.cards[0]
    assert card.verdict == ReleaseVerdict.NOT_RELEASABLE_YET
    assert any("forbidden_field" in b for b in card.blockers)


def test_card_blocked_by_uncleared_rights() -> None:
    corpus = _minimal_corpus(
        rights_posture={
            "rights_class": "unknown",
            "license_basis": "Undetermined.",
            "public_license": None,
            "attribution_required": True,
            "monetization_allowed": False,
            "public_release_allowed": True,
        },
    )
    batch = generate_cards(_minimal_ledger(corpora=[corpus]))
    card = batch.cards[0]
    assert any("uncleared_rights" in b for b in card.blockers)


def test_card_blocked_by_missing_pii_filter() -> None:
    corpus = _minimal_corpus(automated_test_refs=[])
    batch = generate_cards(_minimal_ledger(corpora=[corpus]))
    card = batch.cards[0]
    assert any("missing_pii_filter" in b for b in card.blockers)


def test_skips_corpora_without_dataset_cards_mode() -> None:
    corpus = _minimal_corpus(consumer_modes=["grant_packets"])
    batch = generate_cards(_minimal_ledger(corpora=[corpus]))
    assert len(batch.cards) == 0


def test_multiple_corpora_generate_multiple_cards() -> None:
    corpora = [
        _minimal_corpus(corpus_id="corpus_a", display_name="Corpus A"),
        _minimal_corpus(corpus_id="corpus_b", display_name="Corpus B"),
    ]
    batch = generate_cards(_minimal_ledger(corpora=corpora))
    assert len(batch.cards) == 2
    assert batch.cards[0].corpus_id == "corpus_a"
    assert batch.cards[1].corpus_id == "corpus_b"


def test_render_card_markdown_contains_key_sections() -> None:
    batch = generate_cards(_minimal_ledger())
    md = render_card_markdown(batch.cards[0])
    assert "# Dataset Card:" in md
    assert "## Scope and Methodology" in md
    assert "## Data Fields" in md
    assert "## Rights and Licensing" in md
    assert "## Intended Use" in md
    assert "## Prohibited Use" in md
    assert "## Citation" in md
    assert "## Release Gate" in md


def test_render_batch_markdown_contains_summary() -> None:
    batch = generate_cards(_minimal_ledger())
    md = render_batch_markdown(batch)
    assert "# Research Artifact Dataset Cards" in md
    assert "0/1" in md or "releasable" in md.lower()


def test_scan_text_for_pii_detects_email() -> None:
    findings = scan_text_for_pii("contact me at test@example.com")
    assert "email_address_detected" in findings


def test_scan_text_for_pii_detects_secrets() -> None:
    findings = scan_text_for_pii("api_key: sk-12345")
    assert "secret_pattern_detected" in findings


def test_scan_text_for_pii_detects_local_paths() -> None:
    findings = scan_text_for_pii("file at /tmp/data.json")
    assert "local_path_detected" in findings


def test_scan_text_for_pii_clean_text() -> None:
    findings = scan_text_for_pii("This is safe text without PII.")
    assert findings == []


def test_load_ledger_from_real_config() -> None:
    real_path = Path("config/research-corpus-export-ledger.yaml")
    if not real_path.exists():
        return
    ledger = load_ledger(real_path)
    batch = generate_cards(ledger)
    assert len(batch.cards) >= 7
    corpus_ids = {c.corpus_id for c in batch.cards}
    assert "cc_tasks" in corpus_ids
    assert "refusal_briefs" in corpus_ids
    assert "velocity_evidence" in corpus_ids


def test_cli_main_writes_markdown_output(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.yaml"
    output_path = tmp_path / "dataset-cards.md"
    import yaml

    ledger_path.write_text(yaml.safe_dump(_minimal_ledger()), encoding="utf-8")

    assert main(["--ledger", str(ledger_path), "--output", str(output_path)]) == 0
    output = output_path.read_text(encoding="utf-8")
    assert "# Research Artifact Dataset Cards" in output
    assert "Dataset Card: Test Corpus" in output


def test_not_releasable_card_includes_blockers_in_markdown() -> None:
    batch = generate_cards(_minimal_ledger())
    card = batch.cards[0]
    assert card.verdict == ReleaseVerdict.NOT_RELEASABLE_YET
    md = render_card_markdown(card)
    assert "## Release Blockers" in md
    assert "bootstrap_attestation_not_verified" in md


def test_prohibited_use_covers_required_checks() -> None:
    batch = generate_cards(_minimal_ledger())
    card = batch.cards[0]
    prohibited = card.prohibited_use.lower()
    assert "de-anonymiz" in prohibited
    assert "commercial" in prohibited
    assert "forbidden" in prohibited or "consent" in prohibited
