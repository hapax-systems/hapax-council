"""The extensionless ``scripts/hapax-entitlement-census``: orchestration and exit-code mapping.

Review round 2 on #4743 (claude-1): the shared module was pinned, the CLI was not. These tests load
the script as a module and replace only its I/O seams (host reads, HTTP, secrets, scout, GPU probe,
intake), so ``main()`` itself decides the exit code, the budget and which branch runs.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from shared.entitlement_census import HostHoldings, HttpResponse

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-entitlement-census"


def _load_cli():
    loader = importlib.machinery.SourceFileLoader("hapax_entitlement_census_cli", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    # Never the real durable sink: the history and per-call ledger streams go to a temp root.
    sink_root = tmp_path / "durable-sink"
    sink_root.mkdir()
    monkeypatch.setenv("HAPAX_DURABLE_SINK_ROOT", str(sink_root))
    module = _load_cli()
    module.SINK_ROOT = sink_root
    calls: dict[str, list[Any]] = {"hosts": [], "http": [], "intake": [], "secrets": []}

    def fake_collect(binding, *, login_files, harness_bins, now, timeout):
        calls["hosts"].append((binding.host_id, timeout))
        reachable = binding.transport == "local"
        return HostHoldings(
            host_id=binding.host_id,
            reachable=reachable,
            observed_at=datetime.now(UTC) if reachable else None,
            error=None if reachable else "exit_255",
            filestore_names=("featherless-api-key",) if reachable else (),
        )

    def fake_http(url, headers, timeout):
        calls["http"].append(url)
        return HttpResponse(status=None, body=b"", error="refused")

    def fake_secret(name):
        calls["secrets"].append(name)
        return None

    def fake_intake(path, deltas):
        calls["intake"].append(path)
        return {
            "ok": module.INTAKE_OK,
            "written": [],
            "skipped_existing": 0,
            "ignored_evidence_only": 0,
            "discovered": 0,
            "error": None,
        }

    module.INTAKE_OK = True
    monkeypatch.setattr(module, "collect_holdings", fake_collect)
    monkeypatch.setattr(module, "default_http_get", fake_http)
    monkeypatch.setattr(module, "default_resolve_secret", fake_secret)
    monkeypatch.setattr(module, "_scout_report", lambda config, timeout: None)
    monkeypatch.setattr(module, "_gpu_probe", lambda host: (False, []))
    monkeypatch.setattr(module, "_intake", fake_intake)
    module.calls = calls
    return module


def _files(tmp_path: Path, *, remote: bool = True) -> dict[str, Path]:
    hosts: list[dict[str, Any]] = [{"host_id": "appendix", "transport": "local"}]
    if remote:
        hosts.append({"host_id": "podium", "transport": "ssh_batch", "target": "podium.example"})
    config = {
        "schema": "hapax.entitlement_census.v1",
        "hosts": hosts,
        "entitlements": [
            {
                "entitlement_id": "featherless",
                "provider": "featherless",
                "kind": "cognition",
                "cost_class": "prepaid",
                "credential_names": ["featherless-api-key"],
            }
        ],
    }
    paths = {
        "config": tmp_path / "census.json",
        "registry": tmp_path / "registry.json",
        "out": tmp_path / "out",
        "ledger": tmp_path / "absent-ledger.json",
    }
    paths["config"].write_text(json.dumps(config), encoding="utf-8")
    paths["registry"].write_text(
        json.dumps({"routes": [], "omitted_capability_shapes": []}), "utf-8"
    )
    return paths


def _argv(paths: dict[str, Path], *extra: str) -> list[str]:
    return [
        "--config",
        str(paths["config"]),
        "--registry",
        str(paths["registry"]),
        "--output-root",
        str(paths["out"]),
        "--ledger",
        str(paths["ledger"]),
        "--no-projection-md",
        *extra,
    ]


def test_unreadable_registry_exits_2_and_writes_nothing(cli, tmp_path: Path) -> None:
    paths = _files(tmp_path)
    paths["registry"] = tmp_path / "absent.json"
    assert cli.main(_argv(paths)) == cli.EXIT_REFUSED
    assert not paths["out"].exists()
    assert cli.calls["hosts"] == []  # refused before any host is read


def test_invalid_declaration_exits_2(cli, tmp_path: Path) -> None:
    paths = _files(tmp_path)
    paths["config"].write_text('{"schema": "hapax.entitlement_census.v1"}', encoding="utf-8")
    assert cli.main(_argv(paths)) == cli.EXIT_REFUSED


def test_unreachable_host_exits_3_after_writing_the_view(cli, tmp_path: Path) -> None:
    paths = _files(tmp_path)
    assert cli.main(_argv(paths, "--no-intake")) == cli.EXIT_HOST_UNREACHABLE
    view = json.loads((paths["out"] / "view.json").read_text(encoding="utf-8"))
    assert [h["host_id"] for h in view["hosts"] if not h["reachable"]] == ["podium"]


def test_all_hosts_reachable_exits_0(cli, tmp_path: Path) -> None:
    paths = _files(tmp_path, remote=False)
    assert cli.main(_argv(paths, "--no-intake")) == 0
