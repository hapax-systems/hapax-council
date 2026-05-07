from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_batch_prep_checks_authority_gate_before_model_probe() -> None:
    body = _read(REPO_ROOT / "scripts" / "batch_prep_segments.sh")

    authority = body.index("if ! check_prep_authority; then")
    model_probe = body.index("\nverify_resident_model\n\ngenerated=")
    assert authority < model_probe
    assert "shared.segment_prep_pause --check --activity pool_generation" in body
    assert "require_selected=False" in body


def test_rte_skips_segment_prep_restart_when_authority_gate_blocks() -> None:
    body = _read(REPO_ROOT / "scripts" / "hapax-rte-remediate")

    assert "hapax-segment-prep.service|hapax-segment-prep.timer" in body
    assert "shared.segment_prep_pause --check --activity pool_generation" in body
    assert "skipped_pause_gate" in body
    assert body.index("prep_restart_blocked_by_authority_gate") < body.index(
        "systemctl --user reset-failed"
    )


def test_candidate_review_manifest_write_requires_runtime_load_authority() -> None:
    body = _read(REPO_ROOT / "scripts" / "review_segment_candidate_set.py")

    assert 'assert_segment_prep_allowed("runtime_pool_load")' in body
    assert "write_manifest_blocked" in body
    assert body.index('assert_segment_prep_allowed("runtime_pool_load")') < body.index(
        "write_selected_release_manifest(today"
    )
