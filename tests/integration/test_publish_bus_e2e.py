"""End-to-end integration test for the Phase 1 publish bus.

Validates that an approved ``PreprintArtifact`` dropped at
``$HAPAX_STATE/publish/inbox/{slug}.json`` fans out via the orchestrator's
SURFACE_REGISTRY, hits each per-surface ``publish_artifact()``
entry-point, and lands per-surface results at
``$HAPAX_STATE/publish/log/{slug}.{surface}.json``.

Distinct from ``tests/publish_orchestrator/test_orchestrator.py`` which
unit-tests the orchestrator with mock surface registries. This test
exercises the **real** SURFACE_REGISTRY (post-#1416 wiring) against
mocked transport layers — verifying the import paths, entry-point
signatures, and result-string vocabulary all line up.

If a publisher's ``publish_artifact`` is renamed, removed, or its
return-string vocabulary drifts, this test fails loudly.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from unittest import mock

import yaml
from prometheus_client import CollectorRegistry

from agents.publication_bus.publisher_kit import PublisherResult
from agents.publish_orchestrator.orchestrator import (
    FANOUT_SURFACE_IDS,
    PUBLICATION_BASELINE_REQUIRED_GATES,
    PUBLICATION_FANOUT_REQUIRED_GATES,
    SURFACE_REGISTRY,
    Orchestrator,
    _artifact_fingerprint,
)
from shared import public_gate_receipts
from shared.preprint_artifact import PreprintArtifact
from shared.publication_hardening.gate import (
    PublicationGateChildResult,
    PublicationGateDecision,
    PublicationGateResult,
)
from shared.publication_hardening.review import ReviewReport

TASK_ID = "cc-task-public-gate-test"
AUTHORITY_SECRET = "test-public-gate-authority-secret"
PUBLIC_GATE_AUTHORITY_BLOCK = (
    "authority_case: CASE-PUBLIC-EGRESS-TEST\n"
    "acceptor: claim-verification-council\n"
    "review_profile: claim_verification_council_public_egress\n"
    f"evidence_ref: review-dossier:{TASK_ID}\n"
)


def _drop_approved_artifact(
    state_root,
    *,
    slug: str,
    surfaces: list[str],
) -> None:
    artifact = PreprintArtifact(
        slug=slug,
        title=f"E2E test artifact {slug}",
        abstract="Validates publish-bus end-to-end fan-out.",
        body_md="Body content; not consumed by Phase 1 text-only surfaces.",
        attribution_block=(
            "Hapax + Claude Code (substrate). Oudepode (operator, "
            "unsettled contribution as feature)."
        ),
        surfaces_targeted=surfaces,
    )
    artifact.mark_approved(by_referent="Oudepode")
    artifact.publication_gate_context = {
        "publication_gate_receipts": _write_public_gate_receipts(state_root, artifact)
    }
    inbox_path = artifact.inbox_path(state_root=state_root)
    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    inbox_path.write_text(artifact.model_dump_json(indent=2))


def _write_public_gate_receipts(state_root, artifact: PreprintArtifact) -> dict[str, str]:  # type: ignore[no-untyped-def]
    surfaces = artifact.surfaces_targeted
    gates = (
        PUBLICATION_FANOUT_REQUIRED_GATES
        if set(surfaces).intersection(FANOUT_SURFACE_IDS)
        else PUBLICATION_BASELINE_REQUIRED_GATES
    )
    receipt_root = state_root / "public-gate-receipts"
    authority_root = state_root / "public-gate-authority"
    receipt_root.mkdir(parents=True, exist_ok=True)
    authority_root.mkdir(parents=True, exist_ok=True)
    public_gate_receipts.PUBLIC_GATE_AUTHORITY_ROOTS = (authority_root,)
    os.environ[public_gate_receipts.PUBLIC_GATE_AUTHORITY_SECRET_ENV] = AUTHORITY_SECRET
    surfaces_yaml = "\n".join(f"  - {surface}" for surface in sorted(surfaces))
    for gate in gates:
        (receipt_root / f"{gate}.yaml").write_text(
            f"gate_id: {gate}\n"
            "status: passed\n"
            f"{PUBLIC_GATE_AUTHORITY_BLOCK}"
            f"artifact_slug: {artifact.slug}\n"
            f"artifact_fingerprint: {_artifact_fingerprint(artifact)}\n"
            "target_surfaces:\n"
            f"{surfaces_yaml}\n",
            encoding="utf-8",
        )
    _write_public_gate_review_evidence(
        receipt_root,
        gates=tuple(gates),
        receipt_refs=tuple(f"public-gate:{gate}.yaml" for gate in gates),
        artifact_slug=artifact.slug,
        artifact_fingerprint=_artifact_fingerprint(artifact),
        target_surfaces=tuple(sorted(surfaces)),
    )
    return {gate: f"public-gate:{gate}.yaml" for gate in gates}


def _write_public_gate_review_evidence(  # type: ignore[no-untyped-def]
    receipt_root,
    *,
    gates: tuple[str, ...],
    receipt_refs: tuple[str, ...],
    artifact_slug: str,
    artifact_fingerprint: str,
    target_surfaces: tuple[str, ...],
) -> None:
    del receipt_root
    gate_yaml = "\n".join(f"  - {gate}" for gate in gates)
    receipt_yaml = "\n".join(f"  - {receipt_ref}" for receipt_ref in receipt_refs)
    surface_yaml = "\n".join(f"  - {surface}" for surface in target_surfaces)
    payload = yaml.safe_load(
        "dossier_schema: 1\n"
        f"task_id: {TASK_ID}\n"
        "head_sha: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        "review_team_verdict: quorum-accept\n"
        "quorum_required: 1\n"
        "accept_count: 1\n"
        "required_gates:\n"
        f"{gate_yaml}\n"
        "authorized_public_gate_receipts:\n"
        f"{receipt_yaml}\n"
        f"artifact_slug: {artifact_slug}\n"
        f"artifact_fingerprint: {artifact_fingerprint}\n"
        "target_surfaces:\n"
        f"{surface_yaml}\n"
        "authority_issuer: claim-verification-council\n"
        "reviewers:\n"
        "  - id: cvc-1\n"
        "    family: cvc\n"
        "    verdict: accept\n"
    )
    payload["authority_signature"] = public_gate_receipts.public_gate_authority_signature(
        payload,
        AUTHORITY_SECRET,
    )
    (
        public_gate_receipts.PUBLIC_GATE_AUTHORITY_ROOTS[0] / f"{TASK_ID}.review-dossier.yaml"
    ).write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def _read_log(state_root, slug: str, surface: str) -> dict:
    log_path = state_root / "publish" / "log" / f"{slug}.{surface}.json"
    assert log_path.exists(), f"missing log at {log_path}"
    return json.loads(log_path.read_text())


class _ApprovingReviewPass:
    def review_text(
        self,
        text: str,
        *,
        author_model: str | None = None,
        lint_report: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> ReviewReport:
        del text, lint_report, metadata
        return ReviewReport(
            reviewer_model="test-reviewer",
            author_model=author_model,
            overall_confidence=0.99,
        )


class _PassingHardeningGate:
    def evaluate(self, artifact: PreprintArtifact) -> PublicationGateResult:
        del artifact
        report = ReviewReport(
            reviewer_model="test-reviewer",
            overall_confidence=0.99,
        )
        return PublicationGateResult(
            decision=PublicationGateDecision.PASS,
            generated_at="2026-05-13T00:00:00+00:00",
            child_results=(
                PublicationGateChildResult(
                    name="review",
                    decision=PublicationGateDecision.PASS,
                ),
            ),
            review_report=report.to_frontmatter(),
        )


def _make_orchestrator(state_root) -> Orchestrator:  # type: ignore[no-untyped-def]
    return Orchestrator(
        state_root=state_root,
        public_event_path=state_root / "public-events.jsonl",
        review_pass=_ApprovingReviewPass(),
        hardening_gate=_PassingHardeningGate(),
        public_gate_expected_head_sha="a" * 40,
        registry=CollectorRegistry(),
    )


# ── Phase 1 publishers: real SURFACE_REGISTRY, mocked transports ────


class TestPhase1PublishBusEndToEnd:
    """Validates inbox → fanout → log lifecycle for all 4 cross-surface
    publishers + osf-preprint, against the live SURFACE_REGISTRY."""

    def test_all_phase_1_surfaces_registered(self):
        """Pin: SURFACE_REGISTRY has every Phase 1+2 entry.

        ``discord-webhook`` was retired 2026-05-01 per cc-task
        ``discord-public-event-activation-or-retire`` (constitutional refusal,
        ``leverage-REFUSED-discord-community``). It is now REFUSED tier in the
        canonical registry and intentionally absent from the orchestrator
        dispatch registry.
        """
        for surface in (
            "bluesky-post",
            "mastodon-post",
            "arena-post",
            "osf-preprint",
        ):
            assert surface in SURFACE_REGISTRY, f"{surface} missing from SURFACE_REGISTRY"
        assert "discord-webhook" not in SURFACE_REGISTRY, (
            "discord-webhook is REFUSED; runtime dispatch must not reach it"
        )

    def test_e2e_no_credentials_path(self, tmp_path, monkeypatch):
        """Without env credentials, every Phase 1 surface returns
        ``no_credentials``. Artifact moves to ``failed/`` because
        ``no_credentials`` is terminal but not a publication.
        """
        for env_var in (
            "HAPAX_BLUESKY_HANDLE",
            "HAPAX_BLUESKY_APP_PASSWORD",
            "HAPAX_MASTODON_INSTANCE_URL",
            "HAPAX_MASTODON_ACCESS_TOKEN",
            "HAPAX_ARENA_TOKEN",
            "HAPAX_ARENA_CHANNEL_SLUG",
        ):
            monkeypatch.delenv(env_var, raising=False)

        _drop_approved_artifact(
            tmp_path,
            slug="e2e-no-creds",
            surfaces=[
                "bluesky-post",
                "mastodon-post",
                "arena-post",
            ],
        )
        orch = _make_orchestrator(tmp_path)

        handled = orch.run_once()
        assert handled == 1

        # All 3 active surfaces report no_credentials (terminal failure).
        # discord-webhook was retired 2026-05-01 (REFUSED tier).
        for surface in ("bluesky-post", "mastodon-post", "arena-post"):
            record = _read_log(tmp_path, "e2e-no-creds", surface)
            assert record["result"] == "no_credentials", f"surface={surface} got {record['result']}"

        assert not (tmp_path / "publish" / "published" / "e2e-no-creds.json").exists()
        assert (tmp_path / "publish" / "failed" / "e2e-no-creds.json").exists()
        assert not (tmp_path / "publish" / "inbox" / "e2e-no-creds.json").exists()

    def test_e2e_bsky_ok_with_mocked_transport(self, tmp_path, monkeypatch):
        """With creds + mocked atproto, bsky returns ``ok`` and
        artifact moves to published/."""
        monkeypatch.setenv("HAPAX_BLUESKY_HANDLE", "test.bsky.social")
        monkeypatch.setenv("HAPAX_BLUESKY_APP_PASSWORD", "abcd-efgh-ijkl-mnop")

        _drop_approved_artifact(tmp_path, slug="e2e-bsky-ok", surfaces=["bluesky-post"])

        orch = _make_orchestrator(tmp_path)

        from agents.cross_surface import bluesky_post

        publisher_mock = mock.Mock()
        publisher_mock.publish = mock.Mock(return_value=PublisherResult(ok=True, detail="at://ok"))
        with mock.patch.object(
            bluesky_post, "_default_publisher_factory", return_value=publisher_mock
        ):
            handled = orch.run_once()

        assert handled == 1
        assert _read_log(tmp_path, "e2e-bsky-ok", "bluesky-post")["result"] == "ok"
        assert (tmp_path / "publish" / "published" / "e2e-bsky-ok.json").exists()

        # The publisher was called with the artifact's attribution_block as the
        # body, since attribution_block takes precedence over title/abstract.
        called_text = publisher_mock.publish.call_args.args[0].text
        assert "Hapax + Claude Code" in called_text
        assert "unsettled contribution as feature" in called_text

    def test_e2e_discord_typed_artifact_quarantines_refused_surface(self, tmp_path, monkeypatch):
        """discord-webhook was retired 2026-05-01 (cc-task
        ``discord-public-event-activation-or-retire``). A direct inbox artifact
        targeting ``discord-webhook`` is now rejected at the configured
        publication-surface allowlist before registry dispatch.
        """
        monkeypatch.delenv("HAPAX_DISCORD_WEBHOOK_URL", raising=False)

        _drop_approved_artifact(tmp_path, slug="e2e-discord-refused", surfaces=["discord-webhook"])

        orch = _make_orchestrator(tmp_path)

        handled = orch.run_once()
        assert handled == 1
        assert not (
            tmp_path / "publish" / "log" / "e2e-discord-refused.discord-webhook.json"
        ).exists()
        failed = list((tmp_path / "publish" / "failed").glob("invalid-artifact-*.json"))
        assert len(failed) == 1
        payload = json.loads(failed[0].read_text())
        child = payload["publication_gate_result"]["child_results"][0]
        assert child["name"] == "artifact_envelope"
        assert any("discord-webhook" in finding for finding in child["findings"])

    def test_e2e_arena_ok_with_mocked_transport(self, tmp_path, monkeypatch):
        """With token + slug set + mocked Arena adapter, arena returns ``ok``."""
        monkeypatch.setenv("HAPAX_ARENA_TOKEN", "test-token")
        monkeypatch.setenv("HAPAX_ARENA_CHANNEL_SLUG", "hapax-test-channel")

        _drop_approved_artifact(tmp_path, slug="e2e-arena-ok", surfaces=["arena-post"])

        orch = _make_orchestrator(tmp_path)

        from agents.publication_bus import arena_publisher

        adapter_mock = mock.Mock()
        adapter_mock.add_block = mock.Mock(return_value=None)
        with mock.patch.object(
            arena_publisher, "_default_client_factory", return_value=adapter_mock
        ):
            handled = orch.run_once()

        assert handled == 1
        assert _read_log(tmp_path, "e2e-arena-ok", "arena-post")["result"] == "ok"

        # Arena receives the channel slug as positional + content as kwarg.
        adapter_mock.add_block.assert_called_once()
        args, kwargs = adapter_mock.add_block.call_args
        assert args == ("hapax-test-channel",)
        assert "Hapax + Claude Code" in kwargs["content"]

    def test_e2e_multi_surface_partial_credentials(self, tmp_path, monkeypatch):
        """One surface has creds (bsky), three don't. Each reports
        independently; artifact moves to failed/ because only all-ok
        artifacts count as published."""
        monkeypatch.setenv("HAPAX_BLUESKY_HANDLE", "test.bsky.social")
        monkeypatch.setenv("HAPAX_BLUESKY_APP_PASSWORD", "abcd-efgh-ijkl-mnop")
        for env_var in (
            "HAPAX_MASTODON_INSTANCE_URL",
            "HAPAX_MASTODON_ACCESS_TOKEN",
            "HAPAX_ARENA_TOKEN",
            "HAPAX_ARENA_CHANNEL_SLUG",
        ):
            monkeypatch.delenv(env_var, raising=False)

        _drop_approved_artifact(
            tmp_path,
            slug="e2e-partial",
            surfaces=[
                "bluesky-post",
                "mastodon-post",
                "arena-post",
            ],
        )

        orch = _make_orchestrator(tmp_path)

        from agents.cross_surface import bluesky_post

        publisher_mock = mock.Mock()
        publisher_mock.publish = mock.Mock(return_value=PublisherResult(ok=True, detail="at://ok"))
        with mock.patch.object(
            bluesky_post, "_default_publisher_factory", return_value=publisher_mock
        ):
            handled = orch.run_once()

        assert handled == 1
        assert _read_log(tmp_path, "e2e-partial", "bluesky-post")["result"] == "ok"
        assert _read_log(tmp_path, "e2e-partial", "mastodon-post")["result"] == "no_credentials"
        assert _read_log(tmp_path, "e2e-partial", "arena-post")["result"] == "no_credentials"
        assert not (tmp_path / "publish" / "published" / "e2e-partial.json").exists()
        assert (tmp_path / "publish" / "failed" / "e2e-partial.json").exists()

    def test_e2e_unwired_surface_quarantines_before_dispatch(self, tmp_path):
        """A typo in surfaces_targeted (not in SURFACE_REGISTRY) lands as
        an artifact-envelope quarantine before dispatch."""
        _drop_approved_artifact(
            tmp_path,
            slug="e2e-typo",
            surfaces=["bluesky-pst"],  # typo: should be bluesky-post
        )

        orch = _make_orchestrator(tmp_path)
        handled = orch.run_once()

        assert handled == 1
        assert not (tmp_path / "publish" / "log" / "e2e-typo.bluesky-pst.json").exists()
        assert not (tmp_path / "publish" / "published" / "e2e-typo.json").exists()
        failed = list((tmp_path / "publish" / "failed").glob("invalid-artifact-*.json"))
        assert len(failed) == 1
        payload = json.loads(failed[0].read_text())
        child = payload["publication_gate_result"]["child_results"][0]
        assert child["name"] == "artifact_envelope"
        assert any("bluesky-pst" in finding for finding in child["findings"])
