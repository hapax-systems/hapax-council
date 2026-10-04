"""Recheck tests for two fast-mode waiver-justification legs (#5025 follow-up).

The ``fast_mode@quota_ledger`` waiver in
``tests/docs/test_capability_consideration_completeness_contract.py`` justifies
its bounded extension on three facts. Leg 1 (every route has ``fast_mode=off``)
is pinned by ``test_fast_mode_waiver_requires_disabled_routes``; the Claude half
of the adapter-rejection leg is pinned by
``test_claude_mapping_refuses_every_unimplemented_axis``. These tests close the
remaining gap flagged by seat ruling 20261004T065109Z (obligation 1):

  (a) BOTH launch adapters reject a non-off fast-mode descriptor, so no governed
      launch path can incur fast-mode spend; and
  (b) ``SpendReceipt`` carries no ``fast_mode`` field, so -- being a StrictModel
      that forbids extra fields -- no spend producer can observe fast mode into
      the ledger.

If either fact changes (an adapter stops rejecting fast mode, or the receipt
gains a fast-mode field), the matching test fails and the waiver's justification
must be revisited before a governed fast route ships.
"""

from __future__ import annotations

import pytest

from shared.capability_execution import (
    ExecutionIdentityError,
    claude_execution_binding,
    codex_execution_args,
)
from shared.platform_capability_registry import ExecutionDescriptor
from shared.quota_spend_ledger import SpendReceipt

# A descriptor valid on every axis EXCEPT fast_mode, which is on. It must trip
# both adapters for that reason alone: model_id is claude-prefixed and effort is
# a real Claude effort, so the Claude binding reaches its fast-mode check; the
# Codex adapter ignores the model prefix and reaches the same check.
_FAST_DESCRIPTOR = {
    "model_id": "claude-opus-4-8",
    "effort": "xhigh",
    "context_mode": "standard",
    "fast_mode": "fast",
    "quantization": "none",
}
_OFF_DESCRIPTOR = {**_FAST_DESCRIPTOR, "fast_mode": "off"}

_ADAPTERS = (
    ("codex", codex_execution_args),
    ("claude", claude_execution_binding),
)
_ADAPTER_IDS = [name for name, _ in _ADAPTERS]


@pytest.mark.parametrize(("name", "adapter"), _ADAPTERS, ids=_ADAPTER_IDS)
def test_fast_mode_adapters_reject_non_off_descriptor(name, adapter):
    """Leg (a): every launch adapter refuses a non-off fast-mode descriptor."""
    descriptor = ExecutionDescriptor.model_validate(_FAST_DESCRIPTOR)
    with pytest.raises(ExecutionIdentityError):
        adapter(descriptor)


@pytest.mark.parametrize(("name", "adapter"), _ADAPTERS, ids=_ADAPTER_IDS)
def test_adapters_accept_the_same_descriptor_with_fast_off(name, adapter):
    """Positive control: fast_mode is the ONLY reason the adapters reject above.

    The identical descriptor with ``fast_mode=off`` must be accepted, proving the
    rejection test is sensitive to fast mode specifically rather than to some
    other axis of the descriptor.
    """
    descriptor = ExecutionDescriptor.model_validate(_OFF_DESCRIPTOR)
    adapter(descriptor)  # must not raise


def test_no_spend_producer_observes_fast_mode():
    """Leg (b): SpendReceipt has no fast_mode field, so no producer can meter it.

    SpendReceipt is a StrictModel (extra fields forbidden), so the absence of a
    ``fast_mode`` field is a complete guarantee that no producer observes fast
    mode into the ledger -- not merely that today's producers happen not to.
    When metering lands the field appears and this test fails, forcing the
    waiver to be removed.
    """
    assert "fast_mode" not in SpendReceipt.model_fields
    # Positive control: the axes that ARE modeled remain present, so the field
    # check is real rather than vacuously true against a renamed attribute.
    for modeled in ("model_id", "effort", "quantization"):
        assert modeled in SpendReceipt.model_fields
