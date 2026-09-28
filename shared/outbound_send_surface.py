"""Outbound-message send surfaces: detection and the per-diff verdict.

The outbound_message_egress_sensitive release class's evidence
(RELEASE_MITIGATION_CHECKS, shared/sdlc_lifecycle.py) is a CI check that NAMES
every send surface a diff adds, removes or changes, and FAILS on a new send path
the reviewed registry (config/outbound-send-surfaces.yaml) does not name.

A "send vector" here is mail or a message leaving for a person: an SMTP
library, a Gmail API ``messages``/``drafts`` send or draft creation, or the
Gmail REST send endpoint. The vocabulary and the AST approach come from
tests/test_mail_monitor_credential_scoped_send_guard.py (prior art). That guard
is scoped by credential. This scan is scoped by diff, so it is tighter where the
credential scope was its filter:
- ``messages.create`` is not a Gmail method (it is the LLM SDK call shape);
- ``send_message`` counts only in a file that imports an SMTP library (the relay
  bus has its own ``send_message``).

It is a lower bound over what it can parse and match. Other channels are not
matched, including chat and social APIs and anything reached only through
dynamic dispatch. The review-team quorum the class also requires is the semantic
layer, the same trust split as the billing class.
"""

from __future__ import annotations

import ast
import io
import tokenize
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final, Literal

SMTP_MODULES: Final[frozenset[str]] = frozenset({"smtplib", "aiosmtplib"})
SMTP_SEND_FUNCS: Final[frozenset[str]] = frozenset({"sendmail", "send_message"})
GMAIL_ANCHORS: Final[frozenset[str]] = frozenset({"messages", "drafts"})
REST_SEND_FRAGMENTS: Final[tuple[str, ...]] = ("/messages/send", "/drafts/send")
#: Non-Python executables: a line naming any of these is a send vector.
SCRIPT_SEND_MARKERS: Final[tuple[str, ...]] = (
    *REST_SEND_FRAGMENTS,
    "sendmail",
    "msmtp",
    "smtp://",
    "smtps://",
)
SCRIPT_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".sh", ".bash", ".zsh", ".fish", ".js", ".mjs", ".ts", ".rb", ".pl", ".php"}
)
#: Paths outside the scan. Tests hold fixtures, not deployable send paths.
#: Docs describe vectors. The two gate files necessarily name every shape they hunt.
EXEMPT_PREFIXES: Final[tuple[str, ...]] = ("tests/", "docs/")
EXEMPT_PATHS: Final[frozenset[str]] = frozenset(
    {"shared/outbound_send_surface.py", "scripts/check-outbound-send-surface-diff.py"}
)
REGISTRY_PATH: Final[str] = "config/outbound-send-surfaces.yaml"


class UnparseableSource(ValueError):
    """A Python file in scope could not be decoded or parsed. Never skipped."""


def in_scope(path: str) -> bool:
    token = path.strip()
    if not token or token in EXEMPT_PATHS:
        return False
    if token.startswith(EXEMPT_PREFIXES):
        return False
    return not token.lower().endswith((".md", ".rst", ".txt"))


def _attr_chain(node: ast.AST) -> list[str]:
    names: list[str] = []
    cur: ast.AST | None = node
    while cur is not None:
        if isinstance(cur, ast.Attribute):
            names.append(cur.attr)
            cur = cur.value
        elif isinstance(cur, ast.Call):
            cur = cur.func
        else:
            if isinstance(cur, ast.Name):
                names.append(cur.id)
            break
    return names


def _gmail_aliases(tree: ast.AST) -> set[str]:
    """Names bound to a ``messages()``/``drafts()`` resource, followed to a fixpoint."""
    aliases: set[str] = set()
    grew = True
    while grew:
        grew = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            chain = set(_attr_chain(node.value))
            if not (GMAIL_ANCHORS & chain or aliases & chain):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id not in aliases:
                    aliases.add(target.id)
                    grew = True
    return aliases


def _python_vectors(source: bytes, path: str) -> frozenset[str]:
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(source).readline)
        tree = ast.parse(source.decode(encoding), filename=path)
    except (SyntaxError, UnicodeDecodeError, LookupError, ValueError) as exc:
        raise UnparseableSource(f"{path}: {type(exc).__name__}: {exc}") from exc
    smtp_imported = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            smtp_imported |= any(a.name.split(".")[0] in SMTP_MODULES for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            smtp_imported |= node.module.split(".")[0] in SMTP_MODULES
    vectors: set[str] = {"smtp-import"} if smtp_imported else set()
    aliases = _gmail_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name in SMTP_SEND_FUNCS and smtp_imported:
                vectors.add("smtp-send")
            elif isinstance(func, ast.Attribute) and func.attr in {"send", "create"}:
                chain = set(_attr_chain(func))
                if func.attr == "send" and (GMAIL_ANCHORS & chain or aliases & chain):
                    vectors.add("gmail-api-send")
                elif func.attr == "create" and "drafts" in chain:
                    vectors.add("gmail-api-draft")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if any(fragment in node.value for fragment in REST_SEND_FRAGMENTS):
                vectors.add("gmail-rest-send")
    return frozenset(vectors)


def _is_script(path: str, source: bytes, *, executable: bool) -> bool:
    suffix = "." + path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
    if suffix in SCRIPT_SUFFIXES:
        return True
    return not suffix and executable and source.startswith(b"#!")


def send_vectors(path: str, source: bytes, *, executable: bool = False) -> frozenset[str]:
    """The send vectors one file image holds. Empty for out-of-scope or inert files."""
    if not in_scope(path) or b"\x00" in source[:8192]:
        return frozenset()
    if path.endswith(".py"):
        return _python_vectors(source, path)
    if not _is_script(path, source, executable=executable):
        return frozenset()
    text = source.decode("utf-8", "replace")
    if any(marker in text for marker in SCRIPT_SEND_MARKERS):
        return frozenset({"script-send"})
    return frozenset()


@dataclass(frozen=True)
class SurfaceChange:
    path: str
    kind: Literal["added", "removed", "changed"]
    base_vectors: frozenset[str]
    head_vectors: frozenset[str]
    registered: bool


@dataclass(frozen=True)
class SendSurfaceVerdict:
    changes: tuple[SurfaceChange, ...]
    unparseable: tuple[str, ...]
    registered_in_diff: tuple[str, ...] = field(default=())

    @property
    def unreviewed(self) -> tuple[SurfaceChange, ...]:
        return tuple(c for c in self.changes if c.kind != "removed" and not c.registered)

    @property
    def ok(self) -> bool:
        return not self.unreviewed and not self.unparseable


def assess_diff(
    changed: Mapping[str, tuple[str | None, bytes | None, bytes | None, bool, bool]],
    *,
    base_registry: frozenset[str],
    head_registry: frozenset[str],
) -> SendSurfaceVerdict:
    """Classify each changed path's send surface.

    ``changed`` maps the head path to ``(base_path, base_bytes, head_bytes,
    base_executable, head_executable)``. Each image is classified with its own
    side's executable bit. A missing side is ``None`` ONLY for an added or deleted
    file. A caller that cannot read a side the diff says exists must refuse, never
    pass ``None``: absence reads as "no send surface".
    Only a surface that still exists at head can be unreviewed. A new send path
    must be registered at head. The registry diff is named, and the review
    quorum the class requires judges it.
    """
    changes: list[SurfaceChange] = []
    unparseable: list[str] = []
    for path, (base_path, base_bytes, head_bytes, base_exec, head_exec) in sorted(changed.items()):
        try:
            base = (
                send_vectors(base_path or path, base_bytes, executable=base_exec)
                if base_bytes is not None
                else frozenset()
            )
            head = (
                send_vectors(path, head_bytes, executable=head_exec)
                if head_bytes is not None
                else frozenset()
            )
        except UnparseableSource as exc:
            unparseable.append(str(exc))
            continue
        if not base and not head:
            continue
        kind: Literal["added", "removed", "changed"] = (
            "added" if not base else "removed" if not head else "changed"
        )
        changes.append(
            SurfaceChange(
                path=path,
                kind=kind,
                base_vectors=base,
                head_vectors=head,
                registered=path in head_registry,
            )
        )
    return SendSurfaceVerdict(
        changes=tuple(changes),
        unparseable=tuple(unparseable),
        registered_in_diff=tuple(sorted(head_registry - base_registry)),
    )


def parse_registry(text: str | None) -> frozenset[str]:
    """The registry's reviewed paths. A malformed registry is an error, never empty."""
    import yaml

    if text is None:
        return frozenset()
    data = yaml.safe_load(text)
    surfaces = data.get("surfaces") if isinstance(data, dict) else None
    if not isinstance(surfaces, list):
        raise ValueError(f"{REGISTRY_PATH}: expected a top-level `surfaces:` list")
    paths: set[str] = set()
    for entry in surfaces:
        if not (isinstance(entry, dict) and entry.get("path") and entry.get("reason")):
            raise ValueError(f"{REGISTRY_PATH}: every surface needs a `path` and a `reason`")
        paths.add(str(entry["path"]).strip())
    return frozenset(paths)
