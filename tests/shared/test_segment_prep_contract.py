"""Constructive-binding anti-hallucination contract tests.

These cover the systemic anti-hallucination integration: claims are
constructed from RESOLVED source handles (an index into a closed,
content-hash-bound recruited set), never from free-text refs the model
invents. A fabricated/unresolvable handle is unconstructable-or-refused,
not shape-passed. No expert-rule (regex/allowlist/LLM-judge) is
load-bearing — the dereference against the resolved set is.

Task: systemic-anti-hallucination-constructive-binding-20260607.
"""

from __future__ import annotations

from shared.source_packet import (
    ResolvedSourceSet,
    SourcePacket,
    build_resolved_source_set,
    handle_for_index,
    parse_handle,
    source_provenance_sha256,
    validate_cited_handles,
)


def _packet(ref: str, content_hash: str, consequence: str = "scope narrows") -> SourcePacket:
    return SourcePacket(
        source_ref=ref,
        content_hash=content_hash,
        snippet=f"snippet for {ref}",
        freshness="fresh",
        source_consequence=consequence,
    )


def _set(*refs_and_hashes: tuple[str, str]) -> ResolvedSourceSet:
    packets = tuple(_packet(ref, h) for ref, h in refs_and_hashes)
    built = build_resolved_source_set("test topic", packets)
    assert built is not None
    return built


# ---------------------------------------------------------------------------
# Layer 1 — handle algebra: a citable surface that is an index into a set
# ---------------------------------------------------------------------------


class TestHandleAlgebra:
    def test_handle_for_index_is_src_n(self) -> None:
        assert handle_for_index(0) == "src:0"
        assert handle_for_index(3) == "src:3"

    def test_parse_handle_roundtrip(self) -> None:
        assert parse_handle("src:0") == 0
        assert parse_handle("src:12") == 12

    def test_parse_handle_rejects_freetext_ref(self) -> None:
        # The exact class of fabrication the task targets.
        assert parse_handle("vault:research-notes") is None
        assert parse_handle("vault:2008-financial-crisis") is None

    def test_parse_handle_rejects_malformed(self) -> None:
        assert parse_handle("src:") is None
        assert parse_handle("src:-1") is None
        assert parse_handle("src:x") is None
        assert parse_handle("") is None
        assert parse_handle("0") is None

    def test_handles_property_covers_every_packet(self) -> None:
        s = _set(("vault:a", "h0"), ("rag:b", "h1"), ("qdrant:c", "h2"))
        assert s.handles == ("src:0", "src:1", "src:2")

    def test_packet_for_handle_resolves_index(self) -> None:
        s = _set(("vault:a", "h0"), ("rag:b", "h1"))
        assert s.packet_for_handle("src:1").source_ref == "rag:b"

    def test_packet_for_handle_out_of_range_is_none(self) -> None:
        s = _set(("vault:a", "h0"))
        assert s.packet_for_handle("src:1") is None
        assert s.packet_for_handle("src:99") is None

    def test_content_hash_for_handle(self) -> None:
        s = _set(("vault:a", "h0"), ("rag:b", "h1"))
        assert s.content_hash_for_handle("src:1") == "h1"
        assert s.content_hash_for_handle("src:9") is None


class TestBuildResolvedSourceSet:
    def test_dedups_by_content_hash(self) -> None:
        # Two refs, same content → one citable handle (the content is the identity).
        s = build_resolved_source_set(
            "t", (_packet("vault:a", "dup"), _packet("vault:b", "dup"), _packet("rag:c", "uniq"))
        )
        assert s is not None
        assert len(s.packets) == 2
        assert s.handles == ("src:0", "src:1")

    def test_empty_packets_returns_none_not_empty_set(self) -> None:
        # Refuse-on-empty is constructive: a no-source run cannot build a set.
        assert build_resolved_source_set("t", ()) is None

    def test_embeds_set_hash(self) -> None:
        s = _set(("vault:a", "h0"))
        assert len(s.set_hash) == 64
        assert s.set_hash == s.compute_set_hash()


# ---------------------------------------------------------------------------
# Layer 1 — the constructive dereference: citation is membership, not shape
# ---------------------------------------------------------------------------


class TestValidateCitedHandles:
    def test_resolvable_handles_pass(self) -> None:
        s = _set(("vault:a", "h0"), ("rag:b", "h1"))
        result = validate_cited_handles(s, ["src:0", "src:1"])
        assert result["ok"] is True
        assert result["unresolved"] == []
        assert set(result["resolved_content_hashes"]) == {"h0", "h1"}

    def test_fabricated_handle_is_unresolved(self) -> None:
        s = _set(("vault:a", "h0"))
        result = validate_cited_handles(s, ["src:0", "src:99"])
        assert result["ok"] is False
        assert "src:99" in result["unresolved"]

    def test_freetext_ref_is_unresolved(self) -> None:
        # vault:research-notes was the seeded fabrication — not a handle, refused.
        s = _set(("vault:a", "h0"))
        result = validate_cited_handles(s, ["vault:research-notes"])
        assert result["ok"] is False
        assert "vault:research-notes" in result["unresolved"]

    def test_no_handles_is_refused(self) -> None:
        s = _set(("vault:a", "h0"))
        result = validate_cited_handles(s, [])
        assert result["ok"] is False


class TestSourceProvenance:
    def test_hashes_resolved_content_not_model_text(self) -> None:
        import hashlib

        s = _set(("vault:a", "h0"), ("rag:b", "h1"))
        prov = source_provenance_sha256(s)
        assert len(prov) == 64
        # Provenance is over the resolved content hashes — the model's own prose
        # cannot forge it.
        model_text_hash = hashlib.sha256(b"whatever the model wrote").hexdigest()
        assert prov != model_text_hash

    def test_provenance_stable_and_order_independent(self) -> None:
        s1 = _set(("vault:a", "h0"), ("rag:b", "h1"))
        s2 = _set(("rag:b", "h1"), ("vault:a", "h0"))
        assert source_provenance_sha256(s1) == source_provenance_sha256(s2)

    def test_provenance_changes_with_content(self) -> None:
        s1 = _set(("vault:a", "h0"))
        s2 = _set(("vault:a", "DIFFERENT"))
        assert source_provenance_sha256(s1) != source_provenance_sha256(s2)


# ---------------------------------------------------------------------------
# Layer 2 — the recruiter produces the closed set; never fabricates to fill
# ---------------------------------------------------------------------------


class TestRecruitSourceSet:
    def test_recruits_resolved_set_from_gathered_packets(self, monkeypatch) -> None:
        from agents.hapax_daimonion import angle_resolver

        gathered = [_packet("qdrant:documents:a", "h0"), _packet("vault:30-areas/n.md", "h1")]
        monkeypatch.setattr(angle_resolver, "_gather_sources", lambda *a, **k: gathered)
        s = angle_resolver.recruit_source_set("any topic")
        assert s is not None
        assert s.handles == ("src:0", "src:1")
        assert s.packet_for_handle("src:0").source_ref == "qdrant:documents:a"

    def test_no_sources_refuses_with_none(self, monkeypatch) -> None:
        from agents.hapax_daimonion import angle_resolver

        # Local corpus AND the web leg both dry, and the re-angle pivot yields no new
        # queries → recruit must refuse, not fabricate to fill. Mock all three legs so the
        # unit stays hermetic (no network, no LLM); the refusal here is honest EXHAUSTION
        # (after traversal), not a first-miss.
        monkeypatch.setattr(angle_resolver, "_gather_sources", lambda *a, **k: [])
        monkeypatch.setattr(angle_resolver, "_tavily_packets", lambda *a, **k: [])
        monkeypatch.setattr(angle_resolver, "_reangle_queries", lambda *a, **k: [])
        assert angle_resolver.recruit_source_set("topic with no sources") is None


class TestNoFabricateToFill:
    def test_parse_without_supporting_does_not_invent_first_three(self) -> None:
        from agents.hapax_daimonion.angle_resolver import _parse_angle_response

        packets = [_packet(f"vault:n{i}", f"h{i}") for i in range(5)]
        # LLM named NO supporting/challenging sources.
        text = "THESIS: a thesis\nOPENING_PRESSURE: a hook\n"
        angle = _parse_angle_response("topic", text, packets)
        # Old behavior fabricated supporting = packets[:3]; that is forbidden.
        assert angle.supporting_sources == ()

    def test_llm_failure_does_not_fabricate_all_as_supporting(self, monkeypatch) -> None:
        import litellm

        from agents.hapax_daimonion.angle_resolver import _select_angle

        def _boom(*a, **k):
            raise RuntimeError("provider down")

        monkeypatch.setattr(litellm, "completion", _boom)
        packets = [_packet(f"vault:n{i}", f"h{i}") for i in range(4)]
        # On LLM failure the resolver must NOT invent an angle over all packets.
        assert _select_angle("topic", packets) is None


# ---------------------------------------------------------------------------
# Layer 3a — quarantine unknown grounding refs (stop downstream laundering)
# ---------------------------------------------------------------------------


class TestGealQuarantine:
    def test_known_prefixes_classify(self) -> None:
        from shared.geal_grounding_classifier import classify_source_or_quarantine

        assert classify_source_or_quarantine("vault:30-areas/n.md") == "bl"
        assert classify_source_or_quarantine("qdrant:documents:x") == "bl"
        assert classify_source_or_quarantine("chat:keyword") == "br"

    def test_unknown_ref_is_quarantined(self) -> None:
        from shared.geal_grounding_classifier import classify_source_or_quarantine

        # No silent default-to-'bl' affirmation: unknown → None (quarantine).
        assert classify_source_or_quarantine("wholly_unknown.foo.bar") is None
        assert classify_source_or_quarantine("") is None

    def test_is_known_grounding_source(self) -> None:
        from shared.geal_grounding_classifier import is_known_grounding_source

        assert is_known_grounding_source("vault:x") is True
        assert is_known_grounding_source("wholly_unknown") is False
        assert is_known_grounding_source("") is False

    def test_render_classify_source_stays_back_compat(self) -> None:
        # The visual render keeps a safe default so geal_source never paints None.
        from shared.geal_grounding_classifier import classify_source

        assert classify_source("wholly_unknown.foo.bar") == "bl"
        assert classify_source("") == "bl"


# ---------------------------------------------------------------------------
# Layer 3b — source-consequence binds resolved content, never the script itself
# ---------------------------------------------------------------------------

_CONSEQUENCE_SCRIPT = [
    "Zuboff argues extraction changes the chart, so the ranking places surveillance "
    "capitalism in S-tier because the evidence alters the stakes."
]


class TestSourceConsequenceBinding:
    def test_binds_resolved_content_hash_not_prepared_script(self) -> None:
        from shared.segment_prep_consultation import build_source_consequence_map

        s = _set(("vault:zuboff", "zh0"))
        intents = [{"beat_index": 0, "intents": [{"kind": "source_citation", "target": "src:0"}]}]
        out = build_source_consequence_map(_CONSEQUENCE_SCRIPT, intents, resolved_source_set=s)
        assert out
        assert out[0]["evidence_ref"] == "content_hash:zh0"
        assert all("prepared_script[" not in row["evidence_ref"] for row in out)

    def test_unresolvable_handle_target_is_not_fabricated(self) -> None:
        from shared.segment_prep_consultation import build_source_consequence_map

        s = _set(("vault:zuboff", "zh0"))
        intents = [{"beat_index": 0, "intents": [{"kind": "source_citation", "target": "src:99"}]}]
        out = build_source_consequence_map(_CONSEQUENCE_SCRIPT, intents, resolved_source_set=s)
        # src:99 does not resolve against the set → no fabricated consequence row.
        assert out == []

    def test_legacy_path_has_no_circular_prepared_script_ref(self) -> None:
        from shared.segment_prep_consultation import (
            build_source_consequence_map,
            validate_source_consequence_map,
        )

        out = build_source_consequence_map(_CONSEQUENCE_SCRIPT)
        assert all("prepared_script[" not in row["evidence_ref"] for row in out)
        # Still a valid advisory map (shape unchanged).
        assert validate_source_consequence_map(out)["ok"] is True


# ---------------------------------------------------------------------------
# Layer 4 — the contract dereferences cited handles against the recruited set
# ---------------------------------------------------------------------------

_CONTRACT_SOURCE_REF = "vault:test-segment-source"


def _built_contract(
    *, ref: str = _CONTRACT_SOURCE_REF, cited_handles: list[str] | None = ("src:0",)
) -> tuple:
    """A model-emitted contract that passes no-set validation, plus its script/beats.

    ``ref`` is what claim grounds / source_packet_refs / consequences cite. The
    default is the real recruited ref; pass ``ref="src:0"`` to exercise the
    handle-form citation (cite ONLY by handle). ``cited_handles`` is the index-
    based citation that dereferences against the recruited set.
    """
    from agents.hapax_daimonion import daily_segment_prep as prep

    beats = [
        "open the proof using vault:test-segment-source",
        "compare the claim against vault:test-segment-source",
    ]
    script = [
        "According to the test source, now compare the launch claim against the visible "
        "receipt because the source changes confidence.",
        "Then compare the narrowed claim with the original claim, according to the test "
        "source. Therefore the final decision returns to the opening receipt.",
    ]
    actionability = prep.validate_segment_actionability(script, beats)
    layout = prep.validate_layout_responsibility(actionability["beat_action_intents"])
    model_contract = {
        "source_packet_refs": [
            {
                "id": "packet:test-source",
                "source_ref": ref,
                "evidence_refs": [ref],
            }
        ],
        "claim_map": [
            {"claim": "the receipt changes launch confidence", "evidence_ref": ref},
            {"claim": "the narrowed claim must resolve the opening receipt", "evidence_ref": ref},
        ],
        "source_consequence_map": [
            {"source_ref": ref, "consequence": "launch confidence changes"},
            {"source_ref": ref, "consequence": "the final scope narrows"},
        ],
        "actionability_map": [
            {"beat_index": 0, "action": "comparison", "target": "launch receipt"},
            {"beat_index": 1, "action": "comparison", "target": "narrowed claim"},
        ],
        "layout_need_map": [
            {"beat_index": 0, "need": "source_visible", "evidence_ref": ref},
            {"beat_index": 1, "need": "source_visible", "evidence_ref": ref},
        ],
        "readback_obligations": [],
        "loop_cards": [],
        "role_excellence_plan": {
            "live_event_plan": {
                "bit_engine": "source-backed comparison",
                "audience_job": "inspect the receipt",
                "payoff": "resolve whether the receipt supports launch",
            }
        },
    }
    contract = prep.build_segment_prep_contract(
        programme_id="prog-deref",
        role="lecture",
        topic="Contract dereference",
        segment_beats=beats,
        script=script,
        actionability=actionability,
        layout_responsibility=layout,
        source_refs=[ref],
        model_contract=model_contract,
    )
    if cited_handles is not None:
        contract["cited_handles"] = list(cited_handles)
    return contract, script, beats


def _reasons(report: dict) -> set[str]:
    return {v.get("reason") for v in report.get("violations", [])}


class TestContractDereference:
    def test_no_set_is_backcompat_shape_check(self) -> None:
        from shared.segment_prep_contract import validate_segment_prep_contract

        contract, script, beats = _built_contract(cited_handles=None)
        report = validate_segment_prep_contract(
            contract, prepared_script=script, segment_beats=beats
        )
        # Existing behavior unchanged when no resolved set is supplied.
        assert report == {"ok": True, "violations": []}

    def test_grounds_resolving_in_recruited_set_pass(self) -> None:
        from shared.segment_prep_contract import validate_segment_prep_contract

        contract, script, beats = _built_contract()
        rset = _set((_CONTRACT_SOURCE_REF, "h0"))
        report = validate_segment_prep_contract(
            contract, prepared_script=script, segment_beats=beats, resolved_source_set=rset
        )
        assert report == {"ok": True, "violations": []}

    def test_ground_not_in_recruited_set_is_refused(self) -> None:
        from shared.segment_prep_contract import validate_segment_prep_contract

        contract, script, beats = _built_contract()
        # The set recruited a DIFFERENT real source — the cited ground was never
        # recruited, so dereference fails (not self-closure to the model's packets).
        rset = _set(("vault:some-other-recruited-note", "h0"))
        report = validate_segment_prep_contract(
            contract, prepared_script=script, segment_beats=beats, resolved_source_set=rset
        )
        assert report["ok"] is False
        assert "claim_ground_not_resolved" in _reasons(report)

    def test_missing_cited_handles_refused_in_set_mode(self) -> None:
        from shared.segment_prep_contract import validate_segment_prep_contract

        contract, script, beats = _built_contract(cited_handles=None)
        rset = _set((_CONTRACT_SOURCE_REF, "h0"))
        report = validate_segment_prep_contract(
            contract, prepared_script=script, segment_beats=beats, resolved_source_set=rset
        )
        assert report["ok"] is False
        assert "missing_cited_handles" in _reasons(report)

    def test_fabricated_handle_refused(self) -> None:
        from shared.segment_prep_contract import validate_segment_prep_contract

        contract, script, beats = _built_contract(cited_handles=["src:0", "src:99"])
        rset = _set((_CONTRACT_SOURCE_REF, "h0"))
        report = validate_segment_prep_contract(
            contract, prepared_script=script, segment_beats=beats, resolved_source_set=rset
        )
        assert report["ok"] is False
        assert "cited_handles_unresolved" in _reasons(report)


class TestHandleFormCitation:
    """The composer cites ONLY by handle (src:N); shape checks accept handles and
    the dereference is the load-bearing gate."""

    def test_shape_checks_accept_handles(self) -> None:
        from shared.segment_prep_contract import is_content_evidence_ref, is_source_evidence_ref

        assert is_content_evidence_ref("src:0") is True
        assert is_source_evidence_ref("src:0") is True
        # Real refs still recognized; bare/short non-handles still rejected.
        assert is_source_evidence_ref("vault:30-areas/note.md") is True
        assert is_content_evidence_ref("src:") is False

    def test_build_preserves_cited_handles(self) -> None:
        contract, _script, _beats = _built_contract(ref="src:0", cited_handles=["src:0"])
        assert contract["cited_handles"] == ["src:0"]

    def test_handle_form_contract_dereferences(self) -> None:
        from shared.segment_prep_contract import validate_segment_prep_contract

        # Everything cites src:0 — the recruited handle. The set has one packet at
        # index 0, so src:0 resolves regardless of its underlying source_ref.
        contract, script, beats = _built_contract(ref="src:0", cited_handles=["src:0"])
        rset = _set(("qdrant:documents:recruited", "rh0"))
        report = validate_segment_prep_contract(
            contract, prepared_script=script, segment_beats=beats, resolved_source_set=rset
        )
        assert report == {"ok": True, "violations": []}

    def test_handle_form_fabricated_ground_refused(self) -> None:
        from shared.segment_prep_contract import validate_segment_prep_contract

        # The model cited src:5 — beyond the recruited set (one packet) — so the
        # ground does not dereference and the contract is refused.
        contract, script, beats = _built_contract(ref="src:5", cited_handles=["src:5"])
        rset = _set(("qdrant:documents:recruited", "rh0"))
        report = validate_segment_prep_contract(
            contract, prepared_script=script, segment_beats=beats, resolved_source_set=rset
        )
        assert report["ok"] is False
        reasons = _reasons(report)
        assert "claim_ground_not_resolved" in reasons or "cited_handles_unresolved" in reasons
