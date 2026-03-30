"""Vendored from shared/axiom_registry.py — axiom definitions and implications."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

AXIOMS_PATH: Path = Path(
    os.environ.get(
        "AXIOMS_PATH",
        str(Path(__file__).resolve().parent.parent.parent / "axioms"),
    )
)


@dataclass
class Axiom:
    id: str
    text: str
    weight: int
    type: str  # "hardcoded" | "softcoded"
    created: str
    status: str  # "active" | "retired"
    supersedes: str | None = None
    scope: str = "constitutional"
    domain: str | None = None


@dataclass
class ImplicationScope:
    """E-1: Enumerable scope definition for sufficiency-mode implications."""

    type: str = ""
    rule: str = ""
    items: list[str] | None = None


@dataclass
class Implication:
    id: str
    axiom_id: str
    tier: str  # "T0" | "T1" | "T2" | "T3"
    text: str
    enforcement: str  # "block" | "review" | "warn" | "lint"
    canon: str
    mode: str = "compatibility"
    level: str = "component"
    scope: ImplicationScope | None = None


def load_axioms(*, path: Path = AXIOMS_PATH, scope: str = "", domain: str = "") -> list[Axiom]:
    """Load active axioms from registry.yaml with optional filtering."""
    registry_file = path / "registry.yaml"
    if not registry_file.exists():
        log.warning("Axiom registry not found: %s", registry_file)
        return []

    try:
        data = yaml.safe_load(registry_file.read_text())
    except Exception as e:
        log.error("Failed to parse axiom registry: %s", e)
        return []

    axioms: list[Axiom] = []
    for entry in data.get("axioms", []):
        axiom = Axiom(
            id=entry["id"],
            text=entry.get("text", ""),
            weight=entry.get("weight", 50),
            type=entry.get("type", "softcoded"),
            created=entry.get("created", ""),
            status=entry.get("status", "active"),
            supersedes=entry.get("supersedes"),
            scope=entry.get("scope", "constitutional"),
            domain=entry.get("domain"),
        )
        if axiom.status != "active":
            continue
        if scope and axiom.scope != scope:
            continue
        if domain and axiom.domain != domain:
            continue
        axioms.append(axiom)

    return axioms


def load_implications(axiom_id: str, *, path: Path = AXIOMS_PATH) -> list[Implication]:
    """Load derived implications for a specific axiom."""
    impl_file = path / "implications" / f"{axiom_id.replace('_', '-')}.yaml"
    if not impl_file.exists():
        impl_file = path / "implications" / f"{axiom_id}.yaml"
        if not impl_file.exists():
            return []

    try:
        data = yaml.safe_load(impl_file.read_text())
    except Exception as e:
        log.error("Failed to parse implications for %s: %s", axiom_id, e)
        return []

    impls: list[Implication] = []
    for entry in data.get("implications", []):
        scope_data = entry.get("scope")
        scope = None
        if scope_data and isinstance(scope_data, dict):
            items_raw = scope_data.get("items")
            items = list(items_raw) if items_raw and isinstance(items_raw, list) else None
            scope = ImplicationScope(
                type=scope_data.get("type", ""),
                rule=scope_data.get("rule", ""),
                items=items,
            )
        impls.append(
            Implication(
                id=entry["id"],
                axiom_id=data.get("axiom_id", axiom_id),
                tier=entry.get("tier", "T2"),
                text=entry.get("text", ""),
                enforcement=entry.get("enforcement", "warn"),
                canon=entry.get("canon", ""),
                mode=entry.get("mode", "compatibility"),
                level=entry.get("level", "component"),
                scope=scope,
            )
        )

    return impls
