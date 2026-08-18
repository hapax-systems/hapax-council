"""Pins for the bare-host capability observer.

The tests that matter here are the ones about what the observer *refuses* to say. A probe that
reports only what it found is trivially green and silently wrong, so most of this file is about
absence: an absent CLI must be a row, an unreachable host must be a row, and those two must stay
distinguishable after they both collapse onto ``freshness_state=missing``.
"""

from __future__ import annotations

import shlex
import subprocess
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from shared.bare_host_capability_observer import (
    _SAFE_CLI_NAME,
    ABSENT_REASON_PREFIX,
    BARE_HOST_CLI_RECEIPT_SUBDIR,
    CLI_CATALOGUE,
    NOT_PROBED_REASON_PREFIX,
    OBSERVATION_RECEIPT_CLASS,
    UNREACHABLE_REASON_PREFIX,
    CliShapeSpec,
    HostCliProbe,
    InventoryUnavailable,
    _probe_argv,
    _probe_payload,
    descriptors_for_probe,
    descriptors_from_bare_host_receipts,
    load_bare_host_cli_probe_receipts,
    observation_outcome,
    observe,
    probe_host_clis,
    receipts_for_observation,
    render,
    write_bare_host_cli_probe_receipts,
)
from shared.platform_capability_receipts import (
    BareHostCliProbeReceiptV1,
    PlatformCapabilityReceiptError,
    load_platform_capability_receipts,
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


REAL_SHELL_CATALOGUE: tuple[CliShapeSpec, ...] = (
    CliShapeSpec(
        cli="bash",
        shape_class=CapabilityShapeClass.LOCAL_COMPUTE,
        carrier_family="posix_shell",
        summary="bash present on host.",
        harness_shape="shell",
        resource_semantics=("local-cpu",),
    ),
    CliShapeSpec(
        cli="hapax-definitely-not-installed",
        shape_class=CapabilityShapeClass.LOCAL_COMPUTE,
        carrier_family="nothing",
        summary="a binary that does not exist.",
        harness_shape="none",
        resource_semantics=("local-cpu",),
    ),
)


def test_the_payload_actually_runs_in_a_real_shell_and_parses_back():
    # Every other probe test fabricates stdout, so a payload that is syntactically broken — or
    # whose real output does not match _parse_probe — would leave the whole suite green. This is
    # the one test that runs the production local path end to end: payload -> bash -> parser ->
    # descriptors. `bash` must be found (it just ran the payload) and the invented name must not.
    probe = probe_host_clis(
        linux("localhost"),
        catalogue=REAL_SHELL_CATALOGUE,
        self_name="localhost",  # forces the local `bash -c` branch, no ssh
        now=NOW,
    )

    assert probe.reachable is True, probe.unreachable_reason
    assert "bash" in probe.present
    assert probe.present["bash"].endswith("bash")
    assert probe.absent == ["hapax-definitely-not-installed"]

    rows = descriptors_for_probe(probe, catalogue=REAL_SHELL_CATALOGUE, observed_at=NOW)
    assert [observation_outcome(r) for r in rows] == ["observed", "absent"]


def test_a_trailing_newline_does_not_slip_past_the_injection_guard():
    # re.match with a "$" anchor accepts "gh\n"; only fullmatch refuses it. The guard's own
    # docstring calls itself the single complete point where a name reaches a shell.
    with pytest.raises(ValueError, match="unsafe CLI name"):
        _probe_payload((poisoned_spec("gh\n"),))


def test_the_shipped_catalogue_passes_the_injection_guard():
    # The catalogue is interpolated into a remote command, so this is the injection boundary.
    assert all(_SAFE_CLI_NAME.fullmatch(spec.cli) for spec in CLI_CATALOGUE)
    assert _probe_payload(CLI_CATALOGUE)


def poisoned_spec(name: str) -> CliShapeSpec:
    return CliShapeSpec(
        cli=name,
        shape_class=CapabilityShapeClass.LOCAL_COMPUTE,
        carrier_family="attacker",
        summary="hostile catalogue entry",
        harness_shape="n/a",
        resource_semantics=("local-cpu",),
    )


@pytest.mark.parametrize("hostile", ["gh; rm -rf /", "$(id)", "`id`", "a b", "-rf"])
def test_a_caller_supplied_catalogue_is_guarded_not_just_the_shipped_one(hostile):
    # Asserting the regex rejects the string proves nothing about the production path: the payload
    # builder is the only place a name reaches a shell, so it is the only place that can refuse.
    with pytest.raises(ValueError, match="unsafe CLI name"):
        _probe_payload((poisoned_spec(hostile),))


def test_a_hostile_catalogue_cannot_reach_a_shell_through_the_public_entry_points():
    calls: list[object] = []

    def _record(argv, **kwargs):
        calls.append(argv)
        return FakeCompleted(stdout="")

    with pytest.raises(ValueError, match="unsafe CLI name"):
        observe(
            hosts=[linux("podium")],
            catalogue=(poisoned_spec("$(id)"),),
            runner=_record,
            now=NOW,
        )
    assert calls == [], "no command may be built from an unvalidated catalogue"


def test_a_remote_probe_wraps_the_payload_in_bash_because_a_login_shell_may_be_fish():
    payload = _probe_payload(SMALL_CATALOGUE)
    argv = _probe_argv(payload, "podium")

    assert argv[0] == "ssh"
    assert argv[-2] == "podium"
    # ssh joins everything after the hostname with spaces and hands the result to the remote login
    # shell, so what matters is that THAT string re-lexes to exactly `bash -c <payload>` — asserting
    # it merely starts with "bash -c " would pass on a payload the remote shell would mangle.
    assert shlex.split(argv[-1]) == ["bash", "-c", payload]


def test_the_wrapped_payload_survives_a_shell_that_is_not_posix():
    # The wrapper exists because fish is a login shell on this estate. Round-tripping the joined
    # command through a POSIX lexer is the closest deterministic check that the remote sees one
    # intact argument rather than a for-loop fish would reject.
    payload = _probe_payload(SMALL_CATALOGUE)
    joined = " ".join(_probe_argv(payload, "podium")[-1:])

    assert "for c in" not in shlex.split(joined)[0]
    assert shlex.split(joined)[-1] == payload


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


@pytest.mark.parametrize(
    "line",
    [
        "cli=claude present=1 path=",  # claims present, names nothing
        "cli=claude present= path=/usr/bin/claude",  # empty verdict
        "cli=claude present=yes path=/usr/bin/claude",  # unrecognised verdict
        "cli=claude path=/usr/bin/claude",  # no verdict at all
        "cli=claude",  # truncated
    ],
)
def test_a_malformed_verdict_is_not_a_measurement_of_absence(line):
    # Only an explicit present=0 establishes absence. Everything else is an unintelligible
    # answer, and an unintelligible answer must not be laundered into a finding.
    probe = probe_host_clis(
        linux("podium"),
        catalogue=SMALL_CATALOGUE[:1],
        runner=runner_for(stdout=line + "\n"),
        now=NOW,
    )

    assert probe.absent == []
    assert probe.present == {}


def test_only_an_explicit_zero_establishes_absence():
    probe = probe_host_clis(
        linux("podium"),
        catalogue=SMALL_CATALOGUE[:1],
        runner=runner_for(stdout="cli=claude present=0 path=\n"),
        now=NOW,
    )

    assert probe.absent == ["claude"]
    row = descriptors_for_probe(probe, catalogue=SMALL_CATALOGUE[:1], observed_at=NOW)[0]
    assert observation_outcome(row) == "absent"


def test_a_malformed_verdict_surfaces_as_not_observable_not_absent():
    stdout = "cli=claude present=1 path=/usr/bin/claude\ncli=ollama present=maybe path=\n"

    probe = probe_host_clis(
        linux("podium"), catalogue=SMALL_CATALOGUE, runner=runner_for(stdout=stdout), now=NOW
    )
    rows = descriptors_for_probe(probe, catalogue=SMALL_CATALOGUE, observed_at=NOW)

    assert [observation_outcome(r) for r in rows] == ["observed", "not_observable"]


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
    assert probe.skipped is True
    assert "os=iOS" in probe.unreachable_reason
    assert "next action" in probe.unreachable_reason.lower()
    rows = descriptors_for_probe(probe, catalogue=SMALL_CATALOGUE, observed_at=NOW)
    assert all(d.failure_classes == ["host_not_probed"] for d in rows)
    assert all(any(r.startswith(NOT_PROBED_REASON_PREFIX) for r in d.blocked_reasons) for d in rows)
    assert all(observation_outcome(d) == "not_observable" for d in rows)
    assert not any(d.failure_classes == ["host_unreachable"] for d in rows)


def test_garbage_output_does_not_become_a_reachable_host():
    probe = probe_host_clis(
        linux("podium"),
        catalogue=SMALL_CATALOGUE,
        runner=runner_for(stdout="motd: welcome to podium\n"),
        now=NOW,
    )

    assert probe.reachable is False
    assert "no recognisable cli lines" in probe.unreachable_reason


@pytest.mark.parametrize(
    "runner",
    [
        runner_for(stdout="motd: welcome\n"),
        runner_for(stderr="No route to host", returncode=255),
    ],
)
def test_every_unreachable_reason_names_a_next_action(runner):
    # executive_function: an error a caller reads directly has to say what to do about it.
    probe = probe_host_clis(linux("podium"), catalogue=SMALL_CATALOGUE, runner=runner, now=NOW)

    assert probe.reachable is False
    assert "next action" in probe.unreachable_reason


def test_a_timeout_reason_names_a_next_action():
    def _boom(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=12)

    probe = probe_host_clis(linux("podium"), catalogue=SMALL_CATALOGUE, runner=_boom, now=NOW)

    assert "next action" in probe.unreachable_reason


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
    def _refuse():
        raise InventoryUnavailable("tailscale is not installed")

    monkeypatch.setattr(
        "shared.bare_host_capability_observer.tailnet_hosts",
        _refuse,
    )

    with pytest.raises(InventoryUnavailable):
        observe(runner=runner_for(), now=NOW)


def test_empty_catalogue_is_not_an_unreachable_host():
    calls: list[object] = []

    def _run(argv, **kwargs):
        calls.append(argv)
        return FakeCompleted(returncode=2, stderr="syntax error")

    probe = probe_host_clis(linux("podium"), catalogue=(), runner=_run, now=NOW)
    assert probe.reachable is True
    assert probe.skipped is False
    assert calls == []
    assert _probe_payload(()) == "true\n"


def test_a_nameless_roster_row_does_not_raise():
    probe = probe_host_clis({}, catalogue=SMALL_CATALOGUE, runner=runner_for(), now=NOW)
    assert probe.skipped is True
    assert probe.reachable is False
    assert "no host name" in probe.unreachable_reason


def test_observe_refuses_a_roster_whose_distinct_hosts_slug_to_one_identity():
    # "Pi A" and "Pi-A" are two machines. Slugged, they are one shape_id, and one host's evidence
    # would be filed under the other's name — the precise error this module exists to prevent.
    with pytest.raises(ValueError, match="both slug to"):
        observe(
            hosts=[linux("Pi A"), linux("Pi-A")],
            catalogue=SMALL_CATALOGUE,
            runner=runner_for(stdout="cli=claude present=0 path=\n"),
            now=NOW,
        )


def test_observe_does_not_refuse_a_roster_of_genuinely_distinct_slugs():
    result = observe(
        hosts=[linux("podium"), linux("appendix")],
        catalogue=SMALL_CATALOGUE,
        runner=runner_for(stdout="cli=claude present=0 path=\ncli=ollama present=0 path=\n"),
        now=NOW,
    )

    assert result.host_count == 2
    assert len({d.shape_id for d in result.descriptors}) == len(result.descriptors)


def test_the_same_host_listed_twice_is_not_treated_as_a_collision():
    # A duplicated roster row is a roster problem, not an identity ambiguity: both rows describe
    # the same machine, so refusing here would block a sweep over a harmless duplicate.
    # Render keys by probe index so the later row cannot overwrite the earlier verdict.
    calls = {"n": 0}

    def _run(argv, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeCompleted(stdout="cli=claude present=1 path=/usr/bin/claude\n")
        return FakeCompleted(stderr="No route to host", returncode=255)

    result = observe(
        hosts=[linux("podium"), linux("podium")],
        catalogue=SMALL_CATALOGUE[:1],
        runner=_run,
        now=NOW,
    )

    assert result.host_count == 2
    table = render(result, catalogue=SMALL_CATALOGUE[:1])
    rows = [ln for ln in table.splitlines() if ln.startswith("podium")]
    assert len(rows) == 2
    assert "yes" in rows[0]
    assert "?" in rows[1]


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


def test_render_reads_the_descriptor_stream_and_does_not_re_derive_it():
    stdout = "cli=claude present=1 path=/usr/bin/claude\ncli=ollama present=0 path=\n"
    observation = observe(
        hosts=[linux("podium")],
        catalogue=SMALL_CATALOGUE,
        runner=runner_for(stdout=stdout),
        now=NOW,
    )

    # Rewrite the stream so it disagrees with the probes. A renderer that re-derives from
    # observation.probes would still print "yes" and quietly contradict its own descriptors.
    observation.descriptors = descriptors_for_probe(
        HostCliProbe(host="podium", reachable=False, unreachable_reason="rewritten"),
        catalogue=SMALL_CATALOGUE,
        observed_at=NOW,
    )

    line = next(
        row
        for row in render(observation, catalogue=SMALL_CATALOGUE).splitlines()
        if row.startswith("podium")
    )
    assert "yes" not in line
    assert line.count("?") == len(SMALL_CATALOGUE)


def test_render_refuses_a_catalogue_the_observation_was_not_collected_under():
    stdout = "cli=claude present=1 path=/usr/bin/claude\ncli=ollama present=0 path=\n"
    observation = observe(
        hosts=[linux("podium")],
        catalogue=SMALL_CATALOGUE,
        runner=runner_for(stdout=stdout),
        now=NOW,
    )

    with pytest.raises(ValueError, match="next action"):
        render(observation, catalogue=SMALL_CATALOGUE[:1])


def test_render_refuses_a_stream_whose_host_blocks_were_reordered():
    # Reordering whole per-host blocks keeps the count and every CLI identity intact, so a check
    # on either alone waves it through and renders one host's capabilities under another's row.
    stdout = "cli=claude present=1 path=/usr/bin/claude\ncli=ollama present=0 path=\n"
    observation = observe(
        hosts=[linux("podium"), linux("eta")],
        catalogue=SMALL_CATALOGUE,
        runner=_split_runner(stdout),
        now=NOW,
    )
    stride = len(SMALL_CATALOGUE)
    observation.descriptors = observation.descriptors[stride:] + observation.descriptors[:stride]

    with pytest.raises(ValueError, match="next action"):
        render(observation, catalogue=SMALL_CATALOGUE)


def test_render_refuses_a_same_length_catalogue_that_is_not_the_one_observed():
    # The dangerous mismatch is the one a length check waves through: swap an entry and positional
    # pairing would file claude's verdict under docker's heading and report it as observed.
    stdout = "cli=claude present=1 path=/usr/bin/claude\ncli=ollama present=0 path=\n"
    observation = observe(
        hosts=[linux("podium")],
        catalogue=SMALL_CATALOGUE,
        runner=runner_for(stdout=stdout),
        now=NOW,
    )
    substituted = (poisoned_spec("docker"), SMALL_CATALOGUE[1])

    assert len(substituted) == len(SMALL_CATALOGUE)
    with pytest.raises(ValueError, match=r"is not 'bare-host\.podium\.docker'"):
        render(observation, catalogue=substituted)


def test_render_refuses_a_reordered_catalogue_of_the_same_length():
    stdout = "cli=claude present=1 path=/usr/bin/claude\ncli=ollama present=0 path=\n"
    observation = observe(
        hosts=[linux("podium")],
        catalogue=SMALL_CATALOGUE,
        runner=runner_for(stdout=stdout),
        now=NOW,
    )

    with pytest.raises(ValueError, match=r"is not 'bare-host\.podium\.ollama'"):
        render(observation, catalogue=tuple(reversed(SMALL_CATALOGUE)))


@pytest.mark.parametrize(
    "target",
    [
        "-oProxyCommand=touch /tmp/pwned",
        "-obatchmode=no",
        "--",
        "-l",
        "user@-oProxyCommand=x",
        "host\n-oProxyCommand=x",
        "host with space",
        "host;rm -rf /",
        "$(touch /tmp/pwned)",
    ],
)
def test_a_hostile_ssh_target_is_refused(target: str) -> None:
    """argv passing removes the shell; it does not remove ssh's own option parsing.

    A target of `-oProxyCommand=...` is not a host at all — it is an option that runs a command on
    the LOCAL machine before any connection is attempted. `--` does not save it either: ssh takes
    the first non-option word as the destination, so a leading-dash target still reaches option
    parsing. There is no escaping that makes an option not an option, so these are refused rather
    than quoted.
    """
    from shared.bare_host_capability_observer import _probe_argv

    with pytest.raises(ValueError, match="refusing ssh target"):
        _probe_argv("echo hi", target)


@pytest.mark.parametrize(
    "target", ["podium", "hapax-podium.local", "hapax@pi6", "10.0.0.4", "host_1"]
)
def test_an_ordinary_ssh_target_is_accepted(target: str) -> None:
    """The guard must not refuse the estate's real host forms — a refusal of everything would
    pass every hostile case above and observe nothing."""
    from shared.bare_host_capability_observer import _probe_argv

    argv = _probe_argv("echo hi", target)

    assert argv[0] == "ssh"
    assert target in argv


def test_a_hostile_host_name_never_reaches_the_runner_through_observe() -> None:
    """Through the PUBLIC entry point, with the roster as the attacker.

    Testing `_probe_argv` alone proves the validator works; it does not prove the validator is on
    the path a roster actually takes. All three reviewer families raised this shape independently,
    and the distinction is the one that matters: roster data is not operator input, and a private
    function that is never reached validates nothing.

    The runner records every argv it is handed, so the assertion is that the hostile name never
    became a process argument — not merely that some exception was raised somewhere.
    """
    from shared.bare_host_capability_observer import observe

    seen: list[list[str]] = []

    def recording_runner(argv, **kwargs):
        seen.append(list(argv))
        return FakeCompleted(stdout="", stderr="", returncode=0)

    hostile = dict(linux("-oProxyCommand=touch /tmp/pwned"))
    observation = observe(
        hosts=[hostile], catalogue=SMALL_CATALOGUE, runner=recording_runner, now=NOW
    )

    for argv in seen:
        assert not any(arg.startswith("-oProxyCommand") for arg in argv), (
            f"a hostile roster name reached the runner as {argv!r}"
        )
    # And the host is REPORTED unobservable rather than dropped or fatal. One hostile row must
    # not deny observation of every other host — that is a denial of service handed to whoever
    # can name a machine — and it must not vanish either, or a machine hides by being named badly.
    assert observation.host_count == 1
    assert observation.unreachable == ["-oProxyCommand=touch /tmp/pwned"]
    assert "refusing ssh target" in observation.probes[0].unreachable_reason


def test_one_hostile_row_does_not_stop_the_other_hosts_being_observed() -> None:
    """The denial-of-service shape, stated directly."""
    from shared.bare_host_capability_observer import observe

    observation = observe(
        hosts=[dict(linux("-oProxyCommand=x")), dict(linux("podium"))],
        catalogue=SMALL_CATALOGUE,
        runner=runner_for(stdout="cli=ollama present=1 path=/usr/bin/ollama\n"),
        now=NOW,
    )

    assert observation.host_count == 2
    assert observation.reachable_count == 1, "the well-named host must still have been probed"


# --- L4 receipt landing -----------------------------------------------------------------------


def test_receipts_cover_every_descriptor_and_keep_absent_as_a_row():
    observation = observe(
        hosts=[linux("podium")],
        catalogue=SMALL_CATALOGUE,
        runner=runner_for(
            stdout="cli=claude present=1 path=/usr/bin/claude\ncli=ollama present=0 path=\n"
        ),
        now=NOW,
    )

    receipts = receipts_for_observation(observation, catalogue=SMALL_CATALOGUE)

    assert len(receipts) == len(observation.descriptors)
    by_cli = {r.cli: r for r in receipts}
    assert by_cli["claude"].outcome == "observed"
    assert by_cli["claude"].observed_at == NOW
    assert by_cli["ollama"].outcome == "absent"
    assert by_cli["ollama"].observed_at is None
    assert by_cli["ollama"].evidence_refs
    assert all(r.demand_eligible is False for r in receipts)
    assert all(r.receipt_class == OBSERVATION_RECEIPT_CLASS for r in receipts)


def test_writer_lands_under_the_subdir_and_does_not_break_the_route_overlay(tmp_path):
    observation = observe(
        hosts=[linux("podium"), linux("eta")],
        catalogue=SMALL_CATALOGUE,
        runner=_split_runner(
            "cli=claude present=1 path=/usr/bin/claude\ncli=ollama present=0 path=\n"
        ),
        now=NOW,
    )

    written = write_bare_host_cli_probe_receipts(
        observation, receipt_dir=tmp_path, catalogue=SMALL_CATALOGUE
    )

    assert written
    assert all(path.parent.name == BARE_HOST_CLI_RECEIPT_SUBDIR for path in written)
    assert list(tmp_path.glob("*.json")) == []
    assert load_platform_capability_receipts(tmp_path, now=NOW) == {}
    loaded = BareHostCliProbeReceiptV1.model_validate_json(written[0].read_text(encoding="utf-8"))
    assert loaded.demand_eligible is False


def test_top_level_bare_host_json_breaks_the_route_overlay_loader(tmp_path):
    observation = observe(
        hosts=[linux("podium")],
        catalogue=SMALL_CATALOGUE[:1],
        runner=runner_for(stdout="cli=claude present=1 path=/usr/bin/claude\n"),
        now=NOW,
    )
    receipts = receipts_for_observation(observation, catalogue=SMALL_CATALOGUE[:1])
    poison = tmp_path / "bare-host.podium.claude.json"
    poison.write_text(receipts[0].model_dump_json(), encoding="utf-8")

    with pytest.raises(PlatformCapabilityReceiptError):
        load_platform_capability_receipts(tmp_path, now=NOW)


def test_loaded_receipts_rebuild_as_non_supply_descriptors(tmp_path):
    observation = observe(
        hosts=[linux("podium")],
        catalogue=SMALL_CATALOGUE,
        runner=runner_for(
            stdout="cli=claude present=1 path=/usr/bin/claude\ncli=ollama present=0 path=\n"
        ),
        now=NOW,
    )
    write_bare_host_cli_probe_receipts(observation, receipt_dir=tmp_path, catalogue=SMALL_CATALOGUE)

    loaded = load_bare_host_cli_probe_receipts(tmp_path)
    rebuilt = descriptors_from_bare_host_receipts(loaded, catalogue=SMALL_CATALOGUE)

    assert {row.shape_id for row in rebuilt} == {d.shape_id for d in observation.descriptors}
    assert all(row.demand_eligible is False for row in rebuilt)
    assert all(row.route_ids == [] for row in rebuilt)
    absent = next(row for row in rebuilt if row.shape_id.endswith(".ollama"))
    assert absent.observed_at is None
    assert any(reason.startswith(ABSENT_REASON_PREFIX) for reason in absent.blocked_reasons)
