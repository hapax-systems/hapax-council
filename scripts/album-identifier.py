#!/usr/bin/env python3
"""Album identifier daemon for the studio compositor.

Watches Pi-6 IR overhead camera for vinyl album covers via HTTP frame server.
When a new album is detected, identifies it via Gemini Flash vision.
Tracks current playing track via ACRCloud audio fingerprinting.

The album cover image is saved for the compositor to display as a bouncing
overlay alongside the YouTube PiP.

IR frame source: http://{PI6_IP}:8090/frame.jpg (on-demand, no USR1/scp)
Audio source: PipeWire mixer_master via pw-cat
Track ID: ACRCloud (audio captured → 2x speed restore → fingerprint match)
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("album-identifier")

# --- Config ---
PI6_IP = os.environ.get("PI6_IP", "192.168.68.81")
IR_FRAME_URL = f"http://{PI6_IP}:8090/frame.jpg"

# Album cover detection — vision model finds the album bounding box in the 1080p IR frame

POLL_INTERVAL = 5  # seconds between album change checks
TRACK_ID_INTERVAL = 30  # seconds between track identification attempts
AUDIO_CAPTURE_SECONDS = 12  # seconds of audio to capture for fingerprinting

SHM_DIR = Path("/dev/shm/hapax-compositor")
ALBUM_COVER_FILE = SHM_DIR / "album-cover.png"
MUSIC_ATTRIBUTION_FILE = SHM_DIR / "music-attribution.txt"
ALBUM_STATE_FILE = SHM_DIR / "album-state.json"
ATTRIBUTION_LOG = Path(
    os.path.expanduser("~/Documents/Personal/30-areas/legomena-live/music-attribution-log.md")
)

LYRICS_FILE = SHM_DIR / "track-lyrics.txt"

LITELLM_URL = "http://localhost:4000/v1/chat/completions"
LITELLM_KEY = ""


def _record_album_identifier_spend(data: dict) -> None:
    """LRR Phase 0 item 2: wire the token ledger.

    Every album-identifier LiteLLM call should record its prompt + completion
    token spend into the shared token ledger so the token pole reflects
    album-identifier activity (not just director_loop / hapax). All five LLM
    call sites in this module call this helper after parsing the response
    JSON. Costs default to 0.0 because LiteLLM proxy doesn't surface the
    upstream cost; the token counts are the load-bearing field for the
    sub-logarithmic pole scaling formula.
    """
    try:
        from token_ledger import record_spend

        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        if prompt_tokens or completion_tokens:
            record_spend("album-identifier", prompt_tokens, completion_tokens, cost=0.0)
    except Exception:
        log.debug("token_ledger record_spend failed", exc_info=True)


# --- State ---
_last_hash: str = ""
_current_album: dict = {}
_current_track: str = ""
_album_start_time: float = 0
_track_id_lock = threading.Lock()


def _get_litellm_key() -> str:
    global LITELLM_KEY
    if not LITELLM_KEY:
        try:
            result = subprocess.run(
                ["pass", "show", "litellm/master-key"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            LITELLM_KEY = result.stdout.strip()
        except Exception:
            pass
    return LITELLM_KEY


def fetch_ir_frame() -> bytes | None:
    """Fetch latest IR frame from Pi-6 HTTP frame server."""
    try:
        resp = urllib.request.urlopen(IR_FRAME_URL, timeout=3)
        return resp.read()
    except Exception as e:
        log.debug("IR frame fetch failed: %s", e)
        return None


def detect_and_crop_album(frame_data: bytes) -> bytes | None:
    """Use vision model to detect album cover bounding box, then crop. Returns JPEG bytes."""
    from PIL import Image

    key = _get_litellm_key()
    if not key:
        return None

    img = Image.open(io.BytesIO(frame_data))
    w, h = img.size

    b64 = base64.b64encode(frame_data).decode()
    body = json.dumps(
        {
            "model": "fast",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                        {
                            "type": "text",
                            "text": (
                                f"This {w}x{h} infrared image shows a vinyl album cover on a desk. "
                                "Find the bounding box of the album cover (the square cardboard sleeve). "
                                f'Return ONLY: {{"x1":int,"y1":int,"x2":int,"y2":int}}'
                            ),
                        },
                    ],
                }
            ],
        }
    ).encode()

    try:
        req = urllib.request.Request(
            LITELLM_URL,
            body,
            {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        )
        resp = urllib.request.urlopen(req, timeout=20)
        data = json.loads(resp.read())
        _record_album_identifier_spend(data)
        raw = data["choices"][0]["message"]["content"].strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        box = json.loads(raw)
        x1, y1 = max(0, box["x1"]), max(0, box["y1"])
        x2, y2 = min(w, box["x2"]), min(h, box["y2"])

        cropped = img.crop((x1, y1, x2, y2))
        # Force square (album covers are always square)
        cw, ch = cropped.size
        size = max(cw, ch)
        square = Image.new("RGB", (size, size), (0, 0, 0))
        square.paste(cropped, ((size - cw) // 2, (size - ch) // 2))

        buf = io.BytesIO()
        square.save(buf, format="JPEG", quality=90)
        log.info("Album detected: (%d,%d)-(%d,%d) -> %dx%d", x1, y1, x2, y2, size, size)
        return buf.getvalue()
    except Exception as e:
        log.warning("Album detection failed: %s", e)
        # Fallback: center square crop
        size = min(w, h)
        cx, cy = w // 2, h // 2
        cropped = img.crop((cx - size // 2, cy - size // 2, cx + size // 2, cy + size // 2))
        buf = io.BytesIO()
        cropped.save(buf, format="JPEG", quality=90)
        return buf.getvalue()


def image_hash(data: bytes) -> str:
    """Perceptual hash — downscale to 16x16 grayscale, threshold at mean."""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data)).convert("L").resize((16, 16), Image.LANCZOS)
        pixels = list(img.getdata())
        avg = sum(pixels) / len(pixels)
        bits = "".join("1" if p > avg else "0" for p in pixels)
        # MD5 used for perceptual hash comparison only, not security
        return hashlib.md5(bits.encode(), usedforsecurity=False).hexdigest()
    except Exception:
        return hashlib.md5(data, usedforsecurity=False).hexdigest()


def hamming_distance(h1: str, h2: str) -> int:
    if len(h1) != len(h2):
        return 32
    b1 = bin(int(h1, 16))[2:].zfill(len(h1) * 4)
    b2 = bin(int(h2, 16))[2:].zfill(len(h2) * 4)
    return sum(c1 != c2 for c1, c2 in zip(b1, b2, strict=False))


def identify_album_vision(image_data: bytes) -> dict | None:
    """Send IR album image to Gemini Flash for identification via LiteLLM proxy."""
    b64 = base64.b64encode(image_data).decode()
    key = _get_litellm_key()
    if not key:
        log.warning("No LiteLLM key available")
        return None

    body = json.dumps(
        {
            "model": "balanced",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                        {
                            "type": "text",
                            "text": (
                                "Identify this vinyl album cover photographed under 850nm infrared "
                                "light (grayscale, no color information). Think carefully — this "
                                "collection includes underground hip hop (MF DOOM, Tha God Fahim, "
                                "Griselda, Madlib), dungeon synth, Japanese city pop, jazz, and "
                                "other obscure genres. The album may be rare or limited press. "
                                "Look closely at any text, logos, label marks, catalog numbers, "
                                "and artwork style. If you're unsure, describe what you see in "
                                "detail first, then make your best identification.\n\n"
                                "Return a JSON object with: artist, title, year, label, confidence (0.0-1.0). "
                                'If truly unidentifiable, return {"artist": null}. No other text.'
                            ),
                        },
                    ],
                }
            ],
        }
    ).encode()

    try:
        req = urllib.request.Request(
            LITELLM_URL,
            body,
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
        )
        resp = urllib.request.urlopen(req, timeout=20)
        data = json.loads(resp.read())
        _record_album_identifier_spend(data)
        raw = data["choices"][0]["message"]["content"].strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        result = json.loads(raw)
        if result.get("artist") is None:
            log.info("Album not identified")
            return None
        log.info(
            "Identified: %s — %s (%s)",
            result.get("artist"),
            result.get("title"),
            result.get("year"),
        )
        return result
    except Exception as e:
        log.warning("Vision identification failed: %s", e)
        return None


# --- Combined vision + audio identification ---
def _capture_audio_mp3() -> str | None:
    """Capture audio from PipeWire (right channel), restore nominal pitch/tempo,
    return mp3 path.

    The operator plays records on a Korg Handytrax-PLAY which exposes
    discrete RPM presets plus a ±10% pitch knob. Playing 45 RPM records
    on the 33⅓ setting (a common mode) produces a 0.741× playback rate;
    the pre-2026-04-18 implementation hardcoded a 2× restore (assumed
    literal 0.5× playback) which mangled ACRCloud/Gemini matching when
    the rate was anything other than exactly 0.5×. Now reads the live
    ``vinyl_playback_rate`` signal (:mod:`shared.vinyl_rate`) and
    computes the restoration factor dynamically. ``1.0`` means no
    restoration (identity) — the filter still runs to downmix stereo
    to mono, but the sample-rate distortion is absent.
    """
    from shared.vinyl_rate import rate_to_restore_factor, read_vinyl_playback_rate

    raw_path = ""
    mp3_path = ""
    keep_mp3 = False
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            raw_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir="/tmp") as f:
            mp3_path = f.name

        proc = subprocess.Popen(
            [
                "pw-cat",
                "--record",
                "--target",
                "mixer_master",
                "--rate",
                "44100",
                "--channels",
                "2",
                "--format",
                "s16",
                "--quality",
                "0",
                raw_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(AUDIO_CAPTURE_SECONDS + 1)
        proc.kill()
        proc.wait(timeout=3)

        if not os.path.exists(raw_path) or os.path.getsize(raw_path) < 1000:
            return None

        playback_rate = read_vinyl_playback_rate()
        restore_factor = rate_to_restore_factor(playback_rate)
        restored_rate = int(round(44100 * restore_factor))
        log.info(
            "Restoring audio: playback_rate=%.3f restore_factor=%.3f target_rate=%d",
            playback_rate,
            restore_factor,
            restored_rate,
        )

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                raw_path,
                "-af",
                f"pan=mono|c0=c1,asetrate={restored_rate},aresample=44100",
                "-b:a",
                "128k",
                mp3_path,
            ],
            capture_output=True,
            timeout=15,
        )

        if not os.path.exists(mp3_path) or os.path.getsize(mp3_path) < 1000:
            return None

        keep_mp3 = True
        return mp3_path
    except Exception:
        return None
    finally:
        if raw_path:
            try:
                os.unlink(raw_path)
            except OSError:
                pass
        if mp3_path and not keep_mp3:
            try:
                os.unlink(mp3_path)
            except OSError:
                pass


def identify_album_and_track(image_data: bytes) -> tuple[dict | None, str | None]:
    """Combined identification: album cover image + audio clip in one multimodal call.

    Sends both the IR album cover and a speed-corrected audio sample to Gemini.
    The visual narrows to artist/catalog, the audio pins the specific track.
    """
    key = _get_litellm_key()
    if not key:
        return None, None

    image_b64 = base64.b64encode(image_data).decode()

    # Capture audio in parallel-ish (blocking but that's fine for a daemon)
    mp3_path = _capture_audio_mp3()
    audio_content = []
    if mp3_path:
        try:
            with open(mp3_path, "rb") as f:
                audio_b64 = base64.b64encode(f.read()).decode()
            audio_content = [
                {
                    "type": "input_audio",
                    "input_audio": {"data": audio_b64, "format": "mp3"},
                },
            ]
        finally:
            try:
                os.unlink(mp3_path)
            except OSError:
                pass

    has_audio = bool(audio_content)
    audio_instruction = ""
    if has_audio:
        audio_instruction = (
            "\n\nI've also included an audio clip from this record playing at reduced "
            "speed, sped back up to approximate original tempo. Use BOTH the cover art "
            "AND the audio to identify the album and which specific track is playing."
        )

    body = json.dumps(
        {
            "model": "balanced",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                        },
                        *audio_content,
                        {
                            "type": "text",
                            "text": (
                                "What album is this? What track is playing?"
                                f"{audio_instruction}\n\n"
                                "Return a JSON object with: artist, title, year, label, confidence (0.0-1.0), "
                                "track (specific track, or null), model (your model name). No other text."
                            ),
                        },
                    ],
                }
            ],
        }
    ).encode()

    try:
        req = urllib.request.Request(
            LITELLM_URL,
            body,
            {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        )
        resp = urllib.request.urlopen(req, timeout=45)
        data = json.loads(resp.read())
        _record_album_identifier_spend(data)
        raw = data["choices"][0]["message"]["content"].strip()

        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        result = json.loads(raw)
        if result.get("artist") is None:
            log.info("Album not identified")
            return None, None

        album = {
            "artist": result.get("artist"),
            "title": result.get("title"),
            "year": result.get("year"),
            "label": result.get("label"),
            "model": result.get("model", "Gemini"),
            "confidence": result.get("confidence", 0),
        }
        track = result.get("track")
        confidence = result.get("confidence", 0)

        log.info(
            "Identified: %s — %s, track=%s (confidence=%.2f)",
            album.get("artist"),
            album.get("title"),
            track,
            confidence,
        )

        # Fetch lyrics if track identified
        if track:
            artist = album.get("artist", "Unknown")
            lyrics = _fetch_lyrics(artist, track)
            if lyrics:
                _write_lyrics(lyrics)
            else:
                LYRICS_FILE.unlink(missing_ok=True)

        return album, track

    except Exception as e:
        log.warning("Combined identification failed: %s", e)
        return None, None


def capture_and_identify_track() -> str | None:
    """Standalone track re-identification using audio + known album context."""
    if not _current_album:
        return None

    mp3_path = _capture_audio_mp3()
    if not mp3_path:
        return None

    try:
        with open(mp3_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()
    finally:
        try:
            os.unlink(mp3_path)
        except OSError:
            pass

    key = _get_litellm_key()
    if not key:
        return None

    artist = _current_album.get("artist", "Unknown")
    title = _current_album.get("title", "Unknown")

    body = json.dumps(
        {
            "model": "fast",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {"data": audio_b64, "format": "mp3"},
                        },
                        {
                            "type": "text",
                            "text": (
                                f"This is audio from: {artist} — {title}. "
                                "Playing at reduced speed, sped back up to approximate original tempo. "
                                "Which specific track is this? "
                                'Return ONLY: {"track": "track name", "confidence": 0.0-1.0}. '
                                'If unsure: {"track": null}.'
                            ),
                        },
                    ],
                }
            ],
        }
    ).encode()

    try:
        req = urllib.request.Request(
            LITELLM_URL,
            body,
            {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        )
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read())
        _record_album_identifier_spend(data)
        raw = data["choices"][0]["message"]["content"].strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        result = json.loads(raw)
        track = result.get("track")
        confidence = result.get("confidence", 0)
        if track and confidence >= 0.5:
            log.info("Track re-identified: %s (confidence=%.2f)", track, confidence)
            lyrics = _fetch_lyrics(artist, track)
            if lyrics:
                _write_lyrics(lyrics)
            else:
                LYRICS_FILE.unlink(missing_ok=True)
            return track
        return None
    except Exception as e:
        log.warning("Track re-identification failed: %s", e)
        return None


def _fetch_lyrics(artist: str, track: str) -> str | None:
    """Ask Gemini for lyrics if the track has them."""
    key = _get_litellm_key()
    if not key:
        return None
    try:
        body = json.dumps(
            {
                "model": "fast",
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f'Does the song "{track}" by {artist} have lyrics? '
                            "If yes, return the full lyrics as plain text. "
                            "If the lyrics are not in English, include the original language lyrics "
                            "followed by '---TRANSLATION---' and the English translation. "
                            "If it's an instrumental with no lyrics, return exactly: INSTRUMENTAL\n"
                            "No other commentary."
                        ),
                    }
                ],
            }
        ).encode()
        req = urllib.request.Request(
            LITELLM_URL,
            body,
            {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        )
        resp = urllib.request.urlopen(req, timeout=20)
        data = json.loads(resp.read())
        _record_album_identifier_spend(data)
        text = data["choices"][0]["message"]["content"].strip()
        if "INSTRUMENTAL" in text.upper()[:20]:
            log.info("Track is instrumental, no lyrics")
            return None
        log.info("Lyrics fetched (%d chars)", len(text))
        return text
    except Exception as e:
        log.debug("Lyrics fetch failed: %s", e)
        return None


def _write_lyrics(lyrics: str) -> None:
    """Write lyrics to shm for overlay display."""
    try:
        LYRICS_FILE.write_text(lyrics)
    except OSError:
        pass


def write_state(album: dict, track: str) -> None:
    """Write album state, attribution files, and cover image."""
    artist = album.get("artist", "Unknown")
    title = album.get("title", "Unknown")
    year = album.get("year", "")
    label = album.get("label", "")

    # Splattribution text for overlay
    model = album.get("model", "unknown LLM")
    confidence = album.get("confidence", "?")
    lines = [
        "SPLATTRIBUTION",
        f'{model} says: "{artist} — {title}"',
    ]
    if track:
        lines.append(f'Track: "{track}"')
    # "(LOL)" is deliberate commentary on dumb-LLM-attribution-confidence —
    # it rides inline with the Confidence value rather than dangling on its
    # own line below where it read as an LLM artifact.
    if confidence != "?":
        lines.append(f"Confidence: {int(float(confidence) * 100)}% (LOL)")
    else:
        lines.append("Confidence: ? (LOL)")
    try:
        SHM_DIR.mkdir(parents=True, exist_ok=True)
        MUSIC_ATTRIBUTION_FILE.write_text("\n".join(lines))
    except OSError:
        pass

    # JSON state for other consumers
    state = {
        "type": "splattribution",
        "artist": artist,
        "title": title,
        "year": year,
        "label": label,
        "model": album.get("model", "unknown"),
        "confidence": album.get("confidence", 0),
        "current_track": track,
        "timestamp": time.time(),
    }
    try:
        ALBUM_STATE_FILE.write_text(json.dumps(state))
    except OSError:
        pass


def log_album(album: dict) -> None:
    """Append to persistent attribution log."""
    artist = album.get("artist", "Unknown")
    title = album.get("title", "Unknown")
    year = album.get("year", "")
    label = album.get("label", "")

    try:
        ATTRIBUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(ATTRIBUTION_LOG, "a") as f:
            entry = f"- {artist} — *{title}*"
            if year:
                entry += f" ({year})"
            if label:
                entry += f" [{label}]"
            entry += f" ({datetime.now().strftime('%H:%M')})\n"
            f.write(entry)
    except OSError:
        pass


def track_id_loop() -> None:
    """Background thread: periodically identify the playing track via ACRCloud."""
    global _current_track
    while True:
        time.sleep(TRACK_ID_INTERVAL)
        if not _current_album:
            continue
        with _track_id_lock:
            track = capture_and_identify_track()
            if track:
                _current_track = track
                write_state(_current_album, _current_track)
                log.info("Now playing: %s", track)


def main() -> None:
    global _last_hash, _current_album, _current_track, _album_start_time

    log.info("Album identifier starting — IR source=%s poll=%ds", IR_FRAME_URL, POLL_INTERVAL)

    # Start track identification thread
    threading.Thread(target=track_id_loop, daemon=True).start()

    cooldown_until = 0.0

    while True:
        time.sleep(POLL_INTERVAL)
        now = time.monotonic()

        if now < cooldown_until:
            continue

        # Fetch IR frame from Pi-6
        frame_data = fetch_ir_frame()
        if frame_data is None:
            continue

        # Use the full IR frame — camera is positioned close, album dominates
        cropped = frame_data

        # Check if image changed — but refresh the PNG on EVERY poll so the
        # on-disk crop is always fresh. Only the expensive LLM identify call
        # is gated by the hash-distance threshold.
        h = image_hash(cropped)
        dist = hamming_distance(h, _last_hash) if _last_hash else 999

        # Save cropped cover as PNG every poll. Colorization is deterministic
        # per IR-frame hash so the same album keeps the same tint across
        # re-saves (previously `random.choice(tints)` swapped colors on every
        # tick and read to the operator as "crop coords changing"). Geometry
        # is also deterministic: fixed 15% center-crop margin, 90° rotate,
        # 512×512 resize — so the same scene ALWAYS produces the same PNG.
        try:
            from PIL import Image, ImageOps

            if not isinstance(cropped, (bytes, bytearray)):
                log.warning(
                    "cropped is %s, not bytes — skipping PNG save",
                    type(cropped).__name__,
                )
                raise TypeError("cropped must be bytes-like")

            img = Image.open(io.BytesIO(cropped)).convert("L")
            # Crop to center square with 15% zoom (cut desk edges)
            w, ih = img.size
            size = min(w, ih)
            margin = int(size * 0.15)
            left = (w - size) // 2 + margin
            top = (ih - size) // 2 + margin
            img = img.crop((left, top, left + size - 2 * margin, top + size - 2 * margin))
            # Rotate 90° CW (album is sideways in the IR camera frame)
            img = img.rotate(-90, expand=True)
            # Downscale for overlay (no need for 1080p on a 300px bouncing tile)
            img = img.resize((512, 512), Image.LANCZOS)
            # Duotone colorization — deterministic per hash (stable tint per album)
            tints = [
                ((20, 0, 40), (255, 100, 50)),  # purple → orange
                ((0, 20, 40), (50, 255, 200)),  # dark teal → mint
                ((40, 0, 0), (255, 200, 50)),  # dark red → gold
                ((0, 0, 30), (100, 200, 255)),  # navy → sky blue
                ((30, 10, 0), (255, 80, 120)),  # brown → hot pink
                ((0, 30, 20), (200, 255, 100)),  # forest → lime
                ((20, 0, 20), (255, 150, 255)),  # plum → lavender
                ((10, 20, 0), (255, 255, 100)),  # olive → yellow
            ]
            # _last_hash (or h on first iteration) is a hex STRING — parse the
            # first byte worth (2 hex chars) as int for deterministic tint
            # selection. Previously used int.from_bytes on a str which is
            # the "cannot convert 'str' object to bytes" crash that was
            # burning ~5 TypeErrors/minute in journald.
            hash_hex = h if _last_hash == "" else _last_hash
            tint_idx = int(hash_hex[:2], 16) % len(tints)
            dark, light = tints[tint_idx]
            colored = ImageOps.colorize(img, dark, light)
            # Atomic write — PIL's Image.save writes incrementally, so
            # the compositor's ImageLoader can hit a half-written PNG and
            # raise cairo IOError. Write to a sibling tmp file then
            # os.replace into place; POSIX rename is atomic so readers
            # see either the old PNG or the new one, never partial bytes.
            # Source of the "ImageLoader: failed to decode" pattern in
            # studio-compositor logs (documented in
            # docs/research/2026-04-13/post-option-a-stability/phase-1-long-duration-stability.md).
            tmp_path = ALBUM_COVER_FILE.with_suffix(".png.tmp")
            colored.save(str(tmp_path), format="PNG")
            os.replace(tmp_path, ALBUM_COVER_FILE)
            log.info(
                "Album cover saved (%dx%d) tint=%d (deterministic per hash)",
                colored.size[0],
                colored.size[1],
                tint_idx,
            )
        except Exception:
            log.exception("Album cover save failed")

        # Gate the EXPENSIVE Gemini+ACRCloud identification behind the
        # hash-distance threshold. 32 requires a real scene change
        # (different album placed on deck, operator hand in frame) before
        # re-querying the vision/audio identifiers; prevents LLM-call
        # flooding on IR sensor noise + spinning-record shimmer. The PNG
        # crop above is refreshed every poll regardless.
        if dist < 32:
            continue

        log.info("Album zone changed (distance=%d), identifying...", dist)
        _last_hash = h

        # Combined vision + audio identification
        album, track = identify_album_and_track(cropped)
        if album is not None:
            _current_album = album
            _current_track = track or ""
            _album_start_time = time.time()
            write_state(album, _current_track)
            log_album(album)
            cooldown_until = now + 30
        else:
            cooldown_until = now + 15


if __name__ == "__main__":
    main()
