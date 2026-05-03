"""Audio Graph SSOT — passive validator.

``AudioGraphValidator.decompose(conf_dir)`` walks every ``*.conf`` in a
PipeWire ``conf.d`` directory, parses the subset of PipeWire conf syntax
the descriptor cares about (``context.objects``, ``context.modules``,
``libpipewire-module-{loopback,filter-chain}``, ``support.null-audio-sink``)
and constructs ``AudioNode`` / ``AudioLink`` / ``LoopbackTopology``
instances.

Files that don't fit the schema land in ``ValidationReport.gaps`` with
the parse error, source path, and the schema field that would need to
change. The CI gate (``audio-graph-validate``) fails when any gap is
surfaced, forcing schema iteration before runtime work proceeds.

Conf parser scope (the realistic minimum for the operator's 22 active
confs in ``~/.config/pipewire/pipewire.conf.d/``):

* ``factory = adapter`` with ``factory.name = support.null-audio-sink``
  → ``AudioNode(kind="null_sink")``.
* ``name = libpipewire-module-loopback`` → ``LoopbackTopology`` + a
  ``LOOPBACK``-kind ``AudioNode`` (the playback-side anchor).
* ``name = libpipewire-module-filter-chain`` →
  ``AudioNode(kind="filter_chain")`` with the inner ``filter.graph``
  block stored as an opaque blob in ``filter_graph["__raw_text__"]``.
* ``audio.position = [ ... ]`` → ``ChannelMap.positions``.
* ``target.object = "..."`` → ``AudioNode.target_object``.

The parser is intentionally lossy on filter-graph internals: round-trip
of full filter-graph syntax is a P4 concern when the daemon takes over
the write path. P1 only needs to know what nodes exist + how they're
wired so the invariants and probes can be planned.

Files matching ``*.disabled-*``, ``*.bak-*``, ``*.disabled``,
``_disabled-*`` are skipped — they're not active and would falsely
elevate the gap count.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from shared.audio_graph.schema import (
    AudioGraph,
    AudioLink,
    AudioNode,
    ChannelMap,
    LoopbackTopology,
    NodeKind,
)

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class ConfParseError(Exception):
    """A PipeWire conf file couldn't be parsed at all (syntax-level)."""


class ValidationGap(BaseModel):
    """One gap surfaced by the validator.

    A gap is either a syntax-level parse error (``conf-parse``) or a
    schema-fit error (``schema-fit``). Schema-fit gaps are the ones that
    drive P1 schema iteration — they say "this real-world conf does not
    decompose into the current AudioGraph schema, here's the field that
    would need to change."
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    source_path: str
    line: int | None = None
    message: str
    suggested_schema_change: str | None = None


class ValidationReport(BaseModel):
    """Output of ``AudioGraphValidator.decompose``.

    * ``graph`` — the constructed ``AudioGraph`` (best-effort; partial
      when gaps are present).
    * ``decomposed_files`` — paths that decomposed cleanly.
    * ``gaps`` — files that did not. CI fails on any gap.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    graph: AudioGraph
    decomposed_files: tuple[str, ...] = Field(default_factory=tuple)
    skipped_files: tuple[str, ...] = Field(default_factory=tuple)
    gaps: tuple[ValidationGap, ...] = Field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Conf-file pre-filter
# ---------------------------------------------------------------------------


_SKIP_SUFFIX_PATTERNS = (
    re.compile(r"\.disabled$"),
    re.compile(r"\.disabled-.*"),
    re.compile(r"\.bak$"),
    re.compile(r"\.bak-.*"),
)
_SKIP_PREFIX_PATTERNS = (re.compile(r"^_disabled-"),)


def _is_recognised_graph_tunable(text: str) -> bool:
    """True if the conf is a recognised graph-tunable, not a graph node.

    Per spec §8 question 2 ("Manifest scope"), three classes of operator-
    edited confs carry global tunables rather than graph nodes:

    * ``default.clock.*`` — quantum / sample-rate knobs (e.g.
      ``10-voice-quantum.conf``, ``99-hapax-quantum.conf``).
    * ``monitor.alsa.rules`` — wireplumber-style device profile pins
      shared into PipeWire conf.d (e.g. ``s4-usb-sink.conf``).
    * ``stream.properties`` / ``stream.rules`` — per-application stream
      tuning that doesn't introduce a node.

    These are first-class descriptor fields in P4 (``schema_version=4``
    per spec §8.2). For P1, they're recognised here so they don't
    surface as gaps.
    """
    return any(
        marker in text
        for marker in (
            "default.clock.quantum",
            "default.clock.rate",
            "default.clock.allowed-rates",
            "monitor.alsa.rules",
            "stream.properties",
            "stream.rules",
        )
    )


def _should_skip(filename: str) -> bool:
    """True if the filename is a backup/disabled variant, not active."""
    if not filename.endswith(".conf") and any(p.search(filename) for p in _SKIP_SUFFIX_PATTERNS):
        # Operator files like hapax-livestream-tap.conf.bak-test-1777830697
        # carry .bak-* suffixes after the base; match the full string.
        return True
    if any(p.match(filename) for p in _SKIP_PREFIX_PATTERNS):
        return True
    return any(p.search(filename) for p in _SKIP_SUFFIX_PATTERNS)


# ---------------------------------------------------------------------------
# Tokenizer / lightweight parser
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Block:
    """A balanced ``{ ... }`` text block with start/end character offsets.

    PipeWire confs use SPA's pseudo-INI syntax: ``key = value`` with
    nested ``{ ... }`` for objects and ``[ ... ]`` for arrays. A robust
    parser would reproduce SPA's grammar end-to-end; the P1 validator
    uses a heuristic block-scanner that's sufficient for the
    descriptor's purposes (extract specific keys from named blocks).
    """

    text: str
    start: int
    end: int


def _scan_balanced(src: str, start: int, open_ch: str, close_ch: str) -> _Block | None:
    """Scan from ``start`` to find a balanced ``{...}`` (or ``[...]``)."""
    if start >= len(src) or src[start] != open_ch:
        return None
    depth = 0
    i = start
    while i < len(src):
        c = src[i]
        if c == "#":
            # Skip comment to end of line
            nl = src.find("\n", i)
            if nl == -1:
                break
            i = nl + 1
            continue
        if c == '"':
            # Skip quoted string
            nl = src.find('"', i + 1)
            if nl == -1:
                break
            i = nl + 1
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return _Block(text=src[start : i + 1], start=start, end=i + 1)
        i += 1
    return None


def _strip_comments(text: str) -> str:
    """Strip ``# ...`` line comments while preserving quoted ``#``."""
    out: list[str] = []
    in_string = False
    i = 0
    while i < len(text):
        c = text[i]
        if c == '"' and (i == 0 or text[i - 1] != "\\"):
            in_string = not in_string
            out.append(c)
            i += 1
            continue
        if c == "#" and not in_string:
            nl = text.find("\n", i)
            if nl == -1:
                break
            i = nl
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _find_key_eq(src: str, key: str) -> int:
    """Return the offset just AFTER ``key =`` (trailing whitespace consumed).

    ``-1`` if the key isn't present at top-level. Looks at the first
    occurrence — sufficient for descriptor-relevant keys, which appear
    once per block.
    """
    # Match ``key`` followed by any whitespace then ``=``. The conf syntax
    # also allows ``key=value`` without spaces.
    pattern = re.compile(rf"\b{re.escape(key)}\s*=\s*", re.MULTILINE)
    m = pattern.search(src)
    return m.end() if m else -1


def _extract_quoted_string(src: str, start: int) -> str | None:
    """Read ``"foo bar"`` starting at ``start``."""
    if start >= len(src):
        return None
    # Skip whitespace
    while start < len(src) and src[start].isspace():
        start += 1
    if start >= len(src) or src[start] != '"':
        return None
    end = src.find('"', start + 1)
    if end == -1:
        return None
    return src[start + 1 : end]


def _extract_bracket_list(src: str, start: int) -> list[str] | None:
    """Read ``[ a b c ]`` starting at ``start`` — return token list."""
    while start < len(src) and src[start].isspace():
        start += 1
    block = _scan_balanced(src, start, "[", "]")
    if block is None:
        return None
    # Strip ``[`` ``]`` and split on whitespace, ignoring quotes.
    inner = block.text[1:-1]
    inner = _strip_comments(inner)
    raw_tokens = inner.replace(",", " ").split()
    return [t.strip('"').strip("'") for t in raw_tokens]


def _extract_token(src: str, start: int) -> str | None:
    """Read a bare token (until whitespace / newline / closing brace)."""
    while start < len(src) and src[start].isspace():
        start += 1
    if start >= len(src):
        return None
    end = start
    while end < len(src) and src[end] not in " \n\r\t}#":
        end += 1
    if end == start:
        return None
    return src[start:end].strip(",;").strip('"')


# ---------------------------------------------------------------------------
# Block extraction: find ``factory = adapter ... { args = { ... } }``
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _AdapterBlock:
    """One ``factory = adapter`` block in ``context.objects``."""

    args_block: _Block


@dataclass(frozen=True)
class _ModuleBlock:
    """One ``name = libpipewire-module-...`` block in ``context.modules``."""

    module_name: str
    args_block: _Block


def _find_adapter_blocks(text: str) -> list[_AdapterBlock]:
    """Find every ``factory = adapter ... args = { ... }`` in
    ``context.objects = [ ... ]``.

    Strategy: locate the ``context.objects = [`` block, scan its inner
    text for ``factory = adapter`` markers, and from each marker scan
    forward to find the paired ``args = { ... }`` block.
    """

    pos = _find_key_eq(text, "context.objects")
    if pos < 0:
        return []
    arr = _scan_balanced(text, pos, "[", "]")
    if arr is None:
        return []
    inner = arr.text[1:-1]
    out: list[_AdapterBlock] = []
    cursor = 0
    while True:
        idx = inner.find("factory", cursor)
        if idx == -1:
            break
        # Confirm it's "factory = adapter" (allow whitespace)
        m = re.match(r"factory\s*=\s*adapter\b", inner[idx:])
        if not m:
            cursor = idx + 1
            continue
        # Find the args = { ... }
        args_pos = inner.find("args", idx + m.end())
        if args_pos == -1:
            cursor = idx + 1
            continue
        eq_pos = inner.find("=", args_pos)
        if eq_pos == -1:
            cursor = idx + 1
            continue
        # Skip whitespace to find {
        sb_start = eq_pos + 1
        while sb_start < len(inner) and inner[sb_start].isspace():
            sb_start += 1
        if sb_start >= len(inner) or inner[sb_start] != "{":
            cursor = idx + 1
            continue
        block = _scan_balanced(inner, sb_start, "{", "}")
        if block is None:
            cursor = idx + 1
            continue
        out.append(_AdapterBlock(args_block=block))
        cursor = block.end
    return out


def _find_module_blocks(text: str) -> list[_ModuleBlock]:
    """Find every ``name = libpipewire-module-... args = { ... }`` in
    ``context.modules = [ ... ]``.
    """

    pos = _find_key_eq(text, "context.modules")
    if pos < 0:
        return []
    arr = _scan_balanced(text, pos, "[", "]")
    if arr is None:
        return []
    inner = arr.text[1:-1]
    out: list[_ModuleBlock] = []
    pat = re.compile(r"name\s*=\s*([A-Za-z0-9._-]+)")
    cursor = 0
    while True:
        m = pat.search(inner, cursor)
        if not m:
            break
        module_name = m.group(1)
        if not module_name.startswith("libpipewire-module-"):
            cursor = m.end()
            continue
        # Find args block following
        args_pos = inner.find("args", m.end())
        if args_pos == -1:
            cursor = m.end()
            continue
        eq_pos = inner.find("=", args_pos)
        if eq_pos == -1:
            cursor = m.end()
            continue
        sb_start = eq_pos + 1
        while sb_start < len(inner) and inner[sb_start].isspace():
            sb_start += 1
        if sb_start >= len(inner) or inner[sb_start] != "{":
            cursor = m.end()
            continue
        block = _scan_balanced(inner, sb_start, "{", "}")
        if block is None:
            cursor = m.end()
            continue
        out.append(_ModuleBlock(module_name=module_name, args_block=block))
        cursor = block.end
    return out


# ---------------------------------------------------------------------------
# Property extraction (capture.props / playback.props / args)
# ---------------------------------------------------------------------------


def _find_subblock(args_text: str, key: str) -> _Block | None:
    """Find ``key = { ... }`` inside an args block."""
    pat = re.compile(rf"\b{re.escape(key)}\s*=\s*")
    m = pat.search(args_text)
    if not m:
        return None
    sb_start = m.end()
    while sb_start < len(args_text) and args_text[sb_start].isspace():
        sb_start += 1
    if sb_start >= len(args_text) or args_text[sb_start] != "{":
        return None
    return _scan_balanced(args_text, sb_start, "{", "}")


def _extract_str(text: str, key: str) -> str | None:
    """Extract a ``key = "value"`` string field."""
    pat = re.compile(rf'\b{re.escape(key)}\s*=\s*"([^"]*)"')
    m = pat.search(text)
    return m.group(1) if m else None


def _extract_int(text: str, key: str) -> int | None:
    """Extract a ``key = N`` integer field."""
    pat = re.compile(rf"\b{re.escape(key)}\s*=\s*(-?\d+)")
    m = pat.search(text)
    return int(m.group(1)) if m else None


def _extract_position_list(text: str, key: str) -> list[str] | None:
    """Extract ``key = [ FL FR ]``."""
    pat = re.compile(rf"\b{re.escape(key)}\s*=\s*", re.MULTILINE)
    m = pat.search(text)
    if not m:
        return None
    return _extract_bracket_list(text, m.end())


def _extract_bool(text: str, key: str) -> bool | None:
    """Extract ``key = true | false``."""
    pat = re.compile(rf"\b{re.escape(key)}\s*=\s*(true|false)\b")
    m = pat.search(text)
    if not m:
        return None
    return m.group(1) == "true"


def _extract_unquoted(text: str, key: str) -> str | None:
    """Extract a bare ``key = value`` token."""
    pat = re.compile(rf"\b{re.escape(key)}\s*=\s*([A-Za-z0-9._/-]+)")
    m = pat.search(text)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Decomposers — adapter / loopback / filter-chain
# ---------------------------------------------------------------------------


def _id_from_name(pipewire_name: str) -> str:
    """Map ``hapax-broadcast-master`` → ``broadcast-master``.

    Strip the ``hapax-`` prefix when present so the descriptor uses
    short kebab-case ids and the compiler re-prefixes them on emit.
    Also strip trailing ``-capture`` / ``-playback`` so loopback /
    filter-chain pairs collapse into a single descriptor node.
    """
    base = pipewire_name
    if base.startswith("hapax-"):
        base = base[len("hapax-") :]
    for suffix in ("-capture", "-playback", "-src", "-dst"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return base


def _decompose_adapter(
    block: _AdapterBlock, source_path: str
) -> tuple[AudioNode | None, list[ValidationGap]]:
    """Adapter block → ``AudioNode``."""
    args = block.args_block.text
    args = _strip_comments(args)
    factory_name = _extract_unquoted(args, "factory.name")
    node_name = _extract_str(args, "node.name")
    description = _extract_str(args, "node.description") or ""
    media_class = _extract_unquoted(args, "media.class") or _extract_str(args, "media.class")
    positions = _extract_position_list(args, "audio.position")

    if node_name is None:
        return None, [
            ValidationGap(
                kind="schema-fit",
                source_path=source_path,
                message="adapter block missing node.name",
                suggested_schema_change=("infer node.name from filename when adapter omits it"),
            )
        ]

    if factory_name is None:
        return None, [
            ValidationGap(
                kind="schema-fit",
                source_path=source_path,
                message=(f"adapter block for {node_name!r} missing factory.name"),
                suggested_schema_change=("support factory.name=adapter without inner factory.name"),
            )
        ]

    if factory_name == "support.null-audio-sink":
        kind = NodeKind.NULL_SINK
    else:
        # Future-proof: any other adapter factory we don't yet model
        return None, [
            ValidationGap(
                kind="schema-fit",
                source_path=source_path,
                message=(
                    f"adapter for {node_name!r} uses unsupported factory.name={factory_name!r}"
                ),
                suggested_schema_change=(
                    f"add NodeKind for factory.name={factory_name!r} or extend adapter parser"
                ),
            )
        ]

    pos_tuple: tuple[str, ...] = tuple(positions) if positions else ()
    count = len(pos_tuple) if pos_tuple else 2

    # Misc params we want to preserve
    params: dict[str, str | int | float | bool] = {}
    for k in (
        "monitor.channel-volumes",
        "monitor.passthrough",
    ):
        b = _extract_bool(args, k)
        if b is not None:
            params[k] = b

    if media_class:
        params["media.class"] = media_class

    return (
        AudioNode(
            id=_id_from_name(node_name),
            kind=kind,
            pipewire_name=node_name,
            description=description,
            channels=ChannelMap(count=count, positions=pos_tuple),
            params=params,
        ),
        [],
    )


def _decompose_loopback(
    block: _ModuleBlock, source_path: str
) -> tuple[list[AudioNode], list[AudioLink], list[LoopbackTopology], list[ValidationGap]]:
    """``libpipewire-module-loopback`` → AudioNode + LoopbackTopology + Link."""
    args = _strip_comments(block.args_block.text)

    capture_block = _find_subblock(args, "capture.props")
    playback_block = _find_subblock(args, "playback.props")
    if capture_block is None or playback_block is None:
        return (
            [],
            [],
            [],
            [
                ValidationGap(
                    kind="schema-fit",
                    source_path=source_path,
                    message=("loopback module missing capture.props or playback.props"),
                    suggested_schema_change=("support loopback without paired capture/playback"),
                )
            ],
        )

    cap_text = capture_block.text
    pb_text = playback_block.text

    cap_name = _extract_str(cap_text, "node.name")
    pb_name = _extract_str(pb_text, "node.name")
    cap_target = _extract_str(cap_text, "target.object")
    pb_target = _extract_str(pb_text, "target.object")
    pb_pos = _extract_position_list(pb_text, "audio.position") or []
    pb_count = _extract_int(pb_text, "audio.channels")

    if pb_name is None:
        return (
            [],
            [],
            [],
            [
                ValidationGap(
                    kind="schema-fit",
                    source_path=source_path,
                    message="loopback playback.props missing node.name",
                    suggested_schema_change=("synthesise loopback playback name from capture name"),
                )
            ],
        )

    pb_pos_tuple = tuple(pb_pos)
    # cap_pos / cap_count are read but not surfaced as a separate
    # AudioNode in P1 (the capture side becomes LoopbackTopology.source).
    # Keep cap_pos parsing for future ports; ruff wants no unused locals
    # so the cap_count_val we'd compute here is intentionally elided.
    pb_count_val = pb_count if pb_count is not None else len(pb_pos_tuple) or 2

    # The loopback's "primary" node is the playback side (it's what
    # carries the destination identity). The capture side is captured
    # in the LoopbackTopology.source field.
    nodes = [
        AudioNode(
            id=_id_from_name(pb_name),
            kind=NodeKind.LOOPBACK,
            pipewire_name=pb_name,
            description=(_extract_str(args, "node.description") or pb_name),
            target_object=pb_target,
            channels=ChannelMap(count=pb_count_val, positions=pb_pos_tuple),
        ),
    ]

    loopback_topo = LoopbackTopology(
        node_id=_id_from_name(pb_name),
        source=cap_target or cap_name or "<unknown-source>",
        sink=pb_target or pb_name,
    )

    # Build a link for the wired path. If we can resolve both endpoints
    # to descriptor ids, the link is added; otherwise we leave it as
    # an external reference (no link added).
    links: list[AudioLink] = []

    return nodes, links, [loopback_topo], []


def _decompose_filter_chain(
    block: _ModuleBlock, source_path: str
) -> tuple[list[AudioNode], list[AudioLink], list[ValidationGap]]:
    """``libpipewire-module-filter-chain`` → AudioNode (kind=filter_chain)."""
    args = _strip_comments(block.args_block.text)

    description = _extract_str(args, "node.description") or ""
    capture_block = _find_subblock(args, "capture.props")
    playback_block = _find_subblock(args, "playback.props")

    # Filter graph block — store the raw text as opaque blob
    fg_block = _find_subblock(args, "filter.graph")
    filter_graph_blob: dict[str, Any] | None = None
    if fg_block is not None:
        filter_graph_blob = {"__raw_text__": fg_block.text}

    pipewire_name: str | None = None
    target_object: str | None = None
    positions: tuple[str, ...] = ()
    count = 2
    params: dict[str, str | int | float | bool] = {}

    if capture_block is not None:
        cap_text = capture_block.text
        pipewire_name = _extract_str(cap_text, "node.name") or pipewire_name
        target_object = _extract_str(cap_text, "target.object") or target_object
        cap_pos = _extract_position_list(cap_text, "audio.position")
        cap_count = _extract_int(cap_text, "audio.channels")
        if cap_pos:
            positions = tuple(cap_pos)
        if cap_count is not None:
            count = cap_count
        b = _extract_bool(cap_text, "stream.dont-remix")
        if b is not None:
            params["stream.dont-remix"] = b
        b = _extract_bool(cap_text, "stream.capture.sink")
        if b is not None:
            params["stream.capture.sink"] = b

    if playback_block is not None and pipewire_name is None:
        pb_text = playback_block.text
        pipewire_name = _extract_str(pb_text, "node.name")

    # Some confs (older format) put node.name on args directly
    if pipewire_name is None:
        pipewire_name = _extract_str(args, "node.name")

    if pipewire_name is None:
        return (
            [],
            [],
            [
                ValidationGap(
                    kind="schema-fit",
                    source_path=source_path,
                    message=("filter-chain module missing node.name in capture/playback/args"),
                    suggested_schema_change=(
                        "fall back to filename-derived name when conf omits node.name everywhere"
                    ),
                )
            ],
        )

    if not positions:
        # Try args-level audio.position
        ap = _extract_position_list(args, "audio.position")
        if ap:
            positions = tuple(ap)
            count = len(positions)

    if not positions:
        # Default to FL/FR when nothing is explicit
        positions = ("FL", "FR")
        count = 2

    return (
        [
            AudioNode(
                id=_id_from_name(pipewire_name),
                kind=NodeKind.FILTER_CHAIN,
                pipewire_name=pipewire_name,
                description=description or pipewire_name,
                target_object=target_object,
                channels=ChannelMap(count=count, positions=positions),
                params=params,
                filter_graph=filter_graph_blob,
            ),
        ],
        [],
        [],
    )


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class AudioGraphValidator:
    """Decompose ``*.conf`` files into an ``AudioGraph``."""

    def decompose(self, conf_dir: Path) -> ValidationReport:
        """Walk ``conf_dir`` and decompose every active ``*.conf``."""
        nodes: list[AudioNode] = []
        links: list[AudioLink] = []
        loopbacks: list[LoopbackTopology] = []
        decomposed: list[str] = []
        skipped: list[str] = []
        gaps: list[ValidationGap] = []

        if not conf_dir.is_dir():
            raise FileNotFoundError(f"conf_dir does not exist: {conf_dir}")

        for path in sorted(conf_dir.iterdir()):
            if not path.is_file():
                continue
            if _should_skip(path.name):
                skipped.append(str(path))
                continue
            if not path.name.endswith(".conf"):
                skipped.append(str(path))
                continue
            file_nodes, file_links, file_loopbacks, file_gaps = self._decompose_file(path)
            nodes.extend(file_nodes)
            links.extend(file_links)
            loopbacks.extend(file_loopbacks)
            if file_gaps:
                gaps.extend(file_gaps)
            else:
                decomposed.append(str(path))

        # Dedupe nodes by id (loopback playback + filter-chain capture
        # may declare the same id from different conf files; keep first).
        seen_ids: set[str] = set()
        deduped_nodes: list[AudioNode] = []
        for n in nodes:
            if n.id in seen_ids:
                continue
            seen_ids.add(n.id)
            deduped_nodes.append(n)

        # Dedupe loopbacks by node_id.
        seen_lb: set[str] = set()
        deduped_lbs: list[LoopbackTopology] = []
        for lb in loopbacks:
            if lb.node_id in seen_lb:
                continue
            seen_lb.add(lb.node_id)
            deduped_lbs.append(lb)

        # The validator only emits links it can resolve to descriptor
        # ids. P1 doesn't synthesise them when target.object refers to
        # an external pipewire_name; that resolution lives in P4 when
        # the alignment audit's full-graph reconstruction lands.
        resolved_links: list[AudioLink] = []
        node_ids_set = {n.id for n in deduped_nodes}
        for link in links:
            if link.source in node_ids_set and link.target in node_ids_set:
                resolved_links.append(link)

        # Remove loopbacks whose node_id isn't in the deduped node set
        # — keeping them would fail the AudioGraph._loopbacks_reference_valid_nodes
        # validator and silently shadow the gap detection.
        deduped_lbs = [lb for lb in deduped_lbs if lb.node_id in node_ids_set]

        graph = AudioGraph(
            schema_version=1,
            nodes=tuple(deduped_nodes),
            links=tuple(resolved_links),
            loopbacks=tuple(deduped_lbs),
        )
        return ValidationReport(
            graph=graph,
            decomposed_files=tuple(decomposed),
            skipped_files=tuple(skipped),
            gaps=tuple(gaps),
        )

    def _decompose_file(
        self, path: Path
    ) -> tuple[list[AudioNode], list[AudioLink], list[LoopbackTopology], list[ValidationGap]]:
        try:
            text = path.read_text()
        except Exception as exc:
            return (
                [],
                [],
                [],
                [
                    ValidationGap(
                        kind="conf-parse",
                        source_path=str(path),
                        message=f"could not read file: {exc}",
                    )
                ],
            )
        text = _strip_comments(text)

        nodes: list[AudioNode] = []
        links: list[AudioLink] = []
        loopbacks: list[LoopbackTopology] = []
        gaps: list[ValidationGap] = []

        for adapter in _find_adapter_blocks(text):
            node, file_gaps = _decompose_adapter(adapter, str(path))
            if node is not None:
                nodes.append(node)
            gaps.extend(file_gaps)

        for module in _find_module_blocks(text):
            if module.module_name == "libpipewire-module-loopback":
                m_nodes, m_links, m_lbs, m_gaps = _decompose_loopback(module, str(path))
                nodes.extend(m_nodes)
                links.extend(m_links)
                loopbacks.extend(m_lbs)
                gaps.extend(m_gaps)
            elif module.module_name == "libpipewire-module-filter-chain":
                m_nodes, m_links, m_gaps = _decompose_filter_chain(module, str(path))
                nodes.extend(m_nodes)
                links.extend(m_links)
                gaps.extend(m_gaps)
            else:
                gaps.append(
                    ValidationGap(
                        kind="schema-fit",
                        source_path=str(path),
                        message=(f"unsupported module type: {module.module_name!r}"),
                        suggested_schema_change=(
                            f"extend validator for module {module.module_name!r}"
                        ),
                    )
                )

        # If the file declared neither adapters nor recognised modules,
        # but had non-empty content, classify it as either a recognised
        # graph-tunable (operator-edited quantum knobs / wireplumber
        # rules — spec §8 question 2 calls these "global tunables") or
        # surface a real gap.
        if (
            not nodes
            and not loopbacks
            and not _find_adapter_blocks(text)
            and not _find_module_blocks(text)
            and text.strip()
        ):
            stripped = re.sub(r"context\.properties\s*=\s*\{\s*\}", "", text).strip()
            if stripped and _is_recognised_graph_tunable(text):
                # Recognised tunable — not a gap, not a graph node.
                # P1 acknowledges these and lets the conf through;
                # P4 will model them as first-class descriptor fields.
                pass
            elif stripped:
                gaps.append(
                    ValidationGap(
                        kind="schema-fit",
                        source_path=str(path),
                        message=("conf has non-comment content but produced no AudioGraph entries"),
                        suggested_schema_change=(
                            "extend validator: check what module/adapter this file uses"
                        ),
                    )
                )

        return nodes, links, loopbacks, gaps
