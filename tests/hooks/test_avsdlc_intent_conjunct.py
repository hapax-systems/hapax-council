"""AVSDLC visual-eval — PR 4b: the intent gate conjunct (where intent GATES).

Overall AVSDLC PASS becomes conjunctive: ``floors_pass AND intent_pass AND
obs_moving``. The release gate, under the staged ``require_intent`` switch
(default OFF, env ``HAPAX_AVSDLC_REQUIRE_INTENT_PREDICATE``), enforces that a
declared ``VisualIntentRecord`` (``avsdlc_intent_record`` frontmatter) was:

  * evaluated by the INDEPENDENT witness — the verified receipt's signed
    ``intent_hash`` must equal ``intent_hash_from_record(declared)`` (the witness
    committed to THIS record → swap-resistant), AND
  * CONFIRMED by it — the receipt's signed ``intent_pass`` is True (the realized
    per-region vector, produced by the witness from a live frame, satisfied the
    pre-authored predicates).

The authoring session cannot self-mint the verdict (witness independence). This
is the predict-then-confirm capstone: a claim now corresponds to a prediction
made BEFORE the outcome, mechanically compared by an independent witness over the
exact deployed bytes.

cc-task: avsdlc-visual-eval-gate-conjunct (CASE-AVSDLC-VISUAL-INTENT-20260622).
Self-contained per workspace test convention.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from shared.governance.coord_capabilities import (
    mint_av_witness_receipt,
    parse_av_receipt,
    serialize_av_receipt,
    verify_av_witness_receipt,
)
from shared.release_gate import evaluate_avsdlc_release_gate

KEY = b"operator-secret-key-0123456789abcdef"
NOW = 1_800_000_000.0
CONTENT_HASH = "a" * 64
SOURCE_HEAD = "9757f7bde0363d9e3ca0a7692bb172b2a02084ea"

# A minimal valid VisualIntentRecord: entity_core luma must drop to <= 10
# (the motivating AoA white-fix shape: a dark core, not a white blob).
_INTENT_RECORD = {
    "predicates": [
        {
            "pov_label": "cam0",
            "region": "entity_core",
            "metric": "luma",
            "op": "<=",
            "target": 10.0,
            "direction": "decrease",
            "critical": True,
        }
    ],
    "aggregation_floor": 0.75,
    "note": "core must be dark, not white",
}


def _intent_json() -> str:
    return json.dumps(_INTENT_RECORD)


def _intent_hash() -> str:
    from shared.avsdlc_visual_intent import intent_hash_from_record, parse_intent_record

    return intent_hash_from_record(parse_intent_record(_intent_json()))  # type: ignore[arg-type]


def _receipt(
    *,
    intent_hash: str = "",
    intent_pass: bool = False,
    path: Path | None = None,
) -> Path:
    receipt = mint_av_witness_receipt(
        content_hash=CONTENT_HASH,
        active_source_head=SOURCE_HEAD,
        status="pass",
        obs_moving=True,
        ttl_s=3600.0,
        key=KEY,
        now=NOW,
        intent_hash=intent_hash,
        intent_pass=intent_pass,
    )
    out = path if path is not None else Path(__file__).parent / "_intent_receipt.json"
    out.write_text(serialize_av_receipt(receipt), encoding="utf-8")
    return out


def _fm(
    receipt_path: Path,
    *,
    intent_record: str | None = None,
    axes: list[str] | None = None,
    content_hash: str = CONTENT_HASH,
) -> dict:
    fm: dict = {
        "avsdlc_axes": axes if axes is not None else ["visual"],
        "avsdlc_dossier": "dossier.md",
        "visual_witness": "before-after.png",
        "avsdlc_evidence_collected_at": NOW + 60,
        "avsdlc_content_hash": content_hash,
        "runtime_media_witness": str(receipt_path),
        "runtime_media_impact": True,
    }
    if intent_record is not None:
        fm["avsdlc_intent_record"] = intent_record
    return fm


# ── receipt model: intent_pass is signed + round-trips ─────────────────


class TestReceiptIntentPass:
    def test_intent_pass_round_trips(self) -> None:
        receipt = mint_av_witness_receipt(
            content_hash=CONTENT_HASH,
            active_source_head=SOURCE_HEAD,
            status="pass",
            obs_moving=True,
            ttl_s=3600.0,
            key=KEY,
            now=NOW,
            intent_hash=_intent_hash(),
            intent_pass=True,
        )
        parsed = parse_av_receipt(serialize_av_receipt(receipt))
        assert parsed is not None
        assert parsed.intent_hash == _intent_hash()
        assert parsed.intent_pass is True

    def test_intent_pass_default_false(self) -> None:
        receipt = mint_av_witness_receipt(
            content_hash=CONTENT_HASH,
            active_source_head=SOURCE_HEAD,
            status="pass",
            obs_moving=True,
            ttl_s=3600.0,
            key=KEY,
            now=NOW,
        )
        assert receipt.intent_pass is False
        assert receipt.intent_hash == ""

    def test_intent_pass_tamper_rejected(self) -> None:
        receipt = mint_av_witness_receipt(
            content_hash=CONTENT_HASH,
            active_source_head=SOURCE_HEAD,
            status="pass",
            obs_moving=True,
            ttl_s=3600.0,
            key=KEY,
            now=NOW,
            intent_hash=_intent_hash(),
            intent_pass=False,
        )
        forged = replace(receipt, intent_pass=True)  # flip without re-signing
        assert not verify_av_witness_receipt(forged, key=KEY, now=NOW + 60)


# ── the gate conjunct ──────────────────────────────────────────────────


class TestIntentConjunct:
    def test_require_intent_off_is_inert(self, tmp_path: Path) -> None:
        # Declared record but switch OFF → no intent blocker (backward-compat).
        path = _receipt(path=tmp_path / "r.json")
        fm = _fm(path, intent_record=_intent_json())
        result = evaluate_avsdlc_release_gate(fm, now=NOW + 60, key=KEY)
        assert result.passed
        assert not any(b.startswith("avsdlc_intent_") for b in result.blockers)

    def test_require_intent_on_no_record_visual_axis_blocks(self, tmp_path: Path) -> None:
        path = _receipt(path=tmp_path / "r.json")
        fm = _fm(path)  # visual axis, no avsdlc_intent_record
        result = evaluate_avsdlc_release_gate(fm, now=NOW + 60, key=KEY, require_intent=True)
        assert not result.passed
        assert "avsdlc_intent_record_missing" in result.blockers

    def test_require_intent_on_unparseable_record_blocks(self, tmp_path: Path) -> None:
        path = _receipt(path=tmp_path / "r.json")
        fm = _fm(path, intent_record="{not json")
        result = evaluate_avsdlc_release_gate(fm, now=NOW + 60, key=KEY, require_intent=True)
        assert not result.passed
        assert "avsdlc_intent_record_unparseable" in result.blockers

    def test_require_intent_on_hash_mismatch_blocks(self, tmp_path: Path) -> None:
        # Receipt was minted against a DIFFERENT record than the frontmatter declares
        # → the witness did not evaluate THIS prediction → swap-resistant block.
        path = _receipt(intent_hash="deadbeef" * 8, intent_pass=True, path=tmp_path / "r.json")
        fm = _fm(path, intent_record=_intent_json())
        result = evaluate_avsdlc_release_gate(fm, now=NOW + 60, key=KEY, require_intent=True)
        assert not result.passed
        assert "avsdlc_intent_hash_mismatch" in result.blockers

    def test_require_intent_on_not_confirmed_blocks(self, tmp_path: Path) -> None:
        # Hash matches but the witness verdict was False (realized vector contradicted
        # the prediction) → the change did NOT do what it intended → block.
        path = _receipt(intent_hash=_intent_hash(), intent_pass=False, path=tmp_path / "r.json")
        fm = _fm(path, intent_record=_intent_json())
        result = evaluate_avsdlc_release_gate(fm, now=NOW + 60, key=KEY, require_intent=True)
        assert not result.passed
        assert "avsdlc_intent_not_confirmed" in result.blockers

    def test_require_intent_on_confirmed_passes(self, tmp_path: Path) -> None:
        # Hash matches AND the independent witness confirmed → passes (floors also up).
        path = _receipt(intent_hash=_intent_hash(), intent_pass=True, path=tmp_path / "r.json")
        fm = _fm(path, intent_record=_intent_json())
        result = evaluate_avsdlc_release_gate(fm, now=NOW + 60, key=KEY, require_intent=True)
        assert result.passed
        assert not any(b.startswith("avsdlc_intent_") for b in result.blockers)

    def test_require_intent_on_non_visual_axis_no_record_ok(self, tmp_path: Path) -> None:
        # A non-visual change (e.g. theoretical) is not asked to pre-register visual intent.
        path = _receipt(path=tmp_path / "r.json")
        fm = _fm(path, axes=["theoretical"])
        result = evaluate_avsdlc_release_gate(fm, now=NOW + 60, key=KEY, require_intent=True)
        assert not any(b.startswith("avsdlc_intent_") for b in result.blockers)

    def test_require_intent_unbound_receipt_blocks(self, tmp_path: Path) -> None:
        # No declared deployed content hash → the intent-confirmed receipt is byte-
        # portable across tasks within its TTL → block. The thesis compares over the
        # EXACT deployed bytes, so the intent path requires byte binding.
        path = _receipt(intent_hash=_intent_hash(), intent_pass=True, path=tmp_path / "r.json")
        fm = _fm(path, intent_record=_intent_json())
        fm.pop("avsdlc_content_hash")  # no byte binding declared
        result = evaluate_avsdlc_release_gate(fm, now=NOW + 60, key=KEY, require_intent=True)
        assert not result.passed
        assert "avsdlc_intent_receipt_unbound" in result.blockers


# ── flag source resolution (cutover gap #2: cross-caller env consistency) ───


class TestFlagSourceResolution:
    """The intent flag must resolve from the canonical hapax-secrets.env so the
    autoqueue systemd unit AND the in-session keystroke hook (pr-release-gate.sh,
    which never sources secrets.env) agree on enforcement. os.environ wins when
    set; the secrets file is the shared default."""

    def test_flag_in_secrets_enforces_when_env_unset(self, tmp_path: Path, monkeypatch) -> None:
        # A caller with NO env (the keystroke hook) still enforces because the
        # gate reads the flag from the canonical secrets file.
        secrets = tmp_path / "hapax-secrets.env"
        secrets.write_text(
            "# operator secrets\nLITELLM_API_KEY=sk-x\nHAPAX_AVSDLC_REQUIRE_INTENT_PREDICATE=1\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("shared.release_gate.DEFAULT_HAPAX_SECRETS_ENV", secrets)
        monkeypatch.delenv("HAPAX_AVSDLC_REQUIRE_INTENT_PREDICATE", raising=False)
        path = _receipt(path=tmp_path / "r.json")
        fm = _fm(path)  # visual axis, no intent record
        result = evaluate_avsdlc_release_gate(fm, now=NOW + 60, key=KEY)  # NO require_intent kwarg
        assert not result.passed
        assert "avsdlc_intent_record_missing" in result.blockers

    def test_env_flag_wins_over_secrets(self, tmp_path: Path, monkeypatch) -> None:
        # When the process env explicitly carries the flag, it wins over the
        # secrets file — so an ad-hoc override (tests, a one-off OFF) is respected.
        secrets = tmp_path / "hapax-secrets.env"
        secrets.write_text("HAPAX_AVSDLC_REQUIRE_INTENT_PREDICATE=1\n", encoding="utf-8")
        monkeypatch.setattr("shared.release_gate.DEFAULT_HAPAX_SECRETS_ENV", secrets)
        monkeypatch.setenv("HAPAX_AVSDLC_REQUIRE_INTENT_PREDICATE", "0")  # env wins → inert
        path = _receipt(path=tmp_path / "r.json")
        fm = _fm(path)
        result = evaluate_avsdlc_release_gate(fm, now=NOW + 60, key=KEY)
        assert not any(b.startswith("avsdlc_intent_") for b in result.blockers)

    def test_no_flag_anywhere_is_inert(self, tmp_path: Path, monkeypatch) -> None:
        secrets = tmp_path / "hapax-secrets.env"
        secrets.write_text("LITELLM_API_KEY=sk-x\n", encoding="utf-8")  # no intent flag
        monkeypatch.setattr("shared.release_gate.DEFAULT_HAPAX_SECRETS_ENV", secrets)
        monkeypatch.delenv("HAPAX_AVSDLC_REQUIRE_INTENT_PREDICATE", raising=False)
        path = _receipt(intent_hash=_intent_hash(), intent_pass=True, path=tmp_path / "r.json")
        fm = _fm(path, intent_record=_intent_json())
        result = evaluate_avsdlc_release_gate(fm, now=NOW + 60, key=KEY)
        assert result.passed
        assert not any(b.startswith("avsdlc_intent_") for b in result.blockers)

    def test_helper_reads_quoted_value_and_skips_comments(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from shared.release_gate import _env_or_secrets_flag

        secrets = tmp_path / "hapax-secrets.env"
        secrets.write_text(
            '# comment\nHAPAX_AVSDLC_REQUIRE_INTENT_PREDICATE="yes"\nBARE=plain\n',
            encoding="utf-8",
        )
        monkeypatch.setattr("shared.release_gate.DEFAULT_HAPAX_SECRETS_ENV", secrets)
        monkeypatch.delenv("HAPAX_AVSDLC_REQUIRE_INTENT_PREDICATE", raising=False)
        assert _env_or_secrets_flag("HAPAX_AVSDLC_REQUIRE_INTENT_PREDICATE") == "yes"
        assert _env_or_secrets_flag("BARE") == "plain"
        assert _env_or_secrets_flag("ABSENT_FLAG") == ""
