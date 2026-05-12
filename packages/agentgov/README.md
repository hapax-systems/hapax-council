# agentgov

[![PyPI](https://img.shields.io/pypi/v/agentgov)](https://pypi.org/project/agentgov/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Computational constitutional governance for AI agent systems.

agentgov provides algebraically-verified primitives for governing multi-agent systems: consent contracts, information flow control, principal delegation, provenance tracking, and compositional policy enforcement. Zero dependencies beyond PyYAML. Extracted from [hapax-council](https://github.com/hapax-systems/hapax-council), where it governs 200+ AI agents in production.

## Install

```bash
pip install agentgov
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
