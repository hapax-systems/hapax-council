"""Registry binding and local-only producer/reviewer effect fixtures."""

import importlib.util
import json
import runpy
import shlex
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "config/platform-capability-registry.json"
CONSUMERS = [
    ("shared/quota_spend_ledger.py", "AGY_ADMISSION_MODEL"),
    ("scripts/hapax-agy-reviewer", "PINNED_REVIEW_MODEL"),
    ("scripts/hapax-agy-quota-admission", "MODEL"),
    ("scripts/hapax-quota-telemetry-writer", "AGY_ADMISSION_MODEL"),
]


def test_former_engine_receipt_cannot_admit_argon():
    from shared.quota_spend_ledger import _is_agy_admission_evidence_ref

    prefix = "relay-receipt:agy-quota-admission-fixture.yaml:witness:argon-fixture:supported_tool:hapax-agy-reviewer:"
    suffix = ":observed_at:2026-10-13T21:00:00Z:fresh_until:2026-10-13T21:15:00Z"
    assert _is_agy_admission_evidence_ref(prefix + "model:gemini-4-argon-low" + suffix)
    assert not _is_agy_admission_evidence_ref(prefix + "model:gemini-3.1-pro-high" + suffix)
    assert not _is_agy_admission_evidence_ref(prefix + "model:gemini-3.1-pro-preview" + suffix)


def _registry():
    payload = json.loads(REGISTRY.read_text())
    route = next(r for r in payload["routes"] if r["route_id"] == "agy.review.direct")
    base = route["execution_descriptor"]["model_id"]
    variant = next(
        v
        for v in route["descriptor_variants"]
        if v["knobs_override"].get("model_id", base) == base
        and v["knobs_override"].get("effort") == route["execution_descriptor"]["effort"]
    )
    return payload, route, variant


def _load_ledger(monkeypatch, text):
    read = Path.read_text
    monkeypatch.setattr(
        Path, "read_text", lambda p, *a, **k: text if p == REGISTRY else read(p, *a, **k)
    )
    name = "shared.quota_spend_ledger"
    spec = importlib.util.spec_from_file_location(name, ROOT / "shared/quota_spend_ledger.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("consumer,field", CONSUMERS)
@pytest.mark.parametrize("changed", [False, True])
def test_all_four_consumers_follow_registry_binding(monkeypatch, consumer, field, changed):
    payload, route, variant = _registry()
    if changed:
        variant["variant_id"] = "agy@gemini-synthetic-binding-high"
    expected = variant["variant_id"].removeprefix("agy@")
    ledger = _load_ledger(monkeypatch, json.dumps(payload))
    namespace = vars(ledger) if consumer.startswith("shared/") else runpy.run_path(ROOT / consumer)
    assert namespace[field] == expected
    aliases = (
        namespace["PINNED_REVIEW_MODELS"]
        if consumer.endswith("reviewer")
        else namespace.get("AGY_ADMISSION_MODELS")
    )
    if aliases is not None:
        assert aliases == {expected, route["execution_descriptor"]["model_id"]}


@pytest.mark.parametrize("fault", ["missing", "ambiguous", "blocked", "foreign", "malformed"])
def test_invalid_registry_binding_has_no_default(monkeypatch, fault):
    payload, route, variant = _registry()
    if fault == "missing":
        route["descriptor_variants"].remove(variant)
    elif fault == "ambiguous":
        route["descriptor_variants"].append(dict(variant))
    elif fault == "blocked":
        variant["blocked_reasons"] = ["synthetic-hold"]
    elif fault == "foreign":
        variant["variant_id"] = "agy@claude-synthetic-high"
    with pytest.raises(ValueError, match="agy review registry binding"):
        _load_ledger(monkeypatch, "{" if fault == "malformed" else json.dumps(payload))


@pytest.mark.parametrize("native_rc", [0, 1])
def test_producer_reviewer_model_effect_without_fallback(tmp_path, monkeypatch, capsys, native_rc):
    """Exercise both real scripts with a fake native binary and isolated receipt directory."""
    payload, _, variant = _registry()
    model = variant["variant_id"].removeprefix("agy@")
    calls = tmp_path / "calls.jsonl"
    native = tmp_path / "agy"
    native.write_text(
        f"#!{sys.executable}\nimport json, sys\n"
        f"with open({str(calls)!r}, 'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
        "print('```yaml\\nverdict: accept\\nfindings: []\\nchecklist: {}\\n```')\n"
        f"if {native_rc}: print('model {model} is not recognized as a known model', file=sys.stderr)\n"
        f"sys.exit({native_rc})\n"
    )
    native.chmod(0o755)
    reviewer = tmp_path / "hapax-agy-reviewer"
    reviewer.write_text(
        "#!/bin/sh\nexec "
        + " ".join(
            shlex.quote(str(p))
            for p in [sys.executable, ROOT / "scripts/hapax-agy-reviewer", "--agy-bin", native]
        )
        + ' "$@"\n'
    )
    reviewer.chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path / "empty-operator-home"))
    loader = SourceFileLoader(
        "agy_admission_effect", str(ROOT / "scripts/hapax-agy-quota-admission")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    monkeypatch.setattr(module, "DEFAULT_REVIEWER_COMMAND", reviewer)
    receipts = tmp_path / "receipts"
    rc = module.main(["--receipt-dir", str(receipts), "--now", "2026-07-07T13:00:00Z", "--json"])
    captured = capsys.readouterr()
    invocations = [json.loads(line) for line in calls.read_text().splitlines()]
    assert len(invocations) == 1
    assert invocations[0][invocations[0].index("--model") + 1] == model
    if native_rc:
        assert rc == 2
        assert "returncode=1" in captured.err
        assert f"model {model} is not recognized as a known model" in captured.err
        assert not list(receipts.glob("*.yaml"))
    else:
        assert rc == 0, captured.err
        assert json.loads(captured.out)["model"] == model
        assert len(list(receipts.glob("*.yaml"))) == 1
