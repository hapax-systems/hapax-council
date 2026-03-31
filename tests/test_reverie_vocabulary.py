"""Tests for reverie_vocabulary.json structural integrity."""

import json
from pathlib import Path

VOCAB_PATH = Path(__file__).resolve().parents[1] / "presets" / "reverie_vocabulary.json"


def _load_vocab() -> dict:
    return json.loads(VOCAB_PATH.read_text())


def test_vocabulary_has_rd_node():
    vocab = _load_vocab()
    assert "rd" in vocab["nodes"], "reaction_diffusion node missing from vocabulary"
    assert vocab["nodes"]["rd"]["type"] == "reaction_diffusion"


def test_rd_has_required_params():
    vocab = _load_vocab()
    params = vocab["nodes"]["rd"]["params"]
    assert "feed_rate" in params
    assert "kill_rate" in params
    assert "diffusion_a" in params
    assert "diffusion_b" in params
    assert "speed" in params


def test_rd_is_between_noise_and_colorgrade():
    """R-D should receive noise output and feed into colorgrade."""
    vocab = _load_vocab()
    edges = vocab["edges"]
    assert ["noise", "rd"] in edges, "noise→rd edge missing"
    assert ["rd", "color"] in edges, "rd→color edge missing"
    # noise should NOT connect directly to color anymore
    assert ["noise", "color"] not in edges, "stale noise→color edge still present"


def test_vocabulary_has_8_edges():
    """Core graph: noise→rd→color→drift→breath→fb→content→post→out = 9 nodes, 8 edges."""
    vocab = _load_vocab()
    assert len(vocab["edges"]) == 8


def test_all_edges_reference_existing_nodes():
    vocab = _load_vocab()
    node_ids = set(vocab["nodes"].keys())
    for src, dst in vocab["edges"]:
        assert src in node_ids, f"edge source '{src}' not in nodes"
        assert dst in node_ids, f"edge target '{dst}' not in nodes"
