"""The one estate secret resolver: environment -> FileStore -> ``hapax-secret``. Never pass.

Operator ruling 2026-09-16, verbatim: *"Pass and gopass should never be used going forward to
manage secrets."* The data already lives in the reins FileStore, so no consumer needs pass to
keep working. This module is the Python half of the move; ``scripts/lib/secret.sh`` is the
shell half. **There is no pass path here and there must never be one** — a resolver that falls
back to pass is what keeps pass installed, and the fallback would be reached exactly when the
FileStore is having a bad day, which is the worst moment to widen what the code will read.

Resolution order, narrowest first:

1. **A named environment variable**, when non-empty. This is how systemd units are fed
   (``EnvironmentFile=%t/hapax-secrets.env``) and how a caller overrides for a test. An
   exported-but-empty variable is NOT a value — treating it as one is the classic silent
   empty-credential bug, where a service starts, authenticates as nobody, and fails somewhere
   far away from the cause.
2. **The FileStore**, through the reins pin (``k0.key_capture.default_store``). The backend is
   asserted to be ``file``: if ``default_store()`` ever returns the ``pass`` backend that still
   exists in that module, this refuses rather than reading it.
3. **``hapax-secret <name>``**, for hosts that do not carry the reins API. The CLI performs its
   own name mapping, so there is still exactly one implementation of ``name_of`` on each path —
   never a private reimplementation here, which is the duplicated-derivation defect this estate
   has already paid for once in the exec-auth host resolver.

Then a typed :class:`SecretUnavailable` carrying the name and a legal next action — never a
bare ``KeyError`` and never ``None`` masquerading as a value.

**A corrupt blob is not a missing secret.** Since reins PR 44, ``FileStore.get`` raises
``SecretIntegrityError`` where it used to return ``None``. That is a tampering or corruption
signal and it stops the resolution here: it does not fall through to the CLI, because a failure
path that reaches FURTHER than the primary would let a tampered blob be silently replaced by
whatever another path returns. Failure handling does less, not more.

Values are never logged, never placed on argv, and never interpolated into an exception
message. The only thing that appears in an error is the NAME and what to do about it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = [
    "SecretIntegrityFailed",
    "SecretUnavailable",
    "get_secret",
    "has_secret",
    "list_secret_names",
    "put_instruction",
    "put_secret",
    "reins_api_path",
    "secret_store_name",
    "secret_store_root",
]

#: Where ``hapax-secret`` looks for the reins API, in its order.
_REINS_API_CANDIDATES = (
    Path.home() / ".local" / "share" / "reins" / "current" / "api",
    Path.home() / "projects" / "reins" / "api",
)

# The CLI's name, not a credential: the pre-push scanner's "Secret Keyword" rule fires on
# any SECRET-named constant bound to a string literal. Nothing in this module ever holds a
# value in a module-level name.
_HAPAX_SECRET_CLI = "hapax-secret"  # pragma: allowlist secret
_CLI_TIMEOUT_SECONDS = 20.0


class SecretUnavailable(RuntimeError):
    """A secret could not be resolved. Carries the name and a legal next action."""

    def __init__(self, name: str, legal_next: str) -> None:
        super().__init__(f"secret unavailable: {name}. Next action: {legal_next}")
        self.name = name
        self.legal_next = legal_next


class SecretIntegrityFailed(SecretUnavailable):
    """The stored blob failed its integrity check: corruption or tampering, not absence.

    A subclass of :class:`SecretUnavailable` so existing handlers still catch it, but distinct
    so a caller that wants to escalate tampering can. Resolution STOPS here.
    """

    def __init__(self, name: str) -> None:
        super().__init__(
            name,
            f"run `{_HAPAX_SECRET_CLI} --audit` — the stored blob for {name} failed its "
            "integrity check, which is corruption or tampering, not a missing secret. "
            "Do not re-put over it until the audit says what happened.",
        )


def reins_api_path() -> Path | None:
    """The reins API directory on this host, or ``None`` where it is not installed."""

    override = os.environ.get("HAPAX_REINS_API", "").strip()
    candidates = (Path(override), *_REINS_API_CANDIDATES) if override else _REINS_API_CANDIDATES
    for candidate in candidates:
        if (candidate / "hapax_secret.py").is_file():
            return candidate
    return None


@lru_cache(maxsize=1)
def _name_of() -> Callable[[str], str]:
    """``hapax_secret.name_of`` — the ONE name mapping, imported, never reimplemented.

    ``a/b/c`` -> ``a-b-c`` with three explicit aliases (litellm/master-key,
    langfuse/public-key, langfuse/secret-key). A private copy here would drift from the CLI's
    and resolve the same operator-facing name to two different blobs depending on which path
    ran -- the exact shape of the duplicated exec-auth host derivation this estate has already
    repaired once.
    """

    api = reins_api_path()
    if api is None:
        raise SecretUnavailable(
            "<name mapping>",
            "install the reins API on this host, or resolve through the "
            f"`{_HAPAX_SECRET_CLI}` CLI which carries its own mapping",
        )
    if str(api) not in sys.path:
        sys.path.insert(0, str(api))
    from hapax_secret import name_of

    return name_of


def secret_store_name(raw: str) -> str:
    """The FileStore blob name for an operator-facing secret name."""

    return _name_of()(raw)


def _integrity_error_types() -> tuple[type[BaseException], ...]:
    """``SecretIntegrityError`` where the installed reins carries it (PR 44), else empty.

    Resolved dynamically so this module works against a reins that predates the typed error
    and against one that has it, without a version check that would go stale.
    """

    api = reins_api_path()
    if api is None:
        return ()
    if str(api) not in sys.path:
        sys.path.insert(0, str(api))
    try:
        import k0.key_capture as key_capture
    except ImportError:
        return ()
    error = getattr(key_capture, "SecretIntegrityError", None)
    if isinstance(error, type) and issubclass(error, BaseException):
        return (error,)
    return ()


def _file_store() -> Any | None:
    """The reins FileStore, or ``None`` where the API is not installed on this host."""

    api = reins_api_path()
    if api is None:
        return None
    if str(api) not in sys.path:
        sys.path.insert(0, str(api))
    from k0.key_capture import default_store

    return default_store()


def _file_backend_store(name: str) -> Any | None:
    """The FileStore, ``None`` without the module, and a typed refusal for any other backend.

    Not a fallthrough. If the default store is ever the pass backend, reading or writing it
    would quietly reinstate the dependency this row exists to remove.
    """

    store = _file_store()
    if store is None:
        return None
    backend = getattr(store, "backend_id", "")
    if backend != "file":
        raise SecretUnavailable(
            name,
            f"the reins default store is {backend!r}, not 'file'; point it at the FileStore "
            "— this resolver will not touch a pass backend",
        )
    return store


def _from_store(name: str) -> str | None:
    store = _file_backend_store(name)
    if store is None:
        return None
    mapped = secret_store_name(name)
    try:
        value = store.get(mapped)
    except _integrity_error_types() as exc:  # noqa: B014 - dynamic, may be empty
        raise SecretIntegrityFailed(name) from exc
    if value is None:
        return None
    return value.decode("utf-8", errors="strict").rstrip("\r\n")


def _from_cli(name: str) -> str | None:
    """``hapax-secret <name>``, for hosts without the reins API.

    The CLI maps the name itself, so the mapping still has exactly one implementation on this
    path. A non-zero exit is "not resolvable here", not a crash; stderr is discarded rather
    than logged because the CLI is entitled to mention names this process should not echo.
    """

    try:
        completed = subprocess.run(
            [_HAPAX_SECRET_CLI, name],
            capture_output=True,
            timeout=_CLI_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8", errors="strict").rstrip("\r\n") or None


def get_secret(name: str, *, env: str | None = None, required: bool = True) -> str | None:
    """Resolve one secret. Returns the value, or ``None`` when ``required=False``.

    Args:
        name: the operator-facing name, e.g. ``"langfuse/secret-key"``.
        env: an environment variable consulted first, when non-empty.
        required: raise :class:`SecretUnavailable` instead of returning ``None``.

    Raises:
        SecretUnavailable: nothing resolved and ``required`` is true.
        SecretIntegrityFailed: the stored blob failed its integrity check. Raised whatever
            ``required`` is — a tampered blob is a fact worth interrupting for, and silently
            returning ``None`` would present tampering as absence.
        ValueError: ``name`` does not map to a legal blob name.
    """

    if env:
        from_env = os.environ.get(env, "")
        if from_env.strip():
            return from_env

    stored = _from_store(name)
    if stored is not None:
        return stored

    from_cli = _from_cli(name)
    if from_cli is not None:
        return from_cli

    if not required:
        return None
    raise SecretUnavailable(
        name,
        f"put it with `{_HAPAX_SECRET_CLI}` (TTY dialogue via reins)"
        + (f", or export {env}" if env else ""),
    )


def put_instruction(name: str) -> str:
    """The one operator next-action for a secret that is missing: how to put ``name``.

    Every remediation string, refusal detail and unblocker row that used to read
    ``pass insert <name>`` reads this instead, so the estate has exactly one place that knows
    how a secret is put. The CLI's put is a TTY dialogue (name, secret, confirm — through reins),
    so the instruction is the bare command plus the name the operator will type into it. The
    name is rendered as given: the dialogue applies the one name mapping itself, and this must
    stay importable on hosts (CI runners) that carry no reins module.
    """

    return f"{_HAPAX_SECRET_CLI}   # TTY put dialogue via reins; name: {name}"


def has_secret(name: str) -> bool:
    """Whether ``name`` is present, without ever reading its value.

    FileStore ``has`` where the module is installed; ``hapax-secret --where <name>`` elsewhere
    (exit 0 is presence). A backend that is not the FileStore refuses, as in :func:`get_secret`.
    """

    store = _file_backend_store(name)
    if store is not None:
        return bool(store.has(secret_store_name(name)))
    try:
        completed = subprocess.run(
            [_HAPAX_SECRET_CLI, "--where", name],
            capture_output=True,
            timeout=_CLI_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def put_secret(name: str, value: bytes) -> None:
    """Write ``value`` under ``name`` through the FileStore. Bootstrap and consent flows only.

    There is deliberately no CLI leg: ``hapax-secret``'s put is an operator TTY dialogue, and a
    daemon that cannot reach the FileStore must say so rather than pipe a credential into a
    subprocess. Values never appear in the exception.
    """

    if not isinstance(value, bytes | bytearray):
        raise TypeError("put_secret takes bytes; encode the value at the call site")
    store = _file_backend_store(name)
    if store is None:
        raise SecretUnavailable(
            name,
            "install the reins API on this host — a non-interactive put has no CLI path; "
            f"an operator can put it interactively with `{_HAPAX_SECRET_CLI}`",
        )
    try:
        store.put(secret_store_name(name), bytes(value))
    except OSError as exc:
        raise SecretUnavailable(
            name,
            f"the FileStore is not writable from this process ({type(exc).__name__}); "
            f"put it from the host with `{_HAPAX_SECRET_CLI}`",
        ) from exc


def secret_store_root() -> Path | None:
    """The FileStore's directory on this host, or ``None`` where the module is absent."""

    try:
        store = _file_backend_store("<root>")
    except SecretUnavailable:
        return None
    if store is None:
        return None
    root = getattr(store, "root", None)
    return Path(root) if root else None


def _names_in(root: Path) -> tuple[str, ...]:
    """Blob names under ``root``: ``<name>.bin`` stems, the layout ``hapax-secret --list`` reads."""

    if not root.is_dir():
        return ()
    return tuple(sorted(path.stem for path in root.glob("*.bin")))


def list_secret_names(root: Path | None = None) -> tuple[str, ...]:
    """The blob names present in the FileStore (mapped form, e.g. ``api-anthropic``), sorted.

    Names only, never values. ``root`` lists an explicit store directory (inventories over a
    given root, tests); otherwise the default FileStore where the module is installed, and
    ``hapax-secret --list`` elsewhere. An unreachable store lists as empty rather than raising:
    callers are inventories and health checks, which must degrade to "nothing present" instead
    of crashing.
    """

    if root is not None:
        return _names_in(root)
    try:
        store = _file_backend_store("<list>")
    except SecretUnavailable:
        return ()
    if store is not None:
        return _names_in(Path(getattr(store, "root", "")))
    try:
        completed = subprocess.run(
            [_HAPAX_SECRET_CLI, "--list"],
            capture_output=True,
            timeout=_CLI_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    if completed.returncode != 0:
        return ()
    text = completed.stdout.decode("utf-8", errors="strict")
    return tuple(sorted(line.strip() for line in text.splitlines() if line.strip()))
