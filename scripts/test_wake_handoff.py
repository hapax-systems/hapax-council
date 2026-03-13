#!/usr/bin/env python3
"""Minimal live test: Porcupine wake word → session handoff.

Runs the audio input + Porcupine detector loop.
On detection: logs, fires screen flash, prints timing.
No pipeline, no LLM, no TTS — just the trigger path.

Usage:
    cd ~/projects/ai-agents && eval "$(<.envrc)"
    uv run python scripts/test_wake_handoff.py

Say "Hapax" and watch for detection. Ctrl+C to stop.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import subprocess
import time

import numpy as np

from shared.log_setup import configure_logging

configure_logging(agent="test-wake")
log = logging.getLogger("test_wake_handoff")


async def main() -> None:
    from agents.hapax_voice.audio_input import AudioInputStream
    from agents.hapax_voice.wake_word_porcupine import PorcupineWakeWord

    # --- Init ---
    audio = AudioInputStream(source_name="echo_cancel_capture")
    detector = PorcupineWakeWord(sensitivity=0.5)

    log.info("Loading Porcupine...")
    detector.load()
    if not detector.is_loaded:
        log.error("Porcupine failed to load — check model file and access key")
        return
    log.info(
        "Porcupine loaded (frame_length=%d, sample_rate=16000)",
        detector.frame_length,
    )

    audio.start()
    if not audio.is_active:
        log.error("Audio input failed to start")
        return
    log.info("Audio input active — say 'Hapax' to test detection")
    log.info("Press Ctrl+C to stop\n")

    # --- Audio loop (simplified: no VAD, just wake word) ---
    _WAKE_CHUNK = detector.frame_length * 2  # bytes
    wake_buf = bytearray()
    detection_count = 0
    frames_processed = 0

    def on_wake_word():
        nonlocal detection_count
        detection_count += 1
        now = time.strftime("%H:%M:%S")
        log.info(
            "=== WAKE WORD DETECTED #%d at %s (after %d frames) ===",
            detection_count,
            now,
            frames_processed,
        )
        try:
            subprocess.Popen(
                [
                    "notify-send",
                    "--app-name=Hapax Voice",
                    "--icon=audio-input-microphone",
                    "--expire-time=2000",
                    "--transient",
                    f"Wake word detected (#{detection_count})",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pass

    detector.on_wake_word = on_wake_word

    running = True

    def stop():
        nonlocal running
        running = False

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, stop)
    loop.add_signal_handler(signal.SIGTERM, stop)

    last_status = time.monotonic()

    while running:
        try:
            frame = await audio.get_frame(timeout=1.0)
        except Exception as exc:
            log.warning("Audio error: %s", exc)
            continue
        if frame is None:
            continue

        wake_buf.extend(frame)

        while len(wake_buf) >= _WAKE_CHUNK:
            chunk = bytes(wake_buf[:_WAKE_CHUNK])
            del wake_buf[:_WAKE_CHUNK]
            audio_np = np.frombuffer(chunk, dtype=np.int16)

            # Log audio level periodically for diagnostics
            frames_processed += 1
            detector.process_audio(audio_np)

        # Status every 10 seconds
        now = time.monotonic()
        if now - last_status >= 10.0:
            rms = np.sqrt(np.mean(np.frombuffer(frame, dtype=np.int16).astype(np.float64) ** 2))
            log.info(
                "Status: %d frames processed, %d detections, RMS=%.0f",
                frames_processed,
                detection_count,
                rms,
            )
            last_status = now

    # --- Cleanup ---
    audio.stop()
    detector.close()
    log.info(
        "\nDone. %d detections in %d frames.",
        detection_count,
        frames_processed,
    )


if __name__ == "__main__":
    asyncio.run(main())
