"""Auxiliary async loops for VoiceDaemon (delivery, ambient, impingement, consent)."""

from __future__ import annotations

import asyncio
import json
import logging
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
                _change_points = _vls.get("recent_change_points", [])
                _now_ts = time.time()
                _flow_transition = any(
                    cp.get("signal") == "flow_score" and _now_ts - cp.get("timestamp", 0) < 60.0
                    for cp in _change_points
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
            except (FileNotFoundError, ValueError, OSError):
                pass

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
    it up on next tick. Records the Thompson outcome based on whether
    dispatch succeeded.
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
        )
        family = dispatch(record)
        succeeded = family != "unknown"
        log.info(
            "Compositional dispatch: %s → %s (score=%.2f)",
            candidate.capability_name,
            family,
            candidate.combined,
        )
        daemon._affordance_pipeline.record_outcome(
            candidate.capability_name,
            success=succeeded,
            context={"source": imp.source, "family": family},
        )
    except Exception:
        log.warning("Compositional dispatch failed", exc_info=True)


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

    while daemon._running:
        try:
            _world_enabled = _world_routing_enabled()  # cache per poll cycle
            for imp in consumer.read_new():
                try:
                    candidates = await asyncio.to_thread(daemon._affordance_pipeline.select, imp)
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
                                daemon._affordance_pipeline.record_outcome(
                                    c.capability_name,
                                    success=True,
                                    context={"source": imp.source},
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
                                _write_livestream_control(imp, c)
                                daemon._affordance_pipeline.record_outcome(
                                    c.capability_name,
                                    success=True,
                                    context={"source": imp.source},
                                )
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
                                daemon._affordance_pipeline.record_outcome(
                                    c.capability_name,
                                    success=True,
                                    context={"source": imp.source},
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
                                daemon._affordance_pipeline.record_outcome(
                                    c.capability_name,
                                    success=True,
                                    context={"source": imp.source},
                                )
                            continue

                        # speech_production is owned by CPAL. Skipping here avoids
                        # double-firing spontaneous speech when the adapter has
                        # already set should_surface on the same impingement.
                        if c.capability_name == "speech_production":
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
                    # Dispatch through the affordance pipeline on a thread
                    # so the async loop doesn't block on embedding /
                    # Qdrant I/O. Mirrors the main impingement loop.
                    candidates = await asyncio.to_thread(daemon._affordance_pipeline.select, imp)
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
