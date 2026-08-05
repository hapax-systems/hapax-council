"""N2 thin SdlcRouter shadow-compare — log-only vs frontier/WSJF incumbent.

Calls ``SdlcRouter.route`` and records whether the live-selected path
(frontier incumbent under SHADOW/HOLD, or router ROUTE winner) agrees with
the shadow/best alternative. **Never** mutates coordinator dispatch or
class activation.

Default mode: append one JSON line to a compare ledger for later analysis.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.sdlc_router import (
    DEFAULT_SDLC_ROUTER_STATE,
    SdlcRouteCandidate,
    SdlcRouteDecision,
    SdlcRouter,
    SdlcRouterAction,
    SdlcRoutingRequest,
)

DEFAULT_SHADOW_COMPARE_LOG = Path(
    os.environ.get(
        "HAPAX_SDLC_SHADOW_COMPARE_LOG",
        str(Path.home() / ".cache" / "hapax" / "sdlc-routing" / "shadow-compare.jsonl"),
    )
)


@dataclass(frozen=True)
class ShadowCompareRecord:
    """One log-only shadow compare observation."""

    schema: str
    task_id: str
    routing_class: str
    observed_at: str
    action: str
    frontier_incumbent_route_id: str
    live_selected_route_id: str | None
    shadow_route_id: str | None
    router_would_prefer: str | None
    agree: bool
    reason_codes: tuple[str, ...]
    candidate_scores: tuple[dict[str, Any], ...]
    dispatch_mutated: bool
    router_state_path: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reason_codes"] = list(self.reason_codes)
        payload["candidate_scores"] = list(self.candidate_scores)
        return payload


def _router_would_prefer(decision: SdlcRouteDecision) -> str | None:
    """Best route the router scores as preferred under current gates.

    - ROUTE: the selected winner is the preference.
    - SHADOW: the shadow alternative is the preference (live keeps frontier).
    - HOLD: none.
    """
    if decision.action is SdlcRouterAction.ROUTE:
        return decision.selected_route_id
    if decision.action is SdlcRouterAction.SHADOW:
        return decision.shadow_route_id
    return None


def compare_route(
    request: SdlcRoutingRequest,
    candidates: Sequence[SdlcRouteCandidate] | Iterable[SdlcRouteCandidate],
    *,
    router: SdlcRouter | None = None,
    router_state: Path | str | None = None,
) -> ShadowCompareRecord:
    """Run one shadow compare; does not write dispatch state."""
    state_path = Path(router_state) if router_state is not None else DEFAULT_SDLC_ROUTER_STATE
    engine = router if router is not None else SdlcRouter.load(state_path)
    decision = engine.route(request, candidates)

    live = decision.selected_route_id
    prefer = _router_would_prefer(decision)
    # Agree when live path matches what the router would prefer, or both absent.
    agree = live == prefer

    scores = tuple(
        {
            "route_id": s.route_id,
            "aggregate_score": s.aggregate_score,
            "requirement_fit": s.requirement_fit,
            "historical_fit": s.historical_fit,
            "thompson_sample": s.thompson_sample,
        }
        for s in decision.candidate_scores
    )
    return ShadowCompareRecord(
        schema="hapax.sdlc_router_shadow_compare.v1",
        task_id=request.task_id,
        routing_class=request.routing_class,
        observed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        action=str(decision.action.value if hasattr(decision.action, "value") else decision.action),
        frontier_incumbent_route_id=decision.frontier_incumbent_route_id,
        live_selected_route_id=live,
        shadow_route_id=decision.shadow_route_id,
        router_would_prefer=prefer,
        agree=agree,
        reason_codes=tuple(decision.reason_codes),
        candidate_scores=scores,
        dispatch_mutated=False,
        router_state_path=str(state_path),
    )


def append_compare_record(
    record: ShadowCompareRecord,
    *,
    log_path: Path | str | None = None,
) -> Path:
    """Append one compare line; creates parent dirs. Never touches dispatch."""
    path = Path(log_path) if log_path is not None else DEFAULT_SHADOW_COMPARE_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record.as_dict(), sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
    return path


def shadow_compare(
    request: SdlcRoutingRequest,
    candidates: Sequence[SdlcRouteCandidate] | Iterable[SdlcRouteCandidate],
    *,
    router: SdlcRouter | None = None,
    router_state: Path | str | None = None,
    log_path: Path | str | None = None,
    write_log: bool = True,
) -> ShadowCompareRecord:
    """Compare + optional log append (default on)."""
    record = compare_route(
        request,
        candidates,
        router=router,
        router_state=router_state,
    )
    if write_log:
        append_compare_record(record, log_path=log_path)
    return record
