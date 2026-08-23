#!/usr/bin/env python3
"""Write agent env from reins FileStore (not pass). Estate path = shipped path.

Runs from the source-activation worktree. Imports FileStore from the reins
install pin (~/.local/share/reins/current/api), not a mutable checkout.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REINS_API = Path.home() / ".local/share/reins/current/api"
sys.path.insert(0, str(_REINS_API))
try:
    from k0.key_capture import default_store
except ImportError as exc:
    sys.stderr.write(
        "secret_env_from_filestore: FileStore not importable "
        f"({exc}). Next action: install reins FileStore at "
        "~/.local/share/reins/current (reins#35) and rerun.\n"
    )
    raise SystemExit(2) from exc

store = default_store()
if store.backend_id != "file":
    sys.stderr.write(
        f"secret_env_from_filestore: default_store backend_id={store.backend_id!r} "
        "is not file. Next action: do not point this unit at PassStore.\n"
    )
    raise SystemExit(2)

_LITELLM = os.environ.get(
    "HAPAX_LITELLM_BASE_URL", "https://hapax-podium.tailf9491.ts.net:4000"
)
_LANGFUSE = os.environ.get("HAPAX_LANGFUSE_HOST", "http://127.0.0.1:3000")

REQUIRED: dict[str, str] = {
    "LITELLM_API_KEY": "litellm-master-key",
    "LANGFUSE_PUBLIC_KEY": "langfuse-public-key",
    "LANGFUSE_SECRET_KEY": "langfuse-secret-key",
    "HF_TOKEN": "api-huggingface",
    "MISTRAL_API_KEY": "api-mistral",
    "OPENAI_API_KEY": "api-openai",
}
OPTIONAL: dict[str, str] = {
    "SOUNDCLOUD_CLIENT_ID": "soundcloud-client-id",
    "SOUNDCLOUD_CLIENT_SECRET": "soundcloud-client-secret",
    "HAPAX_SOUNDCLOUD_BANKED_URL": "soundcloud-banked-url-canonical",
    "HAPAX_MASTODON_ACCESS_TOKEN": "mastadon-access-token",
    "HAPAX_BLUESKY_APP_PASSWORD": "bluesky-operator-app-password",
    "HAPAX_BLUESKY_DID": "bluesky-operator-did",
    "HAPAX_IA_ACCESS_KEY": "ia-access-key",
    "HAPAX_IA_SECRET_KEY": "ia-secret-key",
    "HAPAX_OSF_TOKEN": "osf-api-token",
    "HAPAX_PHILARCHIVE_SESSION_COOKIE": "philarchive-session-cookie",
    "HAPAX_PHILARCHIVE_AUTHOR_ID": "philarchive-author-id",
    "HAPAX_ZENODO_TOKEN": "zenodo-api-token",
    "HAPAX_OPERATOR_ORCID": "orcid-orcid",
    "KO_FI_WEBHOOK_VERIFICATION_TOKEN": "kofi-verification-token",
}
LITERALS: dict[str, str] = {
    "LITELLM_BASE_URL": _LITELLM,
    "LITELLM_API_BASE": _LITELLM,
    "ANTHROPIC_API_KEY": "",  # filled from FileStore litellm below
    "ANTHROPIC_BASE_URL": _LITELLM,
    "ANTHROPIC_AUTH_TOKEN": "",
    "LANGFUSE_HOST": _LANGFUSE,
    "HAPAX_SOUNDCLOUD_USERNAME": os.environ.get("HAPAX_SOUNDCLOUD_USERNAME", "oudepode"),
    "HAPAX_MASTODON_INSTANCE_URL": os.environ.get(
        "HAPAX_MASTODON_INSTANCE_URL", "https://mastodon.social"
    ),
    "HAPAX_BLUESKY_HANDLE": os.environ.get(
        "HAPAX_BLUESKY_HANDLE", "hapax-oudepode.bsky.social"
    ),
}


def _first_line(raw: bytes) -> str:
    return raw.decode("utf-8", "replace").split("\n", 1)[0]


uid = os.getuid()
out = Path(f"/run/user/{uid}/hapax-secrets.env")
lines: list[str] = []
missing: list[str] = []
for env_name, spec in REQUIRED.items():
    val = store.get(spec)
    if val is None:
        missing.append(spec)
        continue
    lines.append(f"{env_name}={_first_line(val)}")
if missing:
    sys.stderr.write(
        "secret_env_from_filestore: missing "
        + ",".join(missing)
        + ". Next action: FileStore.put those names (hapax-secret TTY put).\n"
    )
    raise SystemExit(2)

litellm = store.get("litellm-master-key")
assert litellm is not None
litellm_text = _first_line(litellm)
LITERALS["ANTHROPIC_API_KEY"] = litellm_text
LITERALS["ANTHROPIC_AUTH_TOKEN"] = litellm_text
for env_name, spec in OPTIONAL.items():
    val = store.get(spec)
    if val is None:
        continue
    lines.append(f"{env_name}={_first_line(val)}")
for env_name, value in LITERALS.items():
    lines.append(f"{env_name}={value}")

out.write_text("\n".join(lines) + "\n")
os.chmod(out, 0o600)
print(f"wrote {out} keys={len(lines)} backend={store.backend_id}")
