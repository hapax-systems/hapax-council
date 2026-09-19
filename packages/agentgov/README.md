# agentgov

[![PyPI](https://img.shields.io/pypi/v/hapax-agentgov)](https://pypi.org/project/hapax-agentgov/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Computational constitutional governance for AI agent systems.

agentgov provides algebraically-verified primitives for governing multi-agent systems: consent contracts, information flow control, principal delegation, provenance tracking, and compositional policy enforcement. Zero dependencies beyond PyYAML. Extracted from [hapax-council](https://github.com/hapax-systems/hapax-council), where it governs 200+ AI agents in production.

## Install

```bash
pip install hapax-agentgov
```

## Core Concepts

### Principals

Actors in the system. Sovereign principals (humans) originate consent; bound principals (agents) operate under delegated authority with non-amplification guarantees.

```python
from agentgov import Principal, PrincipalKind

operator = Principal(id="operator", kind=PrincipalKind.SOVEREIGN)
agent = operator.delegate("sync-agent", frozenset({"email", "calendar"}))
sub = agent.delegate("sub-agent", frozenset({"email"}))  # narrows authority
```

### Consent Labels (DLM Join-Semilattice)

Information flow labels track who may read data. Labels combine via join — combining data with different consent requirements produces the most restrictive combination.

```python
from agentgov import ConsentLabel

public = ConsentLabel.bottom()  # no restrictions
restricted = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
combined = public.join(restricted)  # most restrictive wins
assert public.can_flow_to(combined)  # less restrictive flows to more
```

### Labeled Values (LIO-Style)

Wrap any value with its consent label and why-provenance.

```python
from agentgov import Labeled, ConsentLabel

data = Labeled(value="secret", label=restricted, provenance=frozenset({"contract-1"}))
transformed = data.map(str.upper)  # label preserved through transformations
```

### Provenance Semirings

Track WHY data exists using algebraic provenance (Green et al., PODS 2007). Supports tensor (both required) and plus (either sufficient) composition.

```python
from agentgov import ProvenanceExpr

combined = ProvenanceExpr.leaf("c1").tensor(ProvenanceExpr.leaf("c2"))
assert combined.evaluate(frozenset({"c1", "c2"}))  # both active: survives
assert not combined.evaluate(frozenset({"c1"}))     # one revoked: purged
```

### Governor (Per-Agent Policy Enforcement)

Each agent gets a governance wrapper that validates inputs/outputs at boundaries. Pure validation layer — allows or denies, never modifies.

```python
from agentgov import GovernorWrapper, GovernorPolicy, Labeled, ConsentLabel

gov = GovernorWrapper("my-agent")
gov.add_input_policy(GovernorPolicy(
    name="require-consent",
    check=lambda agent_id, data: data.label != ConsentLabel.bottom(),
    axiom_id="consent",
))
result = gov.check_input(Labeled(value="data", label=ConsentLabel.bottom()))
assert not result.allowed
```

### VetoChain (Deny-Wins Composition)

Order-independent constraint composition. Any denial blocks the action.

```python
from agentgov import VetoChain, Veto

chain = VetoChain([
    Veto("budget", lambda ctx: ctx["budget"] > 0),
    Veto("auth", lambda ctx: ctx["authenticated"]),
])
result = chain.evaluate({"budget": 100, "authenticated": False})
assert not result.allowed
assert "auth" in result.denied_by
```

### Says Monad (DCC Attribution)

Principal-annotated assertions following Abadi's DCC formalism. Threads authority through data transformations.

```python
from agentgov import Says, Principal, PrincipalKind

operator = Principal(id="op", kind=PrincipalKind.SOVEREIGN)
assertion = Says.unit(operator, "approved")
delegated = assertion.handoff(operator.delegate("agent", frozenset({"approve"})))
```

### Revocation Cascade

When a consent contract is revoked, all data whose provenance includes that contract is automatically purged across registered subsystems.

```python
from agentgov import ConsentRegistry, RevocationPropagator, CarrierRegistry

registry = ConsentRegistry()
propagator = RevocationPropagator(registry)
propagator.register_carrier_registry(carrier_reg)
report = propagator.revoke("alice")  # cascading purge
```

## Algebraic Properties (Hypothesis-Verified)

- **ConsentLabel**: join-semilattice (associative, commutative, idempotent, bottom identity)
- **Labeled[T]**: functor laws (identity, composition)
- **Principal**: non-amplification (bound authority <= delegator authority)
- **ProvenanceExpr**: PosBool(X) semiring (plus/tensor commutativity, associativity, distributivity, annihilation)
- **VetoChain**: monotonic (adding vetoes only restricts, never permits)
- **Governor**: consistent with can_flow_to

## License

MIT


### Identity migration binding

Select the installation binding before resolving identities:

| Selection | Configuration | Behavior |
| --- | --- | --- |
| Non-migrating | `AGENTGOV_IDENTITY_MIGRATION=none` | Exact identifiers; no council or Reins import. |
| Required | `AGENTGOV_IDENTITY_MIGRATION=required` and `AGENTGOV_IDENTITY_PROVIDER` | Each operation loads a validated snapshot from the declared provider module. |
| Unconfigured | Unset, empty or unknown mode; required provider absent or not importable | Resolution refuses with `identity_unconfigured`; consent and matching cannot be granted. |

Applications may instead call `agentgov.consent.configure_identity_migration(mode, provider)`
once at startup. This explicit application selection takes precedence over environment
configuration. Importing the package does not load any provider or custody data.
The council entry points select `required` with provider `shared.governance.consent`;
the authoritative council registry and resolver enforce that binding independently.

Providers export `load_identity_snapshot()`. Its result implements
`resolve_principal_id(candidate)` and `resolve_contract_id(candidate)`, returning a
canonical string or the candidate itself for an unknown identifier. The portable
resolver also preserves the candidate when a provider returns `None` for an unknown
identifier. Required custody validates the document, not registry membership;
unknown identifiers retain exact matching. Required provider failures never choose
non-migrating behavior. Use `identity_operation()` around a compound
operation so nested resolution shares the same snapshot. The snapshot is discarded
on exit; the next operation loads again. Registry operations establish this scope
automatically. Do not retain a scope between operations or use cached custody data.

Ordinary missing-contract errors retain the requested identifier. A request that
resolves as a predecessor instead receives a sanitized registry error. Providers
may implement `contains_predecessor(text)` to classify parse diagnostics without
exporting correspondence: ordinary load errors retain their filename and cause,
while predecessor-bearing diagnostics are sanitized. Required providers without
this optional classifier conservatively suppress load details. Registry errors
are not converted into identity-migration failures.

The council provider reads the single `consent-identifier-compatibility` FileStore
entry through the installed Reins API selected by `HAPAX_REINS_API`. Its version 1
JSON document has `principals` and `contracts` correspondence objects plus a declared
`inventory` array. Both objects must be nonempty; every inventory label must map,
every mapped label must be declared, duplicates and overlapping or cyclic labels
refuse. Values and inventory belong exclusively in private custody. No plaintext
mirror, digest correspondence, or secret environment payload is used. The reader
replaces only the initializing key accessor with an existing-key read; it neither
creates storage nor changes FileStore cryptography. FileStore's absent and
integrity-failed `None` outcomes are distinguished by entry presence: absence refuses
as `compat_missing`, while an existing unreadable entry reports cause class
`CompatibilityIntegrityError` with `compat_unreadable`. Read/import failures also
use `compat_unreadable`, invalid documents `compat_malformed`, duplicate or cyclic
correspondence `compat_conflict`, and inventory gaps `compat_incomplete`.

Failures expose only reason tokens and sanitized `cause_class` fields; WARNINGs for
unreadable custody include the cause class, safe missing module name when available,
and `remedy=restore_compat_custody`, never exception messages, paths or document text.
Reason-token remedies:

- `identity_unconfigured`: select the installation binding and install its declared provider.
- `compat_missing`: provision the compatibility entry through private custody.
- `compat_unreadable`: `restore_compat_custody` — restore the installed API, store access and valid existing key/entry; use the cause class to locate the failing component.
- `compat_malformed`: repair the private document to the version 1 schema.
- `compat_conflict`: reconcile duplicate, overlapping or cyclic labels in private custody.
- `compat_incomplete`: reconcile the declared inventory with all mapped labels in private custody.

Revocation reports distinguish `contract_revoked` from `purge_complete`. Structured
`PurgeResult` outcomes retain completed deletion counts and token-only `failures`.
A failed purge keeps consent revoked, retains pending contracts in
`retry_contract_ids`, and can be retried with `RevocationPropagator.retry_purge(report)`
after reloading contracts and registering the same handlers. Prior effects and
failures remain in `prior_purge_results`; retry never reactivates consent. These
fields, including completion status, survive dataclass serialization in the existing
report path. The council API appends `purge_pending` records (canonical person and
outstanding contract IDs) to the existing archive purge audit, `<archive_root>/purge.log`,
and sends an operator notification at HTTP 503. Successful retries append `purge_complete`
for the completed contracts; historical audit entries stay intact. Startup reads this
residue and warns without re-running a purge. `POST /api/consent/retry/{person_id}` uses
reports retained by the current app process only; after restart it returns 404 pointing
to the durable audit for manual reconciliation. The audit contains no executable retry
report or journal. Private provisioning, inventory reconciliation, validation on implicated
hosts, retention and runtime activation remain deployment responsibilities.
