"""Standalone Chatterbox TTS network server for remote GPU inference.

Run on hapax-appendix (192.168.68.50) to offload TTS synthesis from podium.
Wire protocol matches tts_server.py: newline-terminated JSON request,
newline-terminated JSON header + raw PCM response.

Usage:
    uv run python -m agents.hapax_daimonion.tts_serve_remote
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct

log = logging.getLogger(__name__)

DEFAULT_PORT = 9851
MAX_REQUEST_SIZE = 64 * 1024


async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    tts,
    lock: asyncio.Lock,
) -> None:
    peer = writer.get_extra_info("peername", "?")
    try:
        line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        if not line:
            return
        if len(line) > MAX_REQUEST_SIZE:
            return

        request = json.loads(line)
        text = request.get("text", "")
        use_case = request.get("use_case", "conversation")

        if not text:
            resp = json.dumps({"status": "error", "error": "empty text"}) + "\n"
            writer.write(resp.encode())
            await writer.drain()
            return

        log.info("TTS request from %s: %.40s", peer, text)

        async with lock:
            loop = asyncio.get_running_loop()
            pcm = await loop.run_in_executor(None, tts.synthesize, text, use_case)

        if not pcm:
            resp = json.dumps({"status": "error", "error": "synthesis produced no audio"}) + "\n"
            writer.write(resp.encode())
            await writer.drain()
            return

        header = (
            json.dumps(
                {
                    "status": "ok",
                    "sample_rate": 24000,
                    "channels": 1,
                    "pcm_len": len(pcm),
                }
            )
            + "\n"
        )
        writer.write(header.encode())
        writer.write(pcm)
        await writer.drain()
        log.info("TTS response: %d bytes PCM", len(pcm))
    except Exception:
        log.debug("Client error", exc_info=True)
    finally:
        writer.close()


async def serve(port: int = DEFAULT_PORT, device: str = "cuda:0") -> None:
    from agents.hapax_daimonion.tts import TTSManager

    tts = TTSManager()
    log.info("Loading Chatterbox on %s...", device)

    import os

    os.environ.setdefault("HAPAX_CHATTERBOX_DEVICE", device)

    tts.preload()
    lock = asyncio.Lock()

    server = await asyncio.start_server(
        lambda r, w: _handle_client(r, w, tts, lock),
        host="0.0.0.0",
        port=port,
    )
    log.info("TTS network server listening on :%d (device=%s)", port, device)

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    import os
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    port = int(os.environ.get("HAPAX_TTS_PORT", DEFAULT_PORT))
    device = os.environ.get("HAPAX_CHATTERBOX_DEVICE", "cuda:0")

    asyncio.run(serve(port=port, device=device))
