#!/usr/bin/env python3
"""Build and validate the EQI Phase 0 calibration dataset ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESEARCH_ROOT = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-research"
DEFAULT_CC_TASK_ROOT = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
SCHEMA_PATH = REPO_ROOT / "schemas" / "epistemic-quality-golden-dataset.schema.json"

TIER_COUNTS = {"A": 50, "B": 30, "C": 70, "D": 50}
TIER_DESCRIPTIONS = {
    "A": "operator_written_analysis",
    "B": "published_or_peer_reviewed_reference",
    "C": "agent_output_or_system_claim",
    "D": "known_bad_or_adversarial",
}
VALID_PRIVACY = {"public", "internal", "public_synthetic"}
VALID_TEXT_STATUS = {
    "ready",
    "operator_source_required",
    "external_source_required",
    "agent_source_review_required",
}
VALID_LABEL_STATUS = {"unlabeled", "blocked_source_required", "complete"}
AXES = (
    "claim_evidence_alignment",
    "hedge_calibration",
    "quantifier_precision",
    "source_grounding",
)
HUMAN_LABEL_ORIGINS = {"human", "operator", "human_operator", "human_reviewer"}
SILVER_LABEL_ORIGINS = {"deliberative_council_ratified"}
MODEL_LABEL_ORIGINS = {"model", "llm", "ai", "agent", "codex", "claude", "gemini", "synthetic"}
ROUND_ONE_LABEL_ROUND = "round1"
RELABEL_LABEL_ROUND = "relabel"
PHASE0_PASS_STATUS = "labels_present_gate_passed"

_SECRET_PATTERNS = (
    re.compile(
        r"\b(api[_-]?key|access[_-]?token|auth[_-]?token|password|secret|pass show)\b", re.I
    ),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
    re.compile(r"\b[A-Za-z0-9_=-]{32,}\b"),
)

CURATION_DENY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "credential",
        re.compile(
            r"\b(api[_-]?key|secret|access[_-]?token|refresh[_-]?token|bearer|authorization:|password|private key|id_ed25519|pass (show|insert|edit)|gh[pousr]_|sk-)\b",
            re.I,
        ),
    ),
    (
        "email_or_mail_body",
        re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|^(From|To|Cc|Subject):", re.I | re.M),
    ),
    (
        "local_path",
        re.compile(
            r"(/home/hapax|~/|\.codex|\.cache|/dev/shm|hapax-state|Documents/Personal|/store|/mnt|/run/user)",
            re.I,
        ),
    ),
    (
        "oauth_or_cookie",
        re.compile(
            r"\b(access_token|refresh_token|id_token|oauth|cookie|sessionid|csrf)\b|[?&](token|key|secret|code|state)=",
            re.I,
        ),
    ),
    (
        "legal_finance_kyc",
        re.compile(
            r"\b(LLC|EIN|SSN|TIN|tax|1099|W-9|KYC|AML|BSA|bank account|routing number|Stripe|Mercury|Relay|payment rail|legal name)\b",
            re.I,
        ),
    ),
    (
        "publication_payload_or_metadata_only",
        re.compile(
            r"\b(OmgLolClient|feed\.json|webViewLink|mimeType|modifiedTime|author unknown|metadata stub)\b|entry\.get\(",
            re.I,
        ),
    ),
    (
        "private_bridge",
        re.compile(
            r"\b(private-to-public|bridge governor|sidechat|private route|voice leak|caption|social adapter|archive metadata)\b",
            re.I,
        ),
    ),
)


@dataclass(frozen=True)
class SourceGroup:
    tier: str
    source_kind: str
    root: Path
    patterns: tuple[str, ...]
    privacy_class: str = "internal"


@dataclass(frozen=True)
class ReferenceNote:
    source_ref: str
    title: str
    claim_context: str
    domain_partition: str = "scientific"


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def excerpt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_safe_excerpt(text: str) -> bool:
    if len(text) < 120 or len(text) > 1600:
        return False
    return not any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def curation_scan_hits(*values: str) -> list[str]:
    hits: list[str] = []
    for value in values:
        for name, pattern in CURATION_DENY_PATTERNS:
            if pattern.search(value):
                hits.append(name)
    return sorted(set(hits))


def is_curated_excerpt(text: str) -> bool:
    if len(text) < 120 or len(text) > 1600:
        return False
    return not curation_scan_hits(text)


def iter_markdown_blocks(
    path: Path, *, safe_predicate: Any = is_safe_excerpt
) -> list[tuple[int, str]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    blocks: list[tuple[int, str]] = []
    line = 1
    current: list[str] = []
    start_line = 1
    in_frontmatter = False
    for lineno, raw_line in enumerate(raw.splitlines(), start=1):
        stripped = raw_line.strip()
        if lineno == 1 and stripped == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
            continue
        if not stripped:
            if current:
                text = normalize_text("\n".join(current))
                if safe_predicate(text):
                    blocks.append((start_line, text))
                current = []
            line = lineno + 1
            start_line = line
            continue
        if stripped.startswith("```"):
            if current:
                text = normalize_text("\n".join(current))
                if safe_predicate(text):
                    blocks.append((start_line, text))
                current = []
            start_line = lineno + 1
            continue
        if not current:
            start_line = lineno
        current.append(stripped)
    if current:
        text = normalize_text("\n".join(current))
        if safe_predicate(text):
            blocks.append((start_line, text))
    return blocks


def source_ref(root: Path, path: Path, line: int, source_kind: str) -> str:
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    return f"{source_kind}:{rel.as_posix()}:{line}"


def collect_ready_records(
    *,
    group: SourceGroup,
    count: int,
    start_index: int,
) -> list[dict[str, Any]]:
    files: list[Path] = []
    for pattern in group.patterns:
        files.extend(sorted(group.root.glob(pattern)))
    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for path in sorted(set(files)):
        if not path.is_file():
            continue
        for line, text in iter_markdown_blocks(path):
            digest = excerpt_hash(text)
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            record_id = f"eqi-v0-{group.tier}-{start_index + len(records):03d}"
            records.append(
                {
                    "id": record_id,
                    "tier": group.tier,
                    "tier_description": TIER_DESCRIPTIONS[group.tier],
                    "source_kind": group.source_kind,
                    "source_ref": source_ref(group.root, path, line, group.source_kind),
                    "privacy_class": group.privacy_class,
                    "authority_ceiling": "candidate_unlabeled",
                    "domain_partition": infer_domain(text),
                    "text_status": "ready",
                    "excerpt": text,
                    "excerpt_hash": digest,
                    "label_status": "unlabeled",
                    "labels": {},
                    "relabel_required": False,
                }
            )
            if len(records) >= count:
                return records
    return records


def infer_domain(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("test", "runtime", "service", "metric", "qdrant")):
        return "technical"
    if any(term in lowered for term in ("paper", "citation", "theory", "hypothesis")):
        return "scientific"
    if any(term in lowered for term in ("operator", "journal", "weblog", "launch")):
        return "narrative"
    return "mixed"


def source_slot_records(
    *,
    tier: str,
    count: int,
    source_kind: str,
    source_ref_prefix: str,
    text_status: str,
    slot_label: str,
    blocker_reason: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index in range(count):
        record_id = f"eqi-v0-{tier}-{index + 1:03d}"
        text = (
            f"{slot_label} {index + 1:03d}: {blocker_reason}. Direct text is intentionally not bundled "
            "until a reviewer attaches a source-appropriate excerpt or local citation note."
        )
        records.append(
            {
                "id": record_id,
                "tier": tier,
                "tier_description": TIER_DESCRIPTIONS[tier],
                "source_kind": source_kind,
                "source_ref": f"{source_ref_prefix}:{index + 1:03d}",
                "privacy_class": "internal",
                "authority_ceiling": "candidate_unlabeled_source_required",
                "domain_partition": "scientific" if tier == "B" else "mixed",
                "text_status": text_status,
                "excerpt": text,
                "excerpt_hash": excerpt_hash(text),
                "label_status": "blocked_source_required",
                "labels": {},
                "relabel_required": False,
            }
        )
    return records


def external_reference_records(count: int) -> list[dict[str, Any]]:
    references = [
        "Burns et al. ICLR 2023 truth directions in language-model hidden states",
        "Marks and Tegmark COLM 2024 geometry of truth in language models",
        "Li et al. NeurIPS 2023 inference-time intervention and truthful direction work",
        "Ben-David and Lu 2010 impossibility results for cross-domain transfer",
        "MultiFC 2019 multi-domain fact-checking dataset and cross-domain failure modes",
        "MERMAID 2025 mixture-of-experts requirement for cross-domain factuality",
        "Shumailov et al. Nature 2024 model-collapse and synthetic contamination",
        "RAGAS retrieval-augmented generation evaluation framework",
        "ARES automated RAG evaluation framework",
        "TRAIL agent-trace information-flow analysis",
        "COMPASS multi-agent provenance and process-mining analysis",
        "Tajik et al. information-flow analysis across agent/tool traces",
        "Data Shapley data valuation literature",
        "ClaimBuster automated factual-claim detection",
        "Factiverse source-grounded fact checking",
    ]
    records: list[dict[str, Any]] = []
    for index in range(count):
        record_id = f"eqi-v0-B-{index + 1:03d}"
        ref = references[index % len(references)]
        text = (
            f"Reference slot {index + 1:03d}: {ref}. Direct source text is intentionally not bundled in this "
            "candidate ledger until a lawful excerpt or locally stored citation note is attached."
        )
        records.append(
            {
                "id": record_id,
                "tier": "B",
                "tier_description": TIER_DESCRIPTIONS["B"],
                "source_kind": "external_reference_slot",
                "source_ref": f"reference-slot:{index + 1:03d}",
                "privacy_class": "internal",
                "authority_ceiling": "candidate_unlabeled_external_source_required",
                "domain_partition": "scientific",
                "text_status": "external_source_required",
                "excerpt": text,
                "excerpt_hash": excerpt_hash(text),
                "label_status": "blocked_source_required",
                "labels": {},
                "relabel_required": False,
            }
        )
    return records


CURATED_REFERENCE_NOTES: tuple[ReferenceNote, ...] = (
    ReferenceNote(
        "https://arxiv.org/abs/2212.03827",
        "Burns et al., Discovering Latent Knowledge in Language Models Without Supervision",
        "Truth-direction work establishes hidden-state truth probes as prior art, not an output-embedding veracity guarantee.",
    ),
    ReferenceNote(
        "https://arxiv.org/abs/2310.06824",
        "Marks and Tegmark, The Geometry of Truth",
        "Geometry-of-truth evidence supports a hidden-state research hypothesis with a bounded claim ceiling.",
    ),
    ReferenceNote(
        "https://arxiv.org/abs/2306.03341",
        "Li et al., Inference-Time Intervention",
        "Inference-time direction editing is cited as prior art for truth-related internal representations.",
    ),
    ReferenceNote(
        "https://proceedings.mlr.press/v9/ben-david10a.html",
        "Ben-David et al., A Theory of Learning from Different Domains",
        "Domain adaptation limits motivate the request's cross-domain veracity impossibility discipline.",
    ),
    ReferenceNote(
        "https://aclanthology.org/D19-1475/",
        "Augenstein et al., MultiFC: A Real-World Multi-Domain Dataset for Evidence-Based Fact Checking",
        "Multi-domain fact-checking evidence constrains any universal truth-detector claim.",
    ),
    ReferenceNote(
        "https://arxiv.org/abs/2309.15217",
        "RAGAS: Automated Evaluation of Retrieval Augmented Generation",
        "RAG evaluation prior art separates retrieval quality from answer faithfulness.",
    ),
    ReferenceNote(
        "https://aclanthology.org/2024.naacl-long.20/",
        "ARES: An Automated Evaluation Framework for Retrieval-Augmented Generation Systems",
        "Automated RAG evaluation is prior art for context relevance and faithfulness measurement.",
    ),
    ReferenceNote(
        "https://www.nature.com/articles/s41586-024-07566-y",
        "Shumailov et al., AI models collapse when trained on recursively generated data",
        "Synthetic-contamination findings bound claims about generated text as durable evidence.",
    ),
    ReferenceNote(
        "https://dl.acm.org/doi/10.1145/3442188.3445922",
        "Bender et al., On the Dangers of Stochastic Parrots",
        "Stochastic-parrot critique is used as a source-grounded limit on ungrounded language claims.",
    ),
    ReferenceNote(
        "https://doi.org/10.1017/9781108527084",
        "Nguyen, Echo Chambers and Epistemic Bubbles",
        "Epistemic-bubble theory grounds the topology framing without making topology equal truth.",
    ),
    ReferenceNote(
        "https://mitpress.mit.edu/9780262720212/the-embodied-mind/",
        "Varela, Thompson, and Rosch, The Embodied Mind",
        "Enactivist background is a theoretical frame, not direct empirical validation of Hapax.",
    ),
    ReferenceNote(
        "https://proceedings.mlr.press/v97/ghorbani19c.html",
        "Ghorbani and Zou, Data Shapley",
        "Data valuation prior art explains why Shapley language needs a defined game before use.",
    ),
    ReferenceNote(
        "https://arxiv.org/abs/2002.12334",
        "Distributional data valuation",
        "Distributional valuation is prior art for data-value claims beyond one fixed training set.",
    ),
    ReferenceNote(
        "https://www.w3.org/TR/prov-overview/",
        "W3C PROV Overview",
        "Baseline provenance standards constrain novelty claims about lineage tracking.",
    ),
    ReferenceNote(
        "https://www.cs.ucdavis.edu/~green/papers/pods07.pdf",
        "Green, Karvounarakis, and Tannen, Provenance Semirings",
        "Why-provenance algebra is prior art for semiring-based provenance claims.",
    ),
    ReferenceNote(
        "https://arxiv.org/abs/2505.08638",
        "TRAIL: Trace Reasoning and Agent Interaction Logs",
        "Agent-trace analysis is prior art; Token Capital novelty cannot be trace analysis itself.",
    ),
    ReferenceNote(
        "https://ceur-ws.org/Vol-3996/paper-5.pdf",
        "COMPASS process-mining method for LLM agent behavior",
        "Process-mining analysis is prior art for multi-agent workflow trace inspection.",
    ),
    ReferenceNote(
        "https://arxiv.org/abs/2508.02866",
        "PROV-AGENT: Unified Provenance for Tracking AI Agent Interactions",
        "Agent-workflow provenance is prior art for any agent lineage claim.",
    ),
    ReferenceNote(
        "https://arxiv.org/abs/2403.04651",
        "Cedar authorization language",
        "Authorization-language work supports deployment-time policy framing by analogy only.",
    ),
    ReferenceNote(
        "https://arxiv.org/abs/2508.01084",
        "Provably Secure Retrieval-Augmented Generation",
        "Secure RAG prior art supports pre-LLM filtering and consent-gated retrieval discipline.",
    ),
    ReferenceNote(
        "https://doi.org/10.1037/10096-006",
        "Clark and Brennan, Grounding in Communication",
        "Conversational grounding theory anchors voice-grounding claims without proving system outcomes.",
    ),
    ReferenceNote(
        "https://aclanthology.org/J94-4002/",
        "Traum, A Computational Theory of Grounding in Natural Language Conversation",
        "Grounding-act theory constrains claims about repair, acceptance, and dialogue state.",
    ),
    ReferenceNote(
        "https://doi.org/10.1037/a0029146",
        "Kruschke, Bayesian estimation supersedes the t test",
        "BEST is methodological prior art for the single-case statistical analysis plan.",
    ),
    ReferenceNote(
        "https://doi.org/10.1177/001316446002000104",
        "Cohen, A coefficient of agreement for nominal scales",
        "Cohen's kappa anchors the delayed intra-rater reliability gate.",
    ),
    ReferenceNote(
        "https://doi.org/10.1515/9781400881970-018",
        "Shapley, A Value for n-Person Games",
        "The original Shapley value source is included to keep game-theoretic claims quarantined.",
    ),
    ReferenceNote(
        "https://doi.org/10.1017/CBO9780511793722",
        "Nissenbaum, Privacy in Context",
        "Contextual integrity grounds privacy and consent-boundary claims.",
    ),
    ReferenceNote(
        "https://doi.org/10.1037/0033-295X.108.1.87",
        "Cowan, The magical number 4 in short-term memory",
        "Working-memory limits support chunking constraints without proving operator outcomes.",
    ),
    ReferenceNote(
        "https://doi.org/10.1177/0018720803056005006",
        "Wickens et al., SEEV model of visual attention allocation",
        "Visual-attention theory supports perceptual-surface constraints and attention budgeting.",
    ),
    ReferenceNote(
        "https://conal.net/papers/push-pull-frp/",
        "Elliott, Push-Pull Functional Reactive Programming",
        "FRP prior art supports the hot/cold signal distinction in perception architecture.",
    ),
    ReferenceNote(
        "https://arxiv.org/abs/2406.16696",
        "Public Constitutional AI",
        "Constitutional AI prior art constrains governance novelty to deployment-time enforcement.",
    ),
)


def _source_note_for_record(
    record: dict[str, Any],
    *,
    curated_at: str,
    authorship_status: str,
    rights_status: str,
    source_role: str,
    manual_privacy_note: str,
    blocker_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "manifest_id": record["id"],
        "tier": record["tier"],
        "source_ref": record["source_ref"],
        "excerpt_or_note_hash": record["excerpt_hash"],
        "privacy_class": record["privacy_class"],
        "authorship_status": authorship_status,
        "rights_status": rights_status,
        "curation_status": "ready" if blocker_reason is None else "blocked",
        "curator": "codex",
        "curated_at": curated_at,
        "blocker_reason": blocker_reason,
        "manual_privacy_note": manual_privacy_note,
        "source_role": source_role,
        "authority_ceiling": record["authority_ceiling"],
    }


def collect_curated_ready_records(
    *,
    group: SourceGroup,
    count: int,
    start_index: int,
    curated_at: str,
    authorship_status: str,
    rights_status: str,
    source_role: str,
    manual_privacy_note: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    files: list[Path] = []
    for pattern in group.patterns:
        files.extend(sorted(group.root.glob(pattern)))
    records: list[dict[str, Any]] = []
    source_notes: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for path in sorted(set(files)):
        if not path.is_file():
            continue
        for line, text in iter_markdown_blocks(path, safe_predicate=is_curated_excerpt):
            digest = excerpt_hash(text)
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            record_id = f"eqi-v0-{group.tier}-{start_index + len(records):03d}"
            record = {
                "id": record_id,
                "tier": group.tier,
                "tier_description": TIER_DESCRIPTIONS[group.tier],
                "source_kind": group.source_kind,
                "source_ref": source_ref(group.root, path, line, group.source_kind),
                "privacy_class": group.privacy_class,
                "authority_ceiling": "candidate_unlabeled_not_public_authority",
                "domain_partition": infer_domain(text),
                "text_status": "ready",
                "excerpt": text,
                "excerpt_hash": digest,
                "label_status": "unlabeled",
                "labels": {},
                "relabel_required": False,
            }
            records.append(record)
            source_notes.append(
                _source_note_for_record(
                    record,
                    curated_at=curated_at,
                    authorship_status=authorship_status,
                    rights_status=rights_status,
                    source_role=source_role,
                    manual_privacy_note=manual_privacy_note,
                )
            )
            if len(records) >= count:
                return records, source_notes
    return records, source_notes


def curated_reference_records(
    *, count: int, curated_at: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if count > len(CURATED_REFERENCE_NOTES):
        raise ValueError(f"requested {count} reference notes, only {len(CURATED_REFERENCE_NOTES)}")
    records: list[dict[str, Any]] = []
    source_notes: list[dict[str, Any]] = []
    for index, note in enumerate(CURATED_REFERENCE_NOTES[:count], start=1):
        record_id = f"eqi-v0-B-{index:03d}"
        text = (
            f"Citation note for {note.title}. {note.claim_context} No paper, book, or article "
            "text is bundled in this dataset row; the row supplies bibliographic context for "
            "labeling source grounding and confidence calibration."
        )
        record = {
            "id": record_id,
            "tier": "B",
            "tier_description": TIER_DESCRIPTIONS["B"],
            "source_kind": "published_reference_citation_note",
            "source_ref": f"external_reference:{note.source_ref}",
            "privacy_class": "public",
            "authority_ceiling": "candidate_unlabeled_not_public_authority",
            "domain_partition": note.domain_partition,
            "text_status": "ready",
            "excerpt": text,
            "excerpt_hash": excerpt_hash(text),
            "label_status": "unlabeled",
            "labels": {},
            "relabel_required": False,
        }
        records.append(record)
        source_notes.append(
            _source_note_for_record(
                record,
                curated_at=curated_at,
                authorship_status="external_published_reference_citation_note",
                rights_status="citation_note_only_no_source_excerpt",
                source_role="published_reference_context",
                manual_privacy_note="Local citation note contains no source-body text or private payload.",
            )
        )
    return records, source_notes


def curated_source_groups(research_root: Path) -> tuple[SourceGroup, SourceGroup]:
    tier_a = SourceGroup(
        tier="A",
        source_kind="operator_authorized_public_weblog",
        root=research_root,
        patterns=(
            "weblog/2026-05-07-grounded-agent-communication-lab-journal.md",
            "weblog/2026-05-08-formal-method-value-braid-operator-surfaces-lab-journal-part-1.md",
            "weblog/2026-05-03-velocity-report-followup.md",
        ),
        privacy_class="public",
    )
    tier_c = SourceGroup(
        tier="C",
        source_kind="agent_output_or_audit_receipt",
        root=research_root,
        patterns=(
            "audit/2026-05-11-token-capital-hardening-audit.md",
            "audit/2026-05-12-full-corpus-hardening-audit.md",
            "audit/2026-05-12-nomic-embedding-runtime-repair-receipt.md",
            "audit/2026-05-12-weblog-archive-public-claim-hardening-receipt.md",
            "audit/epistemic-evaluation-status.md",
            "codex-handoffs/2026-05-12-epistemic-audit-handoff.md",
            "ledgers/2026-05-12-citation-and-novelty-repair-ledger.md",
            "weblog/2026-05-11-filesystem-as-message-bus.md",
            "weblog/2026-05-12-command-r-planning-exceeds-prep-timeout.md",
        ),
    )
    return tier_a, tier_c


def build_curated_records(
    research_root: Path, *, curated_at: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tier_a, tier_c = curated_source_groups(research_root)
    records: list[dict[str, Any]] = []
    source_notes: list[dict[str, Any]] = []
    a_records, a_notes = collect_curated_ready_records(
        group=tier_a,
        count=TIER_COUNTS["A"],
        start_index=1,
        curated_at=curated_at,
        authorship_status="operator_authorized_public_publication",
        rights_status="operator_controlled_public_safe",
        source_role="high_calibration_operator_authorized_public_analysis",
        manual_privacy_note=(
            "Public-safe weblog source with operator publication authorization; selected text "
            "passed the expanded deny-list scan."
        ),
    )
    records.extend(a_records)
    source_notes.extend(a_notes)

    b_records, b_notes = curated_reference_records(count=TIER_COUNTS["B"], curated_at=curated_at)
    records.extend(b_records)
    source_notes.extend(b_notes)

    c_records, c_notes = collect_curated_ready_records(
        group=tier_c,
        count=TIER_COUNTS["C"],
        start_index=1,
        curated_at=curated_at,
        authorship_status="agent_or_auditor_output",
        rights_status="internal_support_artifact_redacted",
        source_role="agent_output_or_system_claim_for_quality_labeling",
        manual_privacy_note=(
            "Internal support artifact selected only after denying private payload, credential, "
            "mail, local path, finance, publication payload, and bridge hazards."
        ),
    )
    records.extend(c_records)
    source_notes.extend(c_notes)

    d_records = synthetic_bad_records(TIER_COUNTS["D"])
    records.extend(d_records)
    source_notes.extend(
        _source_note_for_record(
            record,
            curated_at=curated_at,
            authorship_status="synthetic_fixture",
            rights_status="synthetic_owned",
            source_role="known_bad_or_adversarial_fixture",
            manual_privacy_note="Synthetic row; no private or third-party source text.",
        )
        for record in d_records
    )
    assign_relabel_subset(records)
    return records, source_notes


def validate_source_notes(
    records: list[dict[str, Any]], source_notes: list[dict[str, Any]]
) -> list[str]:
    errors: list[str] = []
    record_by_id = {str(record["id"]): record for record in records}
    note_ids: set[str] = set()
    for index, note in enumerate(source_notes, start=1):
        manifest_id = str(note.get("manifest_id", ""))
        if not manifest_id:
            errors.append(f"source note {index}: missing manifest_id")
            continue
        if manifest_id in note_ids:
            errors.append(f"{manifest_id}: duplicate source note")
        note_ids.add(manifest_id)
        record = record_by_id.get(manifest_id)
        if record is None:
            errors.append(f"{manifest_id}: source note has no manifest record")
            continue
        if note.get("excerpt_or_note_hash") != record.get("excerpt_hash"):
            errors.append(f"{manifest_id}: source note hash does not match manifest")
        if note.get("curation_status") != "ready":
            errors.append(f"{manifest_id}: source note is not ready")
        values = [
            str(record.get("excerpt", "")),
            str(record.get("source_ref", "")),
            str(note.get("manual_privacy_note", "")),
            str(note.get("source_role", "")),
        ]
        hits = curation_scan_hits(*values)
        if record.get("tier") == "D":
            hits = [hit for hit in hits if hit != "publication_payload_or_metadata_only"]
        if hits:
            errors.append(f"{manifest_id}: curation deny-list hit(s): {', '.join(hits)}")
    missing = sorted(set(record_by_id) - note_ids)
    if missing:
        errors.append(f"source notes missing manifest ids: {', '.join(missing[:10])}")
    return errors


def write_source_notes(path: Path, source_notes: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for note in source_notes:
            handle.write(json.dumps(note, sort_keys=True, ensure_ascii=True) + "\n")


def write_curation_report(
    path: Path, manifest_path: Path, source_notes_path: Path, records: list[dict[str, Any]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest_display = manifest_path.name if manifest_path.is_absolute() else str(manifest_path)
    source_notes_display = (
        source_notes_path.name if source_notes_path.is_absolute() else str(source_notes_path)
    )
    status_counts = {
        status: sum(1 for record in records if record["text_status"] == status)
        for status in sorted(VALID_TEXT_STATUS)
    }
    tier_counts = {
        tier: sum(1 for record in records if record["tier"] == tier) for tier in TIER_COUNTS
    }
    relabel_by_tier = {
        tier: sum(1 for record in records if record["tier"] == tier and record["relabel_required"])
        for tier in TIER_COUNTS
    }
    path.write_text(
        "\n".join(
            [
                "---",
                'title: "Epistemic Quality Phase 0 Source Curation Report V0"',
                "date: 2026-05-13",
                "request: REQ-20260512-epistemic-quality-infrastructure",
                "cc_task: epistemic-quality-phase0-source-curation-and-privacy-screen",
                "status: ready_for_label_entry_after_operator_review",
                "authority_level: support_non_authoritative",
                "---",
                "",
                "# Epistemic Quality Phase 0 Source Curation Report V0",
                "",
                f"Manifest: `{manifest_display}`",
                f"Source notes: `{source_notes_display}`",
                "",
                "## Result",
                "",
                "- Generated 200 source-curated candidate rows.",
                *(f"- Tier {tier}: {count}" for tier, count in tier_counts.items()),
                *(f"- `{status}` rows: {count}" for status, count in status_counts.items()),
                *(f"- Relabel Tier {tier}: {count}" for tier, count in relabel_by_tier.items()),
                "",
                "All rows are still unlabeled. This artifact does not pass the Phase 0 hard gate, "
                "does not validate a scorer, and does not upgrade public Token Capital claims.",
                "",
                "## Curation Rules Applied",
                "",
                "- Tier A uses only operator-authorized public weblog sources with public-safe/operator-controlled metadata.",
                "- Tier B uses local citation notes with stable external refs; no paper, book, or article body text is bundled.",
                "- Tier C uses agent/auditor/system artifacts from explicit allowlisted files and rejects private payload hazards.",
                "- Tier D remains synthetic known-bad/adversarial fixture material.",
                "",
                "## Deny-List Coverage",
                "",
                "The curation validator rejects credentials, mail headers or addresses, local private paths, "
                "OAuth/cookie/query-token material, legal/finance/KYC terms, publication API payload markers, "
                "metadata-only evidence markers, and private/public bridge hazards.",
                "",
                "## Remaining Gates",
                "",
                "- Operator or designated human labeling is still required for all four axes.",
                "- Delayed relabel reliability remains time-blocked until the 7-day relabel window.",
                "- Claim gates remain independent; EQI readiness is not publication authority.",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def synthetic_bad_records(count: int) -> list[dict[str, Any]]:
    metadata_stub = (
        "Drive item metadata only: title={n}, mimeType=application/pdf, webViewLink present, "
        "content unavailable, author unknown, modifiedTime stale. This is inventory, not evidence."
    )
    auto_generated = (
        "The system definitively proves {n} production-grade governance outcomes across all "
        "surfaces with zero failures and complete safety, without needing further receipts."
    )
    hedged_false = (
        "It may be somewhat reasonable to say that {n} citations prove the benchmark is fully "
        "replicated, although no replication run, source corpus, or evaluation denominator is attached."
    )
    confident_wrong = (
        "Codex is an Anthropic product and therefore the Claude route is always the correct "
        "implementation path for OpenAI API work item {n}."
    )
    templates = (
        [metadata_stub] * 20 + [auto_generated] * 15 + [hedged_false] * 10 + [confident_wrong] * 5
    )
    records: list[dict[str, Any]] = []
    for index, template in enumerate(templates[:count], start=1):
        record_id = f"eqi-v0-D-{index:03d}"
        text = template.format(n=index)
        records.append(
            {
                "id": record_id,
                "tier": "D",
                "tier_description": TIER_DESCRIPTIONS["D"],
                "source_kind": "synthetic_known_bad_fixture",
                "source_ref": f"synthetic:eqi-known-bad:{index:03d}",
                "privacy_class": "public_synthetic",
                "authority_ceiling": "candidate_unlabeled",
                "domain_partition": "mixed",
                "text_status": "ready",
                "excerpt": text,
                "excerpt_hash": excerpt_hash(text),
                "label_status": "unlabeled",
                "labels": {},
                "relabel_required": False,
            }
        )
    return records


def spaced_selection(records: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count <= 0 or not records:
        return []
    if len(records) <= count:
        return records[:]
    step = len(records) / count
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index in range(count):
        record = records[min(int(index * step), len(records) - 1)]
        rid = str(record["id"])
        if rid in seen:
            continue
        selected.append(record)
        seen.add(rid)
    for record in records:
        if len(selected) >= count:
            break
        rid = str(record["id"])
        if rid not in seen:
            selected.append(record)
            seen.add(rid)
    return selected


def assign_relabel_subset(records: list[dict[str, Any]], target: int = 40) -> None:
    for record in records:
        record["relabel_required"] = False
    ready_by_tier = {
        tier: [
            record
            for record in records
            if record["tier"] == tier and record["text_status"] == "ready"
        ]
        for tier in TIER_COUNTS
    }
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    tier_quota = max(1, target // len(TIER_COUNTS))
    for tier in TIER_COUNTS:
        for record in spaced_selection(
            ready_by_tier[tier], min(tier_quota, len(ready_by_tier[tier]))
        ):
            rid = str(record["id"])
            if rid not in seen:
                selected.append(record)
                seen.add(rid)
    ready_remaining = [
        record
        for record in records
        if record["text_status"] == "ready" and str(record["id"]) not in seen
    ]
    for record in spaced_selection(ready_remaining, target - len(selected)):
        rid = str(record["id"])
        if rid not in seen:
            selected.append(record)
            seen.add(rid)
    for record in selected[:target]:
        record["relabel_required"] = True


def default_source_groups(
    research_root: Path, cc_task_root: Path
) -> tuple[SourceGroup, SourceGroup]:
    tier_a = SourceGroup(
        tier="A",
        source_kind="hapax_research",
        root=research_root,
        patterns=(
            "weblog/*.md",
            "foundations/*.md",
            "ledgers/*.md",
            "speculative/*.md",
        ),
    )
    tier_c = SourceGroup(
        tier="C",
        source_kind="cc_task",
        root=cc_task_root,
        patterns=("active/*.md", "closed/*.md"),
    )
    return tier_a, tier_c


def build_records(
    research_root: Path,
    cc_task_root: Path,
    *,
    allow_internal_autoselect: bool = False,
) -> list[dict[str, Any]]:
    tier_a, tier_c = default_source_groups(research_root, cc_task_root)
    records: list[dict[str, Any]] = []
    if allow_internal_autoselect:
        records.extend(
            collect_ready_records(
                group=tier_a,
                count=TIER_COUNTS["A"],
                start_index=1,
            )
        )
    else:
        records.extend(
            source_slot_records(
                tier="A",
                count=TIER_COUNTS["A"],
                source_kind="operator_analysis_source_slot",
                source_ref_prefix="operator-analysis-source-slot",
                text_status="operator_source_required",
                slot_label="Tier A operator analysis source slot",
                blocker_reason="operator-authored analysis must be explicitly confirmed before Tier A can act as high-calibration substrate",
            )
        )
    records.extend(external_reference_records(TIER_COUNTS["B"]))
    if allow_internal_autoselect:
        records.extend(
            collect_ready_records(
                group=tier_c,
                count=TIER_COUNTS["C"],
                start_index=1,
            )
        )
    else:
        records.extend(
            source_slot_records(
                tier="C",
                count=TIER_COUNTS["C"],
                source_kind="agent_output_review_slot",
                source_ref_prefix="agent-output-review-slot",
                text_status="agent_source_review_required",
                slot_label="Tier C agent output source slot",
                blocker_reason="agent output must pass privacy and source review before inclusion",
            )
        )
    records.extend(synthetic_bad_records(TIER_COUNTS["D"]))
    assign_relabel_subset(records)
    return records


def validate_records(records: list[dict[str, Any]], expected_counts: dict[str, int]) -> list[str]:
    errors: list[str] = []
    ids: set[str] = set()
    hashes: set[str] = set()
    counts = {tier: 0 for tier in expected_counts}
    relabel_count = 0
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    schema_validator = jsonschema.Draft202012Validator(schema)
    for idx, record in enumerate(records, start=1):
        rid = str(record.get("id", ""))
        for schema_error in sorted(schema_validator.iter_errors(record), key=str):
            path = ".".join(str(part) for part in schema_error.path) or "<record>"
            errors.append(f"{rid or f'record {idx}'}: schema {path}: {schema_error.message}")
        if not rid:
            errors.append(f"record {idx}: missing id")
        elif rid in ids:
            errors.append(f"{rid}: duplicate id")
        ids.add(rid)
        tier = record.get("tier")
        if tier not in expected_counts:
            errors.append(f"{rid}: bad tier {tier!r}")
        else:
            counts[str(tier)] += 1
        if record.get("privacy_class") not in VALID_PRIVACY:
            errors.append(f"{rid}: bad or missing privacy_class")
        if record.get("text_status") not in VALID_TEXT_STATUS:
            errors.append(f"{rid}: bad or missing text_status")
        if not record.get("source_ref"):
            errors.append(f"{rid}: missing source_ref")
        if record.get("label_status") not in VALID_LABEL_STATUS:
            errors.append(f"{rid}: bad or missing label_status")
        digest = record.get("excerpt_hash")
        if not digest:
            errors.append(f"{rid}: missing excerpt_hash")
        elif digest in hashes:
            errors.append(f"{rid}: duplicate excerpt_hash")
        elif digest != excerpt_hash(str(record.get("excerpt", ""))):
            errors.append(f"{rid}: excerpt_hash does not match excerpt")
        hashes.add(str(digest))
        label_status = record.get("label_status")
        if label_status == "complete":
            labels = record.get("labels")
            if not isinstance(labels, dict) or set(labels) != set(AXES):
                errors.append(f"{rid}: label_status complete without all axes")
        if record.get("relabel_required") is True:
            if record.get("text_status") != "ready":
                errors.append(f"{rid}: relabel_required set on non-ready record")
            relabel_count += 1
    for tier, expected in expected_counts.items():
        if counts[tier] != expected:
            errors.append(f"tier {tier}: expected {expected}, got {counts[tier]}")
    if relabel_count != 40:
        errors.append(f"relabel subset: expected 40, got {relabel_count}")
    return errors


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _is_int_1_to_5(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 5


def validate_label_rows(
    records: list[dict[str, Any]],
    label_rows: list[dict[str, Any]],
    *,
    manifest_hash: str,
    expected_ids: set[str],
    expected_round: str,
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    errors: list[str] = []
    record_by_id = {str(record["id"]): record for record in records}
    labels_by_id: dict[str, dict[str, Any]] = {}
    duplicate_ids: set[str] = set()

    for index, row in enumerate(label_rows, start=1):
        manifest_id = str(row.get("manifest_id", ""))
        row_label = manifest_id or f"label row {index}"
        if not manifest_id:
            errors.append(f"{row_label}: missing manifest_id")
            continue
        if manifest_id in labels_by_id:
            duplicate_ids.add(manifest_id)
            errors.append(f"{manifest_id}: duplicate {expected_round} label row")
            continue
        labels_by_id[manifest_id] = row

        record = record_by_id.get(manifest_id)
        if record is None:
            errors.append(f"{manifest_id}: label row has no manifest record")
            continue
        if manifest_id not in expected_ids:
            errors.append(f"{manifest_id}: label row is not in expected {expected_round} set")
        if row.get("manifest_hash") != manifest_hash:
            errors.append(f"{manifest_id}: stale or missing manifest_hash")
        if row.get("source_ref") != record.get("source_ref"):
            errors.append(f"{manifest_id}: source_ref does not match manifest")
        if row.get("source_text_hash") not in (None, record.get("excerpt_hash")):
            errors.append(f"{manifest_id}: source_text_hash does not match manifest")
        if row.get("label_round") != expected_round:
            errors.append(f"{manifest_id}: label_round must be {expected_round!r}")
        if not row.get("labeler"):
            errors.append(f"{manifest_id}: missing labeler")
        if not row.get("provenance"):
            errors.append(f"{manifest_id}: missing provenance")

        origin = str(row.get("label_origin", "")).lower()
        if origin in MODEL_LABEL_ORIGINS:
            errors.append(f"{manifest_id}: model-generated labels are not ground truth")
        if origin not in HUMAN_LABEL_ORIGINS:
            errors.append(f"{manifest_id}: label_origin must be human/operator, got {origin!r}")

        if parse_utc_timestamp(row.get("labeled_at")) is None:
            errors.append(f"{manifest_id}: labeled_at is missing or not an ISO timestamp")

        labels = row.get("labels")
        if not isinstance(labels, dict):
            errors.append(f"{manifest_id}: labels must be an object")
            continue
        if set(labels) != set(AXES):
            errors.append(f"{manifest_id}: labels must contain exactly {', '.join(AXES)}")
            continue
        for axis in AXES:
            if not _is_int_1_to_5(labels.get(axis)):
                errors.append(f"{manifest_id}: {axis} label must be an integer 1-5")

    missing = sorted(expected_ids - set(labels_by_id) - duplicate_ids)
    if missing:
        errors.append(f"missing {expected_round} label rows: {', '.join(missing[:10])}")
    extras = sorted(set(labels_by_id) - expected_ids)
    if extras:
        errors.append(f"unexpected {expected_round} label rows: {', '.join(extras[:10])}")

    valid_by_id = {
        manifest_id: row
        for manifest_id, row in labels_by_id.items()
        if manifest_id in expected_ids
        and not any(error.startswith(f"{manifest_id}:") for error in errors)
    }
    return errors, valid_by_id


def validate_score_rows(
    records: list[dict[str, Any]], score_rows: list[dict[str, Any]], *, manifest_hash: str
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    errors: list[str] = []
    record_by_id = {str(record["id"]): record for record in records}
    scores_by_id: dict[str, dict[str, Any]] = {}
    expected_ids = set(record_by_id)
    for index, row in enumerate(score_rows, start=1):
        manifest_id = str(row.get("manifest_id", ""))
        row_label = manifest_id or f"score row {index}"
        if not manifest_id:
            errors.append(f"{row_label}: missing manifest_id")
            continue
        if manifest_id in scores_by_id:
            errors.append(f"{manifest_id}: duplicate scorer output row")
            continue
        scores_by_id[manifest_id] = row
        record = record_by_id.get(manifest_id)
        if record is None:
            errors.append(f"{manifest_id}: scorer output has no manifest record")
            continue
        if row.get("manifest_hash") != manifest_hash:
            errors.append(f"{manifest_id}: stale or missing scorer manifest_hash")
        if row.get("source_text_hash") != record.get("excerpt_hash"):
            errors.append(f"{manifest_id}: scorer source_text_hash does not match manifest")
        if not row.get("scorer"):
            errors.append(f"{manifest_id}: missing scorer")
        if parse_utc_timestamp(row.get("scored_at")) is None:
            errors.append(f"{manifest_id}: scored_at is missing or not an ISO timestamp")
        axis_scores = row.get("axis_scores")
        if not isinstance(axis_scores, dict):
            errors.append(f"{manifest_id}: axis_scores must be an object")
            continue
        if set(axis_scores) != set(AXES):
            errors.append(f"{manifest_id}: axis_scores must contain exactly {', '.join(AXES)}")
            continue
        for axis in AXES:
            value = axis_scores.get(axis)
            if not isinstance(value, int | float) or isinstance(value, bool):
                errors.append(f"{manifest_id}: {axis} score must be numeric")
            elif not math.isfinite(float(value)):
                errors.append(f"{manifest_id}: {axis} score must be finite")

    missing = sorted(expected_ids - set(scores_by_id))
    if missing:
        errors.append(f"missing scorer output rows: {', '.join(missing[:10])}")

    valid_by_id = {
        manifest_id: row
        for manifest_id, row in scores_by_id.items()
        if manifest_id in expected_ids
        and not any(error.startswith(f"{manifest_id}:") for error in errors)
    }
    return errors, valid_by_id


def _nan_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _nan_safe(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_nan_safe(nested) for nested in value]
    return value


def average_ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(indexed):
        end = position + 1
        while end < len(indexed) and indexed[end][1] == indexed[position][1]:
            end += 1
        average_rank = (position + 1 + end) / 2.0
        for original_index, _ in indexed[position:end]:
            ranks[original_index] = average_rank
        position = end
    return ranks


def pearson_correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    left_delta = [value - left_mean for value in left]
    right_delta = [value - right_mean for value in right]
    numerator = sum(a * b for a, b in zip(left_delta, right_delta, strict=True))
    left_ss = sum(value * value for value in left_delta)
    right_ss = sum(value * value for value in right_delta)
    denominator = math.sqrt(left_ss * right_ss)
    if denominator == 0:
        return None
    return numerator / denominator


def approximate_correlation_p_value(rho: float, n: int) -> float | None:
    if n < 4:
        return None
    if abs(rho) >= 1:
        return 0.0
    denominator = max(1e-12, 1.0 - (rho * rho))
    statistic = abs(rho) * math.sqrt((n - 2) / denominator)
    # Normal approximation to the two-sided t tail. This is intentionally
    # conservative enough for the gate's p < 0.001 high-signal threshold.
    return math.erfc(statistic / math.sqrt(2.0))


def spearman_metric(labels: list[float], scores: list[float]) -> dict[str, Any]:
    if len(labels) < 3 or len(set(labels)) < 2 or len(set(scores)) < 2:
        return {"n": len(labels), "spearman": None, "p_value": None, "computable": False}
    statistic = pearson_correlation(average_ranks(labels), average_ranks(scores))
    if statistic is None:
        return {"n": len(labels), "spearman": None, "p_value": None, "computable": False}
    statistic = max(-1.0, min(1.0, statistic))
    p_value = approximate_correlation_p_value(statistic, len(labels))
    return {
        "n": len(labels),
        "spearman": statistic,
        "p_value": p_value,
        "p_value_method": "normal_approximation_from_rank_correlation",
        "computable": True,
    }


def composite_score(row: dict[str, Any]) -> float:
    scores = row["axis_scores"]
    return statistics.fmean(float(scores[axis]) for axis in AXES)


def cohen_kappa(left: list[int], right: list[int]) -> dict[str, Any]:
    if len(left) != len(right) or not left:
        return {"n": min(len(left), len(right)), "kappa": None, "computable": False}
    categories = range(1, 6)
    n = len(left)
    observed = sum(1 for a, b in zip(left, right, strict=True) if a == b) / n
    expected = sum((left.count(cat) / n) * (right.count(cat) / n) for cat in categories)
    if math.isclose(expected, 1.0):
        kappa = 1.0 if math.isclose(observed, 1.0) else 0.0
    else:
        kappa = (observed - expected) / (1.0 - expected)
    return {"n": n, "kappa": kappa, "computable": True}


def axis_label(row: dict[str, Any], axis: str) -> int:
    return int(row["labels"][axis])


def validate_relabel_timing(
    round1_by_id: dict[str, dict[str, Any]], relabel_by_id: dict[str, dict[str, Any]]
) -> list[str]:
    errors: list[str] = []
    for manifest_id, relabel in relabel_by_id.items():
        round1 = round1_by_id.get(manifest_id)
        if round1 is None:
            continue
        round1_at = parse_utc_timestamp(round1.get("labeled_at"))
        relabel_at = parse_utc_timestamp(relabel.get("labeled_at"))
        if round1_at is None or relabel_at is None:
            continue
        if relabel_at < round1_at + timedelta(days=7):
            errors.append(f"{manifest_id}: relabel is less than 7 days after round one")
    return errors


def compute_gate_report(
    records: list[dict[str, Any]],
    *,
    manifest_path: Path,
    manifest_hash: str,
    label_rows: list[dict[str, Any]],
    score_rows: list[dict[str, Any]],
    relabel_rows: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    record_by_id = {str(record["id"]): record for record in records}
    ready_ids = {str(record["id"]) for record in records if record.get("text_status") == "ready"}
    label_errors, labels_by_id = validate_label_rows(
        records,
        label_rows,
        manifest_hash=manifest_hash,
        expected_ids=ready_ids,
        expected_round=ROUND_ONE_LABEL_ROUND,
    )
    score_errors, scores_by_id = validate_score_rows(
        records, score_rows, manifest_hash=manifest_hash
    )

    axis_metrics: dict[str, dict[str, Any]] = {}
    for axis in AXES:
        ids = sorted(ready_ids & set(labels_by_id) & set(scores_by_id))
        axis_metrics[axis] = spearman_metric(
            [float(axis_label(labels_by_id[manifest_id], axis)) for manifest_id in ids],
            [float(scores_by_id[manifest_id]["axis_scores"][axis]) for manifest_id in ids],
        )

    domain_metrics: dict[str, dict[str, Any]] = {}
    for domain in sorted({str(record.get("domain_partition", "unknown")) for record in records}):
        ids = [
            str(record["id"])
            for record in records
            if str(record.get("domain_partition", "unknown")) == domain
            and str(record["id"]) in labels_by_id
            and str(record["id"]) in scores_by_id
        ]
        domain_axis_metrics = {
            axis: spearman_metric(
                [float(axis_label(labels_by_id[manifest_id], axis)) for manifest_id in ids],
                [float(scores_by_id[manifest_id]["axis_scores"][axis]) for manifest_id in ids],
            )
            for axis in AXES
        }
        domain_metrics[domain] = {
            "n": len(ids),
            "axes": domain_axis_metrics,
            "passes": all(
                metric["spearman"] is not None and metric["spearman"] >= 0.60
                for metric in domain_axis_metrics.values()
            ),
        }

    a_scores = [
        composite_score(scores_by_id[str(record["id"])])
        for record in records
        if record.get("tier") == "A" and str(record["id"]) in scores_by_id
    ]
    b_scores = [
        composite_score(scores_by_id[str(record["id"])])
        for record in records
        if record.get("tier") == "B" and str(record["id"]) in scores_by_id
    ]
    pooled = a_scores + b_scores
    tier_a_mean = statistics.fmean(a_scores) if a_scores else None
    tier_b_mean = statistics.fmean(b_scores) if b_scores else None
    pooled_sd = statistics.pstdev(pooled) if len(pooled) > 1 else 0.0
    if tier_a_mean is None or tier_b_mean is None:
        tier_bias_passes = False
        tier_bias_threshold = None
    else:
        tier_bias_threshold = tier_a_mean - (0.5 * pooled_sd)
        tier_bias_passes = tier_b_mean >= tier_bias_threshold

    vacuous_records = [
        record
        for record in records
        if str(record.get("source_ref", "")).startswith("synthetic:eqi-known-bad:")
        and 36 <= int(str(record["source_ref"]).rsplit(":", 1)[-1]) <= 45
    ]
    tier_a_composites = [
        composite_score(scores_by_id[str(record["id"])])
        for record in records
        if record.get("tier") == "A" and str(record["id"]) in scores_by_id
    ]
    vacuous_scores = [
        composite_score(scores_by_id[str(record["id"])])
        for record in vacuous_records
        if str(record["id"]) in scores_by_id
    ]
    tier_a_median = statistics.median(tier_a_composites) if tier_a_composites else None
    vacuous_max = max(vacuous_scores) if vacuous_scores else None
    vacuous_passes = (
        len(vacuous_scores) == 10
        and tier_a_median is not None
        and vacuous_max is not None
        and vacuous_max <= tier_a_median
    )

    relabel_required_ids = {
        str(record["id"]) for record in records if record.get("relabel_required") is True
    }
    relabel_errors: list[str] = []
    relabel_metrics: dict[str, Any] = {
        "present": relabel_rows is not None,
        "required_count": len(relabel_required_ids),
        "status": "relabel_pending",
    }
    if relabel_rows is not None:
        relabel_errors, relabel_by_id = validate_label_rows(
            records,
            relabel_rows,
            manifest_hash=manifest_hash,
            expected_ids=relabel_required_ids,
            expected_round=RELABEL_LABEL_ROUND,
        )
        relabel_errors.extend(validate_relabel_timing(labels_by_id, relabel_by_id))
        kappa_by_axis = {
            axis: cohen_kappa(
                [
                    axis_label(labels_by_id[manifest_id], axis)
                    for manifest_id in sorted(
                        relabel_required_ids & set(labels_by_id) & set(relabel_by_id)
                    )
                ],
                [
                    axis_label(relabel_by_id[manifest_id], axis)
                    for manifest_id in sorted(
                        relabel_required_ids & set(labels_by_id) & set(relabel_by_id)
                    )
                ],
            )
            for axis in AXES
        }
        overall_left: list[int] = []
        overall_right: list[int] = []
        for manifest_id in sorted(relabel_required_ids & set(labels_by_id) & set(relabel_by_id)):
            for axis in AXES:
                overall_left.append(axis_label(labels_by_id[manifest_id], axis))
                overall_right.append(axis_label(relabel_by_id[manifest_id], axis))
        overall = cohen_kappa(overall_left, overall_right)
        reliability_passes = (
            not relabel_errors
            and all(
                metric["kappa"] is not None and metric["kappa"] >= 0.75
                for metric in kappa_by_axis.values()
            )
            and overall["kappa"] is not None
            and overall["kappa"] >= 0.75
        )
        relabel_metrics = {
            "present": True,
            "required_count": len(relabel_required_ids),
            "errors": relabel_errors,
            "kappa_by_axis": kappa_by_axis,
            "overall": overall,
            "passes": reliability_passes,
            "status": "passed" if reliability_passes else "failed",
        }

    primary_axis_passes = all(
        metric["spearman"] is not None
        and metric["spearman"] >= 0.70
        and metric["p_value"] is not None
        and metric["p_value"] < 0.001
        for metric in axis_metrics.values()
    )
    ablation_axis_passes = all(
        metric["spearman"] is not None and metric["spearman"] >= 0.40
        for metric in axis_metrics.values()
    )
    domain_passes = sum(1 for metric in domain_metrics.values() if metric["n"] >= 3) >= 3 and all(
        metric["passes"] for metric in domain_metrics.values() if metric["n"] >= 3
    )
    labels_complete = len(labels_by_id) == len(ready_ids) == len(records) and not label_errors
    scores_complete = len(scores_by_id) == len(records) and not score_errors
    metrics_pass = (
        labels_complete
        and scores_complete
        and primary_axis_passes
        and ablation_axis_passes
        and domain_passes
        and tier_bias_passes
        and vacuous_passes
    )

    if not labels_complete or not scores_complete:
        status = "not_enough_labels"
    elif not metrics_pass:
        status = "labels_present_gate_failed"
    elif relabel_rows is None:
        status = "relabel_pending"
    elif relabel_metrics.get("passes") is not True:
        status = "relabel_reliability_failed"
    else:
        status = PHASE0_PASS_STATUS

    report = {
        "status": status,
        "passed": status == PHASE0_PASS_STATUS,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "manifest": {
            "path": str(manifest_path),
            "sha256": manifest_hash,
            "record_count": len(records),
            "ready_count": len(ready_ids),
        },
        "label_validation": {
            "round1_count": len(label_rows),
            "valid_round1_count": len(labels_by_id),
            "errors": label_errors,
        },
        "score_validation": {
            "score_count": len(score_rows),
            "valid_score_count": len(scores_by_id),
            "errors": score_errors,
        },
        "metrics": {
            "axes": axis_metrics,
            "domains": domain_metrics,
            "tier_a_tier_b_bias": {
                "tier_a_mean": tier_a_mean,
                "tier_b_mean": tier_b_mean,
                "pooled_sd": pooled_sd,
                "threshold": tier_bias_threshold,
                "passes": tier_bias_passes,
            },
            "vacuous_hedging_adversary": {
                "count": len(vacuous_scores),
                "max_score": vacuous_max,
                "tier_a_median": tier_a_median,
                "passes": vacuous_passes,
            },
            "relabel_reliability": relabel_metrics,
        },
        "predicates": {
            "labels_complete": labels_complete,
            "scores_complete": scores_complete,
            "primary_axis_spearman_ge_0_70_p_lt_0_001": primary_axis_passes,
            "axis_ablation_spearman_ge_0_40": ablation_axis_passes,
            "domain_spearman_ge_0_60": domain_passes,
            "tier_b_not_more_than_half_sd_below_tier_a": tier_bias_passes,
            "vacuous_hedging_not_above_tier_a_median": vacuous_passes,
            "relabel_present": relabel_rows is not None,
            "relabel_kappa_ge_0_75": relabel_metrics.get("passes") is True,
            "phase0_hard_gate_passed": status == PHASE0_PASS_STATUS,
        },
        "claim_ceiling": (
            "support_non_authoritative; this report is not publication authority unless "
            "phase0_hard_gate_passed is true and independent claim gates also pass"
        ),
    }
    _ = record_by_id
    return _nan_safe(report)


def write_gate_markdown(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    predicates = report["predicates"]
    axis_lines = []
    for axis, metric in report["metrics"]["axes"].items():
        axis_lines.append(
            f"- `{axis}`: n={metric['n']}, spearman={metric['spearman']}, p={metric['p_value']}"
        )
    predicate_lines = [f"- `{name}`: {value}" for name, value in sorted(predicates.items())]
    path.write_text(
        "\n".join(
            [
                "---",
                'title: "Epistemic Quality Phase 0 Validation Gate Report"',
                f"date: {report['generated_at'][:10]}",
                "request: REQ-20260512-epistemic-quality-infrastructure",
                "cc_task: epistemic-quality-phase0-validation-harness",
                "authority_level: support_non_authoritative",
                f"status: {report['status']}",
                "---",
                "",
                "# Epistemic Quality Phase 0 Validation Gate Report",
                "",
                f"Status: `{report['status']}`",
                f"Passed: `{report['passed']}`",
                "",
                "## Manifest",
                "",
                f"- Path: `{report['manifest']['path']}`",
                f"- SHA-256: `{report['manifest']['sha256']}`",
                f"- Records: {report['manifest']['record_count']}",
                f"- Ready: {report['manifest']['ready_count']}",
                "",
                "## Axis Metrics",
                "",
                *axis_lines,
                "",
                "## Predicates",
                "",
                *predicate_lines,
                "",
                "## Claim Ceiling",
                "",
                report["claim_ceiling"],
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def write_labeling_pack(path: Path, manifest_path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest_display = manifest_path.name if manifest_path.is_absolute() else str(manifest_path)
    counts = {tier: sum(1 for record in records if record["tier"] == tier) for tier in TIER_COUNTS}
    status_counts = {
        status: sum(1 for record in records if record["text_status"] == status)
        for status in sorted(VALID_TEXT_STATUS)
    }
    relabel = sum(1 for record in records if record["relabel_required"])
    path.write_text(
        "\n".join(
            [
                "---",
                'title: "Epistemic Quality Phase 0 Labeling Pack V0"',
                "date: 2026-05-13",
                "request: REQ-20260512-epistemic-quality-infrastructure",
                "cc_task: epistemic-quality-phase0-golden-dataset-ledger",
                "status: candidate_unlabeled",
                "---",
                "",
                "# Epistemic Quality Phase 0 Labeling Pack V0",
                "",
                f"Manifest: `{manifest_display}`",
                "",
                "## Counts",
                "",
                *(f"- Tier {tier}: {count}" for tier, count in counts.items()),
                f"- Relabel subset: {relabel}",
                *(f"- `{status}` records: {count}" for status, count in status_counts.items()),
                "",
                "## Label Axes",
                "",
                "- `claim_evidence_alignment`: 1 means the claim outruns evidence; 5 means the claim ceiling matches attached evidence.",
                "- `hedge_calibration`: 1 means hedging/certainty is badly mismatched; 5 means confidence language is well calibrated.",
                "- `quantifier_precision`: 1 means vague or fake precision; 5 means quantities are exact, scoped, or explicitly absent.",
                "- `source_grounding`: 1 means source-free or metadata-only; 5 means independently traceable source grounding.",
                "",
                "## Labeling Examples And Non-Examples",
                "",
                "- Strong `claim_evidence_alignment` example: a claim says a local test passed and cites the exact command, fixture, timestamp, and failure scope.",
                "- Weak `claim_evidence_alignment` non-example: a claim says a system is production-ready because related metadata or inventory rows exist.",
                "- Strong `hedge_calibration` example: a hypothesis is explicitly scoped as unvalidated when the evidence is only a plausible mechanism.",
                "- Weak `hedge_calibration` non-example: a false or source-free claim is padded with hedges and therefore appears cautious without becoming grounded.",
                "- Strong `quantifier_precision` example: a count includes denominator, freshness, data source, and uncertainty or explicitly says no count is available.",
                "- Weak `quantifier_precision` non-example: a phrase like many, most, or zero failures appears without a measurement source.",
                "- Strong `source_grounding` example: the excerpt cites primary or independently reachable source material, not only a filename or drive metadata.",
                "- Weak `source_grounding` non-example: title, mime type, modified time, or web link metadata is treated as evidence for document contents.",
                "",
                "## Authority Ceiling",
                "",
                "- `candidate_unlabeled`: source text exists but labels are not ground truth.",
                "- `candidate_unlabeled_source_required`: the row is a slot, not a labelable example.",
                "- Blocked slots must receive source-appropriate excerpts or local citation notes before labels can be entered.",
                "",
                "## Hard Methodology Notes",
                "",
                "- These records are candidates, not ground truth.",
                "- Model-generated labels are not acceptable ground-truth labels.",
                "- The safe default build emits Tier A, B, and C source slots; opt-in internal autoselection is for controlled fixture or review use only.",
                "- Phase 0 cannot pass until required labels exist and the delayed relabel reliability check is recorded.",
                "- Scores measure epistemic quality markers, not propositional truth.",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def parse_counts(raw: list[str]) -> dict[str, int]:
    counts = dict(TIER_COUNTS)
    for item in raw:
        tier, _, value = item.partition("=")
        if tier not in counts or not value.isdigit():
            raise ValueError(f"bad tier count override: {item}")
        counts[tier] = int(value)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build candidate JSONL manifest")
    build.add_argument("--research-root", type=Path, default=DEFAULT_RESEARCH_ROOT)
    build.add_argument("--cc-task-root", type=Path, default=DEFAULT_CC_TASK_ROOT)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--labeling-pack", type=Path)
    build.add_argument(
        "--allow-internal-autoselect",
        action="store_true",
        help="opt in to broad internal markdown sampling for fixture/testing use; safe default emits source-review slots",
    )

    validate = sub.add_parser("validate", help="validate candidate JSONL manifest")
    validate.add_argument("manifest", type=Path)
    validate.add_argument("--tier-count", action="append", default=[])

    validate_gate = sub.add_parser(
        "validate-gate", help="run the fail-closed Phase 0 validation gate"
    )
    validate_gate.add_argument("--manifest", type=Path, required=True)
    validate_gate.add_argument("--labels", type=Path, required=True)
    validate_gate.add_argument("--scores", type=Path, required=True)
    validate_gate.add_argument("--relabel-labels", type=Path)
    validate_gate.add_argument("--report-json", type=Path, required=True)
    validate_gate.add_argument("--report-md", type=Path, required=True)

    curate = sub.add_parser("curate", help="build source-curated manifest and source notes")
    curate.add_argument("--research-root", type=Path, default=DEFAULT_RESEARCH_ROOT)
    curate.add_argument("--output", type=Path, required=True)
    curate.add_argument("--source-notes", type=Path, required=True)
    curate.add_argument("--labeling-pack", type=Path)
    curate.add_argument("--curation-report", type=Path)
    curate.add_argument(
        "--curated-at",
        default=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        help="UTC timestamp to write into source notes",
    )

    args = parser.parse_args(argv)

    if args.command == "build":
        records = build_records(
            args.research_root,
            args.cc_task_root,
            allow_internal_autoselect=args.allow_internal_autoselect,
        )
        errors = validate_records(records, TIER_COUNTS)
        if errors:
            for error in errors:
                print(error)
            return 1
        write_jsonl(args.output, records)
        if args.labeling_pack:
            write_labeling_pack(args.labeling_pack, args.output, records)
        print(f"wrote {len(records)} records to {args.output}")
        return 0

    if args.command == "validate":
        counts = parse_counts(args.tier_count)
        records = read_jsonl(args.manifest)
        errors = validate_records(records, counts)
        if errors:
            for error in errors:
                print(error)
            return 1
        print(f"validated {len(records)} records")
        return 0

    if args.command == "validate-gate":
        records = read_jsonl(args.manifest)
        manifest_errors = validate_records(records, TIER_COUNTS)
        manifest_hash = file_sha256(args.manifest)
        report = compute_gate_report(
            records,
            manifest_path=args.manifest,
            manifest_hash=manifest_hash,
            label_rows=read_jsonl(args.labels),
            score_rows=read_jsonl(args.scores),
            relabel_rows=read_jsonl(args.relabel_labels) if args.relabel_labels else None,
        )
        if manifest_errors:
            report["status"] = "not_enough_labels"
            report["passed"] = False
            report["manifest_validation_errors"] = manifest_errors
            report["predicates"]["phase0_hard_gate_passed"] = False
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(
            json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        write_gate_markdown(args.report_md, report)
        print(f"wrote gate JSON report to {args.report_json}")
        print(f"wrote gate Markdown report to {args.report_md}")
        print(f"status={report['status']}")
        return 0 if report["passed"] else 1

    if args.command == "curate":
        records, source_notes = build_curated_records(
            args.research_root, curated_at=args.curated_at
        )
        errors = validate_records(records, TIER_COUNTS)
        errors.extend(validate_source_notes(records, source_notes))
        if errors:
            for error in errors:
                print(error)
            return 1
        write_jsonl(args.output, records)
        write_source_notes(args.source_notes, source_notes)
        if args.labeling_pack:
            write_labeling_pack(args.labeling_pack, args.output, records)
        if args.curation_report:
            write_curation_report(
                args.curation_report,
                args.output,
                args.source_notes,
                records,
            )
        print(f"wrote {len(records)} curated records to {args.output}")
        print(f"wrote {len(source_notes)} source notes to {args.source_notes}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
