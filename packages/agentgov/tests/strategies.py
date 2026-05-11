"""Composable hypothesis strategies for agentgov types."""

from __future__ import annotations

from hypothesis import strategies as st

from agentgov.consent_label import ConsentLabel
from agentgov.labeled import Labeled
from agentgov.principal import Principal, PrincipalKind

safe_ids = st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L",)))
scope_items = st.frozensets(safe_ids, min_size=0, max_size=5)


@st.composite
def st_policy(draw):
    owner = draw(safe_ids)
    readers = draw(st.frozensets(safe_ids, min_size=0, max_size=5))
    return (owner, readers)


@st.composite
def st_consent_label(draw, min_policies=0, max_policies=5):
    policies = draw(st.frozensets(st_policy(), min_size=min_policies, max_size=max_policies))
    return ConsentLabel(policies)


@st.composite
def st_sovereign(draw):
    pid = draw(safe_ids)
    authority = draw(scope_items)
    return Principal(id=pid, kind=PrincipalKind.SOVEREIGN, authority=authority)


@st.composite
def st_bound(draw, delegator_id=None, max_authority=None):
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
    if kind is PrincipalKind.SOVEREIGN:
        return draw(st_sovereign())
    if kind is PrincipalKind.BOUND:
        return draw(st_bound())
    return draw(st.one_of(st_sovereign(), st_bound()))


@st.composite
def st_labeled(draw, value_strategy=None):
    value = draw(value_strategy or st.integers())
    label = draw(st_consent_label())
    provenance = draw(st.frozensets(safe_ids, min_size=0, max_size=5))
    return Labeled(value=value, label=label, provenance=provenance)
