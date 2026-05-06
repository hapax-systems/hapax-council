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


# ── Refusal-brief emission (Phase 3c subscriber wire-in) ──────────────


class TestContentResolverRefusalEmission:
    """Refusal-as-data emission: failure-cap path appends an event into
    the canonical refusal log for operator-visible "I gave up on
    fragment X" surfacing."""

    def test_emit_appends_one_event(self, monkeypatch):
        from agents.content_resolver.__main__ import _emit_content_refusal

        captured = []
        import agents.refusal_brief as _pkg

        monkeypatch.setattr(_pkg, "append", lambda ev, **_: captured.append(ev) or True)

        _emit_content_refusal(
            surface="content_resolver:fragment_skip",
            reason="fragment abc123 skipped after 5 validation failures",
        )

        assert len(captured) == 1
        ev = captured[0]
        assert ev.surface == "content_resolver:fragment_skip"
        assert ev.axiom == "resolver_failure_cap"
        assert "abc123" in ev.reason
        assert "5 validation failures" in ev.reason

    def test_emit_caps_long_reason(self, monkeypatch):
        """Reason is hard-capped at 160 chars (REASON_MAX_CHARS)."""
        from agents.content_resolver.__main__ import _emit_content_refusal

        captured = []
        import agents.refusal_brief as _pkg

        monkeypatch.setattr(_pkg, "append", lambda ev, **_: captured.append(ev) or True)

        _emit_content_refusal(surface="content_resolver:fragment_skip", reason="x" * 500)

        assert len(captured) == 1
        assert len(captured[0].reason) <= 160

    def test_writer_failure_does_not_raise(self, monkeypatch):
        """Writer raise is swallowed so the resolver loop is unaffected."""
        import agents.refusal_brief as _pkg
        from agents.content_resolver.__main__ import _emit_content_refusal

        monkeypatch.setattr(
            _pkg, "append", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))
        )

        # Must not raise.
        _emit_content_refusal(surface="content_resolver:fragment_skip", reason="any")


import pytest


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a"', "string"), ("[1,2]", "list"), ("42", "int")],
)
def test_check_for_new_fragment_non_dict_root(tmp_path, payload, kind):
    """Pin check_for_new_fragment against non-dict JSON. Previously the
    data.get('id', '') call inside the (OSError, JSONDecodeError) catch
    let AttributeError escape on non-dict roots, crashing the
    content-resolver poll loop."""
    from agents.content_resolver.__main__ import check_for_new_fragment

    current = tmp_path / "current.json"
    current.write_text(payload)
    frag_id, data = check_for_new_fragment(last_id="", path=current)
    assert frag_id is None, f"non-dict root={kind} must yield (None, None)"
    assert data is None
