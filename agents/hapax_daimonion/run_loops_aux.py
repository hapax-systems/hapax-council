"""Auxiliary async loops for VoiceDaemon (delivery, ambient, impingement, consent)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agents._impingement import Impingement
from agents._impingement_consumer import ImpingementConsumer
from agents.hapax_daimonion.persona import format_notification  # noqa: F401 (patched in tests)

if TYPE_CHECKING:
    from agents.hapax_daimonion.daemon import VoiceDaemon

log = logging.getLogger("hapax_daimonion")

_PROACTIVE_CHECK_INTERVAL_S = 30
_NTFY_BASE_URL = "http://127.0.0.1:8090"
_NTFY_TOPICS = ["hapax"]

_LIVESTREAM_CONTROL_PATH = Path("/dev/shm/hapax-compositor/livestream-control.json")


def _write_livestream_control(imp: Impingement, candidate: Any) -> bool:
    """Write a livestream toggle request to the compositor's control bus.

    The compositor runs in a separate process, so dispatch crosses a
    process boundary via the ``/dev/shm/hapax-compositor/`` tmpfs
    mailbox that ``state_reader_loop`` polls at 10 Hz. The affordance
    pipeline's consent gate has already filtered this recruitment
    upstream; the file write is the transport, not the policy.

    Activation direction is taken from ``imp.content['activate']`` if
    present; otherwise defaults to ``True`` (start) because
    ``compositor.toggle_livestream`` is idempotent and a mis-guessed
    start resolves to ``already live``.

    Returns True if the file was written.
    """
    activate = bool(imp.content.get("activate", True))
    narrative = str(imp.content.get("narrative", imp.source))
    reason = f"affordance recruitment: {narrative[:120]}"
    payload = {
        "activate": activate,
        "reason": reason,
        "request_id": str(imp.content.get("condition_id") or imp.id),
        "requested_at": time.time(),
        "score": float(getattr(candidate, "combined", 0.0)),
        "source": imp.source,
    }
    try:
        _LIVESTREAM_CONTROL_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _LIVESTREAM_CONTROL_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload))
        tmp.replace(_LIVESTREAM_CONTROL_PATH)
    except OSError:
        log.exception("Failed to write livestream control file")
        return False
    log.info(
        "Livestream control written: activate=%s score=%.2f reason=%s",
        activate,
        payload["score"],
        reason[:60],
    )
    return True


def _record_commanded_no_witness(
    pipeline: Any,
    capability_name: str,
    *,
    source: str,
    command_ref: str,
    route_ref: str,
    public_claim_bearing: bool = False,
    reason: str | None = None,
) -> None:
    """Record command acceptance without granting success learning."""

    from shared.affordance_outcome_adapter import build_commanded_no_witness_outcome

    outcome = build_commanded_no_witness_outcome(
        capability_name,
        command_ref=command_ref,
        route_ref=route_ref,
        source_ref=source,
        public_claim_bearing=public_claim_bearing,
        reason=reason,
    )
    pipeline.record_capability_outcome(
        outcome,
        context={"source": source, "command_ref": command_ref, "route_ref": route_ref},
    )


async def proactive_delivery_loop(daemon: VoiceDaemon) -> None:
    """Periodically check for deliverable notifications."""

    while daemon._running:
        try:
            await asyncio.sleep(_PROACTIVE_CHECK_INTERVAL_S)
            if daemon.notifications.pending_count == 0:
                continue
            if daemon.session.is_active:
                continue

            presence = (
                daemon.perception.latest.presence_score
                if daemon.perception.latest
                else "likely_absent"
            )
            if presence == "likely_absent":
                continue

            gate_result = daemon.gate.check()
            if not gate_result.eligible:
                log.debug("Proactive delivery blocked: %s", gate_result.reason)
                continue

            latest = daemon.perception.latest
            sleep_b = daemon.perception.behaviors.get("sleep_quality")
            delivery_threshold = 0.5
            if sleep_b is not None:
                delivery_threshold = 0.5 + 0.3 * (1.0 - sleep_b.value)

            # BOCPD transition windows
            try:
                import json as _json

                _vls_path = Path("/dev/shm/hapax-compositor/visual-layer-state.json")
                _vls = _json.loads(_vls_path.read_text())
            except (FileNotFoundError, ValueError, OSError):
                _vls = None

            # Schema guard: a writer producing valid JSON whose root is
            # null, a list, a string, or a number raises AttributeError
            # out of ``_vls.get(...)`` — the (FileNotFoundError, ValueError,
            # OSError) catch above does not cover it. Same shape as the
            # other recent SHM-read fixes.
            if isinstance(_vls, dict):
                _change_points = _vls.get("recent_change_points", [])
                _now_ts = time.time()
                _flow_transition = any(
                    cp.get("signal") == "flow_score" and _now_ts - cp.get("timestamp", 0) < 60.0
                    for cp in _change_points
                    if isinstance(cp, dict)
                )
                if _flow_transition:
                    delivery_threshold -= 0.15

                _presence_prob = _vls.get("presence_probability", None)
                if _presence_prob is None:
                    _presence_prob = (
                        getattr(latest, "presence_probability", None) if latest else None
                    )
                if _presence_prob is not None and _presence_prob < 0.5:
                    continue
                if _presence_prob is not None:
                    delivery_threshold += 0.1 * (1.0 - _presence_prob)

            if latest is not None and latest.interruptibility_score < delivery_threshold:
                continue

            notification = daemon.notifications.next()
            if notification is None:
                continue

            spoken = format_notification(notification.title, notification.message)
            log.info("Delivering notification: %s", spoken)
            try:
                audio = daemon.tts.synthesize(spoken, use_case="notification")
                log.info("TTS produced %d bytes for notification", len(audio))
            except Exception:
                log.exception("TTS failed for notification")

        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("Error in proactive delivery loop")


async def ambient_refresh_loop(daemon: VoiceDaemon) -> None:
    """Refresh ambient classification cache in executor thread."""
    while daemon._running:
        try:
            await asyncio.sleep(30)
            await daemon.gate.refresh_ambient_cache()
        except asyncio.CancelledError:
            break
        except Exception:
            log.debug("Ambient refresh error (non-fatal)", exc_info=True)


_WORLD_ROUTING_FLAG = Path.home() / ".cache" / "hapax" / "world-routing-enabled"

# World domain prefixes that the daimonion can act on — affordances from the
# shared registry indexed in the daimonion pipeline. When recruited with
# sufficient score, they surface as proactive speech context enrichment.
_WORLD_DOMAIN_PREFIXES = (
    "env.",
    "body.",
    "studio.",
    "digital.",
    "social.",
    "system.",
    "knowledge.",
    "space.",
    "world.",
)


def _world_routing_enabled() -> bool:
    """Check if world affordance routing is enabled (feature flag, hot-toggleable)."""
    try:
        return _WORLD_ROUTING_FLAG.exists()
    except OSError:
        return False


# Compositional capability prefix set — matches every entry in
# shared/compositional_affordances.py. Used to route pipeline recruitments
# through compositional_consumer.dispatch (Epic 2 Phase B).
_COMPOSITIONAL_PREFIXES: tuple[str, ...] = (
    "cam.hero.",
    "fx.family.",
    "overlay.",
    "youtube.",
    "attention.winner.",
    "stream.mode.",
    "ward.",
    "homage.",
    # Phase 6 of preset-variety-plan (#1168): novelty.shift recruits when
    # the perceptual-distance impingement fires (recency cluster sim
    # ≥0.85). Without this prefix the catalog-prefix wiring test rejects
    # the registered capability.
    "novelty.",
    # Phase 7 of preset-variety-plan (#1176/#1177): five transition.*
    # capabilities recruited per chain change, dispatched to primitives
    # via preset_recruitment_consumer's background-thread runner.
    "transition.",
    # GEM (Graffiti Emphasis Mural) — gem.emphasis.* and
    # gem.composition.* + gem.spawn.* recruited from director impingements;
    # producer at agents/hapax_daimonion/gem_producer.py renders CP437
    # keyframes. Catalog rows are placeholders until lssh-002 (P0 GEM
    # rendering redesign).
    "gem.",
    # Director micromove vocabulary expansion (cc-task
    # `director-moves-richness-expansion`): four parametric / programme
    # families. ``composition.reframe`` reframes the active hero camera;
    # ``pace.tempo_shift`` shifts cadence multipliers; ``mood.tone_pivot``
    # pivots color/warmth/saturation parametrically; ``programme.beat_advance``
    # signals the active programme's narrative beat should advance.
    # Operator constraint: NO presets — these are parametric modulation
    # only; the director never picks a preset family.
    "composition.",
    "pace.",
    "mood.",
    "programme.",
    # Director parametric vocabulary expansion tranche 2:
    # intensity.surge / silence.invitation / chrome.density /
    # attention.refocus recruit bounded parametric envelopes only.
    "intensity.",
    "silence.",
    "chrome.",
    "attention.refocus.",
    "node.add.",
    "node.remove.",
    "node.compose.",
    "node.fork.",
    "node.merge.",
    "node.route.",
)


def _is_compositional_capability(name: str) -> bool:
    """True if ``name`` matches a capability in shared/compositional_affordances.py."""
    if not isinstance(name, str):
        return False
    return any(name.startswith(p) for p in _COMPOSITIONAL_PREFIXES)


_RECRUITMENT_LOG = Path("/dev/shm/hapax-daimonion/recruitment-log.jsonl")
_RECRUITMENT_LOG_MAX_LINES = 500


def _publish_recruitment_log(
    kind: str, capability_name: str, score: float, source: str, imp_narrative: str
) -> None:
    """Append a recruited-capability record to a rolling SHM JSONL.

    Meta-structural audit fix #2+#7 — studio.* and world-domain (env.,
    body., digital., social., system., knowledge., space., world.)
    capabilities were being recruited + Thompson-recorded but otherwise
    silent. Any future consumer (UI, operator notification, automation)
    can tail this file to see what the system is recruiting beyond the
    handful of directly-dispatched families (notification /
    compositional / livestream). Rotated at a soft cap so disk
    pressure stays bounded.
    """
    try:
        import json as _json
        import time as _time

        _RECRUITMENT_LOG.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": _time.time(),
            "kind": kind,
            "capability_name": capability_name,
            "score": float(score),
            "source": source[:40],
            "narrative": (imp_narrative or "")[:160],
        }
        with _RECRUITMENT_LOG.open("a", encoding="utf-8") as f:
            f.write(_json.dumps(record) + "\n")
        try:
            lines = _RECRUITMENT_LOG.read_text(encoding="utf-8").splitlines()
            if len(lines) > _RECRUITMENT_LOG_MAX_LINES:
                trimmed = lines[-_RECRUITMENT_LOG_MAX_LINES:]
                tmp = _RECRUITMENT_LOG.with_suffix(".jsonl.tmp")
                tmp.write_text("\n".join(trimmed) + "\n", encoding="utf-8")
                tmp.replace(_RECRUITMENT_LOG)
        except OSError:
            pass
    except Exception:
        log.debug("recruitment-log append failed", exc_info=True)


def _dispatch_compositional(candidate, imp, daemon) -> None:
    """Dispatch a compositional capability through the compositor's consumer.

    Writes the SHM control file matching the capability family so the
    compositor layer (cam.hero → hero-camera-override.json, etc.) picks
    it up on next tick. The compositor consumer emits action receipts;
    this caller records only command acceptance until readback exists.
    """
    try:
        from agents.studio_compositor.compositional_consumer import (
            RecruitmentRecord,
            dispatch,
        )

        record = RecruitmentRecord(
            name=candidate.capability_name,
            score=float(candidate.combined),
            impingement_narrative=str(imp.content.get("narrative", "")),
            ttl_s=30.0,
            request_id=str(imp.content.get("condition_id") or imp.id),
        )
        family = dispatch(record)
        succeeded = family != "unknown"
        log.info(
            "Compositional dispatch: %s → %s (score=%.2f)",
            candidate.capability_name,
            family,
            candidate.combined,
        )
        if succeeded:
            _record_commanded_no_witness(
                daemon._affordance_pipeline,
                candidate.capability_name,
                source=imp.source,
                command_ref=f"compositional-dispatch:{family}",
                route_ref="route:studio-compositional-consumer",
                public_claim_bearing=True,
                reason="Compositional dispatch accepted a control write, but no compositor readback witness exists yet.",
            )
        else:
            daemon._affordance_pipeline.record_outcome(
                candidate.capability_name,
                success=False,
                context={"source": imp.source, "family": family},
            )
    except Exception:
        log.warning("Compositional dispatch failed", exc_info=True)


# Refractory period after a successful narration emission. Replaces the
# hardcoded 120s rate-limit gate in gates.py with a pipeline-native
# inhibition mechanism.
_NARRATION_REFRACTORY_S: float = 120.0
# During segmented-content roles, the segment IS the content and Hapax
# must fill it with beat-by-beat delivery. 120s refractory would yield
# at most 5 utterances in a 10-minute segment — far too sparse.
_SEGMENT_REFRACTORY_S: float = 20.0
_SEGMENTED_CONTENT_ROLES: frozenset[str] = frozenset(
    {"tier_list", "top_10", "rant", "react", "iceberg", "interview", "lecture"}
)


def _effective_refractory_s(daemon: object) -> float:
    """Return the refractory period based on the active programme role.

    Segmented-content roles get a shorter refractory (20s) because the
    segment needs sustained vocal delivery. Operator-context roles keep
    the 120s baseline so the Bayesian drive pressure — not a timer —
    governs whether narration fires.
    """
    pm = getattr(daemon, "programme_manager", None)
    if pm is None:
        return _NARRATION_REFRACTORY_S
    try:
        active = pm.store.active_programme()
        if active is None:
            return _NARRATION_REFRACTORY_S
        role_value = getattr(active.role, "value", str(active.role))
        if role_value in _SEGMENTED_CONTENT_ROLES:
            return _SEGMENT_REFRACTORY_S
    except Exception:
        pass
    return _NARRATION_REFRACTORY_S


# --- Prepared script delivery state ---
# Tracks which beat of each programme has been delivered to avoid repeating.
_delivered_beats: dict[str, int] = {}  # programme_id → last delivered beat index
_prepped_loaded: bool = False
_DELIVERY_WAIT = "__DELIVERY_WAIT__"  # sentinel: script exists, beat already delivered
PREP_VERBATIM_LEGACY_ENV = "HAPAX_PREP_VERBATIM_LEGACY"


def _ensure_prepped_loaded() -> None:
    """Lazy-load today's prepped scripts into active programmes on first call."""
    global _prepped_loaded
    if _prepped_loaded:
        return
    _prepped_loaded = True
    try:
        from agents.hapax_daimonion.daily_segment_prep import load_prepped_programmes

        prepped = load_prepped_programmes()
        if prepped:
            log.info("delivery: loaded %d prepped segments from disk", len(prepped))
    except Exception:
        log.debug("delivery: failed to load prepped segments", exc_info=True)


def _truthy_env(name: str) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _delivery_mode_value(content: object) -> str:
    mode = getattr(content, "delivery_mode", "live_prior")
    return str(getattr(mode, "value", mode) or "live_prior").strip().lower().replace("-", "_")


def _prepared_verbatim_legacy_allowed(content: object) -> bool:
    return _truthy_env(PREP_VERBATIM_LEGACY_ENV) and _delivery_mode_value(content) == (
        "verbatim_legacy"
    )


def _try_prepared_delivery(context: object) -> str | None:
    """Return _DELIVERY_WAIT only for explicit legacy verbatim playback.

    Live-prior prepared artifacts must enrich composition, not suppress it.
    Direct prepared-script TTS is retained only for explicit legacy
    playback mode with the runtime env gate enabled.
    """
    _ensure_prepped_loaded()

    prog = getattr(context, "programme", None)
    if prog is None:
        return None

    content = getattr(prog, "content", None)
    if content is None:
        return None

    script = getattr(content, "prepared_script", None)
    if not script:
        return None

    if not _prepared_verbatim_legacy_allowed(content):
        return None

    return _DELIVERY_WAIT


async def prepared_playback_loop(daemon: object) -> None:
    """Dedicated legacy playback loop for pre-composed scripts.

    Drives TTS synthesis + audio playback directly, block by block,
    with only a 1s breath between paragraphs. Uses resolve_playback_decision
    for correct PipeWire routing (same as the CPAL autonomous narrative path).

    Eliminates the narrative_drive → affordance_pipeline → recruitment →
    CPAL chain overhead that causes 10-20s gaps between blocks. This path
    is legacy-only: content must request ``delivery_mode=verbatim_legacy``
    and the operator/runtime must set ``HAPAX_PREP_VERBATIM_LEGACY``.
    """
    _ensure_prepped_loaded()

    # Wait for the CPAL runner to be fully initialized
    cpal = None
    for _ in range(30):
        cpal = getattr(daemon, "_cpal_runner", None)
        if cpal is not None and getattr(cpal, "_tts_manager", None) is not None:
            break
        await asyncio.sleep(1.0)

    if cpal is None or getattr(cpal, "_tts_manager", None) is None:
        log.warning("prepared_playback_loop: CPAL runner or TTS not available, exiting")
        return

    log.info(
        "prepared_playback_loop: started — legacy direct TTS gated by %s",
        PREP_VERBATIM_LEGACY_ENV,
    )

    while getattr(daemon, "_running", True):
        try:
            from shared.programme_store import default_store

            store = default_store()
            active = store.active_programme()

            content = getattr(active, "content", None) if active is not None else None
            # Only handle programmes with explicit legacy prepared-script playback.
            if (
                active is None
                or content is None
                or not getattr(content, "prepared_script", None)
                or not _prepared_verbatim_legacy_allowed(content)
            ):
                await asyncio.sleep(2.0)
                continue

            prog_id = str(active.programme_id)
            script = content.prepared_script
            role = getattr(active.role, "value", str(active.role))

            # Resolve route directly via classify + resolve_route, bypassing
            # resolve_playback_decision's audio_safe_for_broadcast gate.
            # The playback loop IS the source of broadcast audio — requiring
            # it to already be playing creates a chicken-and-egg deadlock
            # (voice_output_silent_failure blocks playback → no playback →
            # voice_output_silent_failure). Programme auth is already checked
            # by _programme_authorizes_broadcast above.
            from agents.hapax_daimonion.cpal.destination_channel import (
                classify_destination,
                resolve_route,
            )
            from shared.voice_output_router import (
                media_role_for_route,
                target_for_route,
            )

            synth_imp = type(
                "_SynthImp",
                (),
                {
                    "source": "autonomous_narrative",
                    "content": {
                        "public_broadcast_intent": True,
                        "channel": "broadcast",
                        "programme_id": prog_id,
                    },
                },
            )()

            dest_channel = classify_destination(synth_imp)
            route = resolve_route(dest_channel)
            dest_target = target_for_route(route)
            dest_role = media_role_for_route(route)

            if dest_target is None:
                log.warning(
                    "prepared_playback_loop: no route target for %s, retrying",
                    dest_channel.value,
                )
                await asyncio.sleep(5.0)
                continue

            log.info(
                "prepared_playback_loop: playing %s (%s, %d blocks, target=%s, role=%s)",
                prog_id,
                role,
                len(script),
                dest_target,
                dest_role,
            )

            # ── DURF ward press: front the ward for segment display ──
            import json as _json
            import time as _ward_time
            from pathlib import Path as _Path

            from agents.studio_compositor.ward_properties import (
                WardProperties,
                set_ward_properties,
            )

            _SEGMENT_SHM = _Path("/dev/shm/hapax-compositor/segment-playback.json")
            _SEGMENT_SHM.parent.mkdir(parents=True, exist_ok=True)

            # Collect segment assets for this programme (keyed by block index)
            _seg_assets: dict[int, list[dict]] = {}
            if hasattr(active.content, "segment_assets"):
                for asset in active.content.segment_assets:
                    bi = asset.block_index if asset.block_index is not None else -1
                    _seg_assets.setdefault(bi, []).append(asset.model_dump())

            # Front state → "fronting" (ward is transitioning forward)
            set_ward_properties(
                "durf",
                WardProperties(
                    front_state="fronting",
                    front_t0=_ward_time.monotonic(),
                    z_plane="surface-scrim",
                    alpha=0.92,
                ),
                ttl_s=600.0,
            )
            log.info("prepared_playback_loop: DURF ward → fronting for %s", prog_id)

            # Pre-synthesize blocks: overlap TTS synthesis with playback
            # so there's zero gap between blocks. Synthesize block N+1
            # while block N is playing.
            loop = asyncio.get_running_loop()
            pending_pcm: bytes | None = None
            pending_text: str | None = None
            pending_idx: int = -1

            # Find and synthesize the first non-empty block eagerly
            first_idx = -1
            for i, block in enumerate(script):
                text = block.strip()
                if text:
                    first_idx = i
                    log.info(
                        "prepared_playback_loop: block %d/%d (%d chars) for %s",
                        i + 1,
                        len(script),
                        len(text),
                        prog_id,
                    )
                    try:
                        pending_pcm = await loop.run_in_executor(
                            None, cpal._tts_manager.synthesize, text, "proactive"
                        )
                        pending_text = text
                        pending_idx = i
                    except Exception:
                        log.warning(
                            "prepared_playback_loop: TTS failed block %d", i + 1, exc_info=True
                        )
                    break

            if pending_pcm is None:
                log.warning("prepared_playback_loop: no synthesizable blocks in %s", prog_id)
                await asyncio.sleep(2.0)
                continue

            # Play each block while synthesizing the next
            for idx in range(first_idx, len(script)):
                if not getattr(daemon, "_running", True):
                    return

                if idx > pending_idx:
                    # This block hasn't been pre-synthesized yet (edge case)
                    text = script[idx].strip()
                    if not text:
                        continue
                    log.info(
                        "prepared_playback_loop: block %d/%d (%d chars) for %s",
                        idx + 1,
                        len(script),
                        len(text),
                        prog_id,
                    )
                    try:
                        pending_pcm = await loop.run_in_executor(
                            None, cpal._tts_manager.synthesize, text, "proactive"
                        )
                        pending_text = text
                    except Exception:
                        log.warning(
                            "prepared_playback_loop: TTS failed block %d", idx + 1, exc_info=True
                        )
                        continue
                    if not pending_pcm:
                        continue

                current_pcm = pending_pcm
                current_text = pending_text or ""
                pending_pcm = None
                pending_text = None

                # Start synthesizing the NEXT block in background
                next_synth_task = None
                next_idx = None
                for ni in range(idx + 1, len(script)):
                    nt = script[ni].strip()
                    if nt:
                        next_idx = ni
                        log.info(
                            "prepared_playback_loop: block %d/%d (%d chars) for %s",
                            ni + 1,
                            len(script),
                            len(nt),
                            prog_id,
                        )
                        next_synth_task = loop.run_in_executor(
                            None, cpal._tts_manager.synthesize, nt, "proactive"
                        )
                        break

                # ── Publish segment state + ward lifecycle at sentence tempo ──
                _block_assets = _seg_assets.get(idx, _seg_assets.get(-1, []))
                _seg_state = {
                    "programme_id": prog_id,
                    "role": role,
                    "block_index": idx,
                    "block_count": len(script),
                    "block_text": current_text[:300],
                    "assets": _block_assets,
                    "front_state": "fronted",
                    "updated_at": _ward_time.time(),
                }
                try:
                    _tmp = _SEGMENT_SHM.with_suffix(".json.tmp")
                    _tmp.write_text(_json.dumps(_seg_state), encoding="utf-8")
                    _tmp.replace(_SEGMENT_SHM)
                except OSError:
                    log.debug("prepared_playback_loop: SHM write failed", exc_info=True)

                # Front state → "fronted" (content settled, being narrated)
                set_ward_properties(
                    "durf",
                    WardProperties(
                        front_state="fronted",
                        front_t0=_ward_time.monotonic(),
                        z_plane="surface-scrim",
                        alpha=0.92,
                    ),
                    ttl_s=120.0,
                )

                # Play current block — bypass speech_lock so CPAL impingements
                # don't insert 30-40s gaps between blocks.
                try:
                    if cpal._pipeline and hasattr(cpal._pipeline, "_recent_tts_texts"):
                        import time as _time

                        cpal._pipeline._recent_tts_texts.append(
                            (_time.monotonic(), current_text.lower().strip().rstrip(".,!?"))
                        )
                    cpal._buffer.set_speaking(True)
                    if cpal._echo_canceller:
                        cpal._echo_canceller.feed_reference(current_pcm)
                    try:
                        from functools import partial

                        from agents.hapax_daimonion.pw_audio_output import play_pcm

                        await loop.run_in_executor(
                            None,
                            partial(play_pcm, current_pcm, 24000, 1, dest_target, dest_role),
                        )
                    finally:
                        cpal._buffer.set_speaking(False)
                except Exception:
                    log.warning(
                        "prepared_playback_loop: playback failed block %d", idx + 1, exc_info=True
                    )

                # Collect pre-synthesized next block
                if next_synth_task is not None and next_idx is not None:
                    try:
                        pending_pcm = await next_synth_task
                        pending_text = script[next_idx].strip()
                        pending_idx = next_idx
                    except Exception:
                        log.warning(
                            "prepared_playback_loop: TTS failed block %d",
                            next_idx + 1,
                            exc_info=True,
                        )
                        pending_pcm = None

                # Between blocks: "fronting" (next block incoming)
                set_ward_properties(
                    "durf",
                    WardProperties(
                        front_state="fronting",
                        front_t0=_ward_time.monotonic(),
                        z_plane="surface-scrim",
                        alpha=0.88,
                    ),
                    ttl_s=120.0,
                )

                # Brief breath between paragraphs
                await asyncio.sleep(0.5)

            # ── DURF ward retirement: "retiring" → "integrated" ──
            set_ward_properties(
                "durf",
                WardProperties(
                    front_state="retiring",
                    front_t0=_ward_time.monotonic(),
                    z_plane="surface-scrim",
                    alpha=0.7,
                ),
                ttl_s=15.0,
            )
            log.info("prepared_playback_loop: DURF ward → retiring for %s", prog_id)

            # Clean up SHM segment state
            try:
                _SEGMENT_SHM.unlink(missing_ok=True)
            except OSError:
                pass

            # All blocks played — deactivate, auto-cycle picks next
            try:
                store.deactivate(prog_id)
                log.info("prepared_playback_loop: completed %s (%d blocks)", prog_id, len(script))
            except Exception:
                log.debug(
                    "prepared_playback_loop: deactivate failed for %s", prog_id, exc_info=True
                )

            # Post-delivery self-evaluation → impingement
            # Complement to prep-time self-eval: this one measures what
            # was actually delivered, not just what was composed.
            try:
                _bus = _Path("/dev/shm/hapax-dmn/impingements.jsonl")
                if _bus.parent.exists():
                    total_chars = sum(len(b) for b in script if b.strip())
                    delivered_count = sum(1 for b in script if b.strip())
                    avg_chars = total_chars / max(delivered_count, 1)
                    _eval_imp = {
                        "source": "self_evaluation.segment_delivery",
                        "programme_id": prog_id,
                        "role": role,
                        "evaluation": {
                            "blocks_delivered": delivered_count,
                            "total_chars_delivered": total_chars,
                            "avg_chars_per_block": round(avg_chars),
                        },
                        "ts": _ward_time.time(),
                    }
                    with _bus.open("a") as _f:
                        _f.write(_json.dumps(_eval_imp) + "\n")
                    log.info(
                        "self-eval delivery: %s blocks=%d avg_chars=%.0f",
                        prog_id,
                        delivered_count,
                        avg_chars,
                    )
            except Exception:
                log.debug("self-eval delivery: emission failed", exc_info=True)

            # Inter-programme gap — DURF returns to integrated
            await asyncio.sleep(2.0)
            set_ward_properties(
                "durf",
                WardProperties(front_state="integrated", front_t0=_ward_time.monotonic()),
                ttl_s=10.0,
            )

        except Exception:
            log.warning("prepared_playback_loop: tick failed", exc_info=True)
            await asyncio.sleep(5.0)


def _dispatch_autonomous_narration(daemon, imp, candidate) -> None:
    """Dispatch recruited autonomous narration through compose → emit.

    Called by ``impingement_consumer_loop`` when the AffordancePipeline
    recruits ``narration.autonomous_first_system``. This replaces the
    standalone ``loop.py`` + ``gates.py`` polling architecture — narration
    now fires because the pipeline recruited it via cosine similarity,
    not because a timer ticked and 5 hardcoded gates all returned True.

    After successful emission, ``add_inhibition()`` enforces a refractory
    period (120s) so cadence emerges from the pipeline's base_level decay
    + inhibition mechanism rather than a hardcoded interval.
    """
    try:
        if _inhibit_narration_drive_if_missing_evidence(daemon, imp, candidate):
            return

        from agents.hapax_daimonion.autonomous_narrative import compose, emit
        from agents.hapax_daimonion.autonomous_narrative.state_readers import assemble_context

        context = assemble_context(daemon)
        programme_id = _programme_id_from_context(context)
        referent = _pick_referent_for_narration(programme_id)

        # --- Delivery mode: use pre-composed script if available ---
        narrative = _try_prepared_delivery(context)
        if narrative is _DELIVERY_WAIT:
            # Script exists, beat already delivered — skip entirely.
            log.debug("delivery: beat already delivered, waiting for transition")
            return
        if narrative is None:
            # Fallback: live composition (degraded mode)
            narrative = compose.compose_narrative(context, operator_referent=referent)
        if narrative is None:
            emit.record_metric("llm_silent")
            daemon._affordance_pipeline.record_outcome(
                candidate.capability_name,
                success=False,
                context={"source": imp.source, "reason": "llm_silent"},
            )
            return

        now = time.time()
        impulse_id = _narration_impulse_id_for_dispatch(imp, candidate)
        from shared.narration_triad import (
            NarrationTriadLedger,
            build_autonomous_narration_triad,
            speech_event_id_for_utterance,
        )

        speech_event_id = speech_event_id_for_utterance(
            impulse_id=impulse_id,
            text=narrative,
            now=now,
        )
        triad = build_autonomous_narration_triad(
            text=narrative,
            context=context,
            impulse_id=impulse_id,
            speech_event_id=speech_event_id,
            candidate_name=getattr(
                candidate, "capability_name", "narration.autonomous_first_system"
            ),
            now=now,
        )
        triad_ledger = NarrationTriadLedger()
        triad_ledger.append(triad)
        emit_result = emit.emit_narrative(
            narrative,
            programme_id=programme_id,
            operator_referent=referent,
            impulse_id=impulse_id,
            speech_event_id=speech_event_id,
            triad_ids=(triad.triad_id,),
            now=now,
        )
        try:
            from agents.hapax_daimonion.voice_output_witness import (
                record_composed_autonomous_narrative,
            )

            record_composed_autonomous_narrative(
                text=narrative,
                impingement=imp,
                candidate=candidate,
                emit_status="emitted" if emit_result else "emit_failed",
                impulse_id=impulse_id,
                triad_ids=(triad.triad_id,),
                now=now,
            )
        except Exception:
            log.debug("voice-output witness compose update failed", exc_info=True)
        if emit_result:
            partial_success = bool(getattr(emit_result, "partial_success", False))
            emit.record_metric("partial_success" if partial_success else "allow")
            daemon._affordance_pipeline.record_outcome(
                candidate.capability_name,
                success=triad.learning_update_allowed,
                context={
                    "source": imp.source,
                    "programme_id": programme_id or "",
                    "stimmung": getattr(context, "stimmung_tone", ""),
                    "triad_id": triad.triad_id,
                    "semantic_status": triad.status,
                    "learning_update_allowed": triad.learning_update_allowed,
                },
            )
            # Refractory inhibition — pipeline-native replacement for the
            # hardcoded 120s rate-limit gate. Prepared delivery skips
            # refractory entirely so blocks flow as fast as the narrative
            # drive emits (~30s). Live compose keeps 120s.
            _is_prepped = programme_id and programme_id in _delivered_beats
            if not _is_prepped:
                daemon._affordance_pipeline.add_inhibition(
                    imp, duration_s=_effective_refractory_s(daemon)
                )
            _publish_recruitment_log(
                "narration",
                candidate.capability_name,
                candidate.combined,
                imp.source,
                narrative[:160],
            )
            # Beat transitions are now checked in the programme_manager_loop
            # at 1 Hz, independent of narration cadence. No duplicate check
            # needed here.

            log.info(
                "Autonomous narration emitted via recruitment (score=%.2f, source=%s)",
                candidate.combined,
                imp.source[:40],
            )
        else:
            triad_ledger.append_status_update(
                triad,
                status="failed",
                closure_refs=[f"speech_event:{speech_event_id}:write_failed"],
                blocked_reasons=["autonomous_narrative_emit_write_failed"],
                now=now,
            )
            emit.record_metric("write_failed")
            daemon._affordance_pipeline.record_outcome(
                candidate.capability_name,
                success=False,
                context={
                    "source": imp.source,
                    "reason": "write_failed",
                    "triad_id": triad.triad_id,
                    "semantic_status": "failed",
                },
            )
    except Exception:
        log.warning("Autonomous narration dispatch failed", exc_info=True)


def _is_narration_drive_impingement(imp: object) -> bool:
    """True when the endogenous drive explicitly asks to recruit narration."""
    content = getattr(imp, "content", {}) or {}
    return (
        getattr(imp, "source", "") == "endogenous.narrative_drive"
        and isinstance(content, dict)
        and content.get("drive") == "narration"
    )


def _inhibit_narration_drive_if_missing_evidence(
    daemon: object, imp: object, candidate: object
) -> bool:
    """Fail closed when a conative speech impulse lacks execution evidence."""
    if not _is_narration_drive_impingement(imp):
        return False
    try:
        from shared.conative_impingement import (
            action_tendency_impulse_from_impingement,
            execution_inhibition_reasons,
        )

        impulse = action_tendency_impulse_from_impingement(
            imp,
            default_execution_refs=False,
        )
        reasons = execution_inhibition_reasons(impulse)
        if not reasons:
            return False
        reason = "execution_evidence_missing:" + ",".join(reasons)
        fallback_dispatched = bool(
            (getattr(candidate, "payload", {}) or {}).get("capability_contract_evidence")
            == "typed_narration_drive"
        )
        from agents.hapax_daimonion.voice_output_witness import record_drop, record_narration_drive

        record_narration_drive(
            imp,
            fallback_dispatched=fallback_dispatched,
            duplicate_prevented=False,
            terminal_state="inhibited",
            terminal_reason=reason,
        )
        record_drop(
            reason=reason,
            source="autonomous_narrative",
            impulse_id=impulse.impulse_id,
            terminal_state="inhibited",
        )
        pipeline = getattr(daemon, "_affordance_pipeline", None)
        if pipeline is not None:
            pipeline.record_outcome(
                getattr(candidate, "capability_name", "narration.autonomous_first_system"),
                success=False,
                context={"source": getattr(imp, "source", ""), "reason": reason},
            )
        return True
    except Exception:
        log.warning("conative narration evidence inhibition failed", exc_info=True)
        return False


def _narration_drive_fallback_candidate(imp: object) -> Any:
    """Build the narration capability candidate implied by a narration drive.

    The narrative drive exists to emit a semantic recruitment cue for
    ``narration.autonomous_first_system``. If embedding retrieval misses that
    affordance, use the typed drive as the witness that the narration capability
    should be considered, then let the normal compose -> emit path own speech.
    """
    strength = getattr(imp, "strength", 0.3)
    try:
        combined = float(strength)
    except (TypeError, ValueError):
        combined = 0.3
    combined = min(1.0, max(0.3, combined))
    from agents.hapax_daimonion.voice_output_witness import build_narration_impulse

    impulse = build_narration_impulse(
        imp,
        fallback_dispatched=True,
        duplicate_prevented=False,
    )
    return type(
        "NarrationDriveCandidate",
        (),
        {
            "capability_name": "narration.autonomous_first_system",
            "combined": combined,
            "similarity": combined,
            "payload": {
                "source": "endogenous.narrative_drive",
                "drive": "narration",
                "capability_contract_evidence": "typed_narration_drive",
                "impulse_id": impulse["impulse_id"],
                "content_summary": impulse["content_summary"],
                "evidence_refs": impulse["evidence_refs"],
                "action_tendency": impulse["action_tendency"],
                "speech_act_candidate": impulse["speech_act_candidate"],
                "strength_posterior": impulse["strength_posterior"],
                "role_context": impulse["role_context"],
                "inhibition_policy": impulse["inhibition_policy"],
                "wcs_snapshot_ref": impulse["wcs_snapshot_ref"],
                "learning_policy": impulse["learning_policy"],
            },
        },
    )()


def _narration_impulse_id_for_dispatch(imp: object, candidate: object) -> str | None:
    payload = getattr(candidate, "payload", {}) or {}
    if isinstance(payload, dict) and payload.get("impulse_id"):
        return str(payload["impulse_id"])
    if not _is_narration_drive_impingement(imp):
        return None
    from agents.hapax_daimonion.voice_output_witness import narration_impulse_id

    return narration_impulse_id(imp)


def _dispatch_narration_drive_fallback_if_needed(
    daemon: object, imp: object, candidates: list[object]
) -> bool:
    """Dispatch explicit narration drives when vector recruitment misses them."""
    if not _is_narration_drive_impingement(imp):
        return False
    recruited = any(
        getattr(c, "capability_name", "") == "narration.autonomous_first_system"
        and float(getattr(c, "combined", 0.0)) >= 0.3
        for c in candidates
    )
    if recruited:
        try:
            from agents.hapax_daimonion.voice_output_witness import record_narration_drive

            record_narration_drive(
                imp,
                fallback_dispatched=False,
                duplicate_prevented=True,
                terminal_reason="normal_recruitment_already_selected",
            )
        except Exception:
            log.debug("voice-output witness drive update failed", exc_info=True)
        return False

    candidate = _narration_drive_fallback_candidate(imp)
    try:
        from agents.hapax_daimonion.voice_output_witness import record_narration_drive

        record_narration_drive(
            imp,
            fallback_dispatched=True,
            duplicate_prevented=False,
            terminal_reason="fallback_recruited_autonomous_narration",
        )
    except Exception:
        log.debug("voice-output witness drive update failed", exc_info=True)
    _dispatch_autonomous_narration(daemon, imp, candidate)
    return True


def _programme_id_from_context(context) -> str | None:
    """Extract programme_id from a NarrativeContext."""
    prog = getattr(context, "programme", None)
    if prog is None:
        return None
    pid = getattr(prog, "programme_id", None)
    return str(pid) if pid is not None else None


def _pick_referent_for_narration(programme_id: str | None) -> str | None:
    """Pick operator referent for narration — mirrors loop.py logic."""
    if programme_id is None:
        return None
    try:
        from shared.operator_referent import OperatorReferentPicker  # noqa: PLC0415

        return OperatorReferentPicker.pick_for_vod_segment(f"narrative-{programme_id}")
    except (ImportError, Exception):
        return None


async def impingement_consumer_loop(daemon: VoiceDaemon) -> None:
    """Poll DMN impingements and dispatch recruited affordances.

    Owns everything the affordance pipeline recruits EXCEPT spontaneous
    speech — speech surfacing belongs to ``CpalRunner.process_impingement``
    (gated by the adapter's ``should_surface``). Both loops read the same
    JSONL file through independent cursor paths so each impingement is
    seen by both without racing.

    Dispatched effects:

    - ``system.notify_operator`` → ``activate_notification(...)`` and
      Thompson outcome recording.
    - ``studio.*`` control affordances (excluding the always-streaming
      perception feeds) → Thompson outcome recording. Actual invocation
      is deferred to whoever consumes the learned priors.
    - World-domain affordances (``env.``, ``body.``, ``studio.``,
      ``digital.``, ``social.``, ``system.``, ``knowledge.``, ``space.``,
      ``world.``) → feature-flagged Thompson outcome recording.
    - ``system_awareness`` → ``can_resolve()`` gate + ``activate()``.
    - ``capability_discovery`` → discovery handler extract/search/propose.
    - Cross-modal coordination via ``ExpressionCoordinator.coordinate``
      when more than one non-speech capability is recruited.

    Apperception cascade is NOT handled here — it is owned by
    ``shared.apperception_tick.ApperceptionTick`` inside the visual
    layer aggregator. ``speech_production`` recruitment is skipped here
    to avoid double-firing with CPAL's spontaneous speech path.
    """
    consumer = ImpingementConsumer(
        Path("/dev/shm/hapax-dmn/impingements.jsonl"),
        cursor_path=Path.home()
        / ".cache"
        / "hapax"
        / "impingement-cursor-daimonion-affordance.txt",
    )

    # Vocal chain decay timer — elapsed real time since the last `decay()` call.
    # Ticked on a monotonic clock inside the main loop (1 Hz target). The
    # VocalChainCapability was previously dead code: instantiated in
    # init_pipeline but never activated. Phase 1 wires both halves:
    #   (a) `activate_from_impingement(imp)` on every impingement below
    #   (b) `decay(elapsed_s)` on a 1 Hz cadence in this loop
    import time as _voc_time

    _last_vocal_decay_monotonic = _voc_time.monotonic()
    _VOCAL_DECAY_INTERVAL_S = 1.0

    while daemon._running:
        try:
            _world_enabled = _world_routing_enabled()  # cache per poll cycle

            # Vocal chain decay tick — runs at most once per second regardless of
            # impingement volume. Skip entirely if MIDI output never opened
            # so we don't churn counters
            # with no-op CC writes.
            _now_mono = _voc_time.monotonic()
            if _now_mono - _last_vocal_decay_monotonic >= _VOCAL_DECAY_INTERVAL_S:
                _elapsed = _now_mono - _last_vocal_decay_monotonic
                _last_vocal_decay_monotonic = _now_mono
                _vocal_chain = getattr(daemon, "_vocal_chain", None)
                if (
                    _vocal_chain is not None
                    and getattr(_vocal_chain._midi, "is_open", lambda: True)()
                ):
                    try:
                        _vocal_chain.decay(_elapsed)
                    except Exception:
                        log.warning("Vocal chain decay failed", exc_info=True)

            for imp in consumer.read_new():
                # Vocal chain activation — drives Evil Pet + S-4 CC params
                # from impingement narratives. Reads the capability's 9-dim
                # table (vocal_chain.DIMENSIONS) and emits MIDI CCs via the
                # MIDI port configured in DaimonionConfig.
                # Fail-open: capability may be absent if init_pipeline is
                # exercising a partial daemon (tests, etc.).
                _vocal_chain = getattr(daemon, "_vocal_chain", None)
                if (
                    _vocal_chain is not None
                    and getattr(_vocal_chain._midi, "is_open", lambda: True)()
                ):
                    try:
                        _vocal_chain.activate_from_impingement(imp)
                    except Exception:
                        log.warning("Vocal chain activation failed", exc_info=True)

                try:
                    from shared.audio_performance_context import build_performance_context

                    _perf_ctx = build_performance_context()
                    candidates = await asyncio.to_thread(
                        daemon._affordance_pipeline.select, imp, context=_perf_ctx
                    )
                    for c in candidates:
                        # --- Notification dispatch ---
                        if c.capability_name == "system.notify_operator":
                            if c.combined >= 0.4:
                                from agents.notification_capability import (
                                    activate_notification,
                                )

                                narrative = imp.content.get("narrative", imp.source)
                                material = imp.content.get("material", "void")
                                activate_notification(narrative, c.combined, material)
                                _record_commanded_no_witness(
                                    daemon._affordance_pipeline,
                                    c.capability_name,
                                    source=imp.source,
                                    command_ref="notification:activate",
                                    route_ref="route:notification-capability",
                                    reason="Notification dispatch was requested, but no delivery/readback witness exists yet.",
                                )
                            continue

                        # --- Compositional capability dispatch (Epic 2 Phase B) ---
                        # Compositor-origin impingements ("studio_compositor.
                        # director.compositional") recruit compositional
                        # capabilities from shared/compositional_affordances.py
                        # (cam.hero.* / fx.family.* / overlay.* / youtube.* /
                        # attention.winner.* / stream.mode.*.transition). These
                        # resolve via agents.studio_compositor.
                        # compositional_consumer.dispatch, which writes the SHM
                        # control files the compositor layer consumes.
                        if _is_compositional_capability(c.capability_name):
                            if c.combined >= 0.3:
                                _dispatch_compositional(c, imp, daemon)
                            continue

                        # --- Livestream toggle (cross-process to compositor) ---
                        # Special-cased before the generic studio.* branch:
                        # daimonion runs separately from the compositor, so
                        # dispatch writes the control file the compositor
                        # polls. Consent gating is upstream in the pipeline.
                        if c.capability_name == "studio.toggle_livestream":
                            if c.combined >= 0.3:
                                if _write_livestream_control(imp, c):
                                    _record_commanded_no_witness(
                                        daemon._affordance_pipeline,
                                        c.capability_name,
                                        source=imp.source,
                                        command_ref="shm:hapax-compositor/livestream-control.json",
                                        route_ref="route:studio-livestream-control",
                                        public_claim_bearing=True,
                                        reason="Livestream control file was staged, but egress/readback has not confirmed application.",
                                    )
                                else:
                                    daemon._affordance_pipeline.record_outcome(
                                        c.capability_name,
                                        success=False,
                                        context={"source": imp.source, "reason": "write_failed"},
                                    )
                            continue

                        # --- Autonomous narration dispatch (de-expert-system) ---
                        # Replaces the standalone loop.py + gates.py polling
                        # architecture. Narration now fires because the
                        # pipeline recruited it, not because a timer ticked.
                        # Cadence emerges from base_level decay + refractory
                        # inhibition (120s) rather than hardcoded gates.
                        if c.capability_name == "narration.autonomous_first_system":
                            if c.combined >= 0.3:
                                _dispatch_autonomous_narration(daemon, imp, c)
                            continue

                        # --- Studio control dispatch ---
                        if c.capability_name.startswith("studio.") and c.capability_name not in (
                            "studio.midi_beat",
                            "studio.midi_tempo",
                            "studio.mixer_energy",
                            "studio.mixer_bass",
                            "studio.mixer_mid",
                            "studio.mixer_high",
                            "studio.desk_activity",
                            "studio.desk_gesture",
                            "studio.speech_emotion",
                            "studio.music_genre",
                            "studio.flow_state",
                            "studio.audio_events",
                            "studio.ambient_noise",
                        ):
                            if c.combined >= 0.3:
                                log.info(
                                    "Studio control recruited: %s (score=%.2f, source=%s)",
                                    c.capability_name,
                                    c.combined,
                                    imp.source[:30],
                                )
                                _publish_recruitment_log(
                                    "studio",
                                    c.capability_name,
                                    c.combined,
                                    imp.source,
                                    str(imp.content.get("narrative", "")),
                                )
                                _record_commanded_no_witness(
                                    daemon._affordance_pipeline,
                                    c.capability_name,
                                    source=imp.source,
                                    command_ref=f"recruitment-log:studio:{c.capability_name}",
                                    route_ref="route:studio-recruitment-log",
                                    public_claim_bearing=True,
                                    reason="Studio affordance was logged as recruited, but no action/readback receipt exists yet.",
                                )
                            continue

                        # --- World domain routing (feature-flagged) ---
                        if (
                            any(c.capability_name.startswith(p) for p in _WORLD_DOMAIN_PREFIXES)
                            and _world_enabled
                        ):
                            if c.combined >= 0.3:
                                log.info(
                                    "World affordance recruited: %s (score=%.2f, source=%s)",
                                    c.capability_name,
                                    c.combined,
                                    imp.source[:30],
                                )
                                _publish_recruitment_log(
                                    "world",
                                    c.capability_name,
                                    c.combined,
                                    imp.source,
                                    str(imp.content.get("narrative", "")),
                                )
                                _record_commanded_no_witness(
                                    daemon._affordance_pipeline,
                                    c.capability_name,
                                    source=imp.source,
                                    command_ref=f"recruitment-log:world:{c.capability_name}",
                                    route_ref="route:world-domain-recruitment-log",
                                    public_claim_bearing=True,
                                    reason="World-domain affordance was logged as recruited, but no WCS/source/readback witness exists yet.",
                                )
                            continue

                        # Phase 6 (D-28): F5 short-circuit retired. Pipeline-
                        # scored speech now flows through the normal recruitment
                        # path so Thompson learning sees speech_production
                        # activations. Surfacing decisions still belong to CPAL
                        # (via the impingement adapter's programme-aware
                        # threshold + ALWAYS_SURFACE_AT override) — the
                        # capability's `activate()` only queues the impingement
                        # to a bounded buffer; it does not call TTS directly.
                        # Defensive: speech_production may still be skipped only
                        # when the daemon has no _speech_production attached
                        # (mid-rebuild state). All other code paths feed it.
                        if c.capability_name == "speech_production" and not hasattr(
                            daemon, "_speech_production"
                        ):
                            continue

                        if c.capability_name == "system_awareness":
                            if hasattr(daemon, "_system_awareness"):
                                # can_resolve() is an intentional secondary gate, NOT a
                                # pipeline bypass. The pipeline selected by embedding
                                # similarity; can_resolve() checks stimmung stance + 300s
                                # cooldown that the pipeline cannot encode.
                                score = daemon._system_awareness.can_resolve(imp)
                                if score > 0:
                                    daemon._system_awareness.activate(imp, score)
                        elif c.capability_name == "capability_discovery":
                            if hasattr(daemon, "_discovery_handler"):
                                intent = daemon._discovery_handler.extract_intent(imp)
                                results = daemon._discovery_handler.search(intent)
                                if results:
                                    daemon._discovery_handler.propose(results)

                    _dispatch_narration_drive_fallback_if_needed(daemon, imp, candidates)

                    # Cross-modal coordination: distribute fragment to recruited
                    # non-speech capabilities. CPAL owns the auditory modality, so
                    # we also exclude it when dispatching activations.
                    if len(candidates) > 1 and hasattr(daemon, "_expression_coordinator"):
                        recruited_pairs = [
                            (
                                c.capability_name,
                                getattr(daemon, f"_{c.capability_name}", None),
                            )
                            for c in candidates
                            if c.capability_name != "speech_production"
                        ]
                        recruited_pairs = [
                            (n, cap) for n, cap in recruited_pairs if cap is not None
                        ]
                        if len(recruited_pairs) > 1:
                            activations = daemon._expression_coordinator.coordinate(
                                imp.content, recruited_pairs
                            )
                            for act in activations:
                                modality = act.get("modality", "unknown")
                                cap_name = act.get("capability")
                                if modality in ("textual", "notification"):
                                    cap_obj = getattr(daemon, f"_{cap_name}", None)
                                    if cap_obj is not None and hasattr(cap_obj, "activate"):
                                        try:
                                            cap_obj.activate(imp, imp.strength)
                                            log.info(
                                                "Cross-modal dispatch: %s (%s)",
                                                cap_name,
                                                modality,
                                            )
                                        except Exception:
                                            log.debug(
                                                "Cross-modal dispatch failed: %s",
                                                cap_name,
                                                exc_info=True,
                                            )
                            if activations:
                                log.info(
                                    "Cross-modal coordination: %d modalities for %s",
                                    len(activations),
                                    imp.content.get("narrative", "")[:40],
                                )
                except Exception:
                    log.debug("Impingement dispatch error (non-fatal)", exc_info=True)
        except Exception:
            log.debug("Impingement consumer error (non-fatal)", exc_info=True)

        await asyncio.sleep(0.5)


def signal_tpn_active(active: bool) -> None:
    """Signal DMN that TPN (voice) is actively processing."""
    try:
        flag = Path("/dev/shm/hapax-dmn/tpn_active")
        flag.write_text("1" if active else "0", encoding="utf-8")
    except OSError:
        pass


async def ntfy_callback(daemon: VoiceDaemon, notification) -> None:
    """Handle incoming ntfy notification."""
    daemon.notifications.enqueue(notification)
    log.info(
        "Queued ntfy notification: %s (priority=%s)",
        notification.title,
        notification.priority,
    )


# --- Operator sidechat consumer (task #132) -------------------------------
#
# Private, LOCAL-ONLY channel for the operator to whisper
# notes/commands to Hapax during a livestream, separate from public twitch
# chat. Each sidechat message is enqueued as an Impingement with
# PATTERN_MATCH type, priority-boosted strength, and a channel="sidechat"
# tag so downstream consumers can attribute-route it.
#
# Cursor file: `sidechat-cursor-daimonion.txt`. Atomic tmp+rename, identical
# pattern to `impingement-cursor-daimonion-*.txt`.
#
# Privacy: the sidechat JSONL is NEVER copied to twitch/YouTube/chat
# surfaces — see `shared.operator_sidechat` module docstring and the
# `tests/shared/test_operator_sidechat.py::TestEgressPin` regression pin.

_SIDECHAT_CURSOR_PATH = Path.home() / ".cache" / "hapax" / "sidechat-cursor-daimonion.txt"

# Priority boost relative to an "ordinary" impingement. The operator
# directly whispering something is a strong signal — they are present,
# engaged, and explicit — so we bias strength upward. The +2 in the spec
# is on a 1..N priority ladder; we translate to a strength multiplier
# that keeps the final value in the 0..1 range.
_SIDECHAT_STRENGTH = 0.9


def _load_sidechat_cursor() -> float:
    """Load last-seen ts cursor, or 0.0 on missing / malformed file."""
    try:
        raw = _SIDECHAT_CURSOR_PATH.read_text(encoding="utf-8").strip()
        return float(raw) if raw else 0.0
    except (FileNotFoundError, ValueError, OSError):
        return 0.0


def _save_sidechat_cursor(ts: float) -> None:
    """Persist cursor atomically (tmp + rename)."""
    try:
        _SIDECHAT_CURSOR_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _SIDECHAT_CURSOR_PATH.with_suffix(".txt.tmp")
        tmp.write_text(f"{ts}", encoding="utf-8")
        tmp.replace(_SIDECHAT_CURSOR_PATH)
    except OSError:
        log.debug("Failed to persist sidechat cursor", exc_info=True)


async def sidechat_consumer_loop(daemon: VoiceDaemon) -> None:
    """Tail the operator sidechat JSONL and enqueue each line as an Impingement.

    Messages appear in ``/dev/shm/hapax-compositor/operator-sidechat.jsonl``
    via :func:`shared.operator_sidechat.append_sidechat`. Each parsed
    message becomes a PATTERN_MATCH impingement with:

    * ``source = "operator.sidechat"``
    * ``strength = _SIDECHAT_STRENGTH`` (priority-boosted)
    * ``content = {"narrative": <text>, "channel": "sidechat",
       "msg_id": <id>, "role": <role>}``
    * ``interrupt_token = "operator_sidechat"`` so the affordance
      pipeline's pattern-match branch can lift it above background noise.

    The cursor is a last-seen ``ts`` (float), persisted at
    ``~/.cache/hapax/sidechat-cursor-daimonion.txt`` so a daemon restart
    doesn't replay the whole backlog. We advance after each successfully
    enqueued message, not at end-of-batch, so a crash mid-batch
    re-processes only the unhandled tail.
    """
    # Task #144: import the shared-link writer lazily so
    # run_loops_aux stays importable in test environments that don't
    # have the compositor package on the path.
    from agents.studio_compositor.text_repo_commands import apply_sidechat_command
    from agents.studio_compositor.yt_shared_links import (
        append_shared_link,
        parse_link_command,
    )
    from shared.impingement import Impingement, ImpingementType
    from shared.operator_sidechat import SIDECHAT_PATH, tail_sidechat

    cursor_ts = _load_sidechat_cursor()
    log.info(
        "Sidechat consumer started (cursor_ts=%.3f, path=%s)",
        cursor_ts,
        SIDECHAT_PATH,
    )

    while daemon._running:
        try:
            new_msgs = list(tail_sidechat(since_ts=cursor_ts))
            for msg in new_msgs:
                # Task #144: recognize `link <url>` and stage the URL
                # for the YouTube description syncer. The message still
                # flows through the affordance pipeline so the operator
                # sees the same recruitment/observability as any other
                # sidechat utterance — the link capture is additive.
                link_url = parse_link_command(msg.text)
                if link_url is not None:
                    try:
                        append_shared_link(link_url, source="sidechat", ts=msg.ts)
                        log.info(
                            "Sidechat link captured for YouTube description: %s",
                            link_url[:120],
                        )
                    except (ValueError, OSError):
                        log.debug("Sidechat link capture failed (non-fatal)", exc_info=True)

                # Task #160: recognize `point-at-hardm <cell>` and emit
                # a narrative director cue. The message still flows
                # through the affordance pipeline so the operator sees
                # the same recruitment trail as any other sidechat line.
                try:
                    from agents.studio_compositor.hardm_source import (
                        parse_point_at_hardm,
                        write_operator_cue,
                    )

                    hardm_cell = parse_point_at_hardm(msg.text)
                    if hardm_cell is not None:
                        write_operator_cue(hardm_cell)
                        try:
                            from shared.director_observability import (
                                emit_hardm_operator_cue,
                            )

                            emit_hardm_operator_cue(hardm_cell)
                        except Exception:
                            pass
                        log.info(
                            "Sidechat point-at-hardm cue: cell=%d",
                            hardm_cell,
                        )
                except Exception:
                    log.debug("point-at-hardm parse failed (non-fatal)", exc_info=True)

                # Task #126: `add-text <body>` / `rotate-text` commands
                # dispatch into the Hapax-managed Pango text repo. Still
                # flows through the affordance pipeline so the operator
                # retains the same observability as any other sidechat
                # utterance — the repo write is additive.
                try:
                    apply_sidechat_command(msg.text)
                except Exception:
                    log.debug("Sidechat text-repo command failed (non-fatal)", exc_info=True)

                imp = Impingement(
                    timestamp=msg.ts,
                    source="operator.sidechat",
                    type=ImpingementType.PATTERN_MATCH,
                    strength=_SIDECHAT_STRENGTH,
                    content={
                        "narrative": msg.text,
                        "channel": "sidechat",
                        "msg_id": msg.msg_id,
                        "role": msg.role,
                    },
                    interrupt_token="operator_sidechat",
                )
                try:
                    from shared.audio_performance_context import build_performance_context

                    _perf_ctx = build_performance_context()
                    candidates = await asyncio.to_thread(
                        daemon._affordance_pipeline.select, imp, context=_perf_ctx
                    )
                    log.info(
                        "Sidechat → %d candidate(s): %s",
                        len(candidates),
                        msg.text[:80],
                    )
                except Exception:
                    log.debug("Sidechat dispatch error (non-fatal)", exc_info=True)

                cursor_ts = max(cursor_ts, msg.ts)
                _save_sidechat_cursor(cursor_ts)
        except asyncio.CancelledError:
            break
        except Exception:
            log.debug("Sidechat consumer error (non-fatal)", exc_info=True)

        await asyncio.sleep(0.5)
