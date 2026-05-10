from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.studio_compositor.graph_mutation_bus import write_graph_mutation


def test_write_graph_mutation_replaces_target_atomically(tmp_path: Path) -> None:
    target = tmp_path / "graph-mutation.json"
    target.write_text('{"old": true}', encoding="utf-8")

    write_graph_mutation({"nodes": {}, "edges": []}, path=target, source="test")

    assert json.loads(target.read_text(encoding="utf-8")) == {
        "nodes": {},
        "edges": [],
        "_source": "test",
    }
    assert not list(tmp_path.glob(".graph-mutation.json.*.tmp"))


def test_write_graph_mutation_removes_temp_file_after_encode_failure(
    tmp_path: Path,
) -> None:
    target = tmp_path / "graph-mutation.json"
    target.write_text('{"old": true}', encoding="utf-8")

    with pytest.raises(TypeError):
        write_graph_mutation({"bad": object()}, path=target)

    assert target.read_text(encoding="utf-8") == '{"old": true}'
    assert not list(tmp_path.glob(".graph-mutation.json.*.tmp"))
