"""Explicitly cleared Markdown inputs and a small, escaped Markdown renderer.

Readability is not publication permission. Optional vault documents are unavailable
unless their exact resolved paths appear in a supplied allowlist. Relative entries
are resolved beside that allowlist, not against the caller's working directory.
No authorship or prior publication is inferred from a path or its contents.
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
    """True only when the source is explicitly cleared and readable."""


def _vault_dir() -> Path:
    """Resolve the active vault dir from env or default."""
    env = os.environ.get(VAULT_HAPAX_DIR_ENV, "").strip()
    return Path(env) if env else DEFAULT_VAULT_HAPAX_DIR


def read_cleared_inputs(allowlist: Path | None = None) -> frozenset[Path]:
    """Validate every listed file before rendering; an absent list clears nothing."""
    if allowlist is None:
        return frozenset()
    allowlist = allowlist.expanduser().resolve()
    paths = set()
    try:
        lines = allowlist.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"Cannot read --cleared-inputs {allowlist}: {exc}") from exc
    for line in lines:
        if not line.strip():
            continue
        path = Path(line.strip()).expanduser()
        if not path.is_absolute():
            path = allowlist.parent / path
        path = path.resolve()
        try:
            # Validate even listed inputs that no page currently consumes.
            path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"Cleared input refused: {path}: {exc}") from exc
        paths.add(path)
    return frozenset(paths)


def read_vault_document(
    slug: str, *, cleared_inputs: frozenset[Path] = frozenset()
) -> VaultDocument:
    """Read only an explicitly cleared document, refusing a failed cleared read."""
    path = (_vault_dir() / f"{slug}.md").resolve()
    if path not in cleared_inputs:
        return VaultDocument(slug=slug, markdown="", available=False)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"Cleared input refused: {path}: {exc}") from exc
    return VaultDocument(slug=slug, markdown=text, available=True)


# ── Minimal markdown → HTML ───────────────────────────────────────────


_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$")
_BULLET_RE = re.compile(r"^[-*]\s+(.+)$")
_FENCE_RE = re.compile(r"^```(?:[\w-]+)?$")


def _esc(text: str) -> str:
    """HTML escape — minimal, mirrors renderer._esc."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _render_inline(text: str) -> str:
    """Render code, links and strong emphasis without interpreting code contents."""
    from urllib.parse import urlsplit

    pattern = re.compile(r"`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)|\*\*(.+?)\*\*")
    parts: list[str] = []
    end = 0
    for match in pattern.finditer(text):
        parts.append(_esc(text[end : match.start()]))
        code, label, href, strong = match.groups()
        if code is not None:
            parts.append(f"<code>{_esc(code)}</code>")
        elif href is not None:
            if urlsplit(href).scheme.lower() not in ("", "https", "http", "mailto"):
                parts.append(_esc(label))
            else:
                parts.append(f'<a href="{_esc(href)}">{_esc(label)}</a>')
        else:
            parts.append(f"<strong>{_esc(strong)}</strong>")
        end = match.end()
    parts.append(_esc(text[end:]))
    return "".join(parts)


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
    "read_cleared_inputs",
]
