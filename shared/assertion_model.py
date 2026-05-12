"""Assertion data model for the Unb-AIRy discursive plane.

Each assertion is a structured record with canonical text, provenance,
confidence, and domain classification. Inspired by the nanopublication
model (assertion + provenance + publication info) and the AIF ontology
for relationship types.

Extraction pipelines produce Assertion instances from heterogeneous
sources (Python code, YAML configs, Obsidian markdown, governance specs,
commit messages). The Qdrant `assertions` collection stores embeddings
for semantic search.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, Field


class SourceType(StrEnum):
    CODE = "code"
    CONFIG = "config"
    MARKDOWN = "markdown"
    GOVERNANCE = "governance"
    COMMIT = "commit"
    PR = "pr"
    MEMORY = "memory"
    RELAY = "relay"
    TASK = "task"
    REQUEST = "request"


class AssertionType(StrEnum):
    AXIOM = "axiom"
    IMPLICATION = "implication"
    INVARIANT = "invariant"
    CONSTRAINT = "constraint"
    PREFERENCE = "preference"
    FACT = "fact"
    GOAL = "goal"
    DECISION = "decision"
    CLAIM = "claim"
    COROLLARY = "corollary"


class ProvenanceRecord(BaseModel):
    source_commit: str | None = None
    extraction_method: str = "manual"
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    extraction_version: str = "1.0"
    modification_history: list[dict[str, Any]] = Field(default_factory=list)


class Assertion(BaseModel):
    assertion_id: str = ""
    text: str
    atomic_facts: list[str] = Field(default_factory=list)
    source_type: SourceType
    source_uri: str
    source_span: tuple[int, int] | None = None
    confidence: float = 1.0
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    value_scores: dict[str, float] = Field(default_factory=dict)
    domain: str = "general"
    assertion_type: AssertionType
    provenance: ProvenanceRecord = Field(default_factory=ProvenanceRecord)
    tags: list[str] = Field(default_factory=list)
    supersedes: str | None = None
    superseded_by: str | None = None

    def model_post_init(self, _context: Any) -> None:
        if not self.assertion_id:
            content = f"{self.text}:{self.source_uri}:{self.source_type.value}"
            self.assertion_id = sha256(content.encode()).hexdigest()[:16]


def extract_from_axiom_registry(registry_path: str) -> list[Assertion]:
    from pathlib import Path

    import yaml

    path = Path(registry_path)
    if not path.exists():
        return []

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    axioms = data.get("axioms", [])
    assertions = []

    for axiom in axioms:
        assertions.append(
            Assertion(
                text=axiom.get("text", "").strip(),
                source_type=SourceType.GOVERNANCE,
                source_uri=str(path),
                confidence=1.0,
                domain="constitutional",
                assertion_type=AssertionType.AXIOM,
                tags=[
                    f"weight:{axiom.get('weight', 0)}",
                    f"scope:{axiom.get('scope', 'unknown')}",
                    f"type:{axiom.get('type', 'unknown')}",
                    f"id:{axiom.get('id', 'unknown')}",
                ],
                provenance=ProvenanceRecord(
                    extraction_method="axiom_registry_yaml",
                ),
            )
        )

    return assertions


def extract_from_implications(implications_dir: str) -> list[Assertion]:
    from pathlib import Path

    import yaml

    path = Path(implications_dir)
    if not path.is_dir():
        return []

    assertions = []
    for yf in sorted(path.glob("*.yaml")):
        data = yaml.safe_load(yf.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("implications", [])

        for item in items:
            if not isinstance(item, dict):
                continue
            text = item.get("text", item.get("implication", ""))
            if not text:
                continue

            assertions.append(
                Assertion(
                    text=text.strip(),
                    source_type=SourceType.GOVERNANCE,
                    source_uri=str(yf),
                    confidence=1.0,
                    domain="constitutional",
                    assertion_type=AssertionType.IMPLICATION,
                    tags=[
                        f"axiom:{item.get('axiom', item.get('source_axiom', 'unknown'))}",
                        f"id:{item.get('id', 'unknown')}",
                    ],
                    provenance=ProvenanceRecord(
                        extraction_method="constitution_implications_yaml",
                    ),
                )
            )

    return assertions
