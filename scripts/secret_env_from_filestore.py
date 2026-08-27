#!/usr/bin/env python3
"""Write agent env from reins FileStore (not pass). Estate path = shipped path.

Runs from the source-activation worktree. Imports FileStore from the reins
install pin (~/.local/share/reins/current/api), not a mutable checkout.

Validates FileStore prerequisites (.key present, backend is file, required
names resolvable) before touching the destination env file. Writes via temp
+ os.replace so a failed run leaves the last valid environment in place.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REINS_API = Path(
    os.environ.get("HAPAX_REINS_API", "").strip()
    or str(Path.home() / ".local/share/reins/current/api")
)
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

key_path = store.root / ".key"
if not store.root.is_dir() or not key_path.is_file():
    sys.stderr.write(
        "secret_env_from_filestore: FileStore root or .key missing at "
        f"{store.root}. Next action: enroll FileStore (reins#35) then "
        "hapax-secret TTY put for required names; do not start this unit "
        "until .key exists.\n"
    )
    raise SystemExit(2)

_LITELLM = os.environ.get("HAPAX_LITELLM_BASE_URL", "https://hapax-podium.tailf9491.ts.net:4000")
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
    # GLM's Z.ai key. OPTIONAL rather than REQUIRED on purpose: this is a capability credential,
    # and putting it in REQUIRED would make hapax-secrets.service refuse to start on any host with
    # no GLM entitlement — fail-closed in the wrong place. When it is absent the GLM launcher falls
    # back to its legacy `pass` lookup and only then refuses.
    "HAPAX_GLMCP_API_KEY": "glmcp-api-key",
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
    "HAPAX_BLUESKY_HANDLE": os.environ.get("HAPAX_BLUESKY_HANDLE", "hapax-oudepode.bsky.social"),
}


def _first_line(raw: bytes) -> str:
    return raw.decode("utf-8", "replace").split("\n", 1)[0]


uid = os.getuid()
out = Path(os.environ.get("HAPAX_SECRETS_ENV_PATH", f"/run/user/{uid}/hapax-secrets.env"))
resolved: dict[str, str] = {}
missing: list[str] = []
for env_name, spec in REQUIRED.items():
    val = store.get(spec)
    if val is None:
        missing.append(spec)
        continue
    resolved[env_name] = _first_line(val)
if missing:
    sys.stderr.write(
        "secret_env_from_filestore: missing "
        + ",".join(missing)
        + ". Next action: FileStore.put those names (hapax-secret TTY put).\n"
    )
    raise SystemExit(2)

litellm_text = resolved["LITELLM_API_KEY"]
LITERALS["ANTHROPIC_API_KEY"] = litellm_text
LITERALS["ANTHROPIC_AUTH_TOKEN"] = litellm_text
lines: list[str] = [f"{env_name}={resolved[env_name]}" for env_name in REQUIRED]
for env_name, spec in OPTIONAL.items():
    val = store.get(spec)
    if val is None:
        continue
    lines.append(f"{env_name}={_first_line(val)}")
for env_name, value in LITERALS.items():
    lines.append(f"{env_name}={value}")

out.parent.mkdir(parents=True, exist_ok=True)
tmp = out.with_name(f".{out.name}.tmp")
payload = "\n".join(lines) + "\n"
# 0600 EnvironmentFile on /run/user tmpfs (systemd hapax-secrets.service).
# Not durable storage; FileStore remains the store.
fd = -1
try:
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(fd, payload.encode("utf-8"))  # codeql[py/clear-text-storage-sensitive-data]
    os.close(fd)
    fd = -1
    os.replace(tmp, out)
except Exception:
    if fd >= 0:
        os.close(fd)
    tmp.unlink(missing_ok=True)
    raise
print(f"wrote {out} keys={len(lines)} backend={store.backend_id}")
