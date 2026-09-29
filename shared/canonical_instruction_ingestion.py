"""Read the deployed canonical instruction binding for an invocation.

The installer receipt is a filesystem witness, not a native-load witness. Callers
must also observe the returned bytes in the exact child input they launch.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path


class InstructionIngestionError(ValueError):
    """An invocation cannot prove the current canonical body."""


@dataclass(frozen=True)
class CanonicalInstructions:
    body: bytes
    sha256: str
    native_body: bytes | None = None


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise InstructionIngestionError(f"missing instruction binding: {path}") from exc


def read_canonical_instructions(
    *,
    source_root: Path | None = None,
    operator_home: Path | None = None,
    native_binding: tuple[str, str] | None = None,
) -> CanonicalInstructions:
    """Require matching release source, installed receipt and actual home files.

    ``native_binding`` is (installer binding name, path relative to operator
    home). The exact home path must match the receipt; a copy in another home
    cannot satisfy this check.
    """

    root = source_root or Path(
        os.environ.get("HAPAX_SOURCE_ACTIVATE_WORKTREE")
        or Path.home() / ".cache/hapax/source-activation/worktree"
    )
    home = operator_home or Path.home()
    source = _read(root / "config/agent-instructions/AGENTS.md")
    if not source.strip():
        raise InstructionIngestionError("canonical instruction source is empty")
    digest = hashlib.sha256(source).hexdigest()
    installed = home / ".config/hapax/agent-instructions/AGENTS.md"
    receipt_path = home / ".config/hapax/agent-instructions/current.json"
    try:
        receipt = json.loads(_read(receipt_path))
        files = {entry["binding"]: entry for entry in receipt["files"]}
    except (ValueError, KeyError, TypeError) as exc:
        raise InstructionIngestionError("malformed instruction installation receipt") from exc

    def checked(binding: str, path: Path, expected_body: bytes | None = None) -> bytes:
        entry = files.get(binding)
        if not isinstance(entry, dict) or entry.get("path") != str(path):
            raise InstructionIngestionError(f"{binding} instruction receipt names wrong home")
        if path.is_symlink():
            raise InstructionIngestionError(f"{binding} instruction binding leaves declared home")
        body = _read(path)
        if hashlib.sha256(body).hexdigest() != entry.get("sha256"):
            raise InstructionIngestionError(f"{binding} instruction binding is stale or changed")
        if expected_body is not None and body != expected_body:
            raise InstructionIngestionError(f"{binding} instruction binding differs from release")
        return body

    checked("shared", installed, source)
    native_body = None
    if native_binding is not None:
        name, relative_path = native_binding
        native_body = checked(name, home / relative_path)
        if native_body.count(source) != 1:
            raise InstructionIngestionError(f"{name} binding lacks one exact canonical body")
    return CanonicalInstructions(source, digest, native_body)
