"""Background task: every tick, evaluate gates → compose → emit.

Spawned by ``run_inner._make_task(daemon, "autonomous_narrative_loop",
lambda: autonomous_narrative_loop(daemon))`` alongside the existing
proactive_delivery / impingement_consumer / sidechat loops. Per-tick
sleep is short (10 s) so SIGTERM is responsive; the cadence + rate-
limit gates handle when to actually emit.

Default OFF: when ``HAPAX_AUTONOMOUS_NARRATIVE_ENABLED`` is not "1",
the loop spins as a no-op and only logs once at startup that it's
disabled. The operator opts in by setting the env var and restarting
the daemon.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from agents.hapax_daimonion.autonomous_narrative import compose, emit, gates, state_readers

log = logging.getLogger(__name__)


_TICK_SLEEP_S: float = 10.0  # short slice → responsive shutdown


async def autonomous_narrative_loop(daemon: Any) -> None:
    """Run the autonomous narrative director until ``daemon._running`` is False."""
    if not gates.env_enabled():
        log.info(
            "autonomous_narrative_loop disabled (HAPAX_AUTONOMOUS_NARRATIVE_ENABLED=0); "
            "loop will idle. Operator opts in by setting the env var to 1 + restarting "
            "the daimonion."
        )
        await _idle_until_shutdown(daemon)
        return

    interval_s = gates.env_interval_s()
    log.info("autonomous_narrative_loop running with cadence interval_s=%.0f", interval_s)

    last_emission_ts = 0.0
    while getattr(daemon, "_running", True):
        try:
            now = time.time()
            context = state_readers.assemble_context(daemon, now=now)
            decision = gates.evaluate(
                daemon,
                context,
                last_emission_ts=last_emission_ts,
                now=now,
                interval_s=interval_s,
            )
            if not decision.allow:
                emit.record_metric(decision.reason)
            else:
                narrative = compose.compose_narrative(context)
                if narrative is None:
                    emit.record_metric("llm_silent")
                else:
                    referent = _pick_referent_for_programme(context)
                    programme_id = _programme_id(context)
                    ok = emit.emit_narrative(
                        narrative,
                        programme_id=programme_id,
                        operator_referent=referent,
                        now=now,
                    )
                    if ok:
                        emit.record_metric("allow")
                        last_emission_ts = now
                    else:
                        emit.record_metric("write_failed")
        except Exception:
            log.exception("autonomous_narrative_loop tick raised; continuing")
            emit.record_metric("tick_exception")
        await asyncio.sleep(_TICK_SLEEP_S)


async def _idle_until_shutdown(daemon: Any) -> None:
    while getattr(daemon, "_running", True):
        await asyncio.sleep(_TICK_SLEEP_S)


def _programme_id(context: Any) -> str | None:
    prog = getattr(context, "programme", None)
    if prog is None:
        return None
    pid = getattr(prog, "programme_id", None)
    return str(pid) if pid is not None else None


def _pick_referent_for_programme(context: Any) -> str | None:
    """Soft-import the operator referent picker; seed per-programme.

    Per ``su-non-formal-referent-001``, autonomous narrative is a
    non-formal context — the operator is named via the picker. Seeding
    on programme_id keeps the referent stable across multiple
    emissions in the same programme arc.
    """
    pid = _programme_id(context)
    if pid is None:
        return None
    try:
        from shared.operator_referent import (  # noqa: PLC0415
            OperatorReferentPicker,
        )
    except ImportError:
        return None
    try:
        return OperatorReferentPicker.pick_for_vod_segment(f"narrative-{pid}")
    except Exception:
        return None
