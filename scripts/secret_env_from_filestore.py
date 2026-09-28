#!/usr/bin/env python3
"""Write agent env from reins FileStore (not pass). Estate path = shipped path.

Runs from the source-activation worktree. Imports FileStore from the reins
install pin (~/.local/share/reins/current/api), not a mutable checkout.

Validates FileStore prerequisites (.key present, private ownership/modes,
backend is file, required names resolvable) before touching either env file.
Each file uses temp + os.replace so a failed write preserves its prior file.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import NoReturn

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
        "is not file. Next action: do not point this unit at the pass backend.\n"
    )
    raise SystemExit(2)


def _prerequisite_failure(problem: str, repair: str) -> NoReturn:
    sys.stderr.write(f"secret_env_from_filestore: {problem}. Next action: {repair}.\n")
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
    "HAPAX_PUBLIC_GATE_AUTHORITY_HMAC_KEY": "hapax-public-gate-authority-hmac-key",
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


def _integrity_error_types() -> tuple[type[BaseException], ...]:
    """``SecretIntegrityError`` where the installed reins carries it, else empty.

    Resolved dynamically so this unit works against a reins that predates the typed error
    and one that has it, with no version check to go stale.
    """

    from k0 import key_capture

    error = getattr(key_capture, "SecretIntegrityError", None)
    if isinstance(error, type) and issubclass(error, BaseException):
        return (error,)
    return ()


_INTEGRITY_ERRORS = _integrity_error_types()


def _integrity_failure(name: str) -> None:
    sys.stderr.write(
        f"secret_env_from_filestore: integrity_failed: {name}. The stored blob is present "
        "but did not verify — corruption or tampering, NOT an absent secret. Next action: "
        "run `hapax-secret --audit`; do not re-put over it until the audit says what "
        "happened. The previous environment file is left in place.\n"
    )
    raise SystemExit(3)


def _read_secret(name: str) -> bytes | None:
    """The stored bytes, ``None`` when genuinely ABSENT, and a refusal when corrupt.

    Two ways a blob fails to verify, and both must be told apart from absence:

    * reins PR 44 and later RAISE ``SecretIntegrityError``;
    * the reins installed today returns ``None`` for BOTH an absent blob and one that will
      not unwrap, so a tampered secret is indistinguishable from a missing one — and for an
      OPTIONAL name it was silently skipped, which is the single outcome an integrity check
      exists to prevent. ``has()`` is true exactly when the file is on disk, so
      ``has() and get() is None`` is present-but-unreadable regardless of which reins is
      installed.

    Exit code 3, distinct from the 2 used for missing/misconfigured: "put this secret" and
    "audit this store" are different operator actions.
    """

    try:
        value = store.get(name)
    except _INTEGRITY_ERRORS:
        _integrity_failure(name)
        raise  # unreachable; keeps the type checker honest about the None-return contract
    except OSError:
        _prerequisite_failure(
            f"FileStore prerequisite {name} unreadable at {store.root}",
            "restore service-user read access to the FileStore entry and .key and rerun",
        )
    if value is None and store.has(name):
        _integrity_failure(name)
    return value


def _absence_demonstrated(name: str) -> bool:
    """True only when the entry's own blob path is shown missing by an explicit stat.

    ``has()`` is ``Path.is_file()``, which also answers False for errors such as ELOOP, so a
    ``None`` from ``_read_secret`` is not by itself proof that the entry is absent. Anything
    other than FileNotFoundError on the store's own path (no path mapping, another OSError,
    something present) is not demonstrated absence.
    """

    blob_path = getattr(store, "_blob_path", None)
    if not callable(blob_path):
        return False
    try:
        os.lstat(blob_path(name))
    except FileNotFoundError:
        return True
    except (OSError, ValueError):
        return False
    return False


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
    val = _read_secret(spec)
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
optional_values: dict[str, bytes | None] = {}
for env_name, spec in OPTIONAL.items():
    val = _read_secret(spec)
    optional_values[env_name] = val
    if val is None:
        continue
    lines.append(f"{env_name}={_first_line(val)}")
for env_name, value in LITERALS.items():
    lines.append(f"{env_name}={value}")

# The public-gate signing key is also projected alone into a dedicated file, so its
# signing consumers load exactly one variable and never the provider routing above.
# Every decision about it is made before either file is published: an empty value never
# replaces a working key, and only demonstrated absence removes the dedicated file.
AUTHORITY_ENV = "HAPAX_PUBLIC_GATE_AUTHORITY_HMAC_KEY"
authority_name = OPTIONAL[AUTHORITY_ENV]
authority_value = optional_values[AUTHORITY_ENV]
authority_out = out.with_name("hapax-public-gate-authority.env")
if authority_value is None:
    if not _absence_demonstrated(authority_name):
        _prerequisite_failure(
            f"FileStore entry {authority_name} could not be shown absent at {store.root}",
            "restore service-user access to the FileStore root and entry "
            f"(hapax-secret --where {authority_name}) and rerun; both env files are kept",
        )
elif not _first_line(authority_value).strip():
    _prerequisite_failure(
        f"FileStore entry {authority_name} is empty",
        f"re-put {authority_name} with hapax-secret (TTY put) and rerun; both env files are kept",
    )
_write_env(out, lines)
if authority_value is None:
    authority_out.unlink(missing_ok=True)
    authority_outcome = f"removed {authority_out} (entry absent)"
else:
    _write_env(authority_out, [f"{AUTHORITY_ENV}={_first_line(authority_value)}"])
    authority_outcome = f"wrote {authority_out}"
print(f"wrote {out} keys={len(lines)} backend={store.backend_id}; {authority_outcome}")
