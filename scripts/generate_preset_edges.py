"""Generate ``edges`` arrays for graph presets that ship without them.

Background
==========
``EffectGraph`` (``agents/effect_graph/types.py``) requires both ``nodes`` and
``edges``. The runtime loader at ``agents/studio_compositor/state.py:362``
swallows ``ValidationError`` silently, so a preset that ships with only
``nodes`` and no ``edges`` looks identical to a malformed JSON: the operator
just sees the chain holding the previous plan instead of the requested one.

Audit (2026-05-04) found 55 of 86 graph presets in ``presets/`` shipping
without ``edges``. PR #2491 fixed ``sierpinski_line_overlay.json`` by hand;
this generator handles the remaining corpus mechanically.

Strategy
========
For each preset that has ``nodes`` but no ``edges``:

1. Read the dict-ordered ``nodes`` map. The convention across the corpus
   is ``[colorgrade, processing_node_1, processing_node_2, ..., out, content_layer]``
   — insertion order encodes the intended chain.

2. Pull the output node (the single node with ``type == "output"``) and the
   optional ``content_layer`` node out of the ordered list of processing
   nodes.

3. Compose the chain ``@live → processing_node_1 → ... → processing_node_N →
   content_layer → out`` (skipping ``content_layer`` when not present —
   chain terminates ``→ out``).

4. Add ``modulations: []`` if missing (canonical preset shape carries the
   key; ``_default_modulations.json`` provides chain-level fallbacks at
   load time via ``merge_default_modulations``).

5. Write the updated JSON atomically (tmp + rename).

Excluded
========
- ``_default_modulations.json`` — leading-underscore files are conventionally
  excluded from preset enumeration.
- ``shader_intensity_bounds.json`` — config file (``_meta`` + ``node_caps``
  shape, no ``nodes`` map). Not a graph preset.

Validation
==========
After running, every file in ``presets/*.json`` (except the two excluded
above) should construct as ``EffectGraph(**json.load(f))`` without raising
``ValidationError``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

PRESETS_DIR = Path(__file__).resolve().parent.parent / "presets"
NODES_DIR = Path(__file__).resolve().parent.parent / "agents" / "shaders" / "nodes"
EXCLUDED_NAMES = frozenset(
    {
        "shader_intensity_bounds.json",  # config file, not a graph preset
    }
)

# Some shader nodes take two frame inputs (named "a" and "b") for compositing
# operations — chroma/luma keying, displacement-mapping. For lineage presets
# the artistic intent is self-application: the same upstream frame feeds both
# inputs (e.g., a frame displaced by itself yields paper-jam-streak). The
# generator wires the previous stage into BOTH ports for these nodes.
#
# Sourced from ``agents/shaders/nodes/*.json`` (registry manifests). Loaded
# lazily once per generator run via ``_load_dual_input_types``.
_DUAL_INPUT_TYPES_CACHE: frozenset[str] | None = None


def _load_dual_input_types() -> frozenset[str]:
    """Discover node types whose registry manifest declares ports ``{"a", "b"}``."""
    global _DUAL_INPUT_TYPES_CACHE  # noqa: PLW0603 — lazy module-level cache
    if _DUAL_INPUT_TYPES_CACHE is not None:
        return _DUAL_INPUT_TYPES_CACHE
    if not NODES_DIR.is_dir():
        _DUAL_INPUT_TYPES_CACHE = frozenset()
        return _DUAL_INPUT_TYPES_CACHE
    dual: set[str] = set()
    for p in NODES_DIR.glob("*.json"):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        ports = set(raw.get("inputs", {}).keys())
        if ports == {"a", "b"}:
            dual.add(raw.get("node_type", p.stem))
    _DUAL_INPUT_TYPES_CACHE = frozenset(dual)
    return _DUAL_INPUT_TYPES_CACHE


def _is_graph_preset(data: dict) -> bool:
    """Return True if the JSON has the graph-preset shape (a ``nodes`` map)."""
    return isinstance(data, dict) and isinstance(data.get("nodes"), dict)


def _output_node_id(nodes: dict[str, dict]) -> str | None:
    """Return the single node id whose ``type == "output"``, or ``None``."""
    for node_id, defn in nodes.items():
        if isinstance(defn, dict) and defn.get("type") == "output":
            return node_id
    return None


def _content_layer_node_id(nodes: dict[str, dict]) -> str | None:
    """Return the single node id whose ``type == "content_layer"``, or ``None``."""
    for node_id, defn in nodes.items():
        if isinstance(defn, dict) and defn.get("type") == "content_layer":
            return node_id
    return None


def synthesize_edges(nodes: dict[str, dict]) -> list[list[str]]:
    """Build an ``edges`` chain from a dict-ordered ``nodes`` map.

    Convention across the corpus: dict insertion order is
    ``[processing_node_1, ..., processing_node_N, out, content_layer]``.
    The synthesized chain is
    ``@live → processing_node_1 → ... → processing_node_N → content_layer → out``.

    If ``content_layer`` is absent, the chain skips it and terminates at ``out``.

    Dual-input nodes (``chroma_key``/``luma_key``/``displacement_map`` —
    anything with ports ``{"a", "b"}`` in its registry manifest) get the
    previous stage wired into BOTH ports — the lineage-preset intent is
    self-application (a frame keyed against itself, displaced by itself).

    Raises
    ------
    ValueError
        If no ``output``-typed node exists, or if there are no processing
        nodes between ``@live`` and ``out`` (degenerate one-node graph).
    """
    out_id = _output_node_id(nodes)
    if out_id is None:
        msg = "preset has no node with type='output'; cannot terminate chain"
        raise ValueError(msg)

    content_id = _content_layer_node_id(nodes)
    dual_input_types = _load_dual_input_types()

    # Processing nodes = everything except the output node and content_layer,
    # preserving dict insertion order.
    processing: list[str] = [
        node_id for node_id in nodes if node_id != out_id and node_id != content_id
    ]

    if not processing:
        msg = "preset has no processing nodes between @live and out"
        raise ValueError(msg)

    def _connect(src: str, tgt: str) -> list[list[str]]:
        """Wire ``src`` → ``tgt``, splitting into ``a``/``b`` for dual-input ``tgt``.

        ``src`` is treated as the canonical source spec (``@live`` or a
        node-id with implicit ``out`` port). ``tgt`` is the target node id.
        """
        tgt_defn = nodes.get(tgt, {}) if not tgt.startswith("@") else {}
        tgt_type = tgt_defn.get("type", "") if isinstance(tgt_defn, dict) else ""
        if tgt_type in dual_input_types:
            # Self-application: feed previous stage into both ports.
            return [[src, f"{tgt}:a"], [src, f"{tgt}:b"]]
        return [[src, tgt]]

    edges: list[list[str]] = []
    edges.extend(_connect("@live", processing[0]))
    for src, tgt in zip(processing, processing[1:], strict=False):
        edges.extend(_connect(src, tgt))

    last_processing = processing[-1]
    if content_id is not None:
        edges.extend(_connect(last_processing, content_id))
        edges.append([content_id, out_id])
    else:
        edges.append([last_processing, out_id])

    return edges


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write ``data`` as pretty-printed JSON to ``path`` atomically."""
    rendered = json.dumps(data, indent=2) + "\n"
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.stem}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(rendered)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def patch_preset(path: Path, *, dry_run: bool = False) -> bool:
    """Add ``edges`` (and ``modulations`` if missing) to ``path``.

    Returns ``True`` if the file was modified, ``False`` if it was already
    schema-complete or is not a graph preset.
    """
    if path.name in EXCLUDED_NAMES or path.name.startswith("_"):
        return False
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not _is_graph_preset(raw):
        return False

    changed = False
    if "edges" not in raw:
        raw["edges"] = synthesize_edges(raw["nodes"])
        changed = True
    if "modulations" not in raw:
        raw["modulations"] = []
        changed = True

    if changed and not dry_run:
        _atomic_write_json(path, raw)
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing files.",
    )
    parser.add_argument(
        "--presets-dir",
        type=Path,
        default=PRESETS_DIR,
        help=f"Directory containing preset JSON files (default: {PRESETS_DIR}).",
    )
    args = parser.parse_args(argv)

    if not args.presets_dir.is_dir():
        print(f"presets dir not found: {args.presets_dir}", file=sys.stderr)
        return 2

    patched: list[str] = []
    skipped_non_graph: list[str] = []
    already_ok: list[str] = []

    for path in sorted(args.presets_dir.glob("*.json")):
        if path.name.startswith("_") or path.name in EXCLUDED_NAMES:
            skipped_non_graph.append(path.name)
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"[SKIP] {path.name}: invalid JSON ({exc})", file=sys.stderr)
            continue
        if not _is_graph_preset(raw):
            skipped_non_graph.append(path.name)
            continue
        if patch_preset(path, dry_run=args.dry_run):
            patched.append(path.name)
        else:
            already_ok.append(path.name)

    suffix = " (dry-run)" if args.dry_run else ""
    print(f"patched{suffix}: {len(patched)}")
    for name in patched:
        print(f"  + {name}")
    print(f"already ok: {len(already_ok)}")
    print(f"skipped (non-graph / underscored): {len(skipped_non_graph)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
