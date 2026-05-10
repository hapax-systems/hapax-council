from __future__ import annotations

import threading
import urllib.request
from pathlib import Path

from agents.live_surface_guard.hls_no_cache_server import make_server


def test_hls_server_serves_playlist_with_no_cache_headers(tmp_path: Path) -> None:
    playlist = tmp_path / "stream.m3u8"
    playlist.write_text("#EXTM3U\n#EXT-X-TARGETDURATION:2\n", encoding="utf-8")
    server = make_server(directory=tmp_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        host, port = server.server_address
        with urllib.request.urlopen(f"http://{host}:{port}/stream.m3u8", timeout=2.0) as response:
            body = response.read().decode("utf-8")
            cache_control = response.headers["Cache-Control"]
            content_type = response.headers["Content-Type"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)

    assert "#EXTM3U" in body
    assert "no-store" in cache_control
    assert content_type.startswith("application/vnd.apple.mpegurl")
