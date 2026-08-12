"""Pins for the bare-host capability observer.

The tests that matter here are the ones about what the observer *refuses* to say. A probe that
reports only what it found is trivially green and silently wrong, so most of this file is about
absence: an absent CLI must be a row, an unreachable host must be a row, and those two must stay
distinguishable after they both collapse onto ``freshness_state=missing``.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from shared.bare_host_capability_observer import (
    _SAFE_CLI_NAME,
    ABSENT_REASON_PREFIX,
    CLI_CATALOGUE,
    OBSERVATION_RECEIPT_CLASS,
    UNREACHABLE_REASON_PREFIX,
    CliShapeSpec,
    HostCliProbe,
    _probe_argv,
    _probe_payload,
    descriptors_for_probe,
    observation_outcome,
    observe,
    probe_host_clis,
    render,
)
from shared.platform_capability_registry import (
    AuthorityCeiling,
    CapabilityShapeClass,
    CapabilityShapeDescriptor,
    CapabilityShapeFreshnessState,
    CapabilityShapeState,
)

NOW = datetime(2026, 8, 12, 17, 30, tzinfo=UTC)

SMALL_CATALOGUE: tuple[CliShapeSpec, ...] = (
    CliShapeSpec(
        cli="claude",
        shape_class=CapabilityShapeClass.ORCHESTRATOR,
        carrier_family="anthropic_cli_harness",
        summary="Claude Code CLI harness present on host.",
        harness_shape="interactive-and-headless-agent-cli",
        resource_semantics=("provider-subscription-or-api-quota",),
    ),
    CliShapeSpec(
        cli="ollama",
        shape_class=CapabilityShapeClass.LOCAL_COMPUTE,
        carrier_family="local_inference_runtime",
        summary="Ollama local inference runtime present on host.",
        harness_shape="local-model-server-cli",
        resource_semantics=("local-gpu-vram",),
    ),
)


class FakeCompleted:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def runner_for(stdout: str = "", stderr: str = "", returncode: int = 0):
    def _run(argv, **kwargs):
        return FakeCompleted(stdout=stdout, stderr=stderr, returncode=returncode)

    return _run


def linux(name: str) -> dict[str, object]:
    return {"name": name, "ip": "100.64.0.1", "os": "linux", "tags": [], "online": True}


def probe_of(host: str, present: dict[str, str], absent: list[str]) -> HostCliProbe:
    return HostCliProbe(host=host, reachable=True, present=dict(present), absent=list(absent))


# --- an absent CLI is a row, not an omission -------------------------------------------------


def test_absent_cli_emits_a_row_rather_than_being_omitted():
    probe = probe_of("podium", {"claude": "/usr/bin/claude"}, ["ollama"])

    rows = descriptors_for_probe(probe, catalogue=SMALL_CATALOGUE, observed_at=NOW)

    assert len(rows) == len(SMALL_CATALOGUE)
    absent = next(r for r in rows if r.shape_id.endswith(".ollama"))
    assert absent.freshness_state is CapabilityShapeFreshnessState.MISSING
    assert absent.blocked_reasons == [f"{ABSENT_REASON_PREFIX}podium:ollama"]
    assert absent.observed_at is None


def test_every_catalogue_entry_produces_exactly_one_row_per_host():
    probe = probe_of("podium", {}, [spec.cli for spec in CLI_CATALOGUE])

    rows = descriptors_for_probe(probe, observed_at=NOW)

    assert [r.shape_id for r in rows] == [f"bare-host.podium.{s.cli}" for s in CLI_CATALOGUE]


def test_an_unreachable_host_is_a_row_for_every_catalogue_entry():
    probe = HostCliProbe(host="eta", reachable=False, unreachable_reason="ssh: connect timed out")

    rows = descriptors_for_probe(probe, catalogue=SMALL_CATALOGUE, observed_at=NOW)

    assert len(rows) == len(SMALL_CATALOGUE)
    assert all(r.freshness_state is CapabilityShapeFreshnessState.MISSING for r in rows)
    assert all(
        r.blocked_reasons == [f"{UNREACHABLE_REASON_PREFIX}eta:ssh: connect timed out"]
        for r in rows
    )


# --- absent and not-observable must not collapse ---------------------------------------------


def test_absent_and_not_observable_are_distinguishable_though_both_are_missing():
    absent_row = descriptors_for_probe(
        probe_of("podium", {}, ["claude"]), catalogue=SMALL_CATALOGUE[:1], observed_at=NOW
    )[0]
    unobservable_row = descriptors_for_probe(
        HostCliProbe(host="eta", reachable=False, unreachable_reason="down"),
        catalogue=SMALL_CATALOGUE[:1],
        observed_at=NOW,
    )[0]

    # Same freshness — the enum has no third value. That is exactly why the split has to be
    # carried elsewhere, and why a test asserting only on freshness would prove nothing.
    assert absent_row.freshness_state == unobservable_row.freshness_state

    assert observation_outcome(absent_row) == "absent"
    assert observation_outcome(unobservable_row) == "not_observable"
    # The negative probe is real evidence and is cited; an unreached host has none to cite.
    assert absent_row.evidence_refs == ["local_probe:podium:command -v claude -> not-found"]
    assert unobservable_row.evidence_refs == []


def test_observation_outcome_reports_observed_only_when_something_was_observed():
    rows = descriptors_for_probe(
        probe_of("podium", {"claude": "/usr/bin/claude"}, ["ollama"]),
        catalogue=SMALL_CATALOGUE,
        observed_at=NOW,
    )

    assert [observation_outcome(r) for r in rows] == ["observed", "absent"]


def test_a_reachable_host_that_never_answered_about_an_entry_is_not_reported_absent():
    # present union absent does not cover the catalogue: the host answered, but not about ollama.
    probe = probe_of("podium", {"claude": "/usr/bin/claude"}, [])

    rows = descriptors_for_probe(probe, catalogue=SMALL_CATALOGUE, observed_at=NOW)
    unanswered = next(r for r in rows if r.shape_id.endswith(".ollama"))

    assert observation_outcome(unanswered) == "not_observable"
    assert unanswered.failure_classes == ["probe_incomplete"]


def test_a_partial_answer_from_the_host_does_not_become_an_absence():
    # End-to-end through the parser, which is where a truncated reply actually arrives. The
    # hand-built probe above cannot catch a parser that fills the gap with "absent".
    stdout = "cli=claude present=1 path=/usr/bin/claude\n"

    probe = probe_host_clis(
        linux("podium"), catalogue=SMALL_CATALOGUE, runner=runner_for(stdout=stdout), now=NOW
    )

    assert probe.reachable is True
    assert probe.absent == []
    rows = descriptors_for_probe(probe, catalogue=SMALL_CATALOGUE, observed_at=NOW)
    assert [observation_outcome(r) for r in rows] == ["observed", "not_observable"]


# --- presence is evidence of a shape, never supply --------------------------------------------


def test_no_emitted_row_is_demand_eligible_or_carries_routes():
    probe = probe_of("podium", {s.cli: f"/usr/bin/{s.cli}" for s in CLI_CATALOGUE}, [])

    rows = descriptors_for_probe(probe, observed_at=NOW)

    assert rows, "a fully-present host must still emit rows"
    for row in rows:
        assert row.demand_eligible is False
        assert row.route_ids == []
        assert row.authority_ceiling is AuthorityCeiling.READ_ONLY
        assert row.shape_state is CapabilityShapeState.EVIDENCE_ONLY
        assert row.spend_semantics == ["no-spend-authority-observed"]


def test_an_observed_row_still_declares_that_presence_is_not_measured_supply():
    row = descriptors_for_probe(
        probe_of("podium", {"claude": "/usr/bin/claude"}, []),
        catalogue=SMALL_CATALOGUE[:1],
        observed_at=NOW,
    )[0]

    assert row.freshness_state is CapabilityShapeFreshnessState.FRESH
    assert row.blocked_reasons == ["presence_observed_without_measured_supply"]
    assert row.measurement_plan_refs == ["require:measured-probe-post-consent:claude"]


def test_evidence_only_rows_never_emit_a_capability_surface_delta():
    # An observation must not reach the dispatch hold channel; the registry validator agrees,
    # so this pins the choice rather than restating it.
    rows = descriptors_for_probe(
        probe_of("podium", {"claude": "/usr/bin/claude"}, ["ollama"]),
        catalogue=SMALL_CATALOGUE,
        observed_at=NOW,
    )

    assert all(r.surface_delta_signal is None for r in rows)
    assert all(r.observation_receipt_class == OBSERVATION_RECEIPT_CLASS for r in rows)


def test_demand_eligible_is_refused_by_the_registry_not_merely_by_convention():
    row = descriptors_for_probe(
        probe_of("podium", {"claude": "/usr/bin/claude"}, []),
        catalogue=SMALL_CATALOGUE[:1],
        observed_at=NOW,
    )[0]

    poisoned = row.model_dump()
    poisoned["demand_eligible"] = True

    with pytest.raises(ValidationError, match="cannot be demand_eligible"):
        CapabilityShapeDescriptor.model_validate(poisoned)


# --- the probe payload and its transport ------------------------------------------------------


def test_the_payload_asks_about_every_catalogue_entry_explicitly():
    payload = _probe_payload(CLI_CATALOGUE)

    for spec in CLI_CATALOGUE:
        assert spec.cli in payload
    assert "present=1" in payload
    assert "present=0" in payload


def test_catalogue_names_cannot_carry_shell_metacharacters():
    # The catalogue is interpolated into a remote command, so this is the injection boundary.
    assert all(_SAFE_CLI_NAME.match(spec.cli) for spec in CLI_CATALOGUE)
    assert not _SAFE_CLI_NAME.match("gh; rm -rf /")
    assert not _SAFE_CLI_NAME.match("$(id)")


def test_a_remote_probe_wraps_the_payload_in_bash_because_a_login_shell_may_be_fish():
    argv = _probe_argv(_probe_payload(SMALL_CATALOGUE), "podium")

    assert argv[0] == "ssh"
    assert argv[-2] == "podium"
    assert argv[-1].startswith("bash -c ")


def test_the_local_probe_does_not_go_through_ssh():
    argv = _probe_argv(_probe_payload(SMALL_CATALOGUE), "")

    assert argv[0] == "bash"
    assert "ssh" not in argv


def test_probe_parses_present_and_absent_verdicts():
    stdout = "cli=claude present=1 path=/usr/bin/claude\ncli=ollama present=0 path=\n"

    probe = probe_host_clis(
        linux("podium"), catalogue=SMALL_CATALOGUE, runner=runner_for(stdout=stdout), now=NOW
    )

    assert probe.reachable is True
    assert probe.present == {"claude": "/usr/bin/claude"}
    assert probe.absent == ["ollama"]


def test_probe_keeps_a_path_containing_spaces():
    stdout = "cli=claude present=1 path=/opt/my tools/claude\n"

    probe = probe_host_clis(
        linux("podium"), catalogue=SMALL_CATALOGUE[:1], runner=runner_for(stdout=stdout), now=NOW
    )

    assert probe.present == {"claude": "/opt/my tools/claude"}


def test_an_ssh_failure_is_an_unreachable_row_and_never_an_exception():
    probe = probe_host_clis(
        linux("eta"),
        catalogue=SMALL_CATALOGUE,
        runner=runner_for(
            stderr="ssh: connect to host eta port 22: No route to host", returncode=255
        ),
        now=NOW,
    )

    assert probe.reachable is False
    assert "No route to host" in probe.unreachable_reason
    assert probe.present == {}
    assert probe.absent == []


def test_a_timeout_is_an_unreachable_row_and_never_an_exception():
    def _boom(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=12)

    probe = probe_host_clis(linux("eta"), catalogue=SMALL_CATALOGUE, runner=_boom, now=NOW)

    assert probe.reachable is False
    assert "TimeoutExpired" in probe.unreachable_reason


def test_a_non_linux_host_is_recorded_as_not_probed_rather_than_dropped():
    row = {"name": "phone", "ip": "100.64.0.9", "os": "iOS", "tags": [], "online": True}

    probe = probe_host_clis(row, catalogue=SMALL_CATALOGUE, runner=runner_for(), now=NOW)

    assert probe.reachable is False
    assert "os=iOS" in probe.unreachable_reason


def test_garbage_output_does_not_become_a_reachable_host():
    probe = probe_host_clis(
        linux("podium"),
        catalogue=SMALL_CATALOGUE,
        runner=runner_for(stdout="motd: welcome to podium\n"),
        now=NOW,
    )

    assert probe.reachable is False
    assert probe.unreachable_reason == "probe returned no recognisable cli lines"


# --- the estate-wide sweep ---------------------------------------------------------------------


def _split_runner(stdout: str):
    def _run(argv, **kwargs):
        if any("eta" in str(part) for part in argv):
            return FakeCompleted(stderr="No route to host", returncode=255)
        return FakeCompleted(stdout=stdout)

    return _run


def test_observe_keeps_unreachable_hosts_in_the_result():
    hosts = [linux("podium"), linux("eta")]
    stdout = "cli=claude present=1 path=/usr/bin/claude\ncli=ollama present=0 path=\n"

    result = observe(hosts=hosts, catalogue=SMALL_CATALOGUE, runner=_split_runner(stdout), now=NOW)

    assert result.host_count == 2
    assert result.reachable_count == 1
    assert result.unreachable == ["eta"]
    # Both hosts contribute a full set of rows: an unreachable host is never a smaller inventory.
    assert len(result.descriptors) == 2 * len(SMALL_CATALOGUE)


def test_observe_refuses_rather_than_assuming_a_roster(monkeypatch):
    import shared.bare_host_capability_observer as module

    def _refuse():
        raise module.InventoryUnavailable("tailscale is not installed")

    monkeypatch.setattr(module, "tailnet_hosts", _refuse)

    with pytest.raises(module.InventoryUnavailable):
        observe(runner=runner_for(), now=NOW)


def test_shape_ids_are_registry_legal_for_hosts_with_awkward_names():
    # Uppercase and a space are illegal in the registry's shape_id pattern; dot, dash and
    # underscore are legal and must survive, because mangling them would silently merge two hosts.
    probe = probe_of("Pi-6_IR Overhead", {"claude": "/usr/bin/claude"}, [])

    row = descriptors_for_probe(probe, catalogue=SMALL_CATALOGUE[:1], observed_at=NOW)[0]

    # Constructed, not asserted: re-validating proves the id satisfies the registry's own pattern.
    assert CapabilityShapeDescriptor.model_validate(row.model_dump()).shape_id == row.shape_id
    assert row.shape_id == "bare-host.pi-6_ir-overhead.claude"


def test_render_marks_an_unobserved_cell_as_unknown_and_never_as_absent():
    hosts = [linux("podium"), linux("eta")]
    stdout = "cli=claude present=1 path=/usr/bin/claude\ncli=ollama present=0 path=\n"

    text = render(
        observe(hosts=hosts, catalogue=SMALL_CATALOGUE, runner=_split_runner(stdout), now=NOW),
        catalogue=SMALL_CATALOGUE,
    )

    podium_line = next(line for line in text.splitlines() if line.startswith("podium"))
    eta_line = next(line for line in text.splitlines() if line.startswith("eta"))
    assert "yes" in podium_line
    assert "no" in podium_line
    assert "no" not in eta_line
    assert eta_line.count("?") == len(SMALL_CATALOGUE)
