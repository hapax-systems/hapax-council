#!/usr/bin/env python3
"""Write agent env from reins FileStore (not pass). Estate path = shipped path.

Installed live at ~/.local/lib/hapax/secret_env_from_filestore.py; this copy is
the council-tree producer so hapax-secrets.service can run from the activation
worktree.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / "projects" / "reins" / "api"))
try:
    from k0.key_capture import default_store
except ImportError as exc:
    sys.stderr.write(
        "secret_env_from_filestore: FileStore not importable "
        f"({exc}). Next action: keep reins#35 FileStore on PYTHONPATH "
        "(~/projects/reins/api) and rerun.\n"
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

mapping: dict[str, str] = {
    "LITELLM_API_KEY": "litellm-master-key",
    "LITELLM_BASE_URL": _LITELLM,
    "LITELLM_API_BASE": _LITELLM,
    "ANTHROPIC_API_KEY": "litellm-master-key",
    "ANTHROPIC_BASE_URL": _LITELLM,
    "ANTHROPIC_AUTH_TOKEN": "litellm-master-key",
    "LANGFUSE_PUBLIC_KEY": "langfuse-public-key",
    "LANGFUSE_SECRET_KEY": "langfuse-secret-key",
    "LANGFUSE_HOST": _LANGFUSE,
    "HF_TOKEN": "api-huggingface",
    "MISTRAL_API_KEY": "api-mistral",
    "OPENAI_API_KEY": "api-openai",
}

uid = os.getuid()
out = Path(f"/run/user/{uid}/hapax-secrets.env")
lines: list[str] = []
missing: list[str] = []
for env_name, spec in mapping.items():
    if spec.startswith("http"):
        lines.append(f"{env_name}={spec}")
        continue
    val = store.get(spec)
    if val is None:
        missing.append(spec)
        continue
    text = val.decode("utf-8", "replace").split("\n", 1)[0]
    lines.append(f"{env_name}={text}")

if missing:
    sys.stderr.write(
        "secret_env_from_filestore: missing "
        + ",".join(missing)
        + ". Next action: FileStore.put those names (hapax-secret TTY put).\n"
    )
    raise SystemExit(2)

out.write_text("\n".join(lines) + "\n")
os.chmod(out, 0o600)
print(f"wrote {out} keys={len(lines)} backend={store.backend_id}")
