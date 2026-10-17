"""Registry binding and local-only producer/reviewer effect fixtures."""

import importlib.util
import json
import os
import runpy
import shlex
import shutil
import subprocess
import sys
import textwrap
from datetime import UTC, datetime
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "config/platform-capability-registry.json"
CONSUMERS = [
    "shared/quota_spend_ledger.py",
    "scripts/hapax-agy-reviewer",
    "scripts/hapax-agy-quota-admission",
    "scripts/hapax-quota-telemetry-writer",
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

    def registry_text(path, *args, **kwargs):
        if path != REGISTRY:
            return read(path, *args, **kwargs)
        if text is None:
            raise FileNotFoundError("fixture registry missing")
        return text

    monkeypatch.setattr(Path, "read_text", registry_text)
    name = "shared.quota_spend_ledger"
    spec = importlib.util.spec_from_file_location(name, ROOT / "shared/quota_spend_ledger.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("consumer", CONSUMERS)
@pytest.mark.parametrize("fault", ["missing", "ambiguous"])
def test_consumers_import_without_binding_and_refuse_at_use(
    monkeypatch, tmp_path, capsys, consumer, fault
):
    payload, route, variant = _registry()
    route["descriptor_variants"].append(dict(variant))
    ledger = _load_ledger(monkeypatch, None if fault == "missing" else json.dumps(payload))
    namespace = vars(ledger) if consumer.startswith("shared/") else runpy.run_path(ROOT / consumer)

    def forbidden(*args, **kwargs):
        pytest.fail("invalid binding reached a subprocess")

    monkeypatch.setattr(subprocess, "run", forbidden)
    if consumer.endswith("quota-admission"):
        assert namespace["main"](["--receipt-dir", str(tmp_path)]) == 2
        assert "repair the governed" in capsys.readouterr().err
        assert not list(tmp_path.iterdir())
        return
    with pytest.raises(ValueError, match="repair the governed.*no model fallback"):
        if consumer.startswith("shared/"):
            ledger._is_agy_admission_evidence_ref(
                "relay-receipt:agy-quota-admission.yaml:witness:fixture-smoke:"
                "supported_tool:hapax-agy-reviewer:model:gemini-3.1-pro-high:"
                "observed_at:2026-07-07T13:00:00Z:fresh_until:2026-07-07T13:15:00Z"
            )
        elif consumer.endswith("reviewer"):
            namespace["main"](["--agy-bin", "/nonexistent/agy"])
        else:
            namespace["active_agy_admission_receipts"](tmp_path, now=datetime.now(UTC))


@pytest.mark.parametrize("consumer", CONSUMERS)
@pytest.mark.parametrize("changed", [False, True])
def test_all_four_consumers_follow_registry_binding(monkeypatch, consumer, changed):
    payload, route, variant = _registry()
    if changed:
        variant["variant_id"] = "agy@gemini-synthetic-binding-high"
    expected = variant["variant_id"].removeprefix("agy@")
    ledger = _load_ledger(monkeypatch, json.dumps(payload))
    namespace = vars(ledger) if consumer.startswith("shared/") else runpy.run_path(ROOT / consumer)
    assert namespace["agy_review_model_binding"]() == (
        expected,
        route["execution_descriptor"]["model_id"],
    )


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "ambiguous",
        "blocked",
        "foreign",
        "malformed",
        "route_missing",
        "route_duplicate",
        "prefix",
        "base_invalid",
        "base_missing",
        "variants_missing",
        "knobs_missing",
        "blocked_reasons_missing",
        "variant_id_missing",
        "read_failure",
    ],
)
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
    elif fault == "route_missing":
        payload["routes"].remove(route)
    elif fault == "route_duplicate":
        payload["routes"].append(route)
    elif fault == "prefix":
        variant["variant_id"] = "other@gemini-synthetic-high"
    elif fault == "base_invalid":
        base = route["execution_descriptor"]["model_id"]
        route["execution_descriptor"]["model_id"] = "claude-invalid"
        for item in route["descriptor_variants"]:
            if item["knobs_override"].get("model_id", base) == base:
                item["knobs_override"]["model_id"] = "claude-invalid"
    elif fault == "base_missing":
        del route["execution_descriptor"]["model_id"]
    elif fault == "variants_missing":
        del route["descriptor_variants"]
    elif fault in {"knobs_missing", "blocked_reasons_missing", "variant_id_missing"}:
        del variant[
            {
                "knobs_missing": "knobs_override",
                "blocked_reasons_missing": "blocked_reasons",
                "variant_id_missing": "variant_id",
            }[fault]
        ]
    elif fault == "read_failure":
        read = Path.read_text

        def denied(path, *args, **kwargs):
            if path == REGISTRY:
                raise PermissionError("fixture registry unreadable")
            return read(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", denied)
        # The normal import reads the actual path; do not replace this failure with fixture text.
        with pytest.raises(ValueError, match="repair the governed.*no model fallback"):
            runpy.run_path(ROOT / "shared/quota_spend_ledger.py")["agy_review_model_binding"]()
        return
    with pytest.raises(ValueError, match="repair the governed.*no model fallback"):
        _load_ledger(
            monkeypatch, "{" if fault == "malformed" else json.dumps(payload)
        ).agy_review_model_binding()


@pytest.mark.parametrize(
    "blocked_reasons",
    [
        pytest.param(None, id="null"),
        pytest.param(False, id="false"),
        pytest.param("", id="empty-string"),
        pytest.param({}, id="empty-object"),
        pytest.param(0, id="zero"),
    ],
)
def test_malformed_blocked_reasons_has_no_default(monkeypatch, blocked_reasons):
    payload, _, variant = _registry()
    variant["blocked_reasons"] = blocked_reasons
    with pytest.raises(ValueError, match="repair the governed.*no model fallback"):
        _load_ledger(monkeypatch, json.dumps(payload)).agy_review_model_binding()


def test_empty_blocked_reasons_allows_binding(monkeypatch):
    payload, route, variant = _registry()
    variant["blocked_reasons"] = []
    ledger = _load_ledger(monkeypatch, json.dumps(payload))
    assert ledger.agy_review_model_binding() == (
        variant["variant_id"].removeprefix("agy@"),
        route["execution_descriptor"]["model_id"],
    )


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


@pytest.mark.parametrize("changed_base", [False, True])
@pytest.mark.parametrize("native_rc", [0, 1])
def test_changed_binding_crosses_process_and_receipt_consumers(tmp_path, changed_base, native_rc):
    """Fresh normal imports, real consumers, fake native transport; no provider qualification."""
    payload, route, variant = _registry()
    previous_model = variant["variant_id"].removeprefix("agy@")
    previous_alias = route["execution_descriptor"]["model_id"]
    model = "gemini-fixture-selected-high"
    alias = "gemini-fixture-base-preview" if changed_base else previous_alias
    variant["variant_id"] = "agy@" + model
    if changed_base:
        route["execution_descriptor"]["model_id"] = alias
        variant["knobs_override"]["model_id"] = alias

    tree = tmp_path / "repo"
    tree.mkdir()
    shutil.copytree(ROOT / "shared", tree / "shared", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "config", tree / "config")
    (tree / "scripts").mkdir()
    for consumer in CONSUMERS:
        if consumer.startswith("scripts/"):
            shutil.copy2(ROOT / consumer, tree / consumer)
    (tree / "config/platform-capability-registry.json").write_text(json.dumps(payload))
    calls = tmp_path / "native-calls.jsonl"
    native = tmp_path / "agy"
    native.write_text(
        f"#!{sys.executable}\nimport json, sys\n"
        f"with open({str(calls)!r}, 'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
        "print('```yaml\\nverdict: accept\\nfindings: []\\nchecklist: {}\\n```')\n"
        f"if {native_rc}: print('model {model} is not recognized as a known model', file=sys.stderr)\n"
        f"sys.exit({native_rc})\n"
    )
    native.chmod(0o755)
    wrapper = tmp_path / "hapax-agy-reviewer"
    wrapper.write_text(
        "#!/bin/sh\nexec "
        + " ".join(
            shlex.quote(str(p))
            for p in [
                sys.executable,
                tree / "scripts/hapax-agy-reviewer",
                "--agy-bin",
                native,
            ]
        )
        + ' "$@"\n'
    )
    wrapper.chmod(0o755)
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path / "empty-home"),
        "PYTHONPATH": str(tree),
        "OTEL_SDK_DISABLED": "true",
        "LANG": "C.UTF-8",
    }
    driver = textwrap.dedent("""
        import contextlib, io, json, runpy, sys
        from datetime import UTC, datetime
        from pathlib import Path
        import shared.quota_spend_ledger as ledger

        root, wrapper, output, models_json = sys.argv[1:]
        root, output = Path(root), Path(output)
        producer = runpy.run_path(root / 'scripts/hapax-agy-quota-admission')
        # Only the transport is substituted; main and both source consumers are unchanged.
        producer['main'].__globals__['DEFAULT_REVIEWER_COMMAND'] = Path(wrapper)
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = producer['main'](['--receipt-dir', str(output), '--now',
                                  '2026-07-07T13:00:00Z', '--json'])
        result = {'rc': rc, 'stdout': stdout.getvalue(), 'stderr': stderr.getvalue(),
                  'receipts': len(list(output.glob('*.yaml'))), 'consumers': {}}
        if rc == 0:
            summary = json.loads(stdout.getvalue())
            receipt = Path(summary['path']).read_text()
            result['receipt_model'] = next(line[7:] for line in receipt.splitlines()
                                           if line.startswith('model: '))
            writer = runpy.run_path(root / 'scripts/hapax-quota-telemetry-writer')
            now = datetime(2026, 7, 7, 13, 0, tzinfo=UTC)
            for index, model in enumerate(json.loads(models_json)):
                folder = output / str(index)
                folder.mkdir()
                (folder / 'agy-quota-admission.yaml').write_text(receipt.replace(
                    'model: ' + result['receipt_model'] + '\\n', 'model: ' + model + '\\n'))
                scan = writer['active_agy_admission_receipts'](folder, now=now)
                # Exercise ledger rejection even when telemetry correctly dropped the receipt.
                ref = ('relay-receipt:agy-quota-admission.yaml:witness:fixture-smoke:'
                       'supported_tool:hapax-agy-reviewer:model:' + model + ':'
                       'observed_at:2026-07-07T13:00:00Z:fresh_until:2026-07-07T13:15:00Z')
                if scan.admissions:
                    ref = scan.admissions[0].evidence_ref
                record = ledger.QuotaSpendLedger.model_validate({
                    'schema_version': 1, 'ledger_id': 'fixture-agy-binding',
                    'captured_at': now, 'authority_source': 'isap:quota-spend-ledger-20260509',
                    'generated_from': ['scripts/hapax-quota-telemetry-writer'],
                    'consumer_permission_after': 'private_capacity_routing_tests_only',
                    'evidence_refs': ['fixture-binding-check'],
                    'quota_snapshots': [{
                        'quota_snapshot_schema': 1, 'snapshot_id': 'quota-fixture-agy-binding',
                        'captured_at': now, 'fresh_until': '2026-07-07T13:15:00Z',
                        'route_id': 'agy.review.direct', 'provider': 'google-antigravity-cli-agy',
                        'capacity_pool': 'subscription_quota', 'subscription_quota_state': 'fresh',
                        'evidence_refs': [ref], 'operator_visible_reason': 'fixture binding',
                    }],
                })
                state, refs = ledger.subscription_quota_state_for_route(
                    record, 'agy.review.direct', now=now)
                result['consumers'][model] = {'telemetry_count': len(scan.admissions),
                    'ignored_count': len(scan.ignored_evidence_refs), 'ledger_state': state.value,
                    'ledger_refs': refs, 'observed_ref': ref}
        print(json.dumps(result))
    """)
    models = list(dict.fromkeys([model, alias, previous_model, previous_alias]))
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            driver,
            str(tree),
            str(wrapper),
            str(tmp_path / "receipts"),
            json.dumps(models),
        ],
        cwd=tree,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert calls.exists(), observed
    invocations = [json.loads(line) for line in calls.read_text().splitlines()]
    assert len(invocations) == 1
    assert invocations[0][invocations[0].index("--model") + 1] == model
    if native_rc:
        assert observed["rc"] == 2
        assert "returncode=1" in observed["stderr"]
        assert f"model {model} is not recognized" in observed["stderr"]
        assert observed["receipts"] == 0
        return
    assert observed["rc"] == 0, observed
    assert json.loads(observed["stdout"])["model"] == model
    assert observed["receipt_model"] == model
    assert observed["receipts"] == 1
    for identity, consumer in observed["consumers"].items():
        accepted = identity in {model, alias}
        assert consumer["telemetry_count"] == int(accepted), (identity, consumer)
        assert consumer["ignored_count"] == int(not accepted), (identity, consumer)
        assert (consumer["ledger_state"] == "fresh") is accepted, (identity, consumer)
        if accepted:
            assert f":model:{identity}:" in consumer["observed_ref"]
        else:
            assert any("untrusted_agy_admission_evidence" in ref for ref in consumer["ledger_refs"])

    reviewer = tree / "scripts/hapax-agy-reviewer"
    for requested, expected_rc in [(alias, 0), (previous_model, 64)]:
        response = subprocess.run(
            [sys.executable, str(reviewer), "--agy-bin", str(native), "--model", requested],
            input="fixture review",
            cwd=tree,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert response.returncode == expected_rc, response.stderr
    invocations = [json.loads(line) for line in calls.read_text().splitlines()]
    assert len(invocations) == 2  # old pin is refused before native execution
    assert all(args[args.index("--model") + 1] == model for args in invocations)
