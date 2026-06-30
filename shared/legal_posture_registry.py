"""Legal-posture registry reader and MonDLC g2 commit gate.

The registry is the machine-readable substrate for g2: legal in venue.
Committed dispositions are stricter than planning advice: they require an
exact, fresh, operator-signed LIT row for the named surface, venue, and
instrument.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
DEFAULT_LEGAL_POSTURE_REGISTRY: Final = (
    REPO_ROOT / "docs" / "monetization" / "legal-posture-registry.yaml"
)
WILDCARD: Final = "*"
KNOWN_AUTHORITY_BASES: Final[frozenset[str]] = frozenset(
    {
        "statute",
        "regulation",
        "case_law",
        "tos_clause",
        "legal_opinion",
        "agency_guidance",
        "no_research",
        "operator_judgment",
    }
)
COMMITTABLE_LIT_AUTHORITY_BASES: Final[frozenset[str]] = frozenset(
    {
        "statute",
        "regulation",
        "case_law",
        "tos_clause",
        "legal_opinion",
        "agency_guidance",
    }
)


class LegalPostureVerdict(StrEnum):
    """Legal posture verdicts recorded in the registry."""

    LIT = "LIT"
    PARTIAL = "PARTIAL"
    DARK = "DARK"


class G2CommitStatus(StrEnum):
    """Disposition-commit status for the g2 legal gate."""

    ADMIT = "admit"
    BLOCK = "block"


class G2Reason(StrEnum):
    """Machine-readable reason for a g2 commit-gate decision."""

    FRESH_LIT = "fresh_lit"
    INVALID_TARGET = "invalid_target"
    REGISTRY_UNREADABLE = "registry_unreadable"
    NO_EXACT_ROW = "no_exact_row"
    DARK_ROW = "dark_row"
    UNSIGNED_NON_DARK = "unsigned_non_dark"
    STALE_NON_DARK = "stale_non_dark"
    PARTIAL_NOT_COMMITTABLE = "partial_not_committable"
    LIT_AUTHORITY_NOT_COMMITTABLE = "lit_authority_not_committable"
    LIT_HAS_OPEN_QUESTIONS = "lit_has_open_questions"


@dataclass(frozen=True)
class G2GateInput:
    """The only data g2 is allowed to inspect."""

    surface: str
    venue: str
    instrument: str

    def normalized(self) -> G2GateInput:
        return G2GateInput(
            surface=_normalize_target_value(self.surface, "surface"),
            venue=_normalize_target_value(self.venue, "venue"),
            instrument=_normalize_target_value(self.instrument, "instrument"),
        )

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.surface, self.venue, self.instrument)


@dataclass(frozen=True)
class LegalPostureRow:
    """One row from ``docs/monetization/legal-posture-registry.yaml``."""

    surface: str
    venue: str
    instrument: str
    verdict: LegalPostureVerdict
    citation: str
    authority_basis: str
    review_date: date
    freshness_ttl_days: int
    operator_signed: bool
    operator_sign_date: date | None = None
    notes: str = ""
    open_questions: tuple[str, ...] = ()
    blocks_surfaces: tuple[str, ...] = ()
    source_task: str | None = None
    supersedes: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> LegalPostureRow:
        verdict_raw = _required_string(raw, "g2_verdict")
        try:
            verdict = LegalPostureVerdict(verdict_raw)
        except ValueError as exc:
            raise ValueError(f"invalid g2_verdict: {verdict_raw}") from exc

        ttl = raw.get("freshness_ttl_days")
        if not isinstance(ttl, int) or ttl <= 0:
            raise ValueError("freshness_ttl_days must be a positive integer")

        operator_signed = raw.get("operator_signed")
        if not isinstance(operator_signed, bool):
            raise ValueError("operator_signed must be a boolean")

        return cls(
            surface=_required_string(raw, "surface"),
            venue=_required_string(raw, "venue"),
            instrument=_required_string(raw, "instrument"),
            verdict=verdict,
            citation=_required_string(raw, "citation"),
            authority_basis=_authority_basis(raw),
            review_date=_parse_date(raw.get("review_date"), "review_date"),
            freshness_ttl_days=ttl,
            operator_signed=operator_signed,
            operator_sign_date=_parse_optional_date(raw.get("operator_sign_date")),
            notes=_optional_string(raw.get("notes")),
            open_questions=_string_tuple(raw.get("open_questions")),
            blocks_surfaces=_string_tuple(raw.get("blocks_surfaces")),
            source_task=_optional_nullable_string(raw.get("source_task")),
            supersedes=_optional_nullable_string(raw.get("supersedes")),
        )

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.surface, self.venue, self.instrument)

    def is_stale(self, *, today: date) -> bool:
        return today > self.review_date + timedelta(days=self.freshness_ttl_days)


@dataclass(frozen=True)
class LegalPostureRegistry:
    """Parsed legal-posture registry."""

    rows: tuple[LegalPostureRow, ...]
    schema_version: str = ""
    schema_doc: str = ""

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> LegalPostureRegistry:
        rows_raw = raw.get("rows")
        if not isinstance(rows_raw, list):
            raise ValueError("legal-posture registry rows must be a list")

        rows = tuple(LegalPostureRow.from_mapping(row) for row in rows_raw)
        seen: set[tuple[str, str, str]] = set()
        duplicates: list[tuple[str, str, str]] = []
        for row in rows:
            if row.key in seen:
                duplicates.append(row.key)
            seen.add(row.key)
        if duplicates:
            raise ValueError(f"duplicate legal-posture row keys: {duplicates!r}")

        return cls(
            rows=rows,
            schema_version=_optional_string(raw.get("schema_version")),
            schema_doc=_optional_string(raw.get("schema_doc")),
        )

    def exact_row(self, target: G2GateInput) -> LegalPostureRow | None:
        for row in self.rows:
            if row.key == target.key:
                return row
        return None

    def most_specific_row(self, target: G2GateInput) -> LegalPostureRow | None:
        ordered_keys = (
            target.key,
            (target.surface, target.venue, WILDCARD),
            (target.surface, WILDCARD, target.instrument),
            (target.surface, WILDCARD, WILDCARD),
        )
        for key in ordered_keys:
            for row in self.rows:
                if row.key == key:
                    return row
        return None


@dataclass(frozen=True)
class G2GateDecision:
    """Result of evaluating the g2 gate for disposition commit."""

    status: G2CommitStatus
    reason: G2Reason
    target: G2GateInput
    row: LegalPostureRow | None = None
    advisory_row: LegalPostureRow | None = None
    stale: bool = False
    message: str = ""

    @property
    def admitted(self) -> bool:
        return self.status is G2CommitStatus.ADMIT

    @property
    def blocked(self) -> bool:
        return self.status is G2CommitStatus.BLOCK


class LegalPostureRefusal(RuntimeError):
    """Raised when a caller requires g2 admission and the gate blocks."""

    def __init__(self, decision: G2GateDecision) -> None:
        self.decision = decision
        super().__init__(decision.message or decision.reason.value)


def load_legal_posture_registry(
    path: Path | str = DEFAULT_LEGAL_POSTURE_REGISTRY,
) -> LegalPostureRegistry:
    """Load and validate the legal-posture registry YAML."""

    import yaml

    target = Path(path)
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("legal-posture registry root must be a mapping")
    return LegalPostureRegistry.from_mapping(raw)


def evaluate_g2_commit_gate(
    target: G2GateInput,
    *,
    registry: LegalPostureRegistry | None = None,
    registry_path: Path | str | None = None,
    today: date | None = None,
) -> G2GateDecision:
    """Evaluate whether g2 admits a committed disposition.

    This is intentionally only the g2 gate. It does not inspect counterparty
    class (g1) or CapDLC measured value (M); later commit composition should
    combine those sibling gates explicitly.
    """

    evaluation_date = today or date.today()
    try:
        normalized_target = target.normalized()
    except ValueError as exc:
        return _block(
            target=target,
            reason=G2Reason.INVALID_TARGET,
            message=(f"{exc}; provide non-empty surface, venue, and instrument before commit"),
        )

    if registry is None:
        try:
            registry = load_legal_posture_registry(registry_path or DEFAULT_LEGAL_POSTURE_REGISTRY)
        except Exception as exc:  # noqa: BLE001 - g2 must fail closed on any read error.
            return _block(
                target=normalized_target,
                reason=G2Reason.REGISTRY_UNREADABLE,
                message=(
                    f"legal-posture registry unreadable: {exc}; restore "
                    "docs/monetization/legal-posture-registry.yaml or pass a valid "
                    "registry path before commit"
                ),
            )

    advisory_row = registry.most_specific_row(normalized_target)
    row = registry.exact_row(normalized_target)
    if row is None:
        return _block(
            target=normalized_target,
            reason=G2Reason.NO_EXACT_ROW,
            advisory_row=advisory_row,
            message=(
                "no exact legal-posture row for "
                f"{normalized_target.surface}/{normalized_target.venue}/"
                f"{normalized_target.instrument}; add an exact fresh operator-signed "
                "LIT row before commit"
            ),
        )

    if row.verdict is LegalPostureVerdict.DARK:
        return _block(
            target=normalized_target,
            reason=G2Reason.DARK_ROW,
            row=row,
            advisory_row=advisory_row,
            message=(
                "exact legal-posture row is DARK; upgrade to an exact fresh "
                "operator-signed LIT row before commit"
            ),
        )

    if not row.operator_signed:
        return _block(
            target=normalized_target,
            reason=G2Reason.UNSIGNED_NON_DARK,
            row=row,
            advisory_row=advisory_row,
            message=(
                "exact non-DARK legal-posture row lacks operator signature; obtain "
                "operator signature before commit"
            ),
        )

    stale = row.is_stale(today=evaluation_date)
    if stale:
        return _block(
            target=normalized_target,
            reason=G2Reason.STALE_NON_DARK,
            row=row,
            advisory_row=advisory_row,
            stale=True,
            message=(
                "exact non-DARK legal-posture row is stale; refresh review_date and "
                "operator signature before commit"
            ),
        )

    if row.verdict is LegalPostureVerdict.PARTIAL:
        return _block(
            target=normalized_target,
            reason=G2Reason.PARTIAL_NOT_COMMITTABLE,
            row=row,
            advisory_row=advisory_row,
            message=(
                "PARTIAL legal posture is advisory only for commit; resolve open "
                "questions and upgrade to LIT before commit"
            ),
        )

    if row.authority_basis not in COMMITTABLE_LIT_AUTHORITY_BASES:
        return _block(
            target=normalized_target,
            reason=G2Reason.LIT_AUTHORITY_NOT_COMMITTABLE,
            row=row,
            advisory_row=advisory_row,
            message=(
                f"LIT legal-posture row uses non-committable authority_basis "
                f"{row.authority_basis!r}; cite statute, regulation, case law, "
                "ToS clause, legal opinion, or agency guidance before commit"
            ),
        )

    if row.open_questions:
        return _block(
            target=normalized_target,
            reason=G2Reason.LIT_HAS_OPEN_QUESTIONS,
            row=row,
            advisory_row=advisory_row,
            message=("LIT legal-posture row has open questions; resolve questions before commit"),
        )

    return G2GateDecision(
        status=G2CommitStatus.ADMIT,
        reason=G2Reason.FRESH_LIT,
        target=normalized_target,
        row=row,
        advisory_row=advisory_row,
        stale=False,
        message="fresh exact LIT legal-posture row admits g2 commit",
    )


def require_g2_commit_admitted(
    target: G2GateInput,
    *,
    registry: LegalPostureRegistry | None = None,
    registry_path: Path | str | None = None,
    today: date | None = None,
) -> G2GateDecision:
    """Return the g2 decision or raise ``LegalPostureRefusal`` if blocked."""

    decision = evaluate_g2_commit_gate(
        target,
        registry=registry,
        registry_path=registry_path,
        today=today,
    )
    if decision.blocked:
        raise LegalPostureRefusal(decision)
    return decision


def _block(
    *,
    target: G2GateInput,
    reason: G2Reason,
    row: LegalPostureRow | None = None,
    advisory_row: LegalPostureRow | None = None,
    stale: bool = False,
    message: str = "",
) -> G2GateDecision:
    return G2GateDecision(
        status=G2CommitStatus.BLOCK,
        reason=reason,
        target=target,
        row=row,
        advisory_row=advisory_row,
        stale=stale,
        message=message,
    )


def _normalize_target_value(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must be non-empty")
    return normalized


def _required_string(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _authority_basis(raw: Mapping[str, Any]) -> str:
    value = _required_string(raw, "authority_basis")
    if value not in KNOWN_AUTHORITY_BASES:
        raise ValueError(f"invalid authority_basis: {value}")
    return value


def _optional_string(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("optional string field must be a string when present")
    return value.strip()


def _optional_nullable_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("optional nullable string field must be a string when present")
    stripped = value.strip()
    return stripped or None


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("list field must be a list when present")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("list field entries must be non-empty strings")
        result.append(item.strip())
    return tuple(result)


def _parse_date(value: Any, key: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{key} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{key} must be an ISO date") from exc


def _parse_optional_date(value: Any) -> date | None:
    if value is None:
        return None
    return _parse_date(value, "operator_sign_date")


__all__ = [
    "DEFAULT_LEGAL_POSTURE_REGISTRY",
    "G2CommitStatus",
    "G2GateDecision",
    "G2GateInput",
    "G2Reason",
    "LegalPostureRefusal",
    "LegalPostureRegistry",
    "LegalPostureRow",
    "LegalPostureVerdict",
    "evaluate_g2_commit_gate",
    "load_legal_posture_registry",
    "require_g2_commit_admitted",
]
