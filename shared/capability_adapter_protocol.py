"""CapabilityAdapter protocol + type hierarchy (thin, final-delegating).

The adapter layer is a *thin* facade over the existing pure dispatch functions. It
exists to give admitted platforms (claude/codex worker lanes, the api budget authority, the
glmcp review seat) ONE uniform surface —
``describe / admit / observe / collect_receipts`` (FINAL, non-overridable delegations) plus
``preflight / launch / send / classify_failure`` (the per-platform overridable surface) —
WITHOUT widening any authority or duplicating policy.

Two invariants are load-bearing:

1. **A platform is never admitted by editing adapter code.** ``describe`` and ``admit``
   delegate verbatim to ``registry.require`` and ``evaluate_dispatch_policy``; the adapter
   adds zero ``reason_codes`` and cannot widen a decision. Admissibility was decided by
   ``_route_set_matches_contract`` at registry construction time. The four delegations are
   ``@final`` *and* guarded at runtime by ``__init_subclass__`` (``typing.final`` alone is
   advisory — only static checkers honour it).

2. **``launch`` asserts authority FIRST.** ``coord_dispatch.run_atomic_dispatch_launch``
   never re-checks the decision, so ``WorkerAdapter.launch`` is the SOLE enforcement point:
   a non-``LAUNCH`` (or ``launch_allowed=False``) decision raises :class:`AuthorityViolation`
   before any side effect.

Capability differences are expressed at the TYPE level, not via runtime flags: only
:class:`WorkerAdapter` has ``launch``; only :class:`SendCapableAdapter` (a mixin) has
``send``. :class:`BudgetAuthorityAdapter` (api) and :class:`ReviewSeatAdapter` (glmcp) have
neither, so ``hasattr(adapter, "launch")`` is the honest test (genuine ``AttributeError``,
not a ``False`` flag). Retired Antigrav GUI launcher exit codes have only a historical
receipt classifier; live ``agy`` worker adapter support is represented by
:class:`AgyAdapter`, while the live agy review route is exposed through
``scripts/hapax-agy-reviewer``.

NB: the module name is ``capability_adapter_protocol`` because ``capability_adapters`` is
already taken by the unrelated ``PerceptionBackendAdapter``.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import ClassVar, final

from shared.coord_dispatch import (
    DispatchLaunchRequest,
    DispatchLaunchResult,
    replay_terminal_result,
    run_atomic_dispatch_launch,
)
from shared.dispatcher_policy import (
    DispatchAction,
    DispatchRequest,
    RouteDecision,
    evaluate_dispatch_policy,
)
from shared.execution_admission import (
    ContentAddress,
    ExecutionAdmissionError,
    ExecutionCompositionRoot,
    ExecutionInvocationBundlePointer,
    ExecutionInvocationContext,
    ExecutionLease,
)
from shared.failure_classification import (
    FailureCode,
    FailureReceipt,
    failure_code_for_zai,
)
from shared.platform_capability_registry import (
    Platform,
    PlatformCapabilityRegistry,
    PlatformCapabilityRoute,
    RegistryFreshnessCheck,
    check_registry_freshness,
)

__all__ = [
    "AuthorityViolation",
    "CapabilityAdapter",
    "WorkerAdapter",
    "SendCapableAdapter",
    "BudgetAuthorityAdapter",
    "ReviewSeatAdapter",
    "AgyAdapter",
    "ClaudeAdapter",
    "CodexAdapter",
    "VibeAdapter",
]


class AuthorityViolation(RuntimeError):
    """Raised when a launch/send is attempted against a decision that does not authorize it.

    Net-new exception (no prior definition existed anywhere in the tree). It is raised ONLY by
    the worker/send surface, because ``coord_dispatch`` delegates all decision-assertion to the
    ``launch`` callable and ``dispatcher_policy`` itself only returns ``reason_codes`` — it never
    raises. A correctly-built decision never triggers this; callers must not swallow it.
    """


def _require_launch_authority(decision: RouteDecision, *, op: str) -> RouteDecision:
    """Fail-closed authority gate shared by ``launch`` and ``send``.

    Both conditions are asserted defensively. ``launch_allowed`` is a DERIVED field
    (``== (action is LAUNCH)`` in ``dispatcher_policy`` today), so the checks are redundant by
    construction — but asserting both means a future decoupling cannot silently launch a
    non-``LAUNCH`` action. Identity (``is``) matches the canonical dispatcher idiom, not ``==``.
    """

    if type(decision) is not RouteDecision:
        raise AuthorityViolation(f"{op} not authorized: exact route decision is required")
    checked = RouteDecision.model_validate(decision.model_dump(mode="json"))
    if checked.action is not DispatchAction.LAUNCH or not checked.launch_allowed:
        raise AuthorityViolation(
            f"{op} not authorized for route {checked.route_id}: "
            f"action={checked.action} launch_allowed={checked.launch_allowed} "
            f"reason_codes={checked.reason_codes}. "
            f"Next: only a LAUNCH decision with launch_allowed=True may {op}; confirm this "
            "RouteDecision came straight from evaluate_dispatch_policy (via .admit) and was not "
            "mutated, then re-evaluate rather than forcing the call."
        )
    return checked


def _require_composition_pointer(
    composition: ExecutionCompositionRoot,
    invocation_pointer: ExecutionInvocationBundlePointer,
    *,
    op: str,
) -> None:
    if type(composition) is not ExecutionCompositionRoot:
        raise AuthorityViolation(f"{op} not authorized: exact execution composition is required")
    if type(invocation_pointer) is not ExecutionInvocationBundlePointer:
        raise AuthorityViolation(
            f"{op} not authorized: exact execution invocation bundle pointer is required"
        )


def _require_composition_invocation(
    composition: ExecutionCompositionRoot,
    invocation_pointer: ExecutionInvocationBundlePointer,
    *,
    op: str,
    queried_at: str | datetime,
) -> tuple[ExecutionInvocationContext, ExecutionLease]:
    _require_composition_pointer(composition, invocation_pointer, op=op)
    try:
        invocation = composition.resolve_structural_invocation(
            invocation_pointer,
            queried_at=queried_at,
        )
        if type(invocation) is not ExecutionInvocationContext:
            raise TypeError("composition returned a non-canonical invocation")
        lease = invocation.require_admitted(queried_at=queried_at)
        return invocation, lease
    except ExecutionAdmissionError as exc:
        raise AuthorityViolation(f"{op} not authorized: {exc}") from exc
    except Exception as exc:
        raise AuthorityViolation(
            f"{op} not authorized: malformed execution invocation ({type(exc).__name__})"
        ) from exc


def _require_worker_request_binding(
    *,
    platform: Platform,
    decision: RouteDecision,
    request: DispatchLaunchRequest,
) -> None:
    if type(request) is not DispatchLaunchRequest:
        raise AuthorityViolation("launch not authorized: exact dispatch request is required")
    mismatches: list[str] = []
    if decision.task_id != request.task_id:
        mismatches.append("task")
    if decision.lane.strip().lower().replace("_", "-") != request.normalized_lane:
        mismatches.append("lane")
    if decision.platform != request.platform or decision.platform != platform.value:
        mismatches.append("platform")
    if decision.mode != request.mode or decision.profile != request.profile:
        mismatches.append("mode_profile")
    if mismatches:
        raise AuthorityViolation(
            "launch not authorized: dispatch request binding mismatch "
            + ",".join(sorted(mismatches))
        )


def _require_send_invocation_binding(
    *,
    platform: Platform,
    decision: RouteDecision,
    invocation: ExecutionInvocationContext,
    lease: ExecutionLease,
    message: ContentAddress,
) -> None:
    checked_decision = RouteDecision.model_validate(decision.model_dump(mode="json"))
    invocation_decision = RouteDecision.model_validate(
        invocation.route_decision.model_dump(mode="json")
    )
    selected_leaf = checked_decision.selected_descriptor_leaf or f"{checked_decision.route_id}#base"
    if (
        checked_decision != invocation_decision
        or checked_decision.platform != platform.value
        or selected_leaf != lease.selected_descriptor_leaf
        or invocation.protected_request.operation != "relay.send"
        or lease.bound_call.operation != "relay.send"
        or message not in lease.bound_call.requested_effect_targets
    ):
        raise AuthorityViolation("send not authorized: execution invocation route binding mismatch")


# Worker-CLI (claude/codex) failure signatures -> FailureCode. Minimal + verbatim-derived,
# NOT invented: the quota shapes are informed by the same documented Claude subscription-wall
# signatures as scripts/review_team.py:_QUOTA_WALL_SHAPE_RE, but kept deliberately minimal and
# INDEPENDENT (not a literal mirror — this table does not silently drift if that regex changes);
# the auth + transient shapes are the documented Anthropic/provider API error families
# (authentication_error, overloaded_error/529, 503). UNKNOWN is the no-auto-degrade default.
# Extend as real signatures are observed — do not invent.
_CLI_QUOTA_RE = re.compile(
    r"(?i)("
    # the actual Claude Code subscription-wall phrasing (verb BEFORE 'limit'), aligned with the
    # canonical review_team._QUOTA_WALL_SHAPE_RE — the common case the old pattern silently missed
    r"you(?:'ve| have) hit your (?:weekly|usage|session|5-hour) limit"
    r"|usage limit\s+(?:reached|exceeded|hit)|weekly limit"
    r"|rate.?limit\s+(?:reached|exceeded|hit)"
    r"|quota\s+(?:reached|exceeded|exhausted|hit)"
    r"|RESOURCE_EXHAUSTED|HTTP 429|Too Many Requests"
    r"|purchase more credits|credit balance is too low"
    r")"
)
_CLI_AUTH_RE = re.compile(
    r"(?i)(authentication[_ ]error|invalid\s+(?:x-)?api[_ -]?key|"
    r"401\s+unauthorized|\bunauthorized\b)"
)
_CLI_TRANSIENT_RE = re.compile(
    r"(?i)(overloaded|\b529\b|\b503\b|service unavailable|"
    r"connection (?:reset|refused|timed out)|temporarily unavailable)"
)


def _classify_cli_failure(text: str, model_stdout: str = "") -> FailureCode:
    """Map worker-CLI error text to a FailureCode; UNKNOWN default (no auto-degrade).

    Priority quota > auth > transient mirrors the dispatch verdict precedence.
    """

    blob = f"{text}\n{model_stdout}"
    if _CLI_QUOTA_RE.search(blob):
        return FailureCode.QUOTA_EXHAUSTION
    if _CLI_AUTH_RE.search(blob):
        return FailureCode.AUTH_FAILURE
    if _CLI_TRANSIENT_RE.search(blob):
        return FailureCode.TRANSIENT
    return FailureCode.UNKNOWN


_FINAL_DELEGATIONS = ("describe", "admit", "observe", "collect_receipts")


class CapabilityAdapter:
    """Base of the adapter hierarchy. Holds the four FINAL delegations + the overridable
    ``preflight`` / ``classify_failure`` hooks. Has NEITHER ``launch`` NOR ``send`` — those arrive
    only via :class:`WorkerAdapter` / :class:`SendCapableAdapter`, so capability is a type-level fact.

    ``PLATFORM`` is a ``ClassVar`` set by each concrete adapter; the type *is* the platform.
    """

    PLATFORM: ClassVar[Platform]

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        for name in _FINAL_DELEGATIONS:
            if name in cls.__dict__:
                raise TypeError(
                    f"{cls.__name__} may not override CapabilityAdapter.{name}: the four "
                    "delegations (describe/admit/observe/collect_receipts) are FINAL. A platform "
                    "is admitted only by passing _route_set_matches_contract, never by editing "
                    "adapter code."
                )

    @final
    def describe(
        self, registry: PlatformCapabilityRegistry, route_id: str
    ) -> PlatformCapabilityRoute:
        """FINAL. Resolve the governed route via the registry (KeyErrors on an unknown route).

        Asserts the route's platform matches this adapter — a mismatch is a wiring bug
        (``ValueError``), not an authority breach.
        """

        if type(registry) is not PlatformCapabilityRegistry:
            raise TypeError("exact platform capability registry is required")
        route = registry.require(route_id)
        if route.platform is not self.PLATFORM:
            raise ValueError(
                f"route {route_id} is platform {route.platform}, not {self.PLATFORM} "
                "(adapter/route mismatch — wiring bug, not an authority breach)"
            )
        return route

    @final
    def admit(
        self,
        request: DispatchRequest,
        *,
        now: datetime,
        candidate_requests: tuple[DispatchRequest, ...] | None = None,
    ) -> RouteDecision:
        """FINAL. Return ``evaluate_dispatch_policy`` output UNCHANGED — zero widening, zero added
        reason_codes. The adapter is a pure pass-through; it never mutates or re-wraps the decision.
        """

        if type(request) is not DispatchRequest:
            raise TypeError("exact dispatch request is required")
        checked_request = DispatchRequest.model_validate(request.model_dump(mode="json"))
        if type(now) is not datetime or now.tzinfo is None:
            raise TypeError("explicit timezone-aware dispatch decision time is required")
        checked_candidates = None
        if candidate_requests is not None:
            if type(candidate_requests) is not tuple or any(
                type(item) is not DispatchRequest for item in candidate_requests
            ):
                raise TypeError("candidate requests must be an exact tuple of dispatch requests")
            checked_candidates = tuple(
                DispatchRequest.model_validate(item.model_dump(mode="json"))
                for item in candidate_requests
            )
        return evaluate_dispatch_policy(
            checked_request,
            now=now,
            candidate_requests=checked_candidates,
        )

    @final
    def observe(
        self, registry: PlatformCapabilityRegistry, *, now: datetime
    ) -> RegistryFreshnessCheck:
        """FINAL. Read-only freshness observation; pure delegation to the registry's checker."""

        if type(registry) is not PlatformCapabilityRegistry:
            raise TypeError("exact platform capability registry is required")
        if type(now) is not datetime or now.tzinfo is None:
            raise TypeError("explicit timezone-aware registry observation time is required")
        return check_registry_freshness(registry, now=now)

    @final
    def collect_receipts(
        self,
        request: DispatchLaunchRequest,
        *,
        composition: ExecutionCompositionRoot,
        invocation_pointer: ExecutionInvocationBundlePointer,
        queried_at: str | datetime,
        idempotency_key: str | None = None,
    ) -> DispatchLaunchResult | None:
        """FINAL. Inspect canonical outcome truth without projecting operational state."""

        return replay_terminal_result(
            request,
            composition=composition,
            invocation_pointer=invocation_pointer,
            queried_at=queried_at,
            idempotency_key=idempotency_key,
        )

    def preflight(self, request: DispatchRequest) -> tuple[str, ...]:
        """Overridable, ADVISORY-only readiness hints (e.g. token presence, lane health). Does NOT
        gate ``admit`` and must NOT raise :class:`AuthorityViolation` — ``admit`` is the sole
        authority. Default: no preflight blockers.
        """

        return ()

    def classify_failure(
        self,
        text: str,
        *,
        process_failed: bool = False,
        model_stdout: str = "",
        route_id: str | None = None,
        error_class: str | None = None,
        exit_code: int | None = None,
    ) -> FailureReceipt:
        """Overridable. Map a platform failure signal to a lossless :class:`FailureReceipt`.

        Default is the no-auto-degrade UNKNOWN fallback (the receipt is the lossless raw surface,
        not a verdict). Per-platform adapters override with a small table; the dispatch verdict is
        never changed here.
        """

        return FailureReceipt(
            code=FailureCode.UNKNOWN,
            raw_signal=text,
            platform=self.PLATFORM.value,
            route_id=route_id,
            error_class=error_class,
        )


class WorkerAdapter(CapabilityAdapter):
    """Adds the ``launch`` capability. A platform that cannot launch simply is not a
    ``WorkerAdapter`` (so ``hasattr(adapter, "launch")`` is honest).
    """

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if "launch" in cls.__dict__:
            raise TypeError(
                f"{cls.__name__} may not override WorkerAdapter.launch; "
                "platform variability belongs behind the executor registry"
            )

    @final
    def launch(
        self,
        decision: RouteDecision,
        request: DispatchLaunchRequest,
        *,
        composition: ExecutionCompositionRoot,
        invocation_pointer: ExecutionInvocationBundlePointer,
        queried_at: str | datetime,
    ) -> DispatchLaunchResult:
        """Assert authority FIRST (the sole re-check point — coord_dispatch does not re-check),
        then delegate the atomic spawn. Overrides MUST preserve the authority assert (call
        ``super().launch`` or re-assert); the pure-reuse adapters below inherit this verbatim.
        """

        checked_decision = _require_launch_authority(decision, op="launch")
        _require_worker_request_binding(
            platform=self.PLATFORM,
            decision=checked_decision,
            request=request,
        )
        _require_composition_pointer(
            composition,
            invocation_pointer,
            op="launch",
        )
        return run_atomic_dispatch_launch(
            request,
            composition=composition,
            invocation_pointer=invocation_pointer,
            queried_at=queried_at,
        )


class SendCapableAdapter:
    """Mixin granting the relay ``send`` capability. Combine as
    ``class FooAdapter(WorkerAdapter, SendCapableAdapter)``. Platforms without send (api, the glmcp
    review seat) do not mix this in, so ``send`` is absent from their MRO.

    Not a :class:`CapabilityAdapter` subclass on its own (so defining it does not trip the FINAL
    guard). The protocol layer marks the capability + gates authority; the actual relay is wired
    per-platform in glue slices (for example ``scripts/hapax-claude-send`` for Claude lanes).
    """

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if "send" in cls.__dict__:
            raise TypeError(
                f"{cls.__name__} may not override SendCapableAdapter.send; "
                "platform variability belongs behind the executor registry"
            )

    @final
    def send(
        self,
        decision: RouteDecision,
        message: ContentAddress,
        *,
        composition: ExecutionCompositionRoot,
        invocation_pointer: ExecutionInvocationBundlePointer,
        queried_at: str | datetime,
    ) -> str:
        checked_decision = _require_launch_authority(decision, op="send")
        if type(message) is not ContentAddress:
            raise AuthorityViolation(
                "send not authorized: exact content-addressed relay payload is required"
            )
        checked_message = ContentAddress.model_validate(message.model_dump(mode="json"))
        invocation, lease = _require_composition_invocation(
            composition,
            invocation_pointer,
            op="send",
            queried_at=queried_at,
        )
        _require_send_invocation_binding(
            platform=self.PLATFORM,  # type: ignore[attr-defined]
            decision=checked_decision,
            invocation=invocation,
            lease=lease,
            message=checked_message,
        )
        try:
            composition.require_effect_activation()
        except ExecutionAdmissionError as exc:
            raise AuthorityViolation(f"send not authorized: {exc}") from exc
        raise NotImplementedError(
            "relay send is wired per-platform in the glue slices; the protocol layer only marks "
            "the capability and gates authority."
        )


class BudgetAuthorityAdapter(CapabilityAdapter):
    """The api budget authority: priced provider routing, NO launch and NO send (it does not spawn
    a worker or relay to a lane). The absence on the MRO IS the no-launch/no-send guarantee.
    """

    PLATFORM: ClassVar[Platform] = Platform.API


class ReviewSeatAdapter(CapabilityAdapter):
    """The glmcp review seat (``glmcp.review.direct``): read-only, NO launch and NO send. Overrides
    ``classify_failure`` to map the structured Z.ai error envelopes via the shared table.
    """

    PLATFORM: ClassVar[Platform] = Platform.GLMCP

    def classify_failure(
        self,
        text: str,
        *,
        process_failed: bool = False,
        model_stdout: str = "",
        route_id: str | None = None,
        error_class: str | None = None,
        exit_code: int | None = None,
    ) -> FailureReceipt:
        code = failure_code_for_zai(error_class) if error_class else FailureCode.UNKNOWN
        return FailureReceipt(
            code=code,
            raw_signal=text,
            platform=self.PLATFORM.value,
            route_id=route_id,
            error_class=error_class,
        )


class AgyAdapter(WorkerAdapter):
    """Agy worker lanes: pure reuse + the shared CLI failure table."""

    PLATFORM: ClassVar[Platform] = Platform.AGY

    def classify_failure(
        self,
        text: str,
        *,
        process_failed: bool = False,
        model_stdout: str = "",
        route_id: str | None = None,
        error_class: str | None = None,
        exit_code: int | None = None,
    ) -> FailureReceipt:
        return FailureReceipt(
            code=_classify_cli_failure(text, model_stdout),
            raw_signal=text,
            platform=self.PLATFORM.value,
            route_id=route_id,
            error_class=error_class,
        )


class ClaudeAdapter(WorkerAdapter, SendCapableAdapter):
    """Claude worker lanes: pure reuse (inherits launch + the four FINAL delegations verbatim) plus
    a small CLI failure table.
    """

    PLATFORM: ClassVar[Platform] = Platform.CLAUDE

    def classify_failure(
        self,
        text: str,
        *,
        process_failed: bool = False,
        model_stdout: str = "",
        route_id: str | None = None,
        error_class: str | None = None,
        exit_code: int | None = None,
    ) -> FailureReceipt:
        return FailureReceipt(
            code=_classify_cli_failure(text, model_stdout),
            raw_signal=text,
            platform=self.PLATFORM.value,
            route_id=route_id,
            error_class=error_class,
        )


class CodexAdapter(WorkerAdapter, SendCapableAdapter):
    """Codex worker lanes: pure reuse + the shared CLI failure table (same shape as Claude)."""

    PLATFORM: ClassVar[Platform] = Platform.CODEX

    def classify_failure(
        self,
        text: str,
        *,
        process_failed: bool = False,
        model_stdout: str = "",
        route_id: str | None = None,
        error_class: str | None = None,
        exit_code: int | None = None,
    ) -> FailureReceipt:
        return FailureReceipt(
            code=_classify_cli_failure(text, model_stdout),
            raw_signal=text,
            platform=self.PLATFORM.value,
            route_id=route_id,
            error_class=error_class,
        )


class VibeAdapter(WorkerAdapter, SendCapableAdapter):
    """Vibe worker lanes: pure reuse + shared CLI failure table + wrapper-backed send."""

    PLATFORM: ClassVar[Platform] = Platform.VIBE

    def classify_failure(
        self,
        text: str,
        *,
        process_failed: bool = False,
        model_stdout: str = "",
        route_id: str | None = None,
        error_class: str | None = None,
        exit_code: int | None = None,
    ) -> FailureReceipt:
        return FailureReceipt(
            code=_classify_cli_failure(text, model_stdout),
            raw_signal=text,
            platform=self.PLATFORM.value,
            route_id=route_id,
            error_class=error_class,
        )


# Historical Antigrav GUI launcher exit codes (scripts/hapax-antigrav) -> FailureCode. Only the
# two codes with a genuine availability/claim meaning are mapped; usage/env/setup errors
# (2/3/5/6/9) stay UNKNOWN (no auto-degrade). Verbatim from the retired launcher: exit 4 = agy
# binary not found (route gone), exit 8 = cc-claim failed (claim conflict).
_ANTIGRAV_EXIT_CODE_TO_FAILURE: dict[int, FailureCode] = {
    4: FailureCode.ROUTE_UNAVAILABLE,
    8: FailureCode.CLAIM_CONFLICT,
}


class RetiredAntigravFailureClassifier:
    """Historical receipt classifier for retired Antigrav GUI launcher signals.

    This class is intentionally NOT a :class:`CapabilityAdapter`, NOT a :class:`WorkerAdapter`,
    and not exported through ``__all__``. It cannot describe, admit, launch, send, observe, or
    collect receipts; it only preserves a lossless mapping for old terminal evidence and tests.
    """

    PLATFORM: ClassVar[Platform] = Platform.ANTIGRAV

    def classify_failure(
        self,
        text: str,
        *,
        process_failed: bool = False,
        model_stdout: str = "",
        route_id: str | None = None,
        error_class: str | None = None,
        exit_code: int | None = None,
    ) -> FailureReceipt:
        code = (
            _ANTIGRAV_EXIT_CODE_TO_FAILURE.get(exit_code, FailureCode.UNKNOWN)
            if exit_code is not None
            else FailureCode.UNKNOWN
        )
        return FailureReceipt(
            code=code,
            raw_signal=text,
            platform=self.PLATFORM.value,
            route_id=route_id,
            error_class=error_class,
        )
