"""The envelope declaration: everything a capability job may see, and nothing else.

One record for every kind of job (review, panel, witness, benchmark, fabric capability job). A job
imports nothing unless this record names it: no instruction-file walk-up, no user or project
memory, no MCP autoload, no project hooks or settings, and no host environment. The carrier that
enforces the record (bwrap on a host today; systemd units and rootless OCI in the fabric) is a
binding rendered from it, never a second declaration.

Design: frame/capability-dispatch-fabric-placement-20260925/DESIGN.md v1.3 section 3.2a
(sha256 69cd0546...), accepted 2026-09-25.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

HarnessId = Literal["claude", "codex", "agy", "grok", "kimi", "vibe", "opencode", "muse"]
BillingSurface = Literal["subscription", "api"]

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def _check_name(value: str) -> str:
    if not _NAME_RE.fullmatch(value):
        raise ValueError(
            f"{value!r} must match {_NAME_RE.pattern}; next action: use a lowercase name of "
            "letters, digits and hyphens"
        )
    return value


def _check_relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(
            f"{value!r} must be a relative path inside the job without '..'; next action: "
            "give the path relative to the job home or workdir"
        )
    return value


Name = Annotated[str, AfterValidator(_check_name)]
RelativePath = Annotated[str, AfterValidator(_check_relative)]


class DeclaredHook(BaseModel):
    """A hook the job runs, for example an estate governance gate. Bound read-only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Name
    event: str
    script: Path
    matcher: str = ""


class DeclaredMcpServer(BaseModel):
    """An MCP server the job may start. ``binds`` are host paths it needs, bound read-only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Name
    command: tuple[str, ...] = Field(min_length=1)
    binds: tuple[Path, ...] = ()


class CredentialBind(BaseModel):
    """A credential file or directory placed in the job home.

    ``writable`` is for harnesses that refresh a token by rename into their credential directory.
    Credentials never travel through ``env``, because environment values appear in the carrier's
    argument vector.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Path
    target: RelativePath
    writable: bool = False


class DeclaredFile(BaseModel):
    """A file placed read-only in the job home, for example a declared instruction file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Path
    target: RelativePath


class EnvelopeDeclaration(BaseModel):
    """What a capability job may see. Every import defaults to off."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    harness: HarnessId
    argv: tuple[str, ...] = Field(min_length=1)
    binaries: tuple[Path, ...] = ()
    workdir: Path | None = None
    workdir_writable: bool = False
    declared_work_files: tuple[RelativePath, ...] = ()
    home_files: tuple[DeclaredFile, ...] = ()
    credentials: tuple[CredentialBind, ...] = ()
    hooks: tuple[DeclaredHook, ...] = ()
    mcp_servers: tuple[DeclaredMcpServer, ...] = ()
    env: dict[str, str] = Field(default_factory=dict)
    spool: Path | None = None
    billing_surface: BillingSurface = "subscription"
