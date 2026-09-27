#!/usr/bin/env python3
"""Mint a scoped Google OAuth token with ``prompt=consent`` forcing the
Google channel picker — used for brand-account / sub-channel tokens.

Run when you need a token scoped to a YouTube channel *other* than the
main Google account's primary channel. The canonical case is the
streaming sub-channel for Phase 5 (video-id publisher) and Phase 4
(viewer count producer) — the main ``google/token`` cannot see
``liveBroadcasts.list(mine=true)`` on a brand sub-channel, so the
resolver returns ``liveStreamingNotEnabled``.

Usage:
    uv run python scripts/mint-google-token.py \
        --pass-key google/token-youtube-streaming \
        --scopes youtube.readonly youtube.force-ssl

Browser opens with ``prompt=consent`` — pick the account, then pick the
sub-channel on the second screen. The resulting token gets written to
the specified secret name. After minting, ``channels.list(mine=true)``
reports the sub-channel id; the Phase-5 resolver will then see
broadcasts on that channel.

Safety: does NOT touch ``google/token``. The existing main-account
credential used by gmail/calendar/drive/obsidian is unchanged.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build as discovery_build

from shared.google_auth import (
    CLIENT_SECRET_PASS_KEY,
    YOUTUBE_STREAMING_TOKEN_PASS_KEY,
    _save_token,
)
from shared.secrets import get_secret

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mint-google-token")

_DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def _expand_scope(name: str) -> str:
    if name.startswith("http"):
        return name
    return f"https://www.googleapis.com/auth/{name}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pass-key",
        default=YOUTUBE_STREAMING_TOKEN_PASS_KEY,
        help="Secret name to write the token to (the FileStore).",
    )
    parser.add_argument(
        "--scopes",
        nargs="+",
        default=_DEFAULT_SCOPES,
        help="OAuth scopes. Short names auto-prefixed with googleapis.com/auth/.",
    )
    args = parser.parse_args()

    scopes = [_expand_scope(s) for s in args.scopes]
    log.info("Minting token for secret %s with scopes: %s", args.pass_key, scopes)

    client_json = get_secret(CLIENT_SECRET_PASS_KEY)
    flow = InstalledAppFlow.from_client_config(json.loads(client_json), scopes)

    # prompt=consent forces Google to re-show the account picker AND the
    # channel picker even if a prior authorisation was cached. The
    # channel picker is the whole point — that's where the operator
    # selects the brand sub-channel.
    creds = flow.run_local_server(
        port=0,
        prompt="consent",
        authorization_prompt_message=(
            "Google consent flow opening in your browser.\n"
            "1. Pick your Google account\n"
            "2. On the next screen, pick the SUB-CHANNEL (not the main channel)\n"
            "3. Approve scopes\n"
            "Waiting for browser callback..."
        ),
    )

    _save_token(creds, pass_key=args.pass_key)
    log.info("Token saved to the FileStore as secret: %s", args.pass_key)

    # Verify which channel we actually got.
    yt = discovery_build("youtube", "v3", credentials=creds, cache_discovery=False)
    resp = yt.channels().list(part="id,snippet", mine=True).execute()
    items = resp.get("items") or []
    if not items:
        log.warning("channels.list(mine=true) returned no items — token may be wrong scope")
        return 1
    for item in items:
        log.info(
            "Token is scoped to channel: id=%s title=%s",
            item["id"],
            item["snippet"]["title"],
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
