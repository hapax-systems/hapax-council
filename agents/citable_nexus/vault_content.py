"""Vault content ingest for citable-nexus pages.

Reads markdown source files from the operator vault at
``~/Documents/Personal/30-areas/hapax/{manifesto,refusal-brief}.md``
and converts them to HTML for the renderer's ``/manifesto`` and
``/refusal-brief`` pages. Override the vault dir via
``HAPAX_VAULT_HAPAX_DIR``.

Constitutional posture: vault content is operator-authored and
already public-archive-published elsewhere (Manifesto via
omg.lol weblog; Refusal Brief via Zenodo concept-DOI). The renderer
re-exposes it at the citable-nexus front door without modification.

Markdown converter: minimal inline implementation. Handles ``#``
through ``####`` headings, paragraphs, ``-`` / ``*`` bulleted lists,
``` `inline code` ``` spans, ``[text](url)`` links, and code fences
``` ```...``` ```. No table support, no nested-list support — the
operator's source files are flat. If the vault evolves to need
richer rendering, swap to ``markdown-it-py`` as a dep then.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_VAULT_HAPAX_DIR = Path.home() / "Documents" / "Personal" / "30-areas" / "hapax"
"""Default vault path for Hapax-area markdown sources."""

VAULT_HAPAX_DIR_ENV = "HAPAX_VAULT_HAPAX_DIR"
"""Env var that overrides the vault dir at build time."""


@dataclass(frozen=True)
class VaultDocument:
    """One markdown source from the vault."""

    slug: str
    """Filename stem (e.g. ``manifesto`` for ``manifesto.md``)."""
    markdown: str
    """Raw markdown source. Empty when the file is absent."""
    available: bool
    """``True`` when the source file exists; ``False`` triggers
    the placeholder render path."""


def _vault_dir() -> Path:
    """Resolve the active vault dir from env or default."""
    env = os.environ.get(VAULT_HAPAX_DIR_ENV, "").strip()
    return Path(env) if env else DEFAULT_VAULT_HAPAX_DIR


def read_vault_document(slug: str) -> VaultDocument:
    """Read ``<vault_dir>/<slug>.md``; safe-fallback when absent.

    Returns a :class:`VaultDocument` with ``available=False`` and
    empty markdown when the file does not exist or is unreadable —
    the renderer then emits a Phase-1 placeholder rather than
    failing the build.
    """
    path = _vault_dir() / f"{slug}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return VaultDocument(slug=slug, markdown="", available=False)
    return VaultDocument(slug=slug, markdown=text, available=True)


# ── Minimal markdown → HTML ───────────────────────────────────────────


_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$")
_BULLET_RE = re.compile(r"^[-*]\s+(.+)$")
_FENCE_RE = re.compile(r"^```(?:[\w-]+)?$")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _esc(text: str) -> str:
    """HTML escape — minimal, mirrors renderer._esc."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _render_inline(text: str) -> str:
    """Inline-span pass: escape, then re-introduce link + code spans.

    Order matters: escape first so ``<`` in plain text doesn't read
    as a tag, then unescape inside the recovered ``<a>`` / ``<code>``
    elements where we own the surrounding markup.
    """
    out = _esc(text)

    def _code_repl(m: re.Match[str]) -> str:
        return f"<code>{m.group(1)}</code>"

    def _link_repl(m: re.Match[str]) -> str:
        # Inner text is already escaped; href needs its own light
        # validation but we accept whatever the operator put in the
        # vault (vault content is operator-controlled).
        href = m.group(2).replace('"', "%22")
        return f'<a href="{href}">{m.group(1)}</a>'

    out = _INLINE_CODE_RE.sub(_code_repl, out)
    out = _LINK_RE.sub(_link_repl, out)
    return out


def markdown_to_html(markdown: str) -> str:
    """Render flat markdown to HTML via the minimal inline converter.

    Recognized block-level elements: ``# / ## / ### / ####`` headings,
    ``-`` or ``*`` bulleted lists, ``` ``` ``` code fences, blank-line-
    separated paragraphs. Inline: ``code`` spans, ``[text](url)`` links.
    Anything else is treated as a plain paragraph.
    """
    out_lines: list[str] = []
    i = 0
    lines = markdown.splitlines()
    in_list = False
    in_fence = False
    fence_buffer: list[str] = []
    paragraph_buffer: list[str] = []

    def _flush_paragraph() -> None:
        nonlocal paragraph_buffer
        if paragraph_buffer:
            joined = " ".join(paragraph_buffer).strip()
            if joined:
                out_lines.append(f"<p>{_render_inline(joined)}</p>")
            paragraph_buffer = []

    def _flush_list() -> None:
        nonlocal in_list
        if in_list:
            out_lines.append("</ul>")
            in_list = False

    while i < len(lines):
        line = lines[i]
        if _FENCE_RE.match(line):
            if in_fence:
                out_lines.append(f"<pre><code>{_esc(chr(10).join(fence_buffer))}</code></pre>")
                fence_buffer = []
                in_fence = False
            else:
                _flush_paragraph()
                _flush_list()
                in_fence = True
            i += 1
            continue

        if in_fence:
            fence_buffer.append(line)
            i += 1
            continue

        if not line.strip():
            _flush_paragraph()
            _flush_list()
            i += 1
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            _flush_paragraph()
            _flush_list()
            level = len(heading.group(1))
            text = heading.group(2).strip()
            out_lines.append(f"<h{level}>{_render_inline(text)}</h{level}>")
            i += 1
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            _flush_paragraph()
            if not in_list:
                out_lines.append("<ul>")
                in_list = True
            out_lines.append(f"  <li>{_render_inline(bullet.group(1).strip())}</li>")
            i += 1
            continue

        # Default: accumulate into the current paragraph.
        _flush_list()
        paragraph_buffer.append(line.strip())
        i += 1

    _flush_paragraph()
    _flush_list()
    if in_fence and fence_buffer:
        out_lines.append(f"<pre><code>{_esc(chr(10).join(fence_buffer))}</code></pre>")

    return "\n".join(out_lines)


__all__ = [
    "DEFAULT_VAULT_HAPAX_DIR",
    "VAULT_HAPAX_DIR_ENV",
    "VaultDocument",
    "markdown_to_html",
    "read_vault_document",
]
