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


def test_intake_runs_only_without_no_intake_and_its_failure_exits_1(cli, tmp_path: Path) -> None:
    paths = _files(tmp_path, remote=False)
    assert cli.main(_argv(paths, "--no-intake")) == 0
    assert cli.calls["intake"] == []  # held: deltas written, intake not applied
    assert (paths["out"] / "surface-deltas.json").exists()

    cli.INTAKE_OK = False
    assert cli.main(_argv(paths)) == cli.EXIT_INTAKE_FAILED
    assert len(cli.calls["intake"]) == 1


def test_dry_run_writes_nothing(cli, tmp_path: Path) -> None:
    paths = _files(tmp_path, remote=False)
    assert cli.main(_argv(paths, "--dry-run")) == 0
    assert not paths["out"].exists()
    assert cli.calls["intake"] == []


def test_no_remote_never_reads_a_remote_host(cli, tmp_path: Path) -> None:
    paths = _files(tmp_path)
    assert cli.main(_argv(paths, "--no-remote", "--no-intake")) == cli.EXIT_HOST_UNREACHABLE
    assert [host for host, _ in cli.calls["hosts"]] == ["appendix"]


def test_spent_budget_reads_no_host_and_probes_nothing(
    cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _files(tmp_path)
    monkeypatch.setattr(cli, "NETWORK_BUDGET_S", 0.0)
    assert cli.main(_argv(paths, "--no-intake")) == cli.EXIT_HOST_UNREACHABLE
    assert cli.calls["hosts"] == [] and cli.calls["http"] == [] and cli.calls["secrets"] == []
    view = json.loads((paths["out"] / "view.json").read_text(encoding="utf-8"))
    assert {h["error"] for h in view["hosts"]} == {"run_deadline_reached"}


def test_on_another_host_the_run_is_skipped_and_touches_nothing(
    cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """hapax-determine runs on every host (podium too, measured 2026-09-25T05:15Z). The census
    bindings are written from the FileStore host's point of view, so on any other host the run
    must be a witnessed no-op: exit 0, nothing read, nothing written."""
    paths = _files(tmp_path)
    monkeypatch.setattr(cli, "_hostname", lambda: "hapax-podium")
    assert cli.main(_argv(paths, "--run-on-host", "hapax-appendix", "--json")) == 0
    assert cli.calls["hosts"] == [] and cli.calls["http"] == [] and cli.calls["secrets"] == []
    assert not paths["out"].exists()
    assert json.loads(capsys.readouterr().out)["skipped"] is True

    monkeypatch.setattr(cli, "_hostname", lambda: "hapax-appendix")
    cli.main(_argv(paths, "--run-on-host", "hapax-appendix", "--no-intake"))
    assert cli.calls["hosts"]


def test_real_runs_append_the_series_and_dry_runs_never_do(
    cli, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from shared.durable_jsonl_sink import DurableJsonlSink
    from shared.entitlement_census import HISTORY_STREAM

    paths = _files(tmp_path, remote=False)
    history = DurableJsonlSink(cli.SINK_ROOT).path_for_stream(HISTORY_STREAM)
    assert cli.main(_argv(paths, "--dry-run")) == 0
    assert not history.exists()

    cli.main(_argv(paths, "--no-intake", "--now", "2026-09-25T01:00:00Z"))
    capsys.readouterr()  # discard the first run's plain-text line
    cli.main(_argv(paths, "--no-intake", "--now", "2026-09-25T03:00:00Z", "--json"))
    assert len(history.read_text(encoding="utf-8").splitlines()) == 2
    summary = json.loads(capsys.readouterr().out)
    assert summary["ratchet"]["points"] == 2
    assert summary["ratchet"]["availability"] == "flat"
    view = json.loads((paths["out"] / "view.json").read_text(encoding="utf-8"))
    assert view["trend"]["points"] == 2


def test_the_pre_sink_series_still_counts_and_is_never_rewritten(cli, tmp_path: Path) -> None:
    """The two runs before the durable sink wrote a plain history.jsonl beside the view. The move to
    the sink must not drop them from the trend, and the frozen file is evidence: read, never written."""
    paths = _files(tmp_path, remote=False)
    paths["out"].mkdir()
    legacy = paths["out"] / "history.jsonl"
    legacy.write_text(
        json.dumps({"ts": "2026-09-25T00:30:00Z", "states": {"featherless": "held"}}) + "\n",
        encoding="utf-8",
    )
    frozen = legacy.read_bytes()
    assert cli.main(_argv(paths, "--no-intake", "--now", "2026-09-25T01:00:00Z")) == 0
    view = json.loads((paths["out"] / "view.json").read_text(encoding="utf-8"))
    assert view["trend"]["points"] == 2
    assert legacy.read_bytes() == frozen


def test_host_reads_are_capped_by_the_budget(cli, tmp_path: Path) -> None:
    paths = _files(tmp_path)
    cli.main(_argv(paths, "--no-intake"))
    assert cli.calls["hosts"] and all(
        0 < t <= cli.HOST_READ_TIMEOUT_S for _, t in cli.calls["hosts"]
    )
