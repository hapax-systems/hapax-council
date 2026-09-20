"""Cross-host inventory: the collector must never shrink silently.

The defect this module exists to prevent is not "we lack a document". It is that every other
inventory instrument here is host-scoped, so an answer about one host gets read as an answer
about the estate. The tests therefore concentrate on the two ways a collector can lie by
omission -- dropping a host it could not reach, and reporting "not found" when it meant "not
looked at".
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from shared.estate_host_inventory import (
    HostFacts,
    InventoryUnavailable,
    _parse_probe,
    collect,
    find,
    probe_host,
    render,
)

LINUX = {"name": "box", "ip": "100.0.0.1", "os": "linux", "tags": ["hapax"], "online": True}


def _ok(stdout: str):  # noqa: ANN202
    def runner(*_a, **_k):  # noqa: ANN202
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    return runner


def _fail(stderr: str, code: int = 255):  # noqa: ANN202
    def runner(*_a, **_k):  # noqa: ANN202
        return SimpleNamespace(returncode=code, stdout="", stderr=stderr)

    return runner


# --- the central property: absence is a row, never an omission ---------------------


def test_an_unreachable_host_is_recorded_not_dropped() -> None:
    """A collector that drops what it cannot reach returns a smaller, entirely consistent,
    entirely wrong inventory. That is the `skip_missing_files` defect with hosts instead of
    files, and it is the failure this whole module is built against."""
    facts = probe_host(LINUX, runner=_fail("ssh: connect to host box port 22: Connection refused"))

    assert facts.tailnet_name == "box"
    assert facts.reachable is False
    assert "Connection refused" in facts.unreachable_reason


def test_the_reason_is_kept_because_causes_differ() -> None:
    """Refused, timed out, and key-rejected need different fixes. A bare boolean would make
    them one condition, which is how a permission problem gets mistaken for a dead host."""
    refused = probe_host(LINUX, runner=_fail("Connection refused"))
    denied = probe_host(LINUX, runner=_fail("Permission denied (publickey,password)."))

    assert refused.unreachable_reason != denied.unreachable_reason


def test_a_timeout_is_a_row_not_an_exception() -> None:
    def runner(*_a, **_k):  # noqa: ANN202
        raise subprocess.TimeoutExpired(cmd="ssh", timeout=12)

    facts = probe_host(LINUX, runner=runner)

    assert facts.reachable is False
    assert "TimeoutExpired" in facts.unreachable_reason


def test_non_linux_hosts_are_marked_not_probed_rather_than_failing() -> None:
    """A phone is not a broken host. Saying so keeps real failures legible."""
    facts = probe_host({**LINUX, "os": "android"}, runner=_fail("should not run"))

    assert facts.reachable is False
    assert "not probed" in facts.unreachable_reason
    assert "android" in facts.unreachable_reason


def test_render_shows_unreachable_hosts_as_rows(capsys) -> None:  # noqa: ANN001
    """They must survive to the human output too -- an inventory that hides them at the last
    step is as misleading as one that dropped them at the first."""
    inventory = {
        "collected_at": "2026-08-12T01:00:00Z",
        "collected_from": "here",
        "host_count": 2,
        "reachable_count": 1,
        "unreachable": ["gone"],
        "hosts": [
            {
                "tailnet_name": "live",
                "reachable": True,
                "cpus": 8,
                "mem_gb": 32,
                "video_devices": [],
                "running_units": 3,
                "gpus": [],
            },
            {
                "tailnet_name": "gone",
                "reachable": False,
                "unreachable_reason": "Connection refused",
            },
        ],
    }

    text = render(inventory)

    assert "gone" in text
    assert "UNREACHABLE" in text
    assert "1/2 reachable" in text


# --- "not found" and "not looked at" are different answers -------------------------


def test_find_reports_hosts_it_could_not_search(capsys) -> None:  # noqa: ANN001
    """The motivating error in miniature: I concluded "the estate has no RTX 5090" from a
    host that has none, while the host that has one was never checked."""
    inventory = {
        "hosts": [
            {
                "tailnet_name": "a",
                "reachable": True,
                "gpus": ["NVIDIA GeForce RTX 3090, 24576 MiB"],
                "product": "MS-7E59",
                "hostname": "a",
                "video_devices": [],
                "kernel": "6.1",
            },
            {"tailnet_name": "b", "reachable": False, "unreachable_reason": "refused"},
        ]
    }

    hits = find(inventory, "5090")

    assert any("unreachable" in h for h in hits), "a blind spot must be reported, not implied"
    assert any("b" in h for h in hits)


def test_find_matches_gpu_product_and_device_paths() -> None:
    inventory = {
        "hosts": [
            {
                "tailnet_name": "podium",
                "reachable": True,
                "gpus": ["NVIDIA GeForce RTX 5090, 32607 MiB"],
                "product": "System Product Name",
                "hostname": "podium",
                "video_devices": ["/dev/video42"],
                "kernel": "6.1",
            }
        ]
    }

    assert find(inventory, "5090") == ["podium"]
    assert find(inventory, "/dev/video") == ["podium"]
    assert find(inventory, "system product") == ["podium"]
    assert find(inventory, "nonexistent-thing") == []


# --- the roster is measured, and refuses rather than guessing ----------------------


def test_a_missing_tailscale_refuses_instead_of_assuming_a_roster(monkeypatch) -> None:  # noqa: ANN001
    """An assumed roster does not report a missing host as unreachable -- it renders it
    invisible, which is strictly worse. Refuse and say why."""
    monkeypatch.setattr("shared.estate_host_inventory.shutil.which", lambda _n: None)

    with pytest.raises(InventoryUnavailable, match="roster cannot be measured"):
        collect()


# --- probe parsing is tolerant, because a degraded host is still informative --------


def test_a_partial_probe_still_yields_the_fields_that_answered() -> None:
    """One missing tool must not blank the host. `nvidia-smi` absent is a fact about the host,
    not a reason to know nothing about it."""
    facts = HostFacts(tailnet_name="x")
    _parse_probe("hostname=x\ncpus=16\nmem_gb=60\nv4l_by_id=0\n", facts)

    assert facts.hostname == "x"
    assert facts.cpus == 16
    assert facts.mem_gb == 60
    assert facts.gpus == []


def test_probe_collects_multiple_gpus_and_video_devices() -> None:
    facts = HostFacts(tailnet_name="podium")
    _parse_probe(
        "hostname=podium\n"
        "gpu=NVIDIA GeForce RTX 5090, 32607 MiB\n"
        "gpu=NVIDIA GeForce RTX 5060 Ti, 16311 MiB\n"
        "video=/dev/video42\nvideo=/dev/video50\n",
        facts,
    )

    assert len(facts.gpus) == 2
    assert facts.video_devices == ["/dev/video42", "/dev/video50"]


def test_a_probe_that_returns_nothing_is_unreachable_not_empty() -> None:
    """Exit 0 with no hostname means the pipeline ran and told us nothing. Recording that as a
    reachable host with zero devices would assert a measurement that never happened."""
    facts = probe_host(LINUX, runner=_ok("\n"))

    assert facts.reachable is False
    assert facts.unreachable_reason


def test_collect_counts_reachable_separately_from_total(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        "shared.estate_host_inventory.tailnet_hosts",
        lambda: [LINUX, {**LINUX, "name": "dead"}],
    )
    calls = {"n": 0}

    def runner(*_a, **_k):  # noqa: ANN202
        calls["n"] += 1
        if calls["n"] == 1:
            return SimpleNamespace(returncode=0, stdout="hostname=box\ncpus=4\n", stderr="")
        return SimpleNamespace(returncode=255, stdout="", stderr="refused")

    inventory = collect(runner=runner, self_name="somewhere-else")

    assert inventory["host_count"] == 2
    assert inventory["reachable_count"] == 1
    assert inventory["unreachable"] == ["dead"]
    assert len(inventory["hosts"]) == 2, "every host must appear, reachable or not"
