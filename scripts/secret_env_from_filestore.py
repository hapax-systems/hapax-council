#!/usr/bin/env python3
"""Write agent env from the explicitly selected FileStore or helper source.

HAPAX_SECRETS_SOURCE defaults to filestore: import the reins install pin
(~/.local/share/reins/current/api) and validate its private root and .key.
The helper source delegates to hapax-secret (HAPAX_SECRET_HELPER overrides
its executable), with a 20-second timeout per name and no retry or fallback.
All lookups finish before either env file is touched. Each file uses temp +
os.replace so a failed write preserves its prior file.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import NoReturn


def _prerequisite_failure(problem: str, repair: str) -> NoReturn:
    sys.stderr.write(f"secret_env_from_filestore: {problem}. Next action: {repair}.\n")
    raise SystemExit(2)


_SOURCE = os.environ.get("HAPAX_SECRETS_SOURCE", "filestore")
_HELPER_TIMEOUT_SECONDS = 20
_HELPER_REPAIR = (
    "check HAPAX_SECRETS_HOST reachability and FileStore enrollment on that host; "
    "install executable hapax-secret on PATH or set HAPAX_SECRET_HELPER and rerun"
)
if _SOURCE not in ("filestore", "helper"):
    _prerequisite_failure(
        "HAPAX_SECRETS_SOURCE must be filestore or helper",
        "set HAPAX_SECRETS_SOURCE=filestore or HAPAX_SECRETS_SOURCE=helper "
        "(or unset it for filestore) and rerun",
    )

if _SOURCE == "helper":
    _helper = shutil.which(os.environ.get("HAPAX_SECRET_HELPER", "hapax-secret"))
    if _helper is None:
        _prerequisite_failure("helper executable missing or not executable", _HELPER_REPAIR)
    _backend = "filestore-via-helper"
else:
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
    try:
        for path, mode in ((store.root, 0o700), (key_path, 0o600)):
            info = path.stat()
            if info.st_uid != os.getuid():
                _prerequisite_failure(
                    f"FileStore prerequisite {path} has wrong owner",
                    "restore ownership to the service user and rerun",
                )
            if stat.S_IMODE(info.st_mode) != mode:
                _prerequisite_failure(
                    f"FileStore prerequisite {path} has wrong mode",
                    f"restore private permissions with chmod {mode:o} {path} and rerun",
                )
        if not store.root.is_dir() or not key_path.is_file():
            _prerequisite_failure(
                f"FileStore root must be a directory and .key a file at {store.root}",
                "repair the FileStore root and .key types and rerun",
            )
    except FileNotFoundError:
        _prerequisite_failure(
            f"FileStore root or .key missing at {store.root}",
            "enroll FileStore (reins#35) then hapax-secret TTY put for required names; "
            "do not start this unit until .key exists",
        )
    except OSError:
        _prerequisite_failure(
            f"FileStore root or .key unreadable at {store.root}",
            "restore service-user read access to the FileStore root and .key and rerun",
        )
    _backend = store.backend_id

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
    "ANTHROPIC_API_KEY": "",  # filled from the selected litellm source below
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


def _helper_value(name: str) -> bytes | None:
    try:
        result = subprocess.run(
            [_helper, name],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=_HELPER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        _prerequisite_failure(
            f"helper {name} timeout after {_HELPER_TIMEOUT_SECONDS}s", _HELPER_REPAIR
        )
    except OSError:
        _prerequisite_failure(f"helper {name} launch OSError", _HELPER_REPAIR)

    # hapax_secret._do_get: absence is rc=1, empty stdout and this diagnostic.
    # Other rc=1 failures (including Python exceptions) must not remove files.
    absent = (
        f"not found in FileStore: {name}. legal_next: run hapax-secret (TTY put) via reins.\n"
    ).encode()
    if result.returncode == 1 and result.stdout == b"" and result.stderr == absent:
        return None
    if result.returncode != 0:
        _prerequisite_failure(f"helper {name} transport exit {result.returncode}", _HELPER_REPAIR)
    try:
        # Validate all stdout before _first_line; never replace decoding errors
        # in helper output or expose captured output/exception details in logs.
        result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        _prerequisite_failure(f"helper {name} decoding failure (UTF-8)", _HELPER_REPAIR)
    return result.stdout


def _store_value(name: str) -> bytes | None:
    if _SOURCE == "helper":
        return _helper_value(name)
    try:
        return store.get(name)
    except OSError:
        _prerequisite_failure(
            f"FileStore prerequisite {name} unreadable at {store.root}",
            "restore service-user read access to the FileStore entry and .key and rerun",
        )


def _write_env(out: Path, lines: list[str]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.name}.tmp")
    payload = memoryview(("\n".join(lines) + "\n").encode("utf-8"))
    # 0600 EnvironmentFile on /run/user tmpfs (systemd hapax-secrets.service).
    # Not durable storage; FileStore remains the store.
    fd = -1
    try:
        tmp.unlink(missing_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        while payload:
            written = os.write(fd, payload)  # codeql[py/clear-text-storage-sensitive-data]
            if written <= 0:
                raise OSError("EnvironmentFile write made no progress")
            payload = payload[written:]
        os.close(fd)
        fd = -1
        os.replace(tmp, out)
    except Exception:
        if fd >= 0:
            os.close(fd)
        tmp.unlink(missing_ok=True)
        raise


uid = os.getuid()
out = Path(os.environ.get("HAPAX_SECRETS_ENV_PATH", f"/run/user/{uid}/hapax-secrets.env"))
resolved: dict[str, str] = {}
missing: list[str] = []
for env_name, spec in REQUIRED.items():
    val = _store_value(spec)
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
    val = _store_value(spec)
    if val is None:
        continue
    lines.append(f"{env_name}={_first_line(val)}")
for env_name, value in LITERALS.items():
    lines.append(f"{env_name}={value}")

# Resolve this prerequisite before publishing either file; project it only
# after the common environment is complete, without adding it to OPTIONAL.
authority_value = _store_value("hapax-public-gate-authority-hmac-key")
authority_out = out.with_name("hapax-public-gate-authority.env")
_write_env(out, lines)
print(f"wrote {out} keys={len(lines)} source={_SOURCE} backend={_backend}")
if authority_value is None:
    authority_out.unlink(missing_ok=True)
else:
    _write_env(
        authority_out,
        [f"HAPAX_PUBLIC_GATE_AUTHORITY_HMAC_KEY={_first_line(authority_value)}"],
    )
