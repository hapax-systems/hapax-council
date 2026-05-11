"""Generate dataset cards from the research corpus export ledger.

Reads ``config/research-corpus-export-ledger.yaml``, filters to corpora
whose ``consumer_modes`` include ``dataset_cards``, and generates one
structured card per corpus.  Cards that fail safety checks (missing
attestation, unresolved field statuses, PII filter gaps) are emitted as
``not_releasable_yet`` with a blocker list.

Each card includes: scope limits, n=1 methodology note, data fields with
export status, redactions applied, rights class, provenance, intended
use, prohibited use, and citation/identifier state.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

LEDGER_PATH = Path("config/research-corpus-export-ledger.yaml")
CONSUMER_MODE = "dataset_cards"
PRODUCER_NAME = "agents.dataset_card_generator"

_PII_FILTERS = frozenset(
    {
        "legal_name_to_operator_referent",
        "email_address_redaction",
        "secret_value_block",
        "employer_material_path_block",
        "non_operator_person_state_block",
        "private_vault_body_drop",
    }
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}")
_SECRET_RE = re.compile(
    r"(api[_-]?key|token|secret|password|credential|cookie)\s*[:=]",
    re.IGNORECASE,
)
_LOCAL_PATH_RE = re.compile(r"(/home/[a-z]+|/Users/[a-z]+|/tmp/)")


class ExportStatus(StrEnum):
    PUBLIC = "public"
    ANONYMIZED = "anonymized"
    HASH_ONLY = "hash_only"
    AGGREGATE_ONLY = "aggregate_only"
    PRIVATE = "private"
    FORBIDDEN = "forbidden"


class ReleaseVerdict(StrEnum):
    RELEASABLE = "releasable"
    NOT_RELEASABLE_YET = "not_releasable_yet"


class CardModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FieldCard(CardModel):
    """One field's export status within a corpus card."""

    field: str
    status: ExportStatus
    transform: str
    rationale: str


class RightsPosture(CardModel):
    rights_class: str
    license_basis: str
    public_license: str | None
    attribution_required: bool
    monetization_allowed: bool
    public_release_allowed: bool
    notes: str | None = None


class ReleaseGate(CardModel):
    recurring_operator_review_required: bool
    bootstrap_attestation_required: bool
    bootstrap_attestation_ref: str | None = None
    blocks_on_uncertain_fields: bool


class DatasetCard(CardModel):
    """One corpus dataset card — rendered to markdown for release."""

    corpus_id: str
    display_name: str
    generated_at: str
    producer: str = PRODUCER_NAME
    verdict: ReleaseVerdict
    blockers: tuple[str, ...] = Field(default_factory=tuple)
    scope_limits: str
    methodology_note: str
    source_refs: tuple[str, ...]
    fields: tuple[FieldCard, ...]
    redaction_filters: tuple[str, ...]
    rights_posture: RightsPosture
    release_gate: ReleaseGate
    intended_use: str
    prohibited_use: str
    citation_state: str
    failure_mode: str


class DatasetCardBatch(CardModel):
    """All cards for one generator run."""

    schema_version: Literal[1] = 1
    generated_at: str
    producer: str = PRODUCER_NAME
    ledger_id: str
    cards: tuple[DatasetCard, ...]


def load_ledger(path: Path = LEDGER_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def generate_cards(ledger: dict[str, Any]) -> DatasetCardBatch:
    """Generate dataset cards for all corpora that include dataset_cards."""
    now = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    corpora = ledger.get("corpora", [])
    global_policy = ledger.get("global_policy", {})
    cards: list[DatasetCard] = []

    for corpus in corpora:
        if CONSUMER_MODE not in corpus.get("consumer_modes", []):
            continue
        cards.append(_build_card(corpus, global_policy, now))

    return DatasetCardBatch(
        generated_at=now,
        ledger_id=ledger.get("ledger_id", "unknown"),
        cards=tuple(cards),
    )


def _build_card(
    corpus: dict[str, Any],
    global_policy: dict[str, Any],
    now: str,
) -> DatasetCard:
    corpus_id = corpus["corpus_id"]
    display_name = corpus.get("display_name", corpus_id)
    source_refs = tuple(corpus.get("source_refs", []))

    fields = tuple(
        FieldCard(
            field=f["field"],
            status=ExportStatus(f["status"]),
            transform=f.get("transform", "none"),
            rationale=f.get("rationale", ""),
        )
        for f in corpus.get("field_statuses", [])
    )

    rp_raw = corpus.get("rights_posture", {})
    rights_posture = RightsPosture(
        rights_class=rp_raw.get("rights_class", "unknown"),
        license_basis=rp_raw.get("license_basis", ""),
        public_license=rp_raw.get("public_license"),
        attribution_required=rp_raw.get("attribution_required", True),
        monetization_allowed=rp_raw.get("monetization_allowed", False),
        public_release_allowed=rp_raw.get("public_release_allowed", False),
        notes=rp_raw.get("notes"),
    )

    rg_raw = corpus.get("release_gate", {})
    release_gate = ReleaseGate(
        recurring_operator_review_required=rg_raw.get("recurring_operator_review_required", False),
        bootstrap_attestation_required=rg_raw.get("bootstrap_attestation_required", True),
        bootstrap_attestation_ref=rg_raw.get("bootstrap_attestation_ref"),
        blocks_on_uncertain_fields=rg_raw.get("blocks_on_uncertain_fields", True),
    )

    redaction_filters = tuple(corpus.get("automated_test_refs", []))
    failure_mode = corpus.get("failure_mode", "block_release")

    blockers = _compute_blockers(
        fields, rights_posture, release_gate, redaction_filters, global_policy
    )
    verdict = ReleaseVerdict.RELEASABLE if not blockers else ReleaseVerdict.NOT_RELEASABLE_YET

    return DatasetCard(
        corpus_id=corpus_id,
        display_name=display_name,
        generated_at=now,
        verdict=verdict,
        blockers=blockers,
        scope_limits=_scope_limits(corpus_id),
        methodology_note=_methodology_note(),
        source_refs=source_refs,
        fields=fields,
        redaction_filters=redaction_filters,
        rights_posture=rights_posture,
        release_gate=release_gate,
        intended_use=_intended_use(corpus_id),
        prohibited_use=_prohibited_use(),
        citation_state=_citation_state(rights_posture),
        failure_mode=failure_mode,
    )


def _compute_blockers(
    fields: tuple[FieldCard, ...],
    rights_posture: RightsPosture,
    release_gate: ReleaseGate,
    redaction_filters: tuple[str, ...],
    global_policy: dict[str, Any],
) -> tuple[str, ...]:
    blockers: list[str] = []

    if release_gate.bootstrap_attestation_required:
        blockers.append("bootstrap_attestation_not_verified")

    if release_gate.blocks_on_uncertain_fields:
        for f in fields:
            if f.status == ExportStatus.FORBIDDEN:
                blockers.append(f"forbidden_field:{f.field}")

    if not rights_posture.public_release_allowed:
        blockers.append("public_release_not_allowed")

    if rights_posture.rights_class in ("unknown", "uncleared"):
        blockers.append(f"uncleared_rights:{rights_posture.rights_class}")

    missing_pii = _PII_FILTERS - set(redaction_filters)
    for filt in sorted(missing_pii):
        blockers.append(f"missing_pii_filter:{filt}")

    if global_policy.get("fail_closed_on_uncertain_status", True):
        for f in fields:
            if f.transform == "none" and f.status not in (
                ExportStatus.PUBLIC,
                ExportStatus.HASH_ONLY,
            ):
                blockers.append(f"uncertain_field_no_transform:{f.field}")

    return tuple(dict.fromkeys(blockers))


def scan_text_for_pii(text: str) -> list[str]:
    """Scan text for PII patterns. Returns list of findings."""
    findings: list[str] = []
    if _EMAIL_RE.search(text):
        findings.append("email_address_detected")
    if _SECRET_RE.search(text):
        findings.append("secret_pattern_detected")
    if _LOCAL_PATH_RE.search(text):
        findings.append("local_path_detected")
    return findings


def _scope_limits(corpus_id: str) -> str:
    return (
        f"Single-operator (n=1) research apparatus. "
        f"Corpus '{corpus_id}' is derived from one developer's daily work. "
        f"No population-level claims. No multi-site generalization."
    )


def _methodology_note() -> str:
    return (
        "Single-case experimental design (SCED). All observations are from "
        "one operator working on one system. Results document what happened, "
        "not what generalizes. Treat as case-study evidence only."
    )


def _intended_use(corpus_id: str) -> str:
    return (
        f"Research reproducibility, SCED case-study evidence, "
        f"grant/fellowship application documentation, "
        f"and open-science dataset publication for '{corpus_id}'."
    )


def _prohibited_use() -> str:
    return (
        "Training models on private operator data. "
        "De-anonymizing the operator or third parties. "
        "Redistributing forbidden or consent-required fields. "
        "Claiming population-level findings from n=1 data. "
        "Commercial use without explicit license."
    )


def _citation_state(rights_posture: RightsPosture) -> str:
    if rights_posture.public_license:
        return f"Licensed under {rights_posture.public_license}. Attribution required."
    return "License pending per-record rights_class. Attribution required."


def render_card_markdown(card: DatasetCard) -> str:
    """Render one dataset card as markdown."""
    lines: list[str] = []
    lines.append(f"# Dataset Card: {card.display_name}")
    lines.append("")
    lines.append(f"**Corpus ID**: `{card.corpus_id}`")
    lines.append(f"**Generated**: {card.generated_at}")
    lines.append(f"**Producer**: `{card.producer}`")
    lines.append(f"**Verdict**: {card.verdict.value}")
    lines.append("")

    if card.blockers:
        lines.append("## Release Blockers")
        lines.append("")
        for b in card.blockers:
            lines.append(f"- {b}")
        lines.append("")

    lines.append("## Scope and Methodology")
    lines.append("")
    lines.append(card.scope_limits)
    lines.append("")
    lines.append(card.methodology_note)
    lines.append("")

    lines.append("## Source References")
    lines.append("")
    for ref in card.source_refs:
        lines.append(f"- `{ref}`")
    lines.append("")

    lines.append("## Data Fields")
    lines.append("")
    lines.append("| Field | Status | Transform | Rationale |")
    lines.append("|-------|--------|-----------|-----------|")
    for f in card.fields:
        lines.append(f"| `{f.field}` | {f.status.value} | {f.transform} | {f.rationale} |")
    lines.append("")

    lines.append("## Redaction Filters Applied")
    lines.append("")
    for rf in card.redaction_filters:
        lines.append(f"- `{rf}`")
    lines.append("")

    lines.append("## Rights and Licensing")
    lines.append("")
    lines.append(f"- **Rights class**: {card.rights_posture.rights_class}")
    lines.append(f"- **License basis**: {card.rights_posture.license_basis}")
    if card.rights_posture.public_license:
        lines.append(f"- **Public license**: {card.rights_posture.public_license}")
    lines.append(f"- **Attribution required**: {card.rights_posture.attribution_required}")
    lines.append(f"- **Monetization allowed**: {card.rights_posture.monetization_allowed}")
    if card.rights_posture.notes:
        lines.append(f"- **Notes**: {card.rights_posture.notes}")
    lines.append("")

    lines.append("## Intended Use")
    lines.append("")
    lines.append(card.intended_use)
    lines.append("")

    lines.append("## Prohibited Use")
    lines.append("")
    lines.append(card.prohibited_use)
    lines.append("")

    lines.append("## Citation")
    lines.append("")
    lines.append(card.citation_state)
    lines.append("")

    lines.append("## Release Gate")
    lines.append("")
    lines.append(
        f"- **Bootstrap attestation required**: {card.release_gate.bootstrap_attestation_required}"
    )
    if card.release_gate.bootstrap_attestation_ref:
        lines.append(f"- **Attestation ref**: `{card.release_gate.bootstrap_attestation_ref}`")
    lines.append(
        f"- **Blocks on uncertain fields**: {card.release_gate.blocks_on_uncertain_fields}"
    )
    lines.append(f"- **Failure mode**: {card.failure_mode}")
    lines.append("")

    return "\n".join(lines)


def render_batch_markdown(batch: DatasetCardBatch) -> str:
    """Render all cards as a single markdown document."""
    sections: list[str] = []
    sections.append("# Research Artifact Dataset Cards")
    sections.append("")
    sections.append(f"Generated at {batch.generated_at} by `{batch.producer}`.")
    sections.append(f"Ledger: `{batch.ledger_id}`.")
    sections.append("")

    releasable = sum(1 for c in batch.cards if c.verdict == ReleaseVerdict.RELEASABLE)
    total = len(batch.cards)
    sections.append(f"**{releasable}/{total}** corpora releasable.")
    sections.append("")
    sections.append("---")
    sections.append("")

    for card in batch.cards:
        sections.append(render_card_markdown(card))
        sections.append("---")
        sections.append("")

    return "\n".join(sections)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ledger", type=Path, default=LEDGER_PATH, help="Path to export ledger YAML"
    )
    parser.add_argument("--output", type=Path, help="Write markdown to file instead of stdout")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of markdown")
    args = parser.parse_args(argv)

    ledger = load_ledger(args.ledger)
    batch = generate_cards(ledger)

    if args.json:
        import json

        output = json.dumps(batch.model_dump(mode="json"), indent=2)
    else:
        output = render_batch_markdown(batch)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DatasetCard",
    "DatasetCardBatch",
    "ExportStatus",
    "FieldCard",
    "ReleaseGate",
    "ReleaseVerdict",
    "RightsPosture",
    "generate_cards",
    "load_ledger",
    "render_batch_markdown",
    "render_card_markdown",
    "scan_text_for_pii",
]
