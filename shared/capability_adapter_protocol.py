"""CapabilityAdapter protocol + type hierarchy (thin, final-delegating).

The adapter layer is a *thin* facade over the existing pure dispatch functions. It
exists to give admitted platforms (claude/codex worker lanes, the api budget authority, the
glmcp review seat) ONE uniform surface —
``describe / admit / observe / collect_receipts`` (FINAL, non-overridable delegations) plus
``preflight / launch / classify_failure`` (the per-platform overridable surface) —
WITHOUT widening any authority or duplicating policy. ``send`` is the governed SESSION-gate
egress boundary: single-sourced on :class:`SendCapableAdapter` (subclasses may not override it)
with per-platform variation ONLY through the canonical relay-wrapper table.

Three invariants are load-bearing:

1. **A platform is never admitted by editing adapter code.** ``describe`` and ``admit``
   delegate verbatim to ``registry.require`` and ``evaluate_dispatch_policy``; the adapter
   adds zero ``reason_codes`` and cannot widen a decision. Admissibility was decided by
   ``_route_set_matches_contract`` at registry construction time. The four delegations are
   ``@final`` *and* guarded at runtime by ``__init_subclass__`` (``typing.final`` alone is
   advisory — only static checkers honour it).

2. **``launch`` and ``send`` assert authority FIRST.** ``coord_dispatch.run_atomic_dispatch_launch``
   never re-checks the decision, so ``WorkerAdapter.launch`` is the SOLE enforcement point:
   a non-``LAUNCH`` (or ``launch_allowed=False``) decision raises :class:`AuthorityViolation`
   before any side effect. ``SendCapableAdapter.send`` applies the same gate before ANY egress
   side effect, then mints a :class:`SessionSendReceipt` on the evidence bus the reins
   send-gate consumer lights up on.

3. **No boutique send paths.** ``send`` cannot be overridden (``__init_subclass__`` guard on the
   mixin); the ONLY per-platform variation is the ``_SESSION_SEND_RELAYS`` row mapping a platform
   to its already-governed relay wrapper (``scripts/hapax-<platform>-send``). A platform without a
   row fails closed — no ad-hoc ``hapax-<engine>`` egress is minted by adapter code.

Capability differences are expressed at the TYPE level, not via runtime flags: only
:class:`WorkerAdapter` has ``launch``; only :class:`SendCapableAdapter` (a mixin) has
``send``. :class:`BudgetAuthorityAdapter` (api) and :class:`ReviewSeatAdapter` (glmcp) have
neither, so ``hasattr(adapter, "launch")`` is the honest test (genuine ``AttributeError``,
not a ``False`` flag). Retired Antigrav GUI launcher exit codes have only a historical
receipt classifier; live ``agy`` is represented by :class:`AgyAdapter`.

NB: the module name is ``capability_adapter_protocol`` because ``capability_adapters`` is
already taken by the unrelated ``PerceptionBackendAdapter``.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import ClassVar, Literal, final
from uuid import uuid4

from pydantic import BaseModel

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
    "SessionSendReceipt",
    "append_session_send_receipt",
    "DEFAULT_SESSION_SEND_RECEIPTS",
]


class AuthorityViolation(RuntimeError):
    """Raised when a launch/send is attempted against a decision that does not authorize it.

    Net-new exception (no prior definition existed anywhere in the tree). It is raised ONLY by
    the worker/send surface, because ``coord_dispatch`` delegates all decision-assertion to the
    ``launch`` callable and ``dispatcher_policy`` itself only returns ``reason_codes`` — it never
    raises. A correctly-built decision never triggers this; callers must not swallow it.
    """


def _require_launch_authority(decision: RouteDecision, *, op: str) -> None:
    """Fail-closed authority gate shared by ``launch`` and ``send``.

    Both conditions are asserted defensively. ``launch_allowed`` is a DERIVED field
    (``== (action is LAUNCH)`` in ``dispatcher_policy`` today), so the checks are redundant by
    construction — but asserting both means a future decoupling cannot silently launch a
    non-``LAUNCH`` action. Identity (``is``) matches the canonical dispatcher idiom, not ``==``.
    """

    if decision.action is not DispatchAction.LAUNCH or not decision.launch_allowed:
        raise AuthorityViolation(
            f"{op} not authorized for route {decision.route_id}: "
            f"action={decision.action} launch_allowed={decision.launch_allowed} "
            f"reason_codes={decision.reason_codes}. "
            f"Next: only a LAUNCH decision with launch_allowed=True may {op}; confirm this "
            "RouteDecision came straight from evaluate_dispatch_policy (via .admit) and was not "
            "mutated, then re-evaluate rather than forcing the call."
        )


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
        now: datetime | None = None,
        candidate_requests: tuple[DispatchRequest, ...] | None = None,
    ) -> RouteDecision:
        """FINAL. Return ``evaluate_dispatch_policy`` output UNCHANGED — zero widening, zero added
        reason_codes. The adapter is a pure pass-through; it never mutates or re-wraps the decision.
        """

        return evaluate_dispatch_policy(request, now=now, candidate_requests=candidate_requests)

    @final
    def observe(
        self, registry: PlatformCapabilityRegistry, *, now: datetime | None = None
    ) -> RegistryFreshnessCheck:
        """FINAL. Read-only freshness observation; pure delegation to the registry's checker."""

        return check_registry_freshness(registry, now=now)

    @final
    def collect_receipts(
        self, request: DispatchLaunchRequest, *, idempotency_key: str | None = None
    ) -> DispatchLaunchResult | None:
        """FINAL. Read the terminal launch result (if any) from the coord event log. Reads a
        receipt regardless of LAUNCH/REFUSE outcome; defaults the key to the request's own.
        """

        return replay_terminal_result(
            request,
            idempotency_key=idempotency_key or request.effective_idempotency_key,
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

    def launch(
        self,
        decision: RouteDecision,
        request: DispatchLaunchRequest,
        launch_callable: Callable[[], int],
    ) -> DispatchLaunchResult:
        """Assert authority FIRST (the sole re-check point — coord_dispatch does not re-check),
        then delegate the atomic spawn. Overrides MUST preserve the authority assert (call
        ``super().launch`` or re-assert); the pure-reuse adapters below inherit this verbatim.
        """

        _require_launch_authority(decision, op="launch")
        return run_atomic_dispatch_launch(request, launch_callable)


# --- SESSION-gate send: receipts bus + canonical relay table ------------------------------------

#: Persistent (NOT tmpfs) SESSION-send evidence bus — one JSON line per governed egress. The reins
#: send-gate consumer lights up ONLY on receipts read from this path; keep it out of /tmp and
#: /dev/shm (the tmpfs-swap-trap) so the evidence survives a reboot, mirroring ``shared.gate_log``.
DEFAULT_SESSION_SEND_RECEIPTS = Path(
    os.environ.get(
        "HAPAX_SESSION_SEND_RECEIPTS",
        str(Path.home() / ".cache" / "hapax" / "sdlc-routing" / "session-send-receipts.jsonl"),
    )
)

#: The ONLY per-platform variation point of the SESSION gate: platform -> canonical relay wrapper
#: (already-governed transports under ``scripts/``). A send-capable platform missing here fails
#: closed; a platform gains egress by adding a row — never by a new ``hapax-<engine>`` send script
#: and never by overriding ``send``.
_SESSION_SEND_RELAYS: dict[Platform, str] = {
    Platform.CLAUDE: "hapax-claude-send",
    Platform.CODEX: "hapax-codex-send",
    Platform.VIBE: "hapax-vibe-send",
}

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


class SessionSendReceipt(BaseModel):
    """One governed SESSION-gate egress receipt — the authority result the reins send-gate reads.

    Deliberately carries NO message body (the send route is privacy/secret-sensitive): the sha256 +
    length prove WHICH payload egressed without persisting content on the evidence bus.
    """

    receipt_schema: Literal[1] = 1
    receipt_id: str
    created_at: str
    op: Literal["session_send"] = "session_send"
    decision_id: str
    task_id: str
    lane: str
    route_id: str
    platform: str
    authority_action: str
    authority_launch_allowed: bool
    relay_wrapper: str
    message_sha256: str
    message_chars: int
    exit_code: int
    outcome: Literal["sent", "failed"]


def append_session_send_receipt(
    receipt: SessionSendReceipt, *, path: Path | str | None = None
) -> Path:
    """Append one receipt line to the SESSION-send evidence bus.

    Creates the parent directory if needed; an unwritable path raises the OSError to the caller —
    a lost egress receipt must surface, never silently pass (same contract as the gate log).
    """

    target = Path(path) if path is not None else DEFAULT_SESSION_SEND_RECEIPTS
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(receipt.model_dump_json() + "\n")
    return target


def _run_session_relay(argv: tuple[str, ...]) -> int:
    """Default relay runner: execute the canonical wrapper, return its exit code (no capture —
    the wrapper's ack/status output belongs to the operator's terminal, not the receipt).
    """

    return subprocess.run(list(argv), check=False).returncode


class SendCapableAdapter:
    """Mixin granting the governed SESSION-gate ``send`` capability. Combine as
    ``class FooAdapter(WorkerAdapter, SendCapableAdapter)``. Platforms without send (agy, api, the
    glmcp review seat) do not mix this in, so ``send`` is absent from their MRO — capability stays
    a type-level fact, never a runtime ``supports_send`` flag.

    Not a :class:`CapabilityAdapter` subclass on its own (so defining it does not trip the FINAL
    guard). ``send`` IS the SESSION egress boundary: authority asserted FIRST, then the canonical
    per-platform relay wrapper from ``_SESSION_SEND_RELAYS``, then a :class:`SessionSendReceipt`
    on the evidence bus (the receipt the reins send-gate consumer lights up on). Subclasses may
    NOT override ``send`` — a per-engine send override would fork the gate into a boutique path.
    """

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if "send" in cls.__dict__:
            raise TypeError(
                f"{cls.__name__} may not override SendCapableAdapter.send: the SESSION gate is "
                "single-sourced (authority -> canonical relay -> receipt). No boutique send "
                "paths — a platform varies only via the _SESSION_SEND_RELAYS wrapper table."
            )

    def send(
        self,
        decision: RouteDecision,
        message: str,
        *,
        relay_runner: Callable[[tuple[str, ...]], int] | None = None,
        now: datetime | None = None,
        receipts_path: Path | str | None = None,
    ) -> SessionSendReceipt:
        """Authority-checked SESSION egress: assert authority FIRST (before ANY side effect),
        relay through the canonical per-platform wrapper, mint the evidence receipt.

        A non-``LAUNCH`` decision raises :class:`AuthorityViolation` with the relay untouched and
        no receipt written. A platform/decision mismatch or a missing canonical relay is a wiring
        bug (``ValueError`` / ``FileNotFoundError``) — fail closed, never substitute a path.
        """

        _require_launch_authority(decision, op="send")
        platform = getattr(type(self), "PLATFORM", None)
        if not isinstance(platform, Platform):
            raise TypeError(
                "SendCapableAdapter must be mixed into a CapabilityAdapter with a PLATFORM "
                "ClassVar; a bare mixin has no governed relay target."
            )
        if decision.platform != platform.value:
            raise ValueError(
                f"decision routes platform {decision.platform!r}, adapter is {platform.value!r} "
                "(adapter/decision mismatch — wiring bug, not an authority breach)"
            )
        relay_name = _SESSION_SEND_RELAYS.get(platform)
        if relay_name is None:
            raise ValueError(
                f"no canonical session relay registered for platform {platform.value!r}; "
                "send-capable platforms gain egress ONLY via _SESSION_SEND_RELAYS (no boutique "
                "hapax-<engine> send paths)"
            )
        wrapper = _SCRIPTS_DIR / relay_name
        if not wrapper.is_file():
            raise FileNotFoundError(
                f"canonical relay wrapper missing: {wrapper} — fail closed; do NOT substitute an "
                "ad-hoc send path"
            )
        argv = (str(wrapper), "--session", decision.lane, "--", message)
        exit_code = (relay_runner or _run_session_relay)(argv)
        receipt = SessionSendReceipt(
            receipt_id=uuid4().hex,
            created_at=(now or datetime.now(UTC)).isoformat(),
            decision_id=decision.decision_id,
            task_id=decision.task_id,
            lane=decision.lane,
            route_id=decision.route_id,
            platform=platform.value,
            authority_action=decision.action.value,
            authority_launch_allowed=decision.launch_allowed,
            relay_wrapper=f"scripts/{relay_name}",
            message_sha256=sha256(message.encode("utf-8")).hexdigest(),
            message_chars=len(message),
            exit_code=exit_code,
            outcome="sent" if exit_code == 0 else "failed",
        )
        append_session_send_receipt(receipt, path=receipts_path)
        return receipt


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
    """Vibe worker lanes: pure reuse + the shared CLI failure table. Send-capable — vibe lanes are
    live tmux harnesses with a canonical relay (``scripts/hapax-vibe-send``).
    """

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
