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
from pydantic import ValidationError

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
    with pytest.raises(ExecutionIdentityError, match="unsupported"):
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
    """Leg (b): no spend producer can observe fast mode into the ledger.

    Two facts make this a complete guarantee rather than "today's producers
    happen not to": SpendReceipt has no ``fast_mode`` field, AND it forbids
    extra fields, so a producer cannot smuggle ``fast_mode`` in as an extra.
    When metering lands -- the field appears, or the config loosens -- one of
    these assertions fails, forcing the waiver to be removed.
    """
    assert "fast_mode" not in SpendReceipt.model_fields
    # Positive control: the axes that ARE modeled remain present, so the field
    # check is real rather than vacuously true against a renamed attribute.
    for modeled in ("model_id", "effort", "quantization"):
        assert modeled in SpendReceipt.model_fields
    # The field check is only a complete guarantee because the model forbids
    # extras; pin that premise directly and prove it actually bites at
    # construction (loosening to extra="allow" would otherwise let a producer
    # smuggle fast_mode in as __pydantic_extra__ with every assertion green).
    assert SpendReceipt.model_config["extra"] == "forbid"
    with pytest.raises(ValidationError) as exc_info:
        SpendReceipt(fast_mode="fast")  # type: ignore[call-arg]
    assert any(
        err["type"] == "extra_forbidden" and err["loc"] == ("fast_mode",)
        for err in exc_info.value.errors()
    ), "an extra fast_mode field must be rejected at construction, not absorbed"
