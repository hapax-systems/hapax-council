"""Auxiliary async loops for VoiceDaemon (delivery, ambient, impingement, consent)."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from agents._apperception import impingement_to_cascade_event
from agents._impingement_consumer import ImpingementConsumer
from agents.hapax_daimonion.persona import format_notification  # noqa: F401 (patched in tests)

if TYPE_CHECKING:
    from agents.hapax_daimonion.daemon import VoiceDaemon

log = logging.getLogger("hapax_daimonion")

_PROACTIVE_CHECK_INTERVAL_S = 30
_NTFY_BASE_URL = "http://127.0.0.1:8090"
_NTFY_TOPICS = ["hapax"]


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


async def impingement_consumer_loop(daemon: VoiceDaemon) -> None:
    """Poll DMN impingements and route through affordance pipeline."""
    consumer = ImpingementConsumer(Path("/dev/shm/hapax-dmn/impingements.jsonl"))

    while daemon._running:
        try:
            for imp in consumer.read_new():
                try:
                    candidates = await asyncio.to_thread(daemon._affordance_pipeline.select, imp)
                    for c in candidates:
                        if c.capability_name == "speech_production":
                            daemon._speech_capability.activate(imp, c.combined)
                            log.info(
                                "Speech recruited via affordance: %s (score=%.2f)",
                                imp.content.get("metric", imp.source),
                                c.combined,
                            )
                        elif c.capability_name == "system_awareness":
                            if hasattr(daemon, "_system_awareness"):
                                score = daemon._system_awareness.can_resolve(imp)
                                if score > 0:
                                    daemon._system_awareness.activate(imp, score)
                    # Vocal chain: modulate voice character via MIDI
                    if hasattr(daemon, "_vocal_chain") and daemon._vocal_chain is not None:
                        vc_score = daemon._vocal_chain.can_resolve(imp)
                        if vc_score > 0.0:
                            daemon._vocal_chain.activate_from_impingement(imp)
                            log.debug(
                                "Vocal chain activated: %s (score=%.2f)",
                                imp.content.get("metric", imp.source),
                                vc_score,
                            )
                    # Cross-modal coordination
                    if len(candidates) > 1 and hasattr(daemon, "_expression_coordinator"):
                        recruited_pairs = [
                            (
                                c.capability_name,
                                getattr(daemon, f"_{c.capability_name}", None),
                            )
                            for c in candidates
                        ]
                        recruited_pairs = [
                            (n, cap) for n, cap in recruited_pairs if cap is not None
                        ]
                        if len(recruited_pairs) > 1:
                            activations = daemon._expression_coordinator.coordinate(
                                imp.content, recruited_pairs
                            )
                            if activations:
                                log.info(
                                    "Cross-modal coordination: %d modalities for %s",
                                    len(activations),
                                    imp.content.get("narrative", "")[:40],
                                )
                    # Apperception cascade: map perception impingements to cascade events
                    cascade_event = impingement_to_cascade_event(imp)
                    if cascade_event is not None:
                        if (
                            hasattr(daemon, "_apperception_cascade")
                            and daemon._apperception_cascade is not None
                        ):
                            try:
                                apperception = daemon._apperception_cascade.process(
                                    cascade_event,
                                )
                                if apperception is not None and hasattr(
                                    daemon, "_apperception_store"
                                ):
                                    daemon._apperception_store.add(apperception)
                                    log.debug(
                                        "Apperception cascade: %s → %s",
                                        imp.content.get("metric", imp.source),
                                        apperception.theme,
                                    )
                            except Exception:
                                log.debug("Apperception cascade error (non-fatal)", exc_info=True)
                        else:
                            log.debug(
                                "Apperception cascade event generated but no cascade on daemon: %s",
                                cascade_event.source,
                            )
                    # Proactive utterance
                    if imp.source == "imagination" and imp.strength >= 0.65:
                        _handle_proactive_impingement(daemon, imp)
                except Exception:
                    pass
        except Exception:
            log.debug("Impingement consumer error (non-fatal)", exc_info=True)

        await asyncio.sleep(0.5)


def _handle_proactive_impingement(daemon: VoiceDaemon, imp) -> None:
    """Handle imagination-sourced impingement for proactive speech."""
    gate_state = {
        "perception_activity": (
            daemon.perception.latest.activity if daemon.perception.latest else "unknown"
        ),
        "vad_active": daemon.session.is_active,
        "last_utterance_time": daemon._last_utterance_time,
        "tpn_active": False,
    }
    from agents.imagination import ImaginationFragment

    try:
        proxy_frag = ImaginationFragment(
            content_references=[],
            dimensions=imp.context.get("dimensions", {}),
            salience=imp.strength,
            continuation=imp.content.get("continuation", False),
            narrative=imp.content.get("narrative", ""),
        )
        if daemon._proactive_gate.should_speak(proxy_frag, gate_state):
            daemon._proactive_gate.record_utterance()
            daemon._last_utterance_time = time.monotonic()
            log.info("Proactive utterance triggered: %s", imp.content.get("narrative", "")[:60])
            if daemon._conversation_pipeline:
                asyncio.create_task(daemon._conversation_pipeline.generate_spontaneous_speech(imp))
    except Exception:
        log.debug("Proactive gate check failed (non-fatal)", exc_info=True)


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
