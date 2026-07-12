"""Safe YAML loading that rejects duplicate and unhashable mapping keys."""

from __future__ import annotations

from typing import Any

import yaml


class NoDuplicateSafeLoader(yaml.SafeLoader):
    """SafeLoader variant with mapping-key uniqueness enforcement."""


def _construct_unique_mapping(
    loader: NoDuplicateSafeLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


NoDuplicateSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def strict_safe_load(text: str) -> Any:
    """Load YAML with SafeLoader semantics and reject ambiguous mappings."""
    try:
        return yaml.load(text, Loader=NoDuplicateSafeLoader)
    except yaml.YAMLError as exc:
        raise ValueError(str(exc)) from exc
