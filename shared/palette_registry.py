"""Palette registry — load and look up scrim palettes + chains.

Parses ``presets/scrim_palettes/registry.yaml`` into typed
:class:`shared.palette_family.ScrimPalette` and
:class:`shared.palette_family.PaletteChain` instances and exposes
lookup + tag-based recruitment helpers. Built for Phase 3 of the
video-container epic and Phase 5 of the scrim implementation.

## Shape

The YAML has two top-level keys, ``palettes`` and ``chains``. Each
list entry is a dict that model-validates directly into the
corresponding Pydantic record. Gradient-map ``stops`` and duotone
``stop_low`` / ``stop_high`` arrive as plain lists — the curve
evaluator (Phase 3+) reshapes them into tuples / LAB triples at
apply time. Storing them as lists keeps the YAML human-readable.

## Lookup semantics

- :meth:`PaletteRegistry.get_palette` / :meth:`get_chain` return the
  record by id or raise :class:`KeyError`. Callers who need a safe
  variant should use :meth:`find_palette` (returns ``None``).
- :meth:`recruit_by_tags` returns palettes matching ALL given tags
  (AND semantics). Returns empty list if no match. Caller decides
  scoring / Thompson-sampling.
- :meth:`filter_by_affinity` restricts to palettes whose
  ``working_mode_affinity`` includes the given mode OR ``any``.
  Reminder: affinity is a HINT, not a gate — callers may still
  recruit outside affinity.

## Invariants

Validated at load:

- Every chain step references a palette that exists in ``palettes``.
- No duplicate palette ids; no duplicate chain ids.
- All records pass Pydantic validation (catches param shape errors,
  out-of-range axes, etc.).

A registry that fails invariants raises :class:`RegistryLoadError`
rather than silently dropping entries — the loader is the one place
where bad data is allowed to stop startup.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from shared.palette_family import (
    PaletteChain,
    PaletteChainStep,
    PaletteResponseCurve,
    ScrimPalette,
    WorkingModeAffinity,
)

DEFAULT_REGISTRY_PATH: Path = (
    Path(__file__).resolve().parent.parent / "presets" / "scrim_palettes" / "registry.yaml"
)


class RegistryLoadError(Exception):
    """Raised when the palette registry YAML fails validation."""


def _curve_from_dict(raw: dict[str, Any]) -> PaletteResponseCurve:
    """Build a PaletteResponseCurve from a YAML dict.

    YAML arrives with plain lists for ``params`` values that the curve
    model accepts (``dict[str, float | list[float] | dict[str, float]]``);
    nested LAB triples under ``stops`` / ``stop_low`` / ``stop_high`` land
    here as ``list[float]`` and the Pydantic model accepts them directly
    because the params field declares list entries.
    """
    return PaletteResponseCurve(**raw)


def _palette_from_dict(raw: dict[str, Any]) -> ScrimPalette:
    # YAML LAB triples arrive as lists; model accepts tuple or list.
    data = dict(raw)
    if "curve" in data and isinstance(data["curve"], dict):
        data["curve"] = _curve_from_dict(data["curve"])
    return ScrimPalette(**data)


def _chain_from_dict(raw: dict[str, Any]) -> PaletteChain:
    data = dict(raw)
    steps_raw = data.get("steps") or []
    data["steps"] = tuple(PaletteChainStep(**step) for step in steps_raw)
    return PaletteChain(**data)


class PaletteRegistry:
    """In-memory palette + chain store, loaded from the registry YAML."""

    def __init__(
        self,
        palettes: dict[str, ScrimPalette],
        chains: dict[str, PaletteChain],
    ) -> None:
        self._palettes = dict(palettes)
        self._chains = dict(chains)

    # -- load --

    @classmethod
    def load(cls, path: Path | None = None) -> PaletteRegistry:
        """Load + validate the registry YAML. Raises on any schema error."""
        source = path or DEFAULT_REGISTRY_PATH
        try:
            raw = yaml.safe_load(source.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise RegistryLoadError(f"palette registry read failed ({source}): {exc}") from exc
        if not isinstance(raw, dict):
            raise RegistryLoadError(
                f"palette registry root must be a mapping, got {type(raw).__name__}"
            )

        palettes: dict[str, ScrimPalette] = {}
        for entry in raw.get("palettes") or []:
            try:
                pal = _palette_from_dict(entry)
            except Exception as exc:  # pydantic.ValidationError is an Exception subclass
                pid = entry.get("id", "<unknown>") if isinstance(entry, dict) else "<malformed>"
                raise RegistryLoadError(f"palette {pid!r} failed validation: {exc}") from exc
            if pal.id in palettes:
                raise RegistryLoadError(f"duplicate palette id: {pal.id!r}")
            palettes[pal.id] = pal

        chains: dict[str, PaletteChain] = {}
        for entry in raw.get("chains") or []:
            try:
                chain = _chain_from_dict(entry)
            except Exception as exc:
                cid = entry.get("id", "<unknown>") if isinstance(entry, dict) else "<malformed>"
                raise RegistryLoadError(f"chain {cid!r} failed validation: {exc}") from exc
            if chain.id in chains:
                raise RegistryLoadError(f"duplicate chain id: {chain.id!r}")
            for step in chain.steps:
                if step.palette_id not in palettes:
                    raise RegistryLoadError(
                        f"chain {chain.id!r} references unknown palette {step.palette_id!r}"
                    )
            chains[chain.id] = chain

        return cls(palettes=palettes, chains=chains)

    # -- lookup --

    def get_palette(self, palette_id: str) -> ScrimPalette:
        """Return palette by id or raise KeyError."""
        return self._palettes[palette_id]

    def find_palette(self, palette_id: str) -> ScrimPalette | None:
        """Return palette by id or None — safe variant of :meth:`get_palette`."""
        return self._palettes.get(palette_id)

    def get_chain(self, chain_id: str) -> PaletteChain:
        return self._chains[chain_id]

    def find_chain(self, chain_id: str) -> PaletteChain | None:
        return self._chains.get(chain_id)

    def palette_ids(self) -> tuple[str, ...]:
        return tuple(self._palettes.keys())

    def chain_ids(self) -> tuple[str, ...]:
        return tuple(self._chains.keys())

    def all_palettes(self) -> tuple[ScrimPalette, ...]:
        return tuple(self._palettes.values())

    def all_chains(self) -> tuple[PaletteChain, ...]:
        return tuple(self._chains.values())

    # -- recruitment helpers --

    def recruit_by_tags(self, tags: tuple[str, ...] | list[str]) -> tuple[ScrimPalette, ...]:
        """Return palettes whose ``semantic_tags`` contain ALL given tags.

        AND semantics. Empty ``tags`` returns every palette (trivial
        match). Callers layer scoring / Thompson sampling on top.
        """
        required = set(tags)
        if not required:
            return self.all_palettes()
        matches = tuple(p for p in self._palettes.values() if required.issubset(p.semantic_tags))
        return matches

    def filter_by_affinity(self, mode: WorkingModeAffinity) -> tuple[ScrimPalette, ...]:
        """Return palettes whose affinity includes ``mode`` OR ``any``.

        Reminder: affinity is a HINT. Callers wanting hard filtering by
        mode (e.g., quick fallback) use this; recruitment paths
        typically use :meth:`recruit_by_tags` and let the affinity
        weight a Thompson score, not gate.
        """
        out: list[ScrimPalette] = []
        for p in self._palettes.values():
            if mode in p.working_mode_affinity or "any" in p.working_mode_affinity:
                out.append(p)
        return tuple(out)


__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "PaletteRegistry",
    "RegistryLoadError",
]
