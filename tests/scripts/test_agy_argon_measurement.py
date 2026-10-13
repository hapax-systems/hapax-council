"""Measurement is explicit evidence, never production-route admission."""

import importlib.util
import json
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TIERS = tuple(f"gemini-4-argon-{tier}" for tier in ("low", "medium", "high"))
PRODUCTION = "gemini-4-argon-low"
MEASUREMENT_TIERS = TIERS[1:]
REPLY = "```yaml\nverdict: accept\nfindings: []\nchecklist: {}\n```\n"


def load(name):
    loader = SourceFileLoader("argon_test_" + name.replace("-", "_"), str(ROOT / "scripts" / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "operator"))
    native = tmp_path / "agy"
    calls = tmp_path / "calls.jsonl"
    native.write_text(
        f"#!{sys.executable}\nimport json, sys\n"
        f"with open({str(calls)!r}, 'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
        "model = sys.argv[sys.argv.index('--model') + 1]\n"
        f"reply = {REPLY!r}\n"
        "print(json.dumps({'status': 'SUCCESS', 'response': reply, 'model': model}) "
        "if '--output-format' in sys.argv else reply)\n"
    )
    native.chmod(0o755)
    reviewer = tmp_path / "hapax-agy-reviewer"
    command = (sys.executable, ROOT / "scripts/hapax-agy-reviewer", "--agy-bin", native)
    reviewer.write_text("#!/bin/sh\nexec " + shlex.join(map(str, command)) + ' "$@"\n')
    reviewer.chmod(0o755)
    admission = load("hapax-agy-quota-admission")
    monkeypatch.setattr(admission, "DEFAULT_REVIEWER_COMMAND", reviewer)
    return admission, reviewer, native, calls


def invoke(reviewer, *args):
    return subprocess.run(
        [str(reviewer), *args],
        input="review_id: synthetic-smoke\n",
        text=True,
        capture_output=True,
    )


def test_argon_variants_separate_production_from_measurement():
    route = next(
        r
        for r in json.loads((ROOT / "config/platform-capability-registry.json").read_text())[
            "routes"
        ]
        if r["route_id"] == "agy.review.direct"
    )
    from shared.quota_spend_ledger import AGY_ADMISSION_MODEL

    assert AGY_ADMISSION_MODEL == PRODUCTION
    assert route["execution_descriptor"]["model_id"] == "gemini-4-argon"
    assert route["execution_descriptor"]["effort"] == "low"
    assert route["route_state"] == "blocked"
    assert route["blocked_reasons"] == [
        "agy_review_seat_receipt_admission_required",
        "route_specific_quota_receipt_absent",
    ]
    variants = {v["variant_id"]: v for v in route["descriptor_variants"]}
    for model in TIERS:
        v = variants[f"agy@{model}"]
        assert v["blocked_reasons"] == ([] if model == PRODUCTION else ["measurement_only"])
        assert v["scores_inherited_from"] is None and v["score_delta"] == {}
        assert v["knobs_override"] == {
            "model_id": "gemini-4-argon",
            "effort": model.rsplit("-", 1)[1],
        }


@pytest.mark.parametrize("model", ["gemini-unlisted-high", PRODUCTION, "claude-opus-5-5-high"])
def test_undeclared_measurement_refuses_before_native(harness, tmp_path, model):
    admission, reviewer, _, calls = harness
    result = invoke(reviewer, "--measurement-model", model)
    assert result.returncode == 64
    assert admission.main(["--measurement-model", model, "--receipt-dir", str(tmp_path)]) == 64
    assert not calls.exists()
    assert not list(tmp_path.glob("*.yaml"))


@pytest.mark.parametrize("model,served", [(m, m) for m in MEASUREMENT_TIERS] + [(TIERS[1], None)])
def test_measurement_identity_and_receipt_never_admit_production(
    harness, tmp_path, capsys, model, served
):
    admission, _, native, calls = harness
    if served is None:
        native.write_text(native.read_text().replace(", 'model': model", ""))
    assert (
        admission.main(["--measurement-model", model, "--receipt-dir", str(tmp_path), "--json"])
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    receipt_path = Path(summary["path"])
    receipt = yaml.safe_load(receipt_path.read_text())
    assert receipt["model"] == summary["model"] == model
    assert receipt["served_model"] == (served or "unobserved")
    assert receipt["measurement_only"] is True
    assert receipt["positive_admission"] is False
    invocations = [json.loads(v) for v in calls.read_text().splitlines()]
    assert len(invocations) == 1
    assert invocations[0][invocations[0].index("--model") + 1] == model
    writer = load("hapax-quota-telemetry-writer")
    # Promotion cannot make a measurement receipt admit production.
    for receipt_model in TIERS:
        receipt["model"] = receipt_model
        receipt_path.write_text(yaml.safe_dump(receipt))
        scan = writer.active_agy_admission_receipts(tmp_path, now=datetime.now(UTC))
        assert scan.admissions == []
        assert len(scan.ignored_evidence_refs) == 1


@pytest.mark.parametrize("fault", ["served_mismatch", "production_output", "failed_status"])
def test_measurement_mismatch_refuses_receipt(harness, tmp_path, fault):
    admission, reviewer, native, _ = harness
    text = native.read_text()
    if fault == "served_mismatch":
        text = text.replace("'model': model", f"'model': {TIERS[2]!r}")
    elif fault == "production_output":
        text = f"#!{sys.executable}\nprint({REPLY!r})\n"
    else:
        text = text.replace("'SUCCESS'", "'ERROR'")
    native.write_text(text)
    assert invoke(reviewer, "--measurement-model", TIERS[1]).returncode == 65
    assert admission.main(["--measurement-model", TIERS[1], "--receipt-dir", str(tmp_path)]) != 0
    assert not list(tmp_path.glob("*.yaml"))


@pytest.mark.parametrize(
    "field,value", [("measurement_only", False), ("model", PRODUCTION), ("served_model", TIERS[2])]
)
def test_admission_rechecks_reviewer_measurement_identity(
    harness, tmp_path, monkeypatch, field, value
):
    admission, _, _, _ = harness
    payload = {
        "measurement_only": True,
        "model": TIERS[1],
        "served_model": TIERS[1],
        "response": REPLY,
    }
    payload[field] = value
    monkeypatch.setattr(
        admission.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=json.dumps(payload), stderr=""),
    )
    assert admission.main(["--measurement-model", TIERS[1], "--receipt-dir", str(tmp_path)]) == 2
    assert not list(tmp_path.glob("*.yaml"))


def test_conflicting_production_and_measurement_argument_refuses(harness):
    _, reviewer, _, calls = harness
    assert invoke(reviewer, "--model", PRODUCTION, "--measurement-model", TIERS[1]).returncode == 64
    assert not calls.exists()
