"""Synthetic ordinary-work projection; no fixture authorizes a real public emission."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agents.studio_compositor import chronicle_ticker as ct
from shared.chronicle import ChronicleEvent

NOW = datetime(2026, 10, 8, 1, 15, tzinfo=UTC).timestamp()
APERTURE = "aperture:composed-livestream-frame"
SURFACE = "composed_livestream_frame"


def fixture_input():
    """Explicitly synthetic source + admission; observation is later than occurrence."""
    event = {
        "schema_version": 1,
        "event_id": "synthetic:work:001",
        "event_type": "publication.artifact",
        "occurred_at": "2026-10-08T01:14:00Z",
        "broadcast_id": None,
        "programme_id": None,
        "condition_id": None,
        "salience": 0.9,
        "state_kind": "archive_artifact",
        "rights_class": "operator_original",
        "privacy_class": "public_safe",
        "public_url": "https://example.org/work/001",
        "frame_ref": None,
        "chapter_ref": None,
        "attribution_refs": [],
        "source": {
            "producer": "synthetic_fixture",
            "substrate_id": "publication_artifact",
            "task_anchor": "fixture-only",
            "evidence_ref": "fixture:source:001",
            "freshness_ref": "fixture:occurred_at",
        },
        "provenance": {
            "token": "fixture:token",
            "generated_at": "2026-10-08T01:14:30Z",
            "producer": "synthetic_fixture",
            "evidence_refs": ["fixture:source:001"],
            "rights_basis": "Synthetic fixture only",
            "citation_refs": [],
        },
        "surface_policy": {
            "allowed_surfaces": [SURFACE],
            "denied_surfaces": [],
            "claim_live": False,
            "claim_archive": True,
            "claim_monetizable": False,
            "requires_egress_public_claim": False,
            "requires_audio_safe": False,
            "requires_provenance": True,
            "requires_human_review": False,
            "rate_limit_key": "fixture",
            "redaction_policy": "none",
            "fallback_action": "hold",
            "dry_run_reason": None,
        },
    }
    refs = ["ResearchVehiclePublicEvent:synthetic:work:001", APERTURE, "fixture:source:001"]
    gate = {
        "schema_version": 1,
        "gate_id": "synthetic:gate:001",
        "evaluated_at": "2026-10-08T01:14:45Z",
        "producer": "synthetic_fixture",
        "programme_id": None,
        "format_id": None,
        "run_id": None,
        "public_private_mode": "public_live",
        "grounding_question": "What does this fixture support?",
        "permitted_claim_shape": {
            "claim_kind": "observation",
            "authority_ceiling": "evidence_bound",
            "allowed_verbs": ["observed"],
            "forbidden_verbs": [],
            "scope_limit": "Synthetic fixture only",
        },
        "claim": {
            "claim_text": "Fixture outcome undetermined.",
            "evidence_refs": refs,
            "provenance": {
                "producer": "synthetic_fixture",
                "source_refs": refs,
                "model_id": None,
                "tool_id": "fixture",
                "retrieved_at": "2026-10-08T01:14:45Z",
            },
            "confidence": {"kind": "qualitative", "value": None, "label": "low"},
            "uncertainty": "Classification and publication history unresolved.",
            "scope_limit": "Synthetic fixture only",
            "freshness": {
                "status": "fresh",
                "checked_at": "2026-10-08T01:14:45Z",
                "age_s": 45,
                "ttl_s": 600,
            },
            "rights_state": "operator_original",
            "privacy_state": "public_safe",
            "public_private_mode": "public_live",
            "refusal_correction_path": {
                "refusal_reason": None,
                "correction_event_ref": "https://example.org/corrections/001",
                "artifact_ref": "https://example.org/work/001",
            },
        },
        "gate_state": "pass",
        "infractions": [],
        "gate_result": {
            "may_emit_claim": True,
            "may_publish_live": True,
            "may_publish_archive": True,
            "may_monetize": False,
            "must_emit_refusal_artifact": False,
            "must_emit_correction_artifact": False,
            "blockers": [],
            "unavailable_reasons": [],
        },
        "no_expert_system_policy": {
            "rules_may_gate_and_structure_attempts": True,
            "authoritative_verdict_allowed": False,
            "verdict_requires_evidence_bound_claim": True,
            "latest_intelligence_default": True,
            "older_model_exception_requires_grounding_evidence": True,
        },
        "downstream": {
            **dict.fromkeys(
                (
                    "format_registry_ready",
                    "opportunity_model_ready",
                    "format_evaluator_ready",
                    "runner_ready",
                    "caption_ready",
                    "chapter_ready",
                    "metadata_ready",
                    "monetization_ready",
                ),
                False,
            ),
            "public_event_ready": True,
            "event_refs": refs,
        },
    }
    bind_source(event, gate)
    return event, gate


def bind_source(event, gate):
    digest = hashlib.sha256(
        json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    for refs in (gate["claim"]["evidence_refs"], gate["claim"]["provenance"]["source_refs"]):
        refs[:] = [ref for ref in refs if not ref.startswith("sha256:")]
        if f"sha256:{digest}" not in refs:
            refs.append(f"sha256:{digest}")


def project(event=None, gate=None, now=NOW):
    from agents.studio_compositor.public_work_projection import project_public_work

    original, admission = fixture_input()
    return project_public_work(event or original, gate or admission, observed_at=now)


def test_identity_clocks_policy_and_admission_survive_projection():
    event, gate = fixture_input()
    original = copy.deepcopy((event, gate))
    result = project(event, gate)
    assert result is not None
    assert result.event_id == event["event_id"]
    assert result.valid_time == NOW - 60
    assert result.ts == result.transaction_time == NOW
    assert result.transaction_time == NOW
    assert result.aperture_ref == APERTURE
    assert result.payload["public_event"] == event
    assert result.payload["grounding_gate_result"] == gate
    assert (event, gate) == original
    assert ChronicleEvent.from_json(result.to_json()) == result


def test_explicit_composed_surface_is_schema_supported():
    import jsonschema

    from shared.research_vehicle_public_event import ResearchVehiclePublicEvent

    event, _ = fixture_input()
    assert ResearchVehiclePublicEvent.model_validate(event).surface_policy.allowed_surfaces == [
        SURFACE
    ]
    jsonschema.validate(
        event, json.loads(Path("schemas/research-vehicle-public-event.schema.json").read_text())
    )


@pytest.mark.parametrize(
    "path,value",
    [
        ("surface_policy.allowed_surfaces", ["youtube_description"]),
        ("surface_policy.denied_surfaces", [SURFACE]),
        ("surface_policy.dry_run_reason", "secondary fanout held"),
        ("surface_policy.requires_human_review", True),
        ("surface_policy.requires_audio_safe", True),
        ("surface_policy.requires_egress_public_claim", True),
        ("surface_policy.redaction_policy", "redact_private"),
        ("surface_policy.claim_archive", False),
        ("privacy_class", "operator_private"),
        ("privacy_class", "aggregate_only"),
        ("rights_class", "third_party_uncleared"),
        ("rights_class", "third_party_attributed"),
        ("provenance.token", None),
        ("provenance.evidence_refs", []),
        ("provenance.generated_at", "garbage"),
        ("provenance.generated_at", "2026-10-08T01:16:00Z"),
        ("occurred_at", "2026-10-08T01:04:59Z"),
        ("occurred_at", "2026-10-08T01:16:00Z"),
        ("occurred_at", "2026-10-08T01:14:00"),
        ("occurred_at", "garbage"),
        ("public_url", "file:///tmp/private"),
        ("public_url", "https://127.0.0.1/private"),
        ("public_url", "https://10.0.0.1/private"),
        ("public_url", "https://host.local/private"),
        ("public_url", "https://user:pass@example.org/private"),  # pragma: allowlist secret
        ("public_url", "https://example.org/?token=private"),
        ("event_type", "broadcast.boundary"),
    ],
)
def test_unadmitted_or_stale_source_is_excluded(path, value):
    event, gate = fixture_input()
    target = event
    keys = path.split(".")
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    bind_source(event, gate)
    assert project(event, gate) is None


@pytest.mark.parametrize(
    "path,value",
    [
        ("gate_state", "dry_run"),
        ("public_private_mode", "public_archive"),
        ("gate_result.may_publish_live", False),
        ("gate_result.may_emit_claim", False),
        ("gate_result.blockers", ["held"]),
        ("infractions", ["unsupported_claim"]),
        ("claim.evidence_refs", ["ResearchVehiclePublicEvent:other", APERTURE]),
        ("claim.provenance.source_refs", ["ResearchVehiclePublicEvent:synthetic:work:001"]),
        ("claim.freshness.status", "stale"),
        ("claim.freshness.ttl_s", 10),
        ("claim.freshness.checked_at", "2026-10-08T01:16:00Z"),
        ("claim.confidence.label", "none"),
        ("claim.uncertainty", ""),
        ("claim.uncertainty", " "),
        ("claim.privacy_state", "operator_private"),
        ("claim.rights_state", "unknown"),
        ("claim.refusal_correction_path.correction_event_ref", "file:///private"),
        ("claim.claim_text", "private\nbody"),
        ("no_expert_system_policy.authoritative_verdict_allowed", True),
    ],
)
def test_unbound_or_held_grounding_is_excluded(path, value):
    event, gate = fixture_input()
    target = gate
    keys = path.split(".")
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    assert project(event, gate) is None


def test_relabelled_observation_cannot_refresh_old_occurrence():
    result = project()
    assert result is not None
    from agents.studio_compositor.public_work_projection import read_public_work

    assert (
        read_public_work(
            replace(result, ts=NOW + 1000, transaction_time=NOW + 1000), now=NOW + 1000
        )
        is None
    )
    assert read_public_work(replace(result, aperture_ref="aperture:public-event"), now=NOW) is None
    assert read_public_work(replace(result, public_scope="private"), now=NOW) is None
    assert read_public_work(replace(result, event_id="substituted"), now=NOW) is None


@pytest.mark.parametrize("field", ["ts", "valid_time", "evidence_refs", "payload"])
def test_fresh_envelope_integrity_is_checked_before_display(field):
    from agents.studio_compositor.public_work_projection import read_public_work

    original = project()
    assert original is not None
    # All clocks stay inside the occurrence window; expiry cannot mask these checks.
    now = NOW + 2
    assert read_public_work(original, now=now) == original
    changed = {
        "ts": NOW + 1,
        "valid_time": NOW - 59,
        "evidence_refs": (*original.evidence_refs, "fixture:unbound-extra"),
        "payload": {**original.payload, "salience": 1.0},
    }
    assert read_public_work(replace(original, **{field: changed[field]}), now=now) is None


def test_raising_query_cannot_supply_public_work(monkeypatch):
    def unavailable(**kwargs):
        raise OSError("synthetic query failure")

    monkeypatch.setattr(ct, "query", unavailable)
    assert ct._collect_public_work(NOW) == []


def test_private_body_and_unadmitted_type_token_never_reach_selected_renderer(
    tmp_path, monkeypatch
):
    """Unsafe baseline: selection did not require aperture/admission-aware consumption."""
    import importlib.util

    from agents.studio_compositor.source_registry import SourceRegistry

    spec = importlib.util.spec_from_file_location(
        "atlas_projection_test", "scripts/quake-live-ward-atlas-source.py"
    )
    atlas = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(atlas)
    seen = []

    def construct(registry, schema):
        seen.append(schema)
        return object()

    monkeypatch.setattr(SourceRegistry, "construct_backend", construct)
    atlas._construct_backends(atlas.DEFAULT_LAYOUT, software_sources=("chronicle_ticker",))
    assert len(seen) == 1
    assert seen[0].params.get("public_work_only") is True


def test_selected_projection_filters_before_ranking_and_revalidates(tmp_path, monkeypatch):
    events = tmp_path / "events.jsonl"
    public = project()
    assert public is not None
    unadmitted = replace(
        public, event_id="private", public_scope="private", payload={"salience": 1.0}
    )
    events.write_text(
        "\n".join(
            e.to_json() for e in [public, replace(public, event_id="unbound")] + [unadmitted] * 210
        )
        + "\n"
    )
    monkeypatch.setattr(ct, "CHRONICLE_FILE", events)
    rows = ct._collect_public_work(NOW)
    assert len(rows) == 1
    assert rows[0].event_id == public.event_id
    assert ct._collect_public_work(NOW + 601) == []
    events.write_text('{"malformed":true}\n')
    assert ct._collect_public_work(NOW) == []


def test_event_contents_cannot_change_under_the_same_admission():
    event, gate = fixture_input()
    event["public_url"] = "https://example.org/other-result"
    assert project(event, gate) is None


def test_fully_qualified_synthetic_gate_matches_existing_schema():
    import jsonschema

    _, gate = fixture_input()
    jsonschema.validate(
        gate, json.loads(Path("schemas/grounding-commitment-gate.schema.json").read_text())
    )


@pytest.fixture
def render_scoped_claim(monkeypatch, tmp_path):
    """Observe actual draw calls and pixels for schema-valid, separately scoped claims."""
    import cairo

    from agents.studio_compositor import text_render
    from agents.studio_compositor.homage.bitchx import BITCHX_PACKAGE
    from agents.studio_compositor.public_work_projection import read_public_work

    assert text_render._HAS_PANGO, "Scope preservation requires actual Pango rendering"
    monkeypatch.setattr(ct, "get_active_package", lambda: BITCHX_PACKAGE)
    texts = []
    rendered = []
    real = text_render.render_text

    def draw(cr, style, x=0, y=0):
        # Observe what Pango retained, not merely the Python string sent to it.
        texts.append(text_render._build_layout(cr, style).layout.get_text())
        return real(cr, style, x, y)

    monkeypatch.setattr(text_render, "render_text", draw)

    def render(scope, permitted_scope, *, height=400):
        source, gate = fixture_input()
        gate["claim"].update(
            claim_text="Observed all checks passing.",
            uncertainty="Measurement error is possible.",
            scope_limit=scope,
        )
        gate["permitted_claim_shape"]["scope_limit"] = permitted_scope
        record = project(source, gate)
        assert record is not None
        assert read_public_work(record, now=NOW) is not None
        texts.clear()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 512, height)
        ct._render_public_work(cairo.Context(surface), 512, height, [record])
        surface.flush()
        # Retained with pytest --basetemp for a portable offline pixel/text witness.
        image = tmp_path / f"scope-{len(rendered):02d}.png"
        surface.write_to_png(str(image))
        rendered.append(image)
        image.with_suffix(".json").write_text(
            json.dumps(
                {"source": source, "gate": gate, "drawn_text": texts, "size": [512, height]},
                indent=2,
            )
        )
        return list(texts), bytes(surface.get_data())

    return render


@pytest.mark.parametrize("scope_field", ["claim", "permitted"])
@pytest.mark.parametrize("control", ["\x00", "\x01", "\x1f", "\x7f", "\x85", "\u202e", "\u200b"])
def test_control_character_cannot_hide_material_scope(render_scoped_claim, scope_field, control):
    fixed = "Synthetic checks only."
    hidden = f"One example.{control} No deployed behavior examined."
    scopes = (hidden, fixed) if scope_field == "claim" else (fixed, hidden)
    texts, pixels = render_scoped_claim(*scopes, height=256)
    assert len(texts) == 1 and "content does not fit" in texts[0]
    assert "Observed all checks passing." not in texts
    # Pixel witness: the same complete withholding notice as oversized content.
    notice_texts, notice_pixels = render_scoped_claim(fixed * 200, fixed, height=256)
    assert texts == notice_texts
    assert pixels == notice_pixels


def test_unsupported_scope_never_reaches_pango_measurement(render_scoped_claim, monkeypatch):
    from agents.studio_compositor import text_render

    real_measure = text_render.measure_text

    def measure(cr, style):
        assert style.text.isprintable(), "Unsupported scope reached Pango measurement"
        return real_measure(cr, style)

    monkeypatch.setattr(text_render, "measure_text", measure)
    texts, _ = render_scoped_claim(
        "One example.\x00 No deployed behavior examined.", "Synthetic only."
    )
    assert len(texts) == 1 and "content does not fit" in texts[0]


@pytest.mark.parametrize("scope_field", ["claim", "permitted"])
def test_nul_scope_pair_cannot_display_identical_unqualified_claims(
    render_scoped_claim, scope_field
):
    fixed = "Synthetic checks only."
    first = "One example.\x00 No deployed behavior examined."
    second = "One example.\x00 Deployed behavior also examined."
    a = (first, fixed) if scope_field == "claim" else (fixed, first)
    b = (second, fixed) if scope_field == "claim" else (fixed, second)
    text_a, pixels_a = render_scoped_claim(*a, height=256)
    text_b, pixels_b = render_scoped_claim(*b, height=256)
    assert all("Observed all checks passing." not in texts for texts in (text_a, text_b)) or (
        any("No deployed behavior examined." in text for text in text_a)
        and any("Deployed behavior also examined." in text for text in text_b)
        and text_a != text_b
        and pixels_a != pixels_b
    )


@pytest.mark.parametrize("changed_scope", ["claim", "permitted"])
def test_material_scope_changes_drawn_text_and_pixels(render_scoped_claim, changed_scope):
    narrow = "One constructed example only; no deployed behavior or real users examined."
    broader = "Ten constructed examples only; no deployed behavior or real users examined."
    fixed = "Only synthetic checks; no conclusion about production readiness."
    first = (narrow, fixed) if changed_scope == "claim" else (fixed, narrow)
    second = (broader, fixed) if changed_scope == "claim" else (fixed, broader)
    texts, pixels = render_scoped_claim(*first)
    other_texts, other_pixels = render_scoped_claim(*second)
    assert "Observed all checks passing." in texts
    assert f"Scope: {first[0]}" in texts
    assert f"Permitted scope: {first[1]}" in texts
    assert f"Scope: {second[0]}" in other_texts
    assert f"Permitted scope: {second[1]}" in other_texts
    assert texts != other_texts
    assert pixels != other_pixels


def test_identical_scopes_are_drawn_once(render_scoped_claim):
    scope = "One constructed example only; no deployed behavior or real users examined."
    texts, _ = render_scoped_claim(scope, scope, height=256)
    assert "Observed all checks passing." in texts
    assert texts.count(f"Scope: {scope}") == 1
    assert sum(scope in text for text in texts) == 1


def test_distinct_scope_qualification_is_not_deduplicated_by_prefix(render_scoped_claim):
    scope = "Synthetic checks only."
    permitted = f"{scope} No conclusion about production readiness."
    texts, _ = render_scoped_claim(scope, permitted)
    assert f"Scope: {scope}" in texts
    assert f"Permitted scope: {permitted}" in texts


@pytest.mark.parametrize("oversize_scope", ["claim", "permitted"])
def test_oversize_qualified_content_suppresses_claim(render_scoped_claim, oversize_scope):
    short = "Synthetic checks only."
    long = "No deployed behavior or real users examined. " * 80
    scopes = (long, short) if oversize_scope == "claim" else (short, long)
    texts, _ = render_scoped_claim(*scopes, height=256)
    assert len(texts) == 1 and "content does not fit" in texts[0]
    assert "Observed all checks passing." not in texts


@pytest.mark.parametrize("oversize_scope", ["claim", "permitted"])
def test_renderer_text_cap_cannot_discard_material_scope(render_scoped_claim, oversize_scope):
    from agents.studio_compositor.text_render import MAX_PANGO_TEXT_CHARS

    short = "Synthetic checks only."
    # Printable input isolates the character cap from unsupported-control rejection.
    # A tall canvas prevents the independent height check from masking a missing cap.
    long = "A" * MAX_PANGO_TEXT_CHARS + "No deployed behavior or real users examined."
    scopes = (long, short) if oversize_scope == "claim" else (short, long)
    texts, _ = render_scoped_claim(*scopes, height=10000)
    assert len(texts) == 1 and "content does not fit" in texts[0]
    assert "Observed all checks passing." not in texts


def test_renderer_keeps_uncertainty_and_correction_or_suppresses_claim(monkeypatch):
    import cairo

    from agents.studio_compositor import text_render
    from agents.studio_compositor.homage.bitchx import BITCHX_PACKAGE

    monkeypatch.setattr(ct, "get_active_package", lambda: BITCHX_PACKAGE)
    texts = []
    real = text_render.render_text

    def draw(cr, style, x=0, y=0):
        texts.append(style.text)
        return real(cr, style, x, y)

    monkeypatch.setattr(text_render, "render_text", draw)
    record = project()
    assert record is not None
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 512, 256)
    ct._render_public_work(cairo.Context(surface), 512, 256, [record])
    assert "Fixture outcome undetermined." in texts
    assert "Uncertainty: Classification and publication history unresolved." in texts
    assert "Evidence: https://example.org/work/001" in texts
    assert "Correction: https://example.org/corrections/001" in texts
    assert "Occurred 2026-10-08 01:14:00 UTC" in texts
    texts.clear()
    ct._render_public_work(cairo.Context(surface), 512, 40, [record])
    assert len(texts) == 1 and "content does not fit" in texts[0]
    assert "Fixture outcome undetermined." not in texts


@pytest.mark.parametrize(
    "target,key",
    [
        ("event", "schema_version"),
        ("event", "event_id"),
        ("gate", "gate_id"),
        ("gate", "permitted_claim_shape"),
        ("gate", "downstream"),
        ("gate", "schema_version"),
    ],
)
def test_malformed_contracts_cannot_supply_display(target, key):
    event, gate = fixture_input()
    del (event if target == "event" else gate)[key]
    assert project(event, gate) is None


def test_legacy_publication_projection_is_not_implicitly_promoted():
    from shared.preprint_artifact import ApprovalState, PreprintArtifact
    from shared.publication_artifact_public_event import build_publication_artifact_public_event

    artifact = PreprintArtifact(
        slug="synthetic-work",
        title="Private title must stay private",
        body="Private body must stay private",
        approval=ApprovalState.APPROVED,
        surfaces=["omg-weblog"],
    )
    decision = build_publication_artifact_public_event(
        artifact,
        artifact_fingerprint="synthetic",
        state_root=Path("/synthetic"),
        stage="published",
        generated_at="2026-10-08T01:14:30Z",
    )
    assert decision.public_event is not None
    event = decision.public_event.model_dump(mode="json")
    _, gate = fixture_input()
    assert SURFACE not in event["surface_policy"]["allowed_surfaces"]
    assert project(event, gate) is None
    assert "Private title" not in json.dumps(event)
    assert "Private body" not in json.dumps(event)


def test_selected_ranks_only_eligible_events(tmp_path, monkeypatch):
    high = project()
    event, gate = fixture_input()
    event["event_id"] = "synthetic:work:002"
    event["salience"] = 0.7
    gate = json.loads(json.dumps(gate).replace("synthetic:work:001", "synthetic:work:002"))
    bind_source(event, gate)
    low = project(event, gate)
    assert high is not None and low is not None
    path = tmp_path / "events.jsonl"
    path.write_text(high.to_json() + "\n" + low.to_json() + "\n")
    monkeypatch.setattr(ct, "CHRONICLE_FILE", path)
    assert [item.event_id for item in ct._collect_public_work(NOW)] == [high.event_id, low.event_id]


def test_later_observation_does_not_outrank_later_occurrence(tmp_path, monkeypatch):
    older = project()
    event, gate = fixture_input()
    event.update(event_id="synthetic:work:002", occurred_at="2026-10-08T01:14:30Z")
    event["provenance"]["generated_at"] = "2026-10-08T01:14:40Z"
    gate = json.loads(json.dumps(gate).replace("synthetic:work:001", "synthetic:work:002"))
    bind_source(event, gate)
    newer = project(event, gate, now=NOW - 5)
    assert older is not None and newer is not None
    assert older.ts > newer.ts and older.valid_time < newer.valid_time
    path = tmp_path / "events.jsonl"
    path.write_text(newer.to_json() + "\n" + older.to_json() + "\n")
    monkeypatch.setattr(ct, "CHRONICLE_FILE", path)
    assert [item.event_id for item in ct._collect_public_work(NOW)] == [
        newer.event_id,
        older.event_id,
    ]
