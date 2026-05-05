from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from shared.github_publication_log import ANTI_OVERCLAIM_REASON, build_github_publication_event

REPO_ROOT = Path(__file__).parent.parent.parent
RUNNER_PATH = REPO_ROOT / "scripts" / "braided_value_snapshot_runner.py"
NOW = datetime(2026, 4, 30, 0, 0, tzinfo=UTC)


def load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("braided_value_snapshot_runner", RUNNER_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_task(
    root: Path,
    directory: str,
    task_id: str,
    *,
    frontmatter: dict[str, Any] | None = None,
    body: str = "",
) -> Path:
    note_dir = root / directory
    note_dir.mkdir(parents=True, exist_ok=True)
    fm = {
        "type": "cc-task",
        "task_id": task_id,
        "title": task_id.replace("-", " ").title(),
        "status": "offered",
        "priority": "p1",
        "wsjf": 5.0,
    }
    if frontmatter:
        fm.update(frontmatter)
    path = note_dir / f"{task_id}.md"
    path.write_text(f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n\n{body}\n", encoding="utf-8")
    return path


def write_hygiene(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"generated_at": "2026-04-30T00:00:00Z"}), encoding="utf-8")


def row_by_task(snapshot: dict[str, Any], task_id: str) -> dict[str, Any]:
    for row in snapshot["rows"]:
        if row.get("task_id") == task_id:
            return row
    raise AssertionError(f"missing row for {task_id}")


def test_default_witness_specs_cover_first_slice_families() -> None:
    runner = load_runner()

    ids = {spec.witness_id for spec in runner.default_witness_specs()}

    assert {
        "voice_output_witness",
        "narration_triads",
        "broadcast_audio_safety",
        "audio_router_state",
        "audio_ducker_state",
        "audio_safety_state",
        "affordance_dispatch_trace",
        "affordance_recruitment_log",
        "daimonion_recruitment_log",
        "compositor_recent_recruitment",
        "demonet_egress_audit",
        "imagination_current",
        "imagination_health",
        "imagination_uniforms",
        "imagination_pool_metrics",
        "reverie_predictions",
        "compositor_health",
        "compositor_degraded",
        "dmn_status",
        "dmn_impingements",
        "stimmung_state",
        "sensors_snapshot",
        "usb_topology_status",
        "publication_log",
        "logos_health",
        "logos_openapi",
        "research_registry",
    }.issubset(ids)


def test_default_systemd_specs_use_live_logos_api_unit() -> None:
    runner = load_runner()

    units = {spec.unit for spec in runner.default_systemd_specs()}

    assert "logos-api.service" in units
    assert "hapax-logos-api.service" not in units


def test_logos_openapi_witness_accepts_fastapi_validation_error_schema(tmp_path: Path) -> None:
    runner = load_runner()
    path = tmp_path / "openapi.json"
    path.write_text(
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {"title": "logos-api", "version": "0.2.0"},
                "paths": {
                    "/api/ping": {
                        "get": {
                            "responses": {
                                "200": {"description": "Successful Response"},
                                "422": {"description": "Validation Error"},
                            }
                        }
                    }
                },
                "components": {
                    "schemas": {
                        "HTTPValidationError": {
                            "title": "HTTPValidationError",
                            "type": "object",
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    read = runner.probe_witness(
        runner.WitnessSpec(
            "logos_openapi",
            "Logos OpenAPI witness",
            path,
            "executive_function_os",
        ),
        NOW,
    )

    assert read.status == "ok"
    assert read.reasons == ("logos_openapi_present",)


def test_logos_health_and_openapi_recover_executive_function_anchor(tmp_path: Path) -> None:
    runner = load_runner()
    vault = tmp_path / "tasks"
    hygiene = tmp_path / "hygiene.json"
    health_path = tmp_path / "health.json"
    openapi_path = tmp_path / "openapi.json"
    write_hygiene(hygiene)
    health_path.write_text(
        json.dumps(
            {
                "component": "logos-api",
                "status": "ok",
                "ready": True,
                "openapi": {"path": str(openapi_path), "sha256": "abc123"},
            }
        ),
        encoding="utf-8",
    )
    openapi_path.write_text(
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {"title": "logos-api", "version": "0.2.0"},
                "paths": {"/api/ping": {"get": {"responses": {"200": {"description": "OK"}}}}},
            }
        ),
        encoding="utf-8",
    )

    snapshot = runner.build_snapshot(
        task_root=vault,
        hygiene_path=hygiene,
        now=NOW,
        witness_specs=[
            runner.WitnessSpec(
                "logos_health",
                "Logos health witness",
                health_path,
                "executive_function_os",
            ),
            runner.WitnessSpec(
                "logos_openapi",
                "Logos OpenAPI witness",
                openapi_path,
                "executive_function_os",
            ),
        ],
        include_systemd=False,
    )
    row = row_by_task(snapshot, "executive-function-os")

    assert row["braid_recomputed"] == 10.0
    assert row["claimability_reason"] == "live_witnessed_presence_only"
    assert row["blockers"] == []


def test_malformed_frontmatter_and_missing_hygiene_are_visible(tmp_path: Path) -> None:
    runner = load_runner()
    vault = tmp_path / "tasks"
    write_task(vault, "active", "well-formed")
    active = vault / "active"
    (active / "malformed.md").write_text("---\ntype: [\n---\n# broken\n", encoding="utf-8")

    snapshot = runner.build_snapshot(
        task_root=vault,
        hygiene_path=tmp_path / "missing-hygiene.json",
        now=NOW,
        witness_specs=[],
        include_systemd=False,
    )
    dashboard = runner.render_dashboard(snapshot)

    assert snapshot["hygiene"]["status"] == "missing"
    assert row_by_task(snapshot, "malformed")["review_reason"] == ["malformed_frontmatter"]
    assert "hygiene_state_missing" in row_by_task(snapshot, "well-formed")["review_reason"]
    assert "Hygiene state: `missing`" in dashboard


def test_score_delta_and_blocked_high_braid_trigger_review(tmp_path: Path) -> None:
    runner = load_runner()
    vault = tmp_path / "tasks"
    hygiene = tmp_path / "hygiene.json"
    write_hygiene(hygiene)
    write_task(
        vault,
        "active",
        "blocked-value",
        frontmatter={
            "status": "blocked",
            "blocked_reason": "dependency witness absent",
            "wsjf": 12.0,
            "braid_engagement": 10,
            "braid_monetary": 10,
            "braid_research": 10,
            "braid_tree_effect": 10,
            "braid_evidence_confidence": 10,
            "braid_risk_penalty": 0,
            "braid_score": 8.5,
            "updated_at": "2026-04-01T00:00:00Z",
        },
    )

    snapshot = runner.build_snapshot(
        task_root=vault,
        hygiene_path=hygiene,
        now=NOW,
        witness_specs=[],
        include_systemd=False,
    )
    row = row_by_task(snapshot, "blocked-value")

    assert row["braid_recomputed"] == 10.0
    assert "score_delta_gt_1" in row["review_reason"]
    assert "blocked_high_braid" in row["review_reason"]
    assert "possible_stale_blocker" in row["review_reason"]
    assert row["gate_posture"]["deny_wins"] is True


def test_stale_live_witness_downgrades_public_claim(tmp_path: Path) -> None:
    runner = load_runner()
    vault = tmp_path / "tasks"
    hygiene = tmp_path / "hygiene.json"
    witness_path = tmp_path / "audio-safe.json"
    write_hygiene(hygiene)
    witness_path.write_text(json.dumps({"safe_for_broadcast": True}), encoding="utf-8")
    old = (NOW - timedelta(days=2)).timestamp()
    os.utime(witness_path, (old, old))
    write_task(
        vault,
        "active",
        "public-claim",
        frontmatter={
            "public_claim": True,
            "wsjf": 9.0,
            "braid_engagement": 9,
            "braid_monetary": 8,
            "braid_research": 8,
            "braid_tree_effect": 9,
            "braid_evidence_confidence": 8,
            "braid_score": 8.4,
        },
    )

    snapshot = runner.build_snapshot(
        task_root=vault,
        hygiene_path=hygiene,
        now=NOW,
        witness_specs=[
            runner.WitnessSpec(
                "broadcast_audio_safety",
                "Broadcast audio safety",
                witness_path,
                "livestream_studio_stack",
                public_when_ok=True,
            )
        ],
        include_systemd=False,
    )

    assert snapshot["witnesses"][0]["status"] == "stale"
    row = row_by_task(snapshot, "public-claim")
    assert "visible_claim_without_live_witness" in row["review_reason"]
    assert "live_witness_downgrade" in row["review_reason"]
    assert row["mode_ceiling"] == "private"
    assert row["max_public_claim"] == "none"


def test_negative_claim_fixtures_are_default_deny(tmp_path: Path) -> None:
    runner = load_runner()
    vault = tmp_path / "tasks"
    hygiene = tmp_path / "hygiene.json"
    write_hygiene(hygiene)
    write_task(vault, "active", "visible-unwitnessed", body="public_claim: true\nno evidence")
    write_task(
        vault, "active", "selected-recruitment", body="selected: true\nrecruitment trace only"
    )
    write_task(
        vault,
        "active",
        "revenue-rights",
        frontmatter={"braid_monetary": 10},
        body="revenue_claim: true\nrights_state: blocked",
    )
    write_task(
        vault,
        "active",
        "private-audio",
        body="private audio route with public_broadcast_claim: true",
    )
    write_task(
        vault, "active", "tauri-overclaim", body="Tauri logos decommission public_claim: true"
    )
    write_task(
        vault,
        "active",
        "usb-overclaim",
        body="USB bandwidth proves semantic reliability and truth",
    )
    write_task(
        vault,
        "active",
        "telemetry-missing",
        body="audience_claim: true\nrevenue_claim: true\ntelemetry_state: missing",
    )

    snapshot = runner.build_snapshot(
        task_root=vault,
        hygiene_path=hygiene,
        now=NOW,
        witness_specs=[],
        include_systemd=False,
    )

    expected = {
        "visible-unwitnessed": "visible_claim_without_live_witness",
        "selected-recruitment": "selected_not_successful_recruitment",
        "revenue-rights": "rights_blocked_money_claim",
        "private-audio": "private_audio_route_public_claim",
        "tauri-overclaim": "tauri_decommission_overclaim",
        "usb-overclaim": "usb_bandwidth_reliability_overclaim",
        "telemetry-missing": "missing_telemetry_for_audience_or_revenue_claim",
    }
    for task_id, reason in expected.items():
        row = row_by_task(snapshot, task_id)
        assert reason in row["review_reason"]
        assert row["max_public_claim"] == "none"
        assert row["gate_posture"]["deny_wins"] is True


def test_witness_negative_markers_downgrade_implementation_anchors(tmp_path: Path) -> None:
    runner = load_runner()
    vault = tmp_path / "tasks"
    hygiene = tmp_path / "hygiene.json"
    recruitment = tmp_path / "recruitment.jsonl"
    audio = tmp_path / "audio.json"
    write_hygiene(hygiene)
    recruitment.write_text(json.dumps({"selected": True}) + "\n", encoding="utf-8")
    audio.write_text(
        json.dumps({"safe_for_broadcast": True, "route": "private", "broadcast": True}),
        encoding="utf-8",
    )

    snapshot = runner.build_snapshot(
        task_root=vault,
        hygiene_path=hygiene,
        now=NOW,
        witness_specs=[
            runner.WitnessSpec(
                "affordance_recruitment_log",
                "Affordance recruitment",
                recruitment,
                "semantic_affordance_economy",
            ),
            runner.WitnessSpec(
                "broadcast_audio_safety",
                "Broadcast audio safety",
                audio,
                "livestream_studio_stack",
                public_when_ok=True,
            ),
        ],
        include_systemd=False,
    )

    statuses = {witness["witness_id"]: witness["status"] for witness in snapshot["witnesses"]}
    assert statuses["affordance_recruitment_log"] == "selected_not_witnessed"
    assert statuses["broadcast_audio_safety"] == "unsafe"
    semantic_row = row_by_task(snapshot, "semantic-affordance-economy")
    livestream_row = row_by_task(snapshot, "livestream-studio-stack")
    assert semantic_row["mode_ceiling"] == "private"
    assert livestream_row["mode_ceiling"] == "private"


def test_dashboard_sorts_offered_tasks_by_wsjf_before_braid(tmp_path: Path) -> None:
    runner = load_runner()
    vault = tmp_path / "tasks"
    hygiene = tmp_path / "hygiene.json"
    write_hygiene(hygiene)
    write_task(
        vault,
        "active",
        "higher-wsjf-lower-braid",
        frontmatter={"wsjf": 11.0, "braid_score": 1.0},
    )
    write_task(
        vault,
        "active",
        "lower-wsjf-higher-braid",
        frontmatter={"wsjf": 4.0, "braid_score": 10.0},
    )

    snapshot = runner.build_snapshot(
        task_root=vault,
        hygiene_path=hygiene,
        now=NOW,
        witness_specs=[],
        include_systemd=False,
    )
    dashboard = runner.render_dashboard(snapshot)

    assert "WSJF remains the dispatch sort key" in dashboard
    assert dashboard.index("higher-wsjf-lower-braid") < dashboard.index("lower-wsjf-higher-braid")


def test_write_outputs_append_ledger_without_mutating_tasks(tmp_path: Path) -> None:
    runner = load_runner()
    vault = tmp_path / "tasks"
    hygiene = tmp_path / "hygiene.json"
    dashboard = tmp_path / "dashboard.md"
    ledger = tmp_path / "snapshots.jsonl"
    write_hygiene(hygiene)
    note_path = write_task(vault, "active", "stable-task")
    before = note_path.read_text(encoding="utf-8")

    snapshot = runner.build_snapshot(
        task_root=vault,
        hygiene_path=hygiene,
        now=NOW,
        witness_specs=[],
        include_systemd=False,
    )
    runner.write_outputs(snapshot, dashboard_path=dashboard, ledger_path=ledger)

    assert note_path.read_text(encoding="utf-8") == before
    assert "Task state mutation: `false`" in dashboard.read_text(encoding="utf-8")
    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(snapshot["rows"])
    first = json.loads(lines[0])
    assert first["policy"]["dispatch_sort_key"] == "wsjf"
    assert first["policy"]["trend_can_upgrade_claim_confidence"] is False


def test_github_publication_log_witness_feeds_publication_tree_effect(
    tmp_path: Path,
) -> None:
    runner = load_runner()
    vault = tmp_path / "tasks"
    hygiene = tmp_path / "hygiene.json"
    log_path = tmp_path / "publication-log.jsonl"
    write_hygiene(hygiene)
    event = build_github_publication_event(
        repo="ryanklee/hapax-council",
        surface="readme",
        generated_at="2026-05-01T00:50:00Z",
        occurred_at="2026-04-30T03:46:00Z",
        source_refs=("docs/repo-pres/github-public-surface-live-state-reconcile.json",),
        evidence_refs=("gh:contents/ryanklee/hapax-council/README.md",),
        publication_state="public",
        publication_mode="public_archive",
        live_url="https://github.com/ryanklee/hapax-council/blob/main/README.md",
        commit_sha="a" * 40,
        content_sha="b" * 40,
        ref="main",
    )
    log_path.write_text(event.to_json_line(), encoding="utf-8")

    snapshot = runner.build_snapshot(
        task_root=vault,
        hygiene_path=hygiene,
        now=NOW,
        witness_specs=[
            runner.WitnessSpec(
                "publication_log",
                "Publication log",
                log_path,
                "publication_tree_effect",
            )
        ],
        include_systemd=False,
    )

    witness = snapshot["witnesses"][0]
    assert witness["status"] == "ok"
    assert witness["reasons"] == ["github_publication_witness", ANTI_OVERCLAIM_REASON]
    row = row_by_task(snapshot, "publication-tree-effect")
    assert row["mode_ceiling"] == "dry_run"
    assert row["max_public_claim"] == "internal_evidence_summary_only"
    assert row["claimability_reason"] == "live_witnessed_presence_only"
    assert row["gate_posture"]["trend_can_upgrade_claim_confidence"] is False


def test_missing_publication_log_downgrades_publication_tree_effect(tmp_path: Path) -> None:
    runner = load_runner()
    vault = tmp_path / "tasks"
    hygiene = tmp_path / "hygiene.json"
    write_hygiene(hygiene)

    snapshot = runner.build_snapshot(
        task_root=vault,
        hygiene_path=hygiene,
        now=NOW,
        witness_specs=[
            runner.WitnessSpec(
                "publication_log",
                "Publication log",
                tmp_path / "missing-publication-log.jsonl",
                "publication_tree_effect",
            )
        ],
        include_systemd=False,
    )

    witness = snapshot["witnesses"][0]
    assert witness["status"] == "missing"
    assert witness["reasons"] == ["missing_live_witness"]
    row = row_by_task(snapshot, "publication-tree-effect")
    assert row["blockers"] == ["publication_log"]
    assert row["review_reason"] == ["live_witness_downgrade"]
    assert row["mode_ceiling"] == "private"
    assert row["max_public_claim"] == "none"
