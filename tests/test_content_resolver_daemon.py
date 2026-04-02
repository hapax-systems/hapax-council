"""Test content resolver daemon watches for new fragments."""

import json


def test_detect_new_fragment(tmp_path):
    """Verify resolver detects new fragment IDs."""
    from agents.content_resolver.__main__ import check_for_new_fragment

    current = tmp_path / "current.json"
    current.write_text(json.dumps({"id": "abc123", "dimensions": {}}))

    frag_id, data = check_for_new_fragment(last_id="", path=current)
    assert frag_id == "abc123"
    assert data is not None


def test_skip_same_fragment(tmp_path):
    """Verify resolver skips already-processed fragment."""
    from agents.content_resolver.__main__ import check_for_new_fragment

    current = tmp_path / "current.json"
    current.write_text(json.dumps({"id": "abc123", "dimensions": {}}))

    frag_id, data = check_for_new_fragment(last_id="abc123", path=current)
    assert frag_id is None


def test_handle_missing_file(tmp_path):
    """Verify resolver handles missing current.json gracefully."""
    from agents.content_resolver.__main__ import check_for_new_fragment

    frag_id, data = check_for_new_fragment(last_id="", path=tmp_path / "missing.json")
    assert frag_id is None
