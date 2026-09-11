#!/usr/bin/env python3
"""Write agent env from the explicitly selected FileStore or helper source.

HAPAX_SECRETS_SOURCE defaults to filestore: import the reins install pin
(~/.local/share/reins/current/api) and validate its private root and .key.
The helper source delegates to hapax-secret (HAPAX_SECRET_HELPER overrides
its executable), with a 20-second timeout per operation and no retry or fallback.
Presence checks, reads and strict value validation finish before either env
file is touched. Each file uses temp + os.replace; these are two replacements,
so a failure publishing authority can leave the common file refreshed.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import NamedTuple, NoReturn


def _prerequisite_failure(problem: str, repair: str) -> NoReturn:
    sys.stderr.write(f"secret_env_from_filestore: {problem}. Next action: {repair}.\n")
    raise SystemExit(2)


_SOURCE = os.environ.get("HAPAX_SECRETS_SOURCE", "filestore")
_HELPER_TIMEOUT_SECONDS = 20
_HELPER_CONTRACT_PROBE = "hapax-contract-probe-" + "x" * 256
_HELPER_CONTRACT_REPAIR = "install the corrected helper (reins#39) and bump the pin, then rerun"
_HELPER_REPAIR = (
    "check HAPAX_SECRETS_HOST reachability and FileStore enrollment on that host; "
    "install executable hapax-secret on PATH or set HAPAX_SECRET_HELPER and rerun"
)
_STORE_REPAIR = "restore service-user read access and valid FileStore entries and .key and rerun"
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

    try:
        store = default_store()
    except Exception as exc:
        _prerequisite_failure(f"FileStore initialization {type(exc).__name__}", _STORE_REPAIR)
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


def _decoded_value(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="strict")
    # Only helper framing may be removed; FileStore bytes are the stored value.
    if _SOURCE == "helper":
        text = text.removesuffix("\n")
    if any(unicodedata.category(char) == "Cc" for char in text):
        raise ValueError("control character")
    return text


def _validate_env_value(env_name: str, value: str, entry: str) -> None:
    # systemd.exec(5) EnvironmentFile= interprets quotes and backslashes and
    # may log invalid Unicode values. Emit only this conservative ASCII subset.
    # Empty values retain their existing meaning; one helper LF was removed
    # by _decoded_value. Literals receive the same validation before either write.
    for char in value:
        codepoint = ord(char)
        if 0xFDD0 <= codepoint <= 0xFDEF or (codepoint & 0xFFFF) in (0xFFFE, 0xFFFF):
            problem = "Unicode noncharacter"
        elif unicodedata.category(char) == "Cc":
            problem = "control character"
        elif char.isspace():
            problem = "whitespace"
        elif not 0x21 <= codepoint <= 0x7E:
            problem = "non-ASCII character"
        elif char in "\"'\\#;":
            problem = "EnvironmentFile syntax character"
        else:
            continue
        _prerequisite_failure(
            f"EnvironmentFile {env_name} ({entry}) invalid {problem}",
            "use printable ASCII without whitespace, quotes, backslashes, # or ; and rerun",
        )


def _helper_call(name: str, *, where: bool = False) -> subprocess.CompletedProcess[bytes]:
    operation = "--where" if where else "GET"
    label = "contract_probe" if name == _HELPER_CONTRACT_PROBE else name
    try:
        return subprocess.run(
            [_helper, "--where", name] if where else [_helper, name],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=_HELPER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        _prerequisite_failure(
            f"helper {label} {operation} timeout after {_HELPER_TIMEOUT_SECONDS}s", _HELPER_REPAIR
        )
    except OSError:
        _prerequisite_failure(f"helper {label} {operation} launch OSError", _HELPER_REPAIR)


class _HelperFailure(NamedTuple):
    reason: str
    detail: str
    exception: str | None = None


def _helper_unreadable(result: subprocess.CompletedProcess[bytes], name: str) -> str | None:
    # Never echo helper material, even an apparent exception-class field.
    # Reins catches OSError; accept only the built-in class names it can report.
    if result.returncode != 2 or result.stdout:
        return None
    for exception in (
        "OSError",
        "PermissionError",
        "FileNotFoundError",
        "IsADirectoryError",
        "NotADirectoryError",
        "BlockingIOError",
        "InterruptedError",
        "TimeoutError",
        "ConnectionError",
        "BrokenPipeError",
        "ConnectionAbortedError",
        "ConnectionRefusedError",
        "ConnectionResetError",
        "ChildProcessError",
        "ProcessLookupError",
    ):
        if result.stderr == f"unreadable: {name} ({exception})\n".encode():
            return exception
    return None


def _probe_helper_contract() -> bool:
    # Both Reins revisions accept this name, whose path component exceeds the
    # store host's NAME_MAX. No entry is created/read: stat fails ENAMETOOLONG.
    # reins#39 alone maps that failure to exit 2/unreadable in BOTH operations.
    # An old helper, an unreachable host, or any other response cannot attest
    # absence. Probe the selected executable (including its remote forwarding),
    # never a local import, version label, or an assumed installed pin.
    where = _helper_call(_HELPER_CONTRACT_PROBE, where=True)
    get = _helper_call(_HELPER_CONTRACT_PROBE)
    return (
        _helper_unreadable(where, _HELPER_CONTRACT_PROBE) == "OSError"
        and _helper_unreadable(get, _HELPER_CONTRACT_PROBE) == "OSError"
    )


def _helper_value(name: str) -> bytes | None | _HelperFailure:
    where = _helper_call(name, where=True)
    if exception := _helper_unreadable(where, name):
        return _HelperFailure("helper_unreadable", "--where unreadable", exception)
    present = where.returncode == 0 and where.stdout == b"filestore\n" and not where.stderr
    absent = (
        where.returncode == 1
        and where.stdout == f"not found: {name}\n".encode()
        and not where.stderr
    )
    if not (present or absent):
        # Classify complete responses only; helper output is untrusted material.
        backend = {b"pass\n": "pass", b"filestore\n": "filestore", b"": "empty"}.get(
            where.stdout, "unknown"
        )
        return _HelperFailure(
            "helper_response_unrecognized",
            f"--where transport exit {where.returncode} backend={backend} (unrecognized response)",
        )

    result = _helper_call(name)
    if exception := _helper_unreadable(result, name):
        return _HelperFailure("helper_unreadable", "GET unreadable", exception)
    not_found = (
        f"not found in FileStore: {name}. legal_next: run hapax-secret (TTY put) via reins.\n"
    ).encode()
    if result.returncode == 1 and result.stdout == b"" and result.stderr == not_found:
        if present:
            return _HelperFailure(
                "helper_unreadable", "GET present-but-unreadable; --where backend=filestore"
            )
        if not _HELPER_DISTINGUISHES_ABSENCE:
            return _HelperFailure(
                "helper_absence_unverifiable", "GET and --where absence unverified"
            )
        return None
    if result.returncode != 0:
        return _HelperFailure("helper_transport_failure", f"GET transport exit {result.returncode}")
    if absent:
        return _HelperFailure(
            "helper_response_disagreement", "GET disagrees with --where backend=absent"
        )
    return result.stdout


def _verified_store_entries() -> dict[str, Path]:
    # FileStore's public has/get conflate absence and faults. Until a public
    # distinguishing API exists, verify its documented root/<name>.bin layout
    # for EVERY requested name at startup, before any entry is read.
    try:
        blob_path = getattr(store, "_blob_path", None)
        if not callable(blob_path):
            raise ValueError
        root = store.root.resolve(strict=True)
        entries = {}
        for name in (
            *REQUIRED.values(),
            *OPTIONAL.values(),
            "hapax-public-gate-authority-hmac-key",
        ):
            entry = blob_path(name)
            if (
                not isinstance(entry, Path)
                or entry.absolute() != store.root.absolute() / f"{name}.bin"
            ):
                raise ValueError
            # Resolve the parent, not the blob: the latter's own stat errors
            # must retain their read-failure classification (e.g. ELOOP).
            if entry.parent.resolve(strict=True) != root:
                raise ValueError
            entries[name] = entry
        return entries
    except Exception as exc:
        _prerequisite_failure(
            f"FileStore reason=filestore_layout_unverified exception={type(exc).__name__}",
            "install a FileStore with verified root/<name>.bin layout and callable _blob_path, "
            "then rerun",
        )


def _store_value(name: str, env_name: str) -> str | None:
    if _SOURCE == "helper":
        raw = _helper_value(name)
        repair = _HELPER_REPAIR
        if isinstance(raw, _HelperFailure):
            if raw.reason == "helper_absence_unverifiable":
                repair = _HELPER_CONTRACT_REPAIR
            exception = f" exception={raw.exception}" if raw.exception else ""
            _prerequisite_failure(
                f"helper {name} {raw.detail}; reason={raw.reason}{exception}", repair
            )
    else:
        repair = _STORE_REPAIR
        try:
            # Pinned FileStore exposes its validated root/<safe-name>.bin path.
            # has()/get() use is_file(), which can suppress stat errors. Only
            # the entry stat's FileNotFoundError demonstrates optional absence.
            entry = _STORE_ENTRIES[name]
            try:
                entry.stat()
            except FileNotFoundError:
                return None
            raw = store.get(name)
        except Exception as exc:
            _prerequisite_failure(f"FileStore {name} unreadable ({type(exc).__name__})", repair)
        if raw is None:
            _prerequisite_failure(f"FileStore {name} present-but-unreadable", repair)
    if raw is None:
        return None
    try:
        return _decoded_value(raw)
    except UnicodeDecodeError:
        _prerequisite_failure(f"{_SOURCE} {name} ({env_name}) decoding failure (UTF-8)", repair)
    except ValueError:
        _prerequisite_failure(f"{_SOURCE} {name} ({env_name}) invalid control character", repair)


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


def _prior_file_state(path: Path) -> str:
    try:
        path.stat()
    except FileNotFoundError:
        return "absent"
    except OSError as exc:
        return f"unknown (exception={type(exc).__name__})"
    return "retained"


if _SOURCE == "helper":
    _HELPER_DISTINGUISHES_ABSENCE = _probe_helper_contract()
else:
    _STORE_ENTRIES = _verified_store_entries()


uid = os.getuid()
out = Path(os.environ.get("HAPAX_SECRETS_ENV_PATH", f"/run/user/{uid}/hapax-secrets.env"))
resolved: dict[str, str] = {}
missing: list[str] = []
for env_name, spec in REQUIRED.items():
    val = _store_value(spec, env_name)
    if val is None:
        missing.append(spec)
        continue
    resolved[env_name] = val
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
    val = _store_value(spec, env_name)
    if val is None:
        continue
    lines.append(f"{env_name}={val}")
for env_name, value in LITERALS.items():
    lines.append(f"{env_name}={value}")

# Resolve this prerequisite before publishing either file; project it only
# after the common environment is complete, without adding it to OPTIONAL.
authority_value = _store_value(
    "hapax-public-gate-authority-hmac-key", "HAPAX_PUBLIC_GATE_AUTHORITY_HMAC_KEY"
)
authority_out = out.with_name("hapax-public-gate-authority.env")
for line in lines:
    env_name, value = line.split("=", 1)
    _validate_env_value(env_name, value, REQUIRED.get(env_name, OPTIONAL.get(env_name, "literal")))
if authority_value is not None:
    _validate_env_value(
        "HAPAX_PUBLIC_GATE_AUTHORITY_HMAC_KEY",
        authority_value,
        "hapax-public-gate-authority-hmac-key",
    )
try:
    _write_env(out, lines)
except OSError:
    prior_common = _prior_file_state(out)
    _prerequisite_failure(
        f"common replacement failed at {out}; prior common file {prior_common}; authority untouched",
        "restore write access to the environment directory and rerun",
    )
print(f"wrote {out} keys={len(lines)} source={_SOURCE} backend={_backend}")
try:
    if authority_value is None:
        authority_out.unlink(missing_ok=True)
    else:
        _write_env(
            authority_out,
            [f"HAPAX_PUBLIC_GATE_AUTHORITY_HMAC_KEY={authority_value}"],
        )
except OSError:
    prior_authority = _prior_file_state(authority_out)
    action = "removal" if authority_value is None else "replacement"
    _prerequisite_failure(
        f"common refreshed; authority {action} failed at {authority_out}; "
        f"prior authority file {prior_authority}; HAPAX_PUBLIC_GATE_AUTHORITY_HMAC_KEY",
        "restore write access to the authority environment path and rerun",
    )
