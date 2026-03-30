"""logos/_governance.py — Vendored governance types.

Copied from shared/governance/ to dissolve the shared module dependency.
Contains: ConsentContract, ConsentRegistry, load_contracts, ConsentLabel,
Labeled, ProvenanceExpr, ProvenanceOp, Principal, PrincipalKind, Says,
and compositional governance primitives (Veto, VetoChain, etc.).

These are pure data types with no operational dependencies beyond stdlib + yaml.
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

# ── Consent contracts (from shared/governance/consent.py) ──────────────

_CONTRACTS_DIR = Path(__file__).parent.parent / "axioms" / "contracts"

REGISTERED_CHILD_PRINCIPALS: frozenset[str] = frozenset({"simon", "agatha"})


@dataclass(frozen=True)
class ConsentContract:
    """A bilateral consent agreement between operator and subject."""

    id: str
    parties: tuple[str, str]
    scope: frozenset[str]
    direction: str = "one_way"
    visibility_mechanism: str = "on_request"
    created_at: str = ""
    revoked_at: str | None = None
    principal_class: str = ""
    guardian: str | None = None

    @property
    def active(self) -> bool:
        return self.revoked_at is None


@dataclass
class ConsentRegistry:
    """Runtime registry of consent contracts."""

    _contracts: dict[str, ConsentContract] = field(default_factory=dict)

    def load(self, contracts_dir: Path | None = None) -> int:
        directory = contracts_dir or _CONTRACTS_DIR
        if not directory.exists():
            log.info("No contracts directory at %s", directory)
            return 0

        count = 0
        for path in sorted(directory.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text())
                if data is None:
                    continue
                contract = _parse_contract(data)
                self._contracts[contract.id] = contract
                if contract.active:
                    count += 1
                    log.info(
                        "Loaded contract %s: %s ↔ %s (scope: %s)",
                        contract.id,
                        contract.parties[0],
                        contract.parties[1],
                        ", ".join(sorted(contract.scope)),
                    )
            except Exception:
                log.exception("Failed to load contract from %s", path)

        return count

    def get(self, contract_id: str) -> ConsentContract | None:
        return self._contracts.get(contract_id)

    def __iter__(self):
        return iter(self._contracts.values())

    def contract_check(self, person_id: str, data_category: str) -> bool:
        for contract in self._contracts.values():
            if not contract.active:
                continue
            if person_id in contract.parties and data_category in contract.scope:
                return True
        return False

    def get_contract_for(self, person_id: str) -> ConsentContract | None:
        for contract in self._contracts.values():
            if contract.active and person_id in contract.parties:
                return contract
        return None

    def subject_data_categories(self, person_id: str) -> frozenset[str]:
        categories: set[str] = set()
        for contract in self._contracts.values():
            if contract.active and person_id in contract.parties:
                categories |= contract.scope
        return frozenset(categories)

    def purge_subject(self, person_id: str) -> list[str]:
        revoked: list[str] = []
        for contract_id, contract in self._contracts.items():
            if contract.active and person_id in contract.parties:
                revoked_contract = ConsentContract(
                    id=contract.id,
                    parties=contract.parties,
                    scope=contract.scope,
                    direction=contract.direction,
                    visibility_mechanism=contract.visibility_mechanism,
                    created_at=contract.created_at,
                    revoked_at=datetime.now().isoformat(),
                    principal_class=contract.principal_class,
                    guardian=contract.guardian,
                )
                self._contracts[contract_id] = revoked_contract
                revoked.append(contract_id)
                log.info("Revoked contract %s for %s", contract_id, person_id)
        return revoked

    def create_contract(
        self,
        person_id: str,
        scope: frozenset[str],
        *,
        contract_id: str | None = None,
        direction: str = "one_way",
        visibility_mechanism: str = "on_request",
        contracts_dir: Path | None = None,
    ) -> ConsentContract:
        now = datetime.now().isoformat()
        cid = contract_id or f"contract-{person_id}-{now[:10]}"

        contract = ConsentContract(
            id=cid,
            parties=("operator", person_id),
            scope=scope,
            direction=direction,
            visibility_mechanism=visibility_mechanism,
            created_at=now,
        )

        directory = contracts_dir or _CONTRACTS_DIR
        directory.mkdir(parents=True, exist_ok=True)
        contract_path = directory / f"{cid}.yaml"
        contract_data: dict[str, Any] = {
            "id": contract.id,
            "parties": list(contract.parties),
            "scope": sorted(contract.scope),
            "direction": contract.direction,
            "visibility_mechanism": contract.visibility_mechanism,
            "created_at": contract.created_at,
        }
        if contract.principal_class:
            contract_data["principal_class"] = contract.principal_class
        if contract.guardian:
            contract_data["guardian"] = contract.guardian
        contract_path.write_text(yaml.dump(contract_data, default_flow_style=False))
        log.info("Created consent contract %s for %s at %s", cid, person_id, contract_path)

        self._contracts[cid] = contract
        return contract

    @property
    def active_contracts(self) -> list[ConsentContract]:
        return [c for c in self._contracts.values() if c.active]


def _parse_contract(data: dict[str, Any]) -> ConsentContract:
    parties = data.get("parties", [])
    if len(parties) != 2:
        raise ValueError(f"Contract must have exactly 2 parties, got {len(parties)}")

    return ConsentContract(
        id=data["id"],
        parties=(parties[0], parties[1]),
        scope=frozenset(data.get("scope", [])),
        direction=data.get("direction", "one_way"),
        visibility_mechanism=data.get("visibility_mechanism", "on_request"),
        created_at=data.get("created_at", ""),
        revoked_at=data.get("revoked_at"),
        principal_class=data.get("principal_class", ""),
        guardian=data.get("guardian"),
    )


def is_child_principal(person_id: str, registry: ConsentRegistry | None = None) -> bool:
    if person_id in REGISTERED_CHILD_PRINCIPALS:
        return True
    if registry is not None:
        contract = registry.get_contract_for(person_id)
        if contract is not None and contract.principal_class == "child":
            return True
    return False


def load_contracts(contracts_dir: Path | None = None) -> ConsentRegistry:
    """Convenience function: create and load a ConsentRegistry."""
    registry = ConsentRegistry()
    registry.load(contracts_dir)
    return registry


# ── ConsentLabel (from shared/governance/consent_label.py) ─────────────


@dataclass(frozen=True)
class ConsentLabel:
    """Immutable information flow label for consent-governed data."""

    policies: frozenset[tuple[str, frozenset[str]]]

    def join(self, other: ConsentLabel) -> ConsentLabel:
        return ConsentLabel(self.policies | other.policies)

    def can_flow_to(self, target: ConsentLabel) -> bool:
        return self.policies <= target.policies

    @staticmethod
    def bottom() -> ConsentLabel:
        return ConsentLabel(frozenset())

    @staticmethod
    def from_contract(contract: ConsentContract) -> ConsentLabel:
        if not contract.active:
            return ConsentLabel.bottom()
        owner = contract.parties[1]
        readers = frozenset(contract.parties)
        return ConsentLabel(frozenset({(owner, readers)}))

    @staticmethod
    def from_contracts(contracts: list[ConsentContract]) -> ConsentLabel:
        result = ConsentLabel.bottom()
        for contract in contracts:
            result = result.join(ConsentLabel.from_contract(contract))
        return result


# ── Provenance semiring (from shared/governance/provenance.py) ─────────


class ProvenanceOp(enum.Enum):
    TENSOR = "tensor"
    PLUS = "plus"


@dataclass(frozen=True)
class ProvenanceExpr:
    """A provenance expression in the PosBool(X) semiring."""

    contract_id: str | None = None
    op: ProvenanceOp | None = None
    left: ProvenanceExpr | None = None
    right: ProvenanceExpr | None = None
    _is_zero: bool = False
    _is_one: bool = False

    @staticmethod
    def leaf(contract_id: str) -> ProvenanceExpr:
        return ProvenanceExpr(contract_id=contract_id)

    @staticmethod
    def zero() -> ProvenanceExpr:
        return ProvenanceExpr(_is_zero=True)

    @staticmethod
    def one() -> ProvenanceExpr:
        return ProvenanceExpr(_is_one=True)

    @staticmethod
    def from_contracts(contract_ids: frozenset[str]) -> ProvenanceExpr:
        if not contract_ids:
            return ProvenanceExpr.one()
        ids = sorted(contract_ids)
        result = ProvenanceExpr.leaf(ids[0])
        for cid in ids[1:]:
            result = result.tensor(ProvenanceExpr.leaf(cid))
        return result

    def tensor(self, other: ProvenanceExpr) -> ProvenanceExpr:
        if self._is_one:
            return other
        if other._is_one:
            return self
        if self._is_zero or other._is_zero:
            return ProvenanceExpr.zero()
        return ProvenanceExpr(op=ProvenanceOp.TENSOR, left=self, right=other)

    def plus(self, other: ProvenanceExpr) -> ProvenanceExpr:
        if self._is_zero:
            return other
        if other._is_zero:
            return self
        if self == other:
            return self
        return ProvenanceExpr(op=ProvenanceOp.PLUS, left=self, right=other)

    def evaluate(self, active_contracts: frozenset[str]) -> bool:
        if self._is_zero:
            return False
        if self._is_one:
            return True
        if self.contract_id is not None:
            return self.contract_id in active_contracts
        if self.op is ProvenanceOp.TENSOR:
            assert self.left is not None and self.right is not None
            return self.left.evaluate(active_contracts) and self.right.evaluate(active_contracts)
        if self.op is ProvenanceOp.PLUS:
            assert self.left is not None and self.right is not None
            return self.left.evaluate(active_contracts) or self.right.evaluate(active_contracts)
        return False

    def contract_ids(self) -> frozenset[str]:
        if self._is_zero or self._is_one:
            return frozenset()
        if self.contract_id is not None:
            return frozenset({self.contract_id})
        ids: set[str] = set()
        if self.left is not None:
            ids |= self.left.contract_ids()
        if self.right is not None:
            ids |= self.right.contract_ids()
        return frozenset(ids)

    def to_flat(self) -> frozenset[str]:
        return self.contract_ids()

    @property
    def is_trivial(self) -> bool:
        return self._is_zero or self._is_one or self.contract_id is not None

    def __repr__(self) -> str:
        if self._is_zero:
            return "Zero"
        if self._is_one:
            return "One"
        if self.contract_id is not None:
            return self.contract_id
        if self.op is ProvenanceOp.TENSOR:
            return f"({self.left!r} ⊗ {self.right!r})"
        if self.op is ProvenanceOp.PLUS:
            return f"({self.left!r} ⊕ {self.right!r})"
        return "?"


# ── Labeled[T] (from shared/governance/labeled.py) ────────────────────


@dataclass(frozen=True)
class Labeled[T]:
    """Immutable value tagged with consent label and provenance."""

    value: T
    label: ConsentLabel
    provenance: frozenset[str] = frozenset()
    provenance_expr: ProvenanceExpr | None = None

    def with_expr(self, expr: ProvenanceExpr) -> Labeled[T]:
        return Labeled(
            value=self.value,
            label=self.label,
            provenance=expr.to_flat(),
            provenance_expr=expr,
        )

    def effective_expr(self) -> ProvenanceExpr:
        if self.provenance_expr is not None:
            return self.provenance_expr
        return ProvenanceExpr.from_contracts(self.provenance)

    def evaluate_provenance(self, active_contracts: frozenset[str]) -> bool:
        return self.effective_expr().evaluate(active_contracts)

    def map[U](self, f: Callable[[T], U]) -> Labeled[U]:
        return Labeled(
            value=f(self.value),
            label=self.label,
            provenance=self.provenance,
            provenance_expr=self.provenance_expr,
        )

    def join_with[U](self, other: Labeled[U]) -> tuple[ConsentLabel, frozenset[str]]:
        return (self.label.join(other.label), self.provenance | other.provenance)

    def join_with_expr[U](self, other: Labeled[U]) -> tuple[ConsentLabel, ProvenanceExpr]:
        joined_label = self.label.join(other.label)
        joined_prov = self.effective_expr().tensor(other.effective_expr())
        return (joined_label, joined_prov)

    def can_flow_to(self, target_label: ConsentLabel) -> bool:
        return self.label.can_flow_to(target_label)

    def relabel(self, new_label: ConsentLabel) -> Labeled[T]:
        if not self.label.can_flow_to(new_label):
            raise ValueError("Cannot relabel: flow not permitted to target label")
        return Labeled(
            value=self.value,
            label=new_label,
            provenance=self.provenance,
            provenance_expr=self.provenance_expr,
        )

    def unlabel(self) -> T:
        return self.value


# ── Principal (from shared/governance/principal.py) ────────────────────


class PrincipalKind(enum.Enum):
    SOVEREIGN = "sovereign"
    BOUND = "bound"


@dataclass(frozen=True)
class Principal:
    """Immutable actor in the consent governance system."""

    id: str
    kind: PrincipalKind
    delegated_by: str | None = None
    authority: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.kind is PrincipalKind.SOVEREIGN and self.delegated_by is not None:
            raise ValueError("Sovereign principals cannot have a delegator")
        if self.kind is PrincipalKind.BOUND and self.delegated_by is None:
            raise ValueError("Bound principals must have a delegator")

    @property
    def is_sovereign(self) -> bool:
        return self.kind is PrincipalKind.SOVEREIGN

    def can_delegate(self, scope: frozenset[str]) -> bool:
        if self.is_sovereign:
            return True
        return scope <= self.authority

    def delegate(self, child_id: str, scope: frozenset[str]) -> Principal:
        if not self.is_sovereign:
            excess = scope - self.authority
            if excess:
                raise ValueError(
                    f"Non-amplification violation: {sorted(excess)} "
                    f"not in delegator authority {sorted(self.authority)}"
                )
        return Principal(
            id=child_id,
            kind=PrincipalKind.BOUND,
            delegated_by=self.id,
            authority=scope,
        )


# ── Says monad (from shared/governance/says.py) ───────────────────────


@dataclass(frozen=True)
class Says[T]:
    """Principal-annotated assertion: 'principal says value'."""

    principal: Principal
    value: T

    @staticmethod
    def unit(principal: Principal, value: T) -> Says[T]:
        return Says(principal=principal, value=value)

    def bind[U](self, f: Callable[[T], Says[U]]) -> Says[U]:
        inner = f(self.value)
        return Says(principal=self.principal, value=inner.value)

    def map[U](self, f: Callable[[T], U]) -> Says[U]:
        return Says(principal=self.principal, value=f(self.value))

    def handoff(self, target: Principal, scope: frozenset[str] | None = None) -> Says[T]:
        if not self.principal.is_sovereign:
            check_scope = scope or self.principal.authority
            excess = check_scope - self.principal.authority
            if excess:
                raise ValueError(
                    f"Non-amplification: {self.principal.id} cannot hand off "
                    f"scope {sorted(excess)} beyond authority "
                    f"{sorted(self.principal.authority)}"
                )
        return Says(principal=target, value=self.value)

    def speaks_for(self, target: Principal) -> bool:
        if self.principal.id == target.id:
            return True
        return target.delegated_by == self.principal.id

    def to_labeled(
        self, label: ConsentLabel, provenance: frozenset[str] = frozenset()
    ) -> Labeled[T]:
        return Labeled(value=self.value, label=label, provenance=provenance)

    @staticmethod
    def from_labeled(principal: Principal, labeled: Labeled[T]) -> Says[Labeled[T]]:
        return Says(principal=principal, value=labeled)

    @property
    def authority(self) -> frozenset[str]:
        return self.principal.authority

    @property
    def asserter_id(self) -> str:
        return self.principal.id


# ── Governor wrapper (from shared/governance/governor.py) ──────────────


@dataclass(frozen=True)
class GovernorDenial:
    """Outcome when a governor denies a data flow."""

    agent_id: str
    direction: str  # "input" | "output"
    reason: str
    axiom_ids: tuple[str, ...] = ()
    data_category: str = ""


@dataclass(frozen=True)
class GovernorResult:
    """Outcome of a governor check."""

    allowed: bool
    denial: GovernorDenial | None = None


@dataclass(frozen=True)
class GovernorPolicy:
    """A single governance policy for an agent."""

    name: str
    check: Callable[[str, Labeled[Any]], bool]
    axiom_id: str = ""
    description: str = ""


class GovernorWrapper:
    """Per-agent governance wrapper (AMELI pattern)."""

    __slots__ = ("_agent_id", "_input_policies", "_output_policies", "_audit_log")

    def __init__(self, agent_id: str) -> None:
        self._agent_id = agent_id
        self._input_policies: list[GovernorPolicy] = []
        self._output_policies: list[GovernorPolicy] = []
        self._audit_log: list[GovernorResult] = []

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def audit_log(self) -> list[GovernorResult]:
        return list(self._audit_log)

    def add_input_policy(self, policy: GovernorPolicy) -> None:
        self._input_policies.append(policy)

    def add_output_policy(self, policy: GovernorPolicy) -> None:
        self._output_policies.append(policy)

    def check_input(self, data: Labeled[Any]) -> GovernorResult:
        return self._evaluate("input", self._input_policies, data)

    def check_output(self, data: Labeled[Any]) -> GovernorResult:
        return self._evaluate("output", self._output_policies, data)

    def _evaluate(
        self, direction: str, policies: list[GovernorPolicy], data: Labeled[Any]
    ) -> GovernorResult:
        for policy in policies:
            if not policy.check(self._agent_id, data):
                result = GovernorResult(
                    allowed=False,
                    denial=GovernorDenial(
                        agent_id=self._agent_id,
                        direction=direction,
                        reason=f"Policy '{policy.name}' denied",
                        axiom_ids=(policy.axiom_id,) if policy.axiom_id else (),
                    ),
                )
                self._audit_log.append(result)
                return result

        result = GovernorResult(allowed=True)
        self._audit_log.append(result)
        return result


def consent_input_policy(required_label: ConsentLabel) -> GovernorPolicy:
    """Create a policy that validates input consent labels."""

    def _check(agent_id: str, data: Labeled[Any]) -> bool:
        return data.label.can_flow_to(required_label)

    return GovernorPolicy(
        name="consent_input",
        check=_check,
        axiom_id="interpersonal_transparency",
        description=f"Input must flow to {required_label}",
    )


def consent_output_policy(max_label: ConsentLabel) -> GovernorPolicy:
    """Create a policy that validates output consent labels."""

    def _check(agent_id: str, data: Labeled[Any]) -> bool:
        return data.label.can_flow_to(max_label)

    return GovernorPolicy(
        name="consent_output",
        check=_check,
        axiom_id="interpersonal_transparency",
        description=f"Output must flow to {max_label}",
    )


# ── Compositional governance primitives (from shared/governance/primitives.py) ──


@dataclass(frozen=True)
class VetoResult:
    """Outcome of a VetoChain evaluation."""

    allowed: bool
    denied_by: tuple[str, ...] = ()
    axiom_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class GatedResult[T]:
    """Result of gating a value through a VetoChain."""

    veto_result: VetoResult
    value: T | None = None


@dataclass
class Veto[C]:
    """A single governance constraint."""

    name: str
    predicate: Callable[[C], bool]
    axiom: str | None = None
    description: str = ""


class VetoChain[C]:
    """Order-independent deny-wins constraint composition."""

    __slots__ = ("_vetoes",)

    def __init__(self, vetoes: list[Veto[C]] | None = None) -> None:
        self._vetoes: list[Veto[C]] = list(vetoes) if vetoes else []

    @property
    def vetoes(self) -> list[Veto[C]]:
        return list(self._vetoes)

    def add(self, veto: Veto[C]) -> None:
        self._vetoes.append(veto)

    def evaluate(self, context: C) -> VetoResult:
        denials: list[str] = []
        axiom_ids: list[str] = []
        for veto in self._vetoes:
            if not veto.predicate(context):
                denials.append(veto.name)
                if veto.axiom is not None:
                    axiom_ids.append(veto.axiom)
        return VetoResult(
            allowed=len(denials) == 0,
            denied_by=tuple(denials),
            axiom_ids=tuple(axiom_ids),
        )

    def gate(self, context: C, value: object) -> GatedResult:
        veto_result = self.evaluate(context)
        return GatedResult(
            veto_result=veto_result,
            value=value if veto_result.allowed else None,
        )

    def __or__(self, other: VetoChain[C]) -> VetoChain[C]:
        return VetoChain(self._vetoes + other._vetoes)


@dataclass(frozen=True)
class Selected[T]:
    """Output of a FallbackChain selection."""

    action: T
    selected_by: str


@dataclass
class Candidate[C, T]:
    """A candidate action with eligibility condition."""

    name: str
    predicate: Callable[[C], bool]
    action: T
    veto_chain: VetoChain[C] | None = None


class FallbackChain[C, T]:
    """Priority-ordered action selection."""

    __slots__ = ("_candidates", "_default")

    def __init__(self, candidates: list[Candidate[C, T]], default: T) -> None:
        self._candidates = list(candidates)
        self._default = default

    @property
    def candidates(self) -> list[Candidate[C, T]]:
        return list(self._candidates)

    def select(self, context: C) -> Selected[T]:
        for c in self._candidates:
            if c.predicate(context):
                return Selected(action=c.action, selected_by=c.name)
        return Selected(action=self._default, selected_by="default")

    def __or__(self, other: FallbackChain[C, T]) -> FallbackChain[C, T]:
        return FallbackChain(self._candidates + other._candidates, self._default)


__all__ = [
    "Candidate",
    "ConsentContract",
    "ConsentLabel",
    "ConsentRegistry",
    "FallbackChain",
    "GatedResult",
    "GovernorDenial",
    "GovernorPolicy",
    "GovernorResult",
    "GovernorWrapper",
    "Labeled",
    "Principal",
    "PrincipalKind",
    "ProvenanceExpr",
    "ProvenanceOp",
    "REGISTERED_CHILD_PRINCIPALS",
    "Says",
    "Selected",
    "Veto",
    "VetoChain",
    "VetoResult",
    "consent_input_policy",
    "consent_output_policy",
    "is_child_principal",
    "load_contracts",
]
