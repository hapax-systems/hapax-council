"""Single-writer OAuth refresher for codex auth.json.

FALSIFIED upstream (3 ways): the strong-form CODEX_ACCESS_TOKEN external
carrier does not work.
  - Binary binds it to --use-agent-identity-auth (NOT chatgpt).
  - `codex login --with-access-token` rejects the ChatGPT access_token:
    "agent identity JWT payload is not valid JSON" (no auth.json written).
  - auth.json without refresh_token -> codex `auth mode: none` (access_token
    is NOT used). Codex ties access_token usability to refresh_token presence.
The external_command model_provider auth is incompatible with
requires_openai_auth (routes via api_key path = billed, loses subscription).

THEREFORE: weak-form flock daemon. One process on appendix owns auth.json
(with refresh_token) and is the SOLE writer. Consumers (codex lanes) read
auth.json read-only at startup. Intra-rig race is practically eliminated by
proactive pre-refresh (refresh days before expiry; consumers never see stale).
flock serializes the rare consumer self-refresh during daemon outage.
Cross-rig: podium receives a synced read-only copy (chmod 444); podium
never refreshes.

Future strong-form upgrade: the app-server `chatgptAuthTokens` JSON-RPC
path (account/login/start) is the only true external ChatGPT-bearer mode
("In external auth mode this flag is ignored. Clients should refresh tokens
themselves"). Requires `codex app-server` on appendix + `codex exec --remote`
consumers. Not this slice.
"""

from __future__ import annotations

import base64
import fcntl
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("codex_oauth_refresher")

AUTH_JSON = Path(os.path.expanduser("~/.codex/auth.json"))
LOCK_FILE = Path(os.path.expanduser("~/.codex/auth.json.flock"))
# Refresh when fewer than this many seconds remain on the access_token.
# access_token lifetime is ~10d (863_984s observed); 3-day headroom.
REFRESH_THRESHOLD_S = 3 * 86_400
# Codex binary (resolved through the npm shim).
CODEX_BIN = "codex"
# A trivial codex invocation that exercises the bearer and triggers codex's
# own auto-refresh on near-expiry. --ephemeral avoids persisting a session;
# --skip-git-repo-check lets us run outside a repo; the prompt is minimal.
REFRESH_PROBE_ARGS = [
    CODEX_BIN,
    "exec",
    "--skip-git-repo-check",
    "--ephemeral",
    "--dangerously-bypass-approvals-and-sandbox",
    "-m",
    "gpt-5.4-mini",  # cheapest model; we discard output, only want the refresh side-effect
    "ok",
]


@dataclass(frozen=True)
class TokenInfo:
    exp: int  # access_token expiry, unix seconds
    iat: int
    has_refresh: bool
    auth_mode: str

    @property
    def remaining_s(self) -> float:
        return self.exp - time.time()


def _b64url_decode(seg: str) -> bytes:
    seg = seg + "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg)


def read_token_info(path: Path = AUTH_JSON) -> TokenInfo:
    """Decode auth.json -> TokenInfo. NEVER mutate."""
    raw = json.loads(path.read_text())
    tokens = raw.get("tokens", {})
    at = tokens.get("access_token", "")
    parts = at.split(".")
    if len(parts) != 3:
        raise ValueError(f"access_token is not a JWT (segments={len(parts)})")
    payload = json.loads(_b64url_decode(parts[1]))
    return TokenInfo(
        exp=int(payload["exp"]),
        iat=int(payload["iat"]),
        has_refresh=bool(tokens.get("refresh_token")),
        auth_mode=raw.get("auth_mode", "unknown"),
    )


def _flocked_refresh() -> tuple[bool, str]:
    """Acquire flock on LOCK_FILE, invoke codex's own auto-refresh, verify.

    Codex refreshes automatically when it detects a near-expiry token during
    a real API call. We trigger that call under flock so the auth.json write
    is serialized against any concurrent consumer self-refresh. We rely on
    codex's refresh logic (the SSOT for a valid auth.json shape) rather than
    hand-rolling the OAuth POST (which risks producing a file codex rejects).
    """
    before = read_token_info()
    if before.auth_mode != "chatgpt":
        return False, f"auth_mode is {before.auth_mode}, expected chatgpt"
    if not before.has_refresh:
        return False, "no refresh_token in auth.json (cannot refresh)"

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "w") as lockf:
        # Blocking exclusive lock; sibling consumers acquire the same lock
        # for their (rare) self-refresh writes -> no concurrent writers.
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        log.info("flock acquired; invoking codex refresh probe")
        proc = subprocess.run(
            REFRESH_PROBE_ARGS,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            log.warning("codex probe rc=%d stderr=%r", proc.returncode, proc.stderr[:400])

    after = read_token_info()
    if after.exp > before.exp:
        gained_s = after.exp - before.exp
        return (
            True,
            f"refreshed: exp advanced {gained_s}s -> {after.remaining_s / 86400:.1f}d remaining",
        )
    return (
        False,
        f"no-op (exp unchanged at {before.remaining_s / 86400:.1f}d remaining); probe rc={proc.returncode}",
    )


def run_once(threshold_s: int = REFRESH_THRESHOLD_S) -> int:
    """Single check. Returns process exit code."""
    info = read_token_info()
    days = info.remaining_s / 86_400
    if info.remaining_s > threshold_s:
        log.info(
            "token healthy: %.1fd remaining (>%.1fd threshold); no refresh",
            days,
            threshold_s / 86_400,
        )
        return 0
    log.info("token below threshold (%.1fd remaining); refreshing under flock", days)
    ok, msg = _flocked_refresh()
    if ok:
        log.info("refresh OK: %s", msg)
        return 0
    log.error("refresh FAILED: %s", msg)
    return 1


def main(argv: list[str]) -> int:
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--threshold-days", type=float, default=REFRESH_THRESHOLD_S / 86_400)
    p.add_argument("--once", action="store_true", help="single check and exit (else loop)")
    p.add_argument("--interval-s", type=int, default=3600, help="loop interval (default 1h)")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    threshold = int(args.threshold_days * 86_400)

    if args.once:
        return run_once(threshold)

    while True:
        try:
            run_once(threshold)
        except Exception:
            log.exception("refresh loop iteration failed")
        time.sleep(args.interval_s)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
