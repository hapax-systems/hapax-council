"""Knowledge sufficiency check functions for vault knowledge auditing.

Scans the Obsidian vault to determine whether required management
knowledge exists, using frontmatter metadata and file content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
from logos._config import HAPAXROMANA_DIR, VAULT_PATH
from shared.vault_utils import parse_frontmatter

KNOWLEDGE_MODEL_PATH = HAPAXROMANA_DIR / "knowledge" / "management-sufficiency.yaml"
DOMAIN_REGISTRY_PATH = HAPAXROMANA_DIR / "domains" / "registry.yaml"
KNOWLEDGE_DIR = HAPAXROMANA_DIR / "knowledge"

PRIORITY_MAP: dict[str, int] = {
    "foundational": 90,
    "structural": 60,
    "enrichment": 35,
}

MIN_BODY_LENGTH = 50


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class KnowledgeGap:
    """A single knowledge requirement that may or may not be satisfied."""

    requirement_id: str
    category: str  # foundational | structural | enrichment
    priority: int  # 90, 60, or 35
    description: str
    acquisition_method: str  # interview | nudge | external
    interview_question: str | None
    depends_on: list[str] = field(default_factory=list)
    satisfied: bool = False


@dataclass
class SufficiencyReport:
    """Aggregated result of a knowledge sufficiency audit."""

    gaps: list[KnowledgeGap]
    total_requirements: int
    satisfied_count: int
    foundational_complete: bool
    structural_complete: bool
    sufficiency_score: float  # 0.0 - 1.0


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _get_matching_notes(
    vault_path: Path,
    rel_path: str,
    filter_fields: dict[str, str],
) -> list[Path]:
    """Glob .md files under vault_path/rel_path and filter by frontmatter fields.

    Returns paths whose frontmatter matches all key=value pairs in
    *filter_fields*.  An empty *filter_fields* dict matches every .md file.
    """
    folder = vault_path / rel_path
    if not folder.is_dir():
        return []

    matched: list[Path] = []
    for md_file in sorted(folder.glob("*.md")):
        fm = parse_frontmatter(md_file)
        if all(str(fm.get(k, "")) == v for k, v in filter_fields.items()):
            matched.append(md_file)
    return matched


def _get_body(path: Path) -> str:
    """Extract the body text after the YAML frontmatter markers.

    Returns the content after the closing ``---`` marker (stripped),
    or the full file text if no frontmatter is present.  Returns empty
    string on read failure.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""

    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            # Skip past the closing --- and any immediate newline
            return text[end + 3 :].strip()

    return text.strip()


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------


def check_file_exists(vault_path: Path, rel_path: str) -> bool:
    """Check that a file exists and has a body longer than MIN_BODY_LENGTH."""
    target = vault_path / rel_path
    if not target.is_file():
        return False
    body = _get_body(target)
    return len(body) > MIN_BODY_LENGTH


def check_min_count(
    vault_path: Path,
    rel_path: str,
    *,
    filter_fields: dict[str, str],
    min_count: int,
) -> bool:
    """Check that at least *min_count* notes match the filter criteria."""
    notes = _get_matching_notes(vault_path, rel_path, filter_fields)
    return len(notes) >= min_count


def check_field_populated(
    vault_path: Path,
    rel_path: str,
    *,
    filter_fields: dict[str, str],
    field: str,
) -> bool:
    """Check that ALL matching notes have a non-empty value for *field*.

    Returns True vacuously if no notes match the filter.
    """
    notes = _get_matching_notes(vault_path, rel_path, filter_fields)
    if not notes:
        return True  # vacuously true

    for note_path in notes:
        fm = parse_frontmatter(note_path)
        value = fm.get(field, "")
        if not str(value).strip():
            return False
    return True


def check_field_coverage(
    vault_path: Path,
    rel_path: str,
    *,
    filter_fields: dict[str, str],
    field: str,
    threshold: float,
) -> bool:
    """Check that >= threshold% of matching notes have a non-empty *field*.

    Returns False if there are zero matching notes (cannot meet coverage
    with nothing).
    """
    notes = _get_matching_notes(vault_path, rel_path, filter_fields)
    if not notes:
        return False

    populated = sum(
        1 for note_path in notes if str(parse_frontmatter(note_path).get(field, "")).strip()
    )
    coverage_pct = (populated / len(notes)) * 100
    return coverage_pct >= threshold


def check_any_content(vault_path: Path, rel_path: str) -> bool:
    """Alias for check_file_exists — checks file exists with substantive body."""
    return check_file_exists(vault_path, rel_path)


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------


def load_knowledge_model(path: Path | None = None) -> dict:
    """Load the YAML knowledge model from disk."""
    target = path or KNOWLEDGE_MODEL_PATH
    with open(target, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_domain_registry(path: Path | None = None) -> dict:
    """Load the domain registry YAML from disk."""
    target = path or DOMAIN_REGISTRY_PATH
    with open(target, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Audit orchestrator
# ---------------------------------------------------------------------------


def _run_check(vault_path: Path, check: dict) -> bool:
    """Dispatch a single check against the vault."""
    check_type = check.get("type", "")

    if check_type == "file_exists":
        return check_file_exists(vault_path, check["path"])

    if check_type == "min_count":
        return check_min_count(
            vault_path,
            check["path"],
            filter_fields=check.get("filter", {}),
            min_count=check.get("min", 1),
        )

    if check_type == "field_populated":
        return check_field_populated(
            vault_path,
            check["path"],
            filter_fields=check.get("filter", {}),
            field=check["field"],
        )

    if check_type == "field_coverage":
        return check_field_coverage(
            vault_path,
            check["path"],
            filter_fields=check.get("filter", {}),
            field=check["field"],
            threshold=check.get("threshold", 50),
        )

    if check_type == "any_content":
        return check_any_content(vault_path, check["path"])

    # Unknown or 'derived' type — always unsatisfied
    return False


def run_audit(
    model: dict,
    *,
    vault_path: Path | None = None,
) -> SufficiencyReport:
    """Run the full knowledge sufficiency audit.

    Loads each requirement from the model, runs its check against the vault,
    and produces a SufficiencyReport with all gaps.
    """
    vp = vault_path or VAULT_PATH
    requirements = model.get("requirements", [])
    gaps: list[KnowledgeGap] = []

    for req in requirements:
        check = req.get("check", {})
        satisfied = _run_check(vp, check)
        acq = req.get("acquisition", {})

        gaps.append(
            KnowledgeGap(
                requirement_id=req["id"],
                category=req.get("category", "enrichment"),
                priority=req.get(
                    "priority", PRIORITY_MAP.get(req.get("category", "enrichment"), 35)
                ),
                description=req.get("description", ""),
                acquisition_method=acq.get("method", "nudge"),
                interview_question=acq.get("question"),
                depends_on=req.get("depends_on", []),
                satisfied=satisfied,
            )
        )

    total = len(gaps)
    satisfied_count = sum(1 for g in gaps if g.satisfied)
    foundational = [g for g in gaps if g.category == "foundational"]
    structural = [g for g in gaps if g.category == "structural"]

    return SufficiencyReport(
        gaps=gaps,
        total_requirements=total,
        satisfied_count=satisfied_count,
        foundational_complete=all(g.satisfied for g in foundational) if foundational else True,
        structural_complete=all(g.satisfied for g in structural) if structural else True,
        sufficiency_score=satisfied_count / total if total > 0 else 1.0,
    )


def collect_all_domain_gaps(
    vault_path: Path | None = None,
) -> dict[str, SufficiencyReport]:
    """Load every domain's sufficiency model and run audit.

    Returns {domain_id: SufficiencyReport} for each domain that has
    a sufficiency YAML file. Silently skips domains without models.
    Returns empty dict if the registry file is missing.
    """
    if not DOMAIN_REGISTRY_PATH.is_file():
        return {}

    vp = vault_path or VAULT_PATH

    try:
        registry = load_domain_registry()
    except Exception:
        return {}

    reports: dict[str, SufficiencyReport] = {}
    for domain in registry.get("domains", []):
        domain_id = domain.get("id", "")
        model_ref = domain.get("sufficiency_model", "")
        if not domain_id or not model_ref:
            continue

        model_path = (
            KNOWLEDGE_DIR / model_ref.split("/", 1)[-1]
            if "/" in model_ref
            else KNOWLEDGE_DIR / model_ref
        )
        if not model_path.is_file():
            continue

        try:
            model = load_knowledge_model(model_path)
            reports[domain_id] = run_audit(model, vault_path=vp)
        except Exception:
            continue

    return reports


def collect_knowledge_gaps(vault_path: Path | None = None) -> SufficiencyReport:
    """Public entry point — loads the real knowledge model and runs audit.

    Returns an empty report (score=1.0) if the model file is missing.
    Safe to call from the nudge system.
    """
    if not KNOWLEDGE_MODEL_PATH.is_file():
        return SufficiencyReport(
            gaps=[],
            total_requirements=0,
            satisfied_count=0,
            foundational_complete=True,
            structural_complete=True,
            sufficiency_score=1.0,
        )

    model = load_knowledge_model()
    return run_audit(model, vault_path=vault_path or VAULT_PATH)


# ---------------------------------------------------------------------------
# Nudge generation
# ---------------------------------------------------------------------------


def gaps_to_nudges(gaps: list[KnowledgeGap], *, domain_id: str = "") -> list[Nudge]:
    """Convert unsatisfied knowledge gaps to nudges.

    Skips satisfied gaps and gaps whose dependencies are unsatisfied.
    Returns Nudge objects compatible with the nudge system.
    """
    from logos.data.nudges import Nudge

    satisfied_ids = {g.requirement_id for g in gaps if g.satisfied}
    nudges: list[Nudge] = []

    for gap in gaps:
        if gap.satisfied:
            continue

        # Skip if any dependency is unsatisfied
        if any(dep not in satisfied_ids for dep in gap.depends_on):
            continue

        label = (
            "high"
            if gap.category == "foundational"
            else "medium"
            if gap.category == "structural"
            else "low"
        )

        if gap.acquisition_method == "interview":
            action = f"Run /setup {gap.requirement_id} in Obsidian chat"
            hint = f"/setup {gap.requirement_id}"
        else:
            action = f"Create: {gap.description.strip()}"
            hint = ""

        nudges.append(
            Nudge(
                category="knowledge",
                priority_score=gap.priority,
                priority_label=label,
                title=f"Missing: {gap.description.strip()[:80]}",
                detail=gap.description.strip(),
                suggested_action=action,
                command_hint=hint,
                source_id=f"knowledge:{domain_id}:{gap.requirement_id}"
                if domain_id
                else f"knowledge:{gap.requirement_id}",
            )
        )

    return nudges
