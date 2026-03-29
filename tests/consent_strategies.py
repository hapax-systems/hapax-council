"""Composable hypothesis strategies for consent governance types.

Provides strategies for Principal, ConsentLabel, and Labeled[T].
Follows the pattern from tests/hapax_daimonion/hypothesis_strategies.py.
"""

from __future__ import annotations

from hypothesis import strategies as st

from shared.governance.consent_label import ConsentLabel
from shared.governance.labeled import Labeled
from shared.governance.principal import Principal, PrincipalKind

# ── Shared strategies ─────────────────────────────────────────────────

safe_ids = st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L",)))
scope_items = st.frozensets(safe_ids, min_size=0, max_size=5)


# ── ConsentLabel ──────────────────────────────────────────────────────


@st.composite
def st_policy(draw):
    """Generate a single (owner, readers) policy tuple."""
    owner = draw(safe_ids)
    readers = draw(st.frozensets(safe_ids, min_size=0, max_size=5))
    return (owner, readers)


@st.composite
def st_consent_label(draw, min_policies=0, max_policies=5):
    """Generate a ConsentLabel with random policies."""
    policies = draw(st.frozensets(st_policy(), min_size=min_policies, max_size=max_policies))
    return ConsentLabel(policies)


# ── Principal ─────────────────────────────────────────────────────────


@st.composite
def st_sovereign(draw):
    """Generate a sovereign Principal."""
    pid = draw(safe_ids)
    authority = draw(scope_items)
    return Principal(id=pid, kind=PrincipalKind.SOVEREIGN, authority=authority)


@st.composite
def st_bound(draw, delegator_id=None, max_authority=None):
    """Generate a bound Principal with valid delegator."""
    pid = draw(safe_ids)
    did = delegator_id or draw(safe_ids)
    if max_authority is not None:
        authority = draw(
            st.frozensets(st.sampled_from(sorted(max_authority)), max_size=len(max_authority))
            if max_authority
            else st.just(frozenset())
        )
    else:
        authority = draw(scope_items)
    return Principal(id=pid, kind=PrincipalKind.BOUND, delegated_by=did, authority=authority)


@st.composite
def st_principal(draw, kind=None):
    """Generate a valid Principal (sovereign or bound)."""
    if kind is PrincipalKind.SOVEREIGN:
        return draw(st_sovereign())
    if kind is PrincipalKind.BOUND:
        return draw(st_bound())
    return draw(st.one_of(st_sovereign(), st_bound()))


# ── Labeled[T] ────────────────────────────────────────────────────────


@st.composite
def st_labeled(draw, value_strategy=None):
    """Generate a Labeled[T] with random label and provenance."""
    value = draw(value_strategy or st.integers())
    label = draw(st_consent_label())
    provenance = draw(st.frozensets(safe_ids, min_size=0, max_size=5))
    return Labeled(value=value, label=label, provenance=provenance)
