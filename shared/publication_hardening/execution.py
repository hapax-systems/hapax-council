"""Explicit publication completion binding; installation/admission is a separate act.

Executor descriptions are evidence, not authority. The current task-bound route
receipt must name their exact content addresses before the extracted transport runs.
"""

from __future__ import annotations

import hashlib
import os
import socket
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from shared import glm_review_execution
from shared.capability_execution import resolve_execution_descriptor
from shared.dispatcher_policy import route_authority_receipt_reference
from shared.execution_admission import ExecutorDescriptor, ExecutorRegistryProjection
from shared.mcp_connector_policy import (
    _latest_route_decision,
    _ledger_path,
    _load_route_receipts,
    _receipt_root,
)
from shared.platform_capability_registry import ExecutionDescriptor
from shared.publication_hardening.admission import (
    PublicationAdmissionError,
    publication_hold,
    require_publication_admission,
)
from shared.quota_spend_ledger import PaidRouteRequest, SpendReason


@dataclass(frozen=True)
class AdmittedPublicationCompletion:
    """A source-only callable until independently qualified for its actual route.

    No default provider, credential lookup, subscription/PAYG translation, retry,
    or budget is selected. A raw injected completion cannot satisfy this contract.
    """

    request: PaidRouteRequest
    descriptor: ExecutionDescriptor
    authority_case: str
    budget_id: str
    task_hash: str
    ledger_path: Path
    base_url: str
    thinking: str
    timeout_seconds: float
    spend_reason: SpendReason
    quality_preservation_reason: str
    api_key: str = field(repr=False)
    executor: ExecutorDescriptor | None = None
    projection: ExecutorRegistryProjection | None = None

    def _require_qualified(self) -> None:
        admission = require_publication_admission("review", review_model=self.descriptor.model_id)
        if (
            self.request.task_id != os.environ.get("HAPAX_PUBLICATION_TASK_ID")
            or self.request.route_id != admission.route_id
            or self.request.task_class != "publication-review"
        ):
            raise ValueError("review_call_binding_mismatch")
        if self.executor is None or self.projection is None:
            raise ValueError("review_executor_unqualified")
        executor = ExecutorDescriptor.model_validate(self.executor.model_dump(by_alias=True))
        projection = ExecutorRegistryProjection.model_validate(
            self.projection.model_dump(by_alias=True)
        )
        now = datetime.now(UTC)
        if not (
            datetime.fromisoformat(projection.checked_at)
            <= now
            < datetime.fromisoformat(projection.stale_after)
        ):
            raise ValueError("review_executor_qualification_stale")
        row = _latest_route_decision(
            task_id=self.request.task_id,
            role=os.environ.get("HAPAX_PUBLICATION_ROLE"),
            ledger_path=_ledger_path(None),
        )
        selected = row.get("selected_descriptor_leaf") or self.request.route_id
        if (
            executor.selected_descriptor_leaf != selected
            or resolve_execution_descriptor(selected) != self.descriptor
            or executor.profile != self.request.profile
            or executor.execution_host != socket.gethostname()
            or projection.execution_host != executor.execution_host
            or executor.entrypoint
            != "shared.publication_hardening.execution.AdmittedPublicationCompletion"
            or not any(
                d.ref == executor.descriptor_ref and d.sha256 == executor.descriptor_hash
                for d in projection.descriptors
            )
        ):
            raise ValueError("review_executor_identity_mismatch")
        paths = (
            (executor.executor, Path(glm_review_execution.__file__)),
            (executor.adapter, Path(__file__)),
            (executor.harness, Path(__file__).with_name("review.py")),
            (executor.runtime_identity, Path(sys.executable).resolve()),
        )
        if any(
            address.sha256 != hashlib.sha256(path.read_bytes()).hexdigest()
            for address, path in paths
        ):
            raise ValueError("review_executor_source_mismatch")
        root = _receipt_root(None)
        receipts = [
            r
            for r in _load_route_receipts(root)
            if route_authority_receipt_reference(r) == admission.receipt_ref
        ]
        required = {
            f"authority-case:{self.authority_case}",
            f"budget:{self.budget_id}",
            executor.descriptor_ref,
            projection.projection_ref,
        }
        if len(receipts) != 1 or not required.issubset(receipts[0].evidence_refs):
            raise ValueError("review_executor_qualification_absent")
        if self.request.quality_floor not in receipts[0].quality_floors:
            raise ValueError("review_executor_quality_unqualified")

    def __call__(
        self,
        *,
        model: str,
        messages: tuple[dict[str, str], ...],
        temperature: float,
        max_tokens: int,
    ) -> str:
        try:
            if model != self.descriptor.model_id:
                raise ValueError("review_model_identity_mismatch")
            # This check is repeated under the ledger lock immediately before reservation.
            self._require_qualified()
            reply, _observation, _receipt = glm_review_execution.execute_paid_completion(
                request=self.request,
                descriptor=self.descriptor,
                authority_case=self.authority_case,
                budget_id=self.budget_id,
                task_hash=self.task_hash,
                ledger_path=self.ledger_path,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                thinking=self.thinking,
                timeout_seconds=self.timeout_seconds,
                base_url=self.base_url,
                api_key=self.api_key,
                spend_reason=self.spend_reason,
                quality_preservation_reason=self.quality_preservation_reason,
                require_admission=self._require_qualified,
            )
            return reply
        except PublicationAdmissionError:
            raise
        except Exception as exc:
            # No provider-controlled text or review content in a route refusal.
            raise PublicationAdmissionError(
                publication_hold(
                    "review_execution_or_accounting_refused",
                    route_id=self.request.route_id,
                )
            ) from exc
