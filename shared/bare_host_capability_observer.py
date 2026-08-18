"""Observe which capability *shapes* exist on a bare host, and render an absent CLI as absent.

``shared/estate_host_inventory`` (PR #4561) built the transport: a tailnet-measured roster, a
per-host read-only SSH probe, and the rule that an unreachable host stays in the result as a row
rather than vanishing. What it observes is host *hardware* -- cpus, memory, GPUs, video devices.
Those are ``R1.2-host-invariants-registry`` facts. Nothing turned them into capability records.

This module is ``R3.1-bare-host-probe-observer``: it reuses that roster, probes for the presence of
capability-bearing CLIs, and emits ``CapabilityShapeDescriptor`` rows -- the evidence-only record
the registry already defines. It folds into #4561 rather than duplicating it.

Three rules carry the weight here, and only the first is obvious:

* **Presence is evidence of a shape, never supply.** ``CapabilityShapeDescriptor``'s own
  ``_omitted_shape_is_not_supply`` validator refuses ``demand_eligible`` and refuses ``route_ids``;
  every row this module emits is ``evidence_only`` with a ``read_only`` ceiling. An installed
  ``claude`` binary means a shape exists on a host. It is not a route, not capacity, and not a
  score. That is ``R3.8-zero-asserted-scores-from-birth``.

* **An absent CLI is a row, not an omission.** Omission reads as "not applicable" and is
  indistinguishable from "never asked". An absent CLI emits a descriptor with
  ``freshness_state=missing`` and a ``cli_absent_on_host:`` blocker.

* **"Absent" and "not observable" are different findings and must not collapse.** A host that
  answered "no such binary" produced a measurement; an unreachable host produced nothing. Both are
  ``missing`` -- the freshness enum has no third value -- so the distinction is carried where it
  stays machine-checkable: an absent row has a negative-probe ``evidence_refs`` entry and a
  ``cli_absent_on_host:`` blocker, an unobservable row has empty ``evidence_refs`` and a
  ``host_unreachable:`` blocker. Read that distinction through :func:`observation_outcome`, never
  by re-parsing the strings at each call site.

Nothing this module runs on a remote host mutates it: the payload is ``command -v`` and nothing
else. One local write is possible and is not hidden -- ``StrictHostKeyChecking=accept-new`` will
append a first-contact key to the caller's ``known_hosts``. That is the transport's setting,
inherited deliberately (prompting would hang a headless sweep), but "read-only throughout" would
have been false, so it is stated rather than claimed away.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from shared.estate_host_inventory import (
    SSH_TIMEOUT_SECONDS,
    InventoryUnavailable,
    tailnet_hosts,
)
from shared.platform_capability_registry import (
    AuthorityCeiling,
    CapabilityShapeClass,
    CapabilityShapeDescriptor,
    CapabilityShapeFreshnessState,
    CapabilityShapeState,
)

__all__ = [
    "ABSENT_REASON_PREFIX",
    "CLI_CATALOGUE",
    "OBSERVATION_RECEIPT_CLASS",
    "STALE_AFTER",
    "UNREACHABLE_REASON_PREFIX",
    "NOT_PROBED_REASON_PREFIX",
    "BareHostObservation",
    "CliShapeSpec",
    "HostCliProbe",
    "InventoryUnavailable",
    "descriptors_for_probe",
    "observation_outcome",
    "observe",
    "probe_host_clis",
    "render",
]

#: The receipt class every row from this module carries. ``CapabilityShapeDescriptor`` requires an
#: ``observation_receipt_class`` on every ``evidence_only`` shape, so an observation can always be
#: traced back to the instrument that made it.
OBSERVATION_RECEIPT_CLASS = "BareHostCliProbeReceiptV1"

#: Blocker prefixes. These are the machine-checkable carrier of the absent/not-observable split;
#: :func:`observation_outcome` is the only supported reader.
ABSENT_REASON_PREFIX = "cli_absent_on_host:"
UNREACHABLE_REASON_PREFIX = "host_unreachable:"
NOT_PROBED_REASON_PREFIX = "host_not_probed:"

#: Presence changes on the timescale of a package install, not a request. A day is long enough that
#: the row is not permanently re-probing itself and short enough that a stale row is visibly stale.
STALE_AFTER = "1d"

#: Catalogue entries are interpolated into a remote shell command. Anything outside this pattern is
#: rejected by :func:`_probe_payload` -- the one place a name reaches a shell, so it holds for a
#: caller-supplied catalogue too, which an import-time check over ``CLI_CATALOGUE`` would not.
_SAFE_CLI_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

#: ``[user@]host``, and the FIRST character of each part may not be a dash. That leading-character
#: rule is the whole point: ssh reads any argument beginning with ``-`` as an option, and
#: ``-oProxyCommand=...`` runs a command on the LOCAL machine before a connection is opened.
#: Matched with ``fullmatch`` so a trailing newline cannot smuggle a second word past the end.
_SAFE_SSH_TARGET = re.compile(r"(?:[A-Za-z0-9_][A-Za-z0-9._-]*@)?[A-Za-z0-9_][A-Za-z0-9._-]*")

#: ``shape_id`` must satisfy the registry's own pattern; host names from a tailnet do not.
_ID_UNSAFE = re.compile(r"[^a-z0-9._-]+")


@dataclass(frozen=True)
class CliShapeSpec:
    """One capability-bearing CLI worth asking a host about.

    This catalogue is a list of *questions*, not a claim about what any host has. A CLI missing
    from it is genuinely never asked about -- which is why the catalogue, not the result, is the
    place to argue about coverage.
    """

    cli: str
    shape_class: CapabilityShapeClass
    carrier_family: str
    summary: str
    harness_shape: str
    resource_semantics: tuple[str, ...]


CLI_CATALOGUE: tuple[CliShapeSpec, ...] = (
    CliShapeSpec(
        cli="claude",
        shape_class=CapabilityShapeClass.ORCHESTRATOR,
        carrier_family="anthropic_cli_harness",
        summary="Claude Code CLI harness present on host.",
        harness_shape="interactive-and-headless-agent-cli",
        resource_semantics=("provider-subscription-or-api-quota",),
    ),
    CliShapeSpec(
        cli="codex",
        shape_class=CapabilityShapeClass.ORCHESTRATOR,
        carrier_family="openai_cli_harness",
        summary="Codex CLI harness present on host.",
        harness_shape="interactive-and-headless-agent-cli",
        resource_semantics=("provider-subscription-or-api-quota",),
    ),
    CliShapeSpec(
        cli="agy",
        shape_class=CapabilityShapeClass.ORCHESTRATOR,
        carrier_family="agy_cli_harness",
        summary="agy CLI harness present on host.",
        harness_shape="review-oriented-agent-cli",
        resource_semantics=("provider-subscription-or-api-quota",),
    ),
    CliShapeSpec(
        cli="ollama",
        shape_class=CapabilityShapeClass.LOCAL_COMPUTE,
        carrier_family="local_inference_runtime",
        summary="Ollama local inference runtime present on host.",
        harness_shape="local-model-server-cli",
        resource_semantics=("local-gpu-vram", "local-cpu"),
    ),
    CliShapeSpec(
        cli="nvidia-smi",
        shape_class=CapabilityShapeClass.LOCAL_COMPUTE,
        carrier_family="nvidia_driver_tooling",
        summary="NVIDIA driver tooling present on host.",
        harness_shape="gpu-introspection-cli",
        resource_semantics=("local-gpu-vram",),
    ),
    CliShapeSpec(
        cli="docker",
        shape_class=CapabilityShapeClass.LOCAL_COMPUTE,
        carrier_family="container_runtime",
        summary="Container runtime CLI present on host.",
        harness_shape="container-lifecycle-cli",
        resource_semantics=("local-cpu", "local-memory"),
    ),
    CliShapeSpec(
        cli="gh",
        shape_class=CapabilityShapeClass.PUBLICATION_BUS,
        carrier_family="github_forge",
        summary="GitHub CLI present on host.",
        harness_shape="forge-api-cli",
        resource_semantics=("forge-api-rate-limit",),
    ),
    CliShapeSpec(
        cli="ffmpeg",
        shape_class=CapabilityShapeClass.CCTV_RUNNER,
        carrier_family="media_transcode",
        summary="ffmpeg media pipeline present on host.",
        harness_shape="media-transcode-cli",
        resource_semantics=("local-cpu", "local-gpu-encode"),
    ),
    CliShapeSpec(
        cli="gst-launch-1.0",
        shape_class=CapabilityShapeClass.CCTV_RUNNER,
        carrier_family="gstreamer_pipeline",
        summary="GStreamer pipeline tooling present on host.",
        harness_shape="live-media-pipeline-cli",
        resource_semantics=("local-cpu", "local-gpu-encode", "capture-devices"),
    ),
    CliShapeSpec(
        cli="uv",
        shape_class=CapabilityShapeClass.LOCAL_COMPUTE,
        carrier_family="python_toolchain",
        summary="uv Python toolchain present on host.",
        harness_shape="python-env-and-runner-cli",
        resource_semantics=("local-cpu",),
    ),
)


@dataclass
class HostCliProbe:
    """One host's answer. ``reachable=False`` rows are kept: absence of data is the datum."""

    host: str
    reachable: bool = False
    skipped: bool = False
    unreachable_reason: str = ""
    present: dict[str, str] = field(default_factory=dict)
    absent: list[str] = field(default_factory=list)
    probed_at: str = ""


@dataclass
class BareHostObservation:
    """Descriptors for every (host, catalogue entry) pair. Nothing is dropped."""

    probed_at: str
    host_count: int
    reachable_count: int
    unreachable: list[str]
    probes: list[HostCliProbe]
    descriptors: list[CapabilityShapeDescriptor]


def _probe_payload(catalogue: tuple[CliShapeSpec, ...]) -> str:
    """A POSIX payload that reports every catalogue entry, present or not.

    Every entry is echoed on its own line with an explicit ``present=`` verdict. A payload that
    only echoed what it found could not distinguish "not installed" from "the probe stopped early",
    which is the same conflation this module exists to prevent, one layer down.

    Names are validated *here* rather than where ``CLI_CATALOGUE`` is defined, because every probe
    path funnels through this function and callers may supply their own catalogue. Checking the
    module constant at import would have left the caller-supplied path unguarded while looking
    guarded -- and a second check at the definition site would be a second thing to disagree with
    this one.
    """
    for spec in catalogue:
        # fullmatch, not match: Python's ``$`` also matches just before a final newline, so
        # ``match`` would accept "gh\n" and interpolate the newline straight into the for-list.
        if not _SAFE_CLI_NAME.fullmatch(spec.cli):
            raise ValueError(
                f"unsafe CLI name in catalogue: {spec.cli!r}; this name is interpolated into a "
                "remote shell command. Next action: restrict the entry to letters, digits, dot, "
                "dash and underscore."
            )
    names = " ".join(spec.cli for spec in catalogue)
    if not names:
        # An empty for-list is a shell syntax error (`for c in ; do`). That would come
        # back as a non-zero exit with no stdout and be filed as unreachable — the
        # exact "not asked" vs "not reachable" collapse this module exists to prevent.
        return "true\n"
    return (
        f"for c in {names}; do\n"
        '  p="$(command -v "$c" 2>/dev/null || true)"\n'
        '  if [ -n "$p" ]; then echo "cli=$c present=1 path=$p"; '
        'else echo "cli=$c present=0 path="; fi\n'
        "done\n"
    )


def _probe_argv(payload: str, target: str) -> list[str]:
    """Local or remote argv for the payload.

    The remote form wraps in ``bash -c`` rather than handing the payload to ssh bare. ssh runs the
    remote *login* shell, and at least one host on this estate logs in to fish, where a POSIX
    ``for ... do ... done`` is a syntax error -- a fish host would report a probe failure that
    looks exactly like an unreachable host.
    """
    if not target:
        return ["bash", "-c", payload]
    # A HOST NAME IS AN ARGUMENT, AND ssh READS ARGUMENTS AS OPTIONS.
    #
    # argv passing removes the shell from this call, which is why the payload is safe. It does
    # nothing about ssh's own parsing: a target of `-oProxyCommand=...` is not a host at all, it
    # is an option that runs a command locally before any connection is attempted. `--` does not
    # help either, because ssh takes the first non-option word as the destination and the rest as
    # the remote command, so a leading-dash target still reaches option parsing.
    #
    # The validation is therefore on the target itself, and it is a whitelist: hosts on this
    # estate are names, IPv4 literals, or user@ forms of the same. Anything else is refused
    # rather than escaped, because there is no escaping that makes an option not an option.
    if not _SAFE_SSH_TARGET.fullmatch(target):
        raise ValueError(
            f"refusing ssh target {target!r}: expected [user@]host with only letters, digits, "
            "dot, dash or underscore, never a leading dash. A target that starts with '-' is "
            "read by ssh as an option, and options such as -oProxyCommand run commands. Next: "
            "pass the host's name or address"
        )
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        # Half the overall budget, matching the transport in estate_host_inventory: connecting and
        # running must both fit, and a host that cannot even connect in half the window is a
        # finding worth returning early rather than waiting out.
        f"ConnectTimeout={SSH_TIMEOUT_SECONDS // 2}",
        "-o",
        "StrictHostKeyChecking=accept-new",
        target,
        f"bash -c {shlex.quote(payload)}",
    ]


def _parse_probe(text: str, catalogue: tuple[CliShapeSpec, ...], probe: HostCliProbe) -> None:
    """Read verdicts, and read *only* verdicts.

    Absence is established by exactly one thing: an explicit ``present=0``. A missing or
    unrecognised ``present`` field, or a ``present=1`` with no path, is a malformed answer, and a
    malformed answer is not a measurement -- it leaves the entry unanswered, which surfaces as
    ``not_observable``. Folding those into "absent" would manufacture the very measurement this
    module refuses to invent.
    """
    known = {spec.cli for spec in catalogue}
    answered: dict[str, str | None] = {}
    for line in text.splitlines():
        fields = dict(part.split("=", 1) for part in line.strip().split(" ", 2) if "=" in part)
        cli = fields.get("cli", "")
        if cli not in known:
            continue
        verdict = fields.get("present")
        path = (fields.get("path") or "").strip()
        if verdict == "1" and path:
            answered[cli] = path
        elif verdict == "0":
            answered[cli] = None

    for spec in catalogue:
        if spec.cli not in answered:
            # The host answered, but not intelligibly about this entry. Silently treating it as
            # absent would manufacture a measurement that was never made.
            continue
        path = answered[spec.cli]
        if path is None:
            probe.absent.append(spec.cli)
        else:
            probe.present[spec.cli] = path


def probe_host_clis(
    row: dict[str, object],
    *,
    catalogue: tuple[CliShapeSpec, ...] = CLI_CATALOGUE,
    runner: object = None,
    self_name: str = "",
    now: datetime | None = None,
) -> HostCliProbe:
    """Ask one host which catalogue CLIs it has. Never raises: unreachable is a populated row."""
    name = str(row.get("name") or "")
    probe = HostCliProbe(host=name, probed_at=_stamp(now))
    if not name:
        probe.skipped = True
        probe.unreachable_reason = (
            "not probed: roster row has no host name. Next action: fix the roster row"
        )
        return probe

    if str(row.get("os") or "") != "linux":
        probe.skipped = True
        probe.unreachable_reason = (
            f"not probed: os={row.get('os') or 'unknown'!s}; the payload is POSIX shell. "
            "Next action: if this host does host capabilities, add an os-specific payload rather "
            "than dropping the row"
        )
        return probe

    if not catalogue:
        # No questions to ask is not a transport failure and is not an OS skip.
        probe.reachable = True
        return probe

    payload = _probe_payload(catalogue)
    try:
        argv = _probe_argv(payload, "" if name == self_name else name)
    except ValueError as exc:
        # A REFUSED NAME IS A ROW, NOT AN ABORTED SWEEP.
        #
        # This function's contract above is "never raises: unreachable is a populated row", and
        # the roster is data from a tailnet rather than operator input. Letting the target guard
        # propagate would mean one hostile or malformed row denies observation of every other
        # host — a denial of service handed to whoever can name a machine. It also contradicts
        # the rule the rest of the module runs on: an unanswered entry renders as unanswered,
        # never as an omission, because omissions read as "nothing there".
        probe.unreachable_reason = (
            f"not probed: {exc}. The host stays in the inventory as unobserved rather than being "
            "dropped, so a machine cannot hide by carrying a name that cannot be probed"
        )
        return probe
    run = runner if callable(runner) else subprocess.run
    try:
        result = run(
            argv,
            capture_output=True,
            text=True,
            timeout=SSH_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        probe.unreachable_reason = (
            f"{type(exc).__name__}: {exc}; next action: check `tailscale status` and "
            f"`ssh {name} true`"
        )
        return probe

    if result.returncode != 0 and not result.stdout.strip():
        detail = (result.stderr or "").strip().splitlines()
        failure = detail[-1][:160] if detail else f"exit {result.returncode}"
        probe.unreachable_reason = f"{failure}; next action: `ssh {name} true` to reproduce"
        return probe

    _parse_probe(result.stdout, catalogue, probe)
    probe.reachable = bool(probe.present or probe.absent)
    if not probe.reachable:
        probe.unreachable_reason = (
            "probe returned no recognisable cli lines (a login banner or a non-POSIX login shell "
            f"will do this); next action: run `ssh {name} bash -c 'command -v uv'` by hand"
        )
    return probe


def _stamp(now: datetime | None) -> str:
    moment = now if now is not None else datetime.now(UTC)
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _shape_id(host: str, cli: str) -> str:
    """The registry's ``shape_id`` pattern is narrower than a tailnet host name, so this slugs.

    Slugging is lossy -- ``Pi A`` and ``Pi-A`` both land on ``pi-a`` -- which means two distinct
    hosts can produce one identity and have their evidence merged under it. Rather than paper over
    that with a disambiguating suffix, :func:`_refuse_colliding_hosts` refuses a roster where it
    happens: silently attributing one host's capabilities to another is the exact failure this
    module exists to prevent, and a merged row is indistinguishable from a correct one.
    """
    slug = _ID_UNSAFE.sub("-", f"bare-host.{host}.{cli}".lower())
    return slug.lstrip("-._") or "bare-host.unnamed"


def _refuse_colliding_hosts(hosts: list[str]) -> None:
    """Refuse a roster whose names are distinct but whose slugs are not."""
    seen: dict[str, str] = {}
    for host in hosts:
        slug = _shape_id(host, "x")
        first = seen.setdefault(slug, host)
        if first != host:
            raise ValueError(
                f"hosts {first!r} and {host!r} both slug to {slug!r}, so their capability "
                "observations would merge under one identity. Next action: rename one host on the "
                "tailnet, or probe them in separate runs"
            )


def _descriptor(
    spec: CliShapeSpec,
    *,
    host: str,
    observed_at: datetime | None,
    evidence_refs: list[str],
    blocked_reasons: list[str],
    freshness: CapabilityShapeFreshnessState,
    failure_classes: list[str],
    remediation_refs: list[str],
) -> CapabilityShapeDescriptor:
    return CapabilityShapeDescriptor(
        shape_id=_shape_id(host, spec.cli),
        shape_class=spec.shape_class,
        carrier_family=spec.carrier_family,
        summary=f"{spec.summary} host={host}",
        harness_shape=spec.harness_shape,
        # Evidence-only with a read-only ceiling is what makes this a sighting rather than a
        # supply claim; the descriptor's own validator enforces the pairing.
        authority_ceiling=AuthorityCeiling.READ_ONLY,
        shape_state=CapabilityShapeState.EVIDENCE_ONLY,
        demand_eligible=False,
        route_ids=[],
        resource_semantics=list(spec.resource_semantics),
        # Finding a binary grants no spend authority. Saying so on every row keeps a later reader
        # from inferring one from the carrier family.
        spend_semantics=["no-spend-authority-observed"],
        observability=[f"local_probe:command-v:{spec.cli}"],
        failure_classes=failure_classes,
        measurement_plan_refs=[f"require:measured-probe-post-consent:{spec.cli}"],
        remediation_refs=remediation_refs,
        # Evidence-only shapes may not emit surface deltas: an observation must not reach the
        # dispatch hold channel.
        surface_delta_signal=None,
        observation_receipt_class=OBSERVATION_RECEIPT_CLASS,
        observed_at=observed_at,
        stale_after=STALE_AFTER,
        freshness_state=freshness,
        evidence_refs=evidence_refs,
        blocked_reasons=blocked_reasons,
    )


def descriptors_for_probe(
    probe: HostCliProbe,
    *,
    catalogue: tuple[CliShapeSpec, ...] = CLI_CATALOGUE,
    observed_at: datetime | None = None,
) -> list[CapabilityShapeDescriptor]:
    """Every catalogue entry becomes exactly one descriptor, whatever the host said."""
    stamp = observed_at if observed_at is not None else datetime.now(UTC)
    rows: list[CapabilityShapeDescriptor] = []
    for spec in catalogue:
        if probe.skipped:
            rows.append(
                _descriptor(
                    spec,
                    host=probe.host,
                    observed_at=None,
                    evidence_refs=[],
                    blocked_reasons=[
                        f"{NOT_PROBED_REASON_PREFIX}{probe.host}:"
                        f"{probe.unreachable_reason or 'unknown'}"
                    ],
                    freshness=CapabilityShapeFreshnessState.MISSING,
                    failure_classes=["host_not_probed"],
                    remediation_refs=[f"require:os-specific-payload:{probe.host}"],
                )
            )
            continue
        if not probe.reachable:
            rows.append(
                _descriptor(
                    spec,
                    host=probe.host,
                    # No probe ran, so nothing was observed and there is no evidence to cite.
                    # The empty evidence_refs IS the distinction from an absent CLI.
                    observed_at=None,
                    evidence_refs=[],
                    blocked_reasons=[
                        f"{UNREACHABLE_REASON_PREFIX}{probe.host}:"
                        f"{probe.unreachable_reason or 'unknown'}"
                    ],
                    freshness=CapabilityShapeFreshnessState.MISSING,
                    failure_classes=["host_unreachable"],
                    remediation_refs=[f"require:reach-host:{probe.host}"],
                )
            )
            continue

        path = probe.present.get(spec.cli)
        if path:
            rows.append(
                _descriptor(
                    spec,
                    host=probe.host,
                    observed_at=stamp,
                    evidence_refs=[f"local_probe:{probe.host}:command -v {spec.cli} -> {path}"],
                    # An observed row still carries a blocker: presence is not throughput, and
                    # nothing downstream may read this as measured supply.
                    blocked_reasons=["presence_observed_without_measured_supply"],
                    freshness=CapabilityShapeFreshnessState.FRESH,
                    failure_classes=["presence_without_measured_throughput"],
                    remediation_refs=[f"require:capability-intake-stage0:{spec.cli}"],
                )
            )
            continue

        if spec.cli in probe.absent:
            rows.append(
                _descriptor(
                    spec,
                    host=probe.host,
                    # The probe ran and found nothing. No capability was observed, so observed_at
                    # stays None -- but the negative probe is real and is cited as evidence.
                    observed_at=None,
                    evidence_refs=[f"local_probe:{probe.host}:command -v {spec.cli} -> not-found"],
                    blocked_reasons=[f"{ABSENT_REASON_PREFIX}{probe.host}:{spec.cli}"],
                    freshness=CapabilityShapeFreshnessState.MISSING,
                    failure_classes=["cli_absent"],
                    remediation_refs=[f"require:install-or-intake:{spec.cli}"],
                )
            )
            continue

        # Reachable host that never answered about this entry: not present, not absent, not asked.
        rows.append(
            _descriptor(
                spec,
                host=probe.host,
                observed_at=None,
                evidence_refs=[],
                blocked_reasons=[
                    f"{UNREACHABLE_REASON_PREFIX}{probe.host}:probe returned no verdict "
                    f"for {spec.cli}"
                ],
                freshness=CapabilityShapeFreshnessState.MISSING,
                failure_classes=["probe_incomplete"],
                remediation_refs=[f"require:reprobe-host:{probe.host}"],
            )
        )
    return rows


def observation_outcome(
    descriptor: CapabilityShapeDescriptor,
) -> Literal["observed", "absent", "not_observable"]:
    """The single supported reader of the absent/not-observable split.

    ``freshness_state`` is ``missing`` for both a CLI the host said it does not have and a CLI on a
    host that never answered. Those are different findings -- "not found" versus "not looked at" --
    and the enum has no third value, so the split lives in the blockers. Every consumer reads it
    here so the parsing exists once.
    """
    if descriptor.observed_at is not None:
        return "observed"
    if any(reason.startswith(ABSENT_REASON_PREFIX) for reason in descriptor.blocked_reasons):
        return "absent"
    return "not_observable"


def observe(
    *,
    hosts: list[dict[str, object]] | None = None,
    catalogue: tuple[CliShapeSpec, ...] = CLI_CATALOGUE,
    runner: object = None,
    self_name: str = "",
    now: datetime | None = None,
) -> BareHostObservation:
    """Observe capability shapes across the estate.

    The roster is measured, never declared: with ``hosts`` omitted this raises
    :class:`InventoryUnavailable` rather than falling back to a hardcoded list, because an assumed
    roster silently omits hosts and returns an inventory that reads complete.
    """
    rows = hosts if hosts is not None else tailnet_hosts()
    _refuse_colliding_hosts(
        [str(row.get("name") or "") for row in rows if str(row.get("name") or "")]
    )
    stamp_dt = now if now is not None else datetime.now(UTC)
    probes = [
        probe_host_clis(row, catalogue=catalogue, runner=runner, self_name=self_name, now=stamp_dt)
        for row in rows
    ]
    descriptors: list[CapabilityShapeDescriptor] = []
    for probe in probes:
        descriptors.extend(descriptors_for_probe(probe, catalogue=catalogue, observed_at=stamp_dt))
    return BareHostObservation(
        probed_at=_stamp(stamp_dt),
        host_count=len(probes),
        reachable_count=sum(1 for p in probes if p.reachable),
        unreachable=[p.host for p in probes if not p.reachable and not p.skipped],
        probes=probes,
        descriptors=descriptors,
    )


_OUTCOME_MARK = {"observed": "yes", "absent": "no", "not_observable": "?"}


def render(
    observation: BareHostObservation,
    *,
    catalogue: tuple[CliShapeSpec, ...] = CLI_CATALOGUE,
) -> str:
    """Human table. An unobserved cell renders as ``?`` and never as ``no``.

    Reads ``observation.descriptors`` -- the stream itself, not a fresh re-derivation from the
    probes. Re-deriving would let a loaded or transformed observation render a table that
    contradicts its own descriptors while the docstring promised it could not.
    """
    names = [spec.cli for spec in catalogue]
    hosts = [p.host for p in observation.probes]
    stride = len(catalogue)
    if len(observation.descriptors) != len(hosts) * stride:
        raise ValueError(
            "observation carries "
            f"{len(observation.descriptors)} descriptors for {len(hosts)} hosts x {stride} "
            "catalogue entries; next action: render with the catalogue the observation was "
            "collected under"
        )

    grid: dict[tuple[str, str], str] = {}
    for host_index, host in enumerate(hosts):
        block = observation.descriptors[host_index * stride : (host_index + 1) * stride]
        for spec, descriptor in zip(catalogue, block, strict=True):
            # Counting descriptors is not enough. Positional pairing would otherwise file one
            # cell's verdict under another's heading -- reporting a capability as observed on the
            # strength of a different capability, or one host's answer under another host's row.
            # A substituted catalogue and a reordered host block are the same failure, so they get
            # the same check: shape_id encodes both identities, and it is built by the same
            # function that built the descriptor, so one comparison settles both.
            expected = _shape_id(host, spec.cli)
            if descriptor.shape_id != expected:
                raise ValueError(
                    f"descriptor {descriptor.shape_id!r} is not {expected!r}; next action: render "
                    "with the catalogue and probe order the observation was collected under"
                )
            grid[(host_index, spec.cli)] = _OUTCOME_MARK[observation_outcome(descriptor)]

    width = max((len(h) for h in hosts), default=4) + 1
    lines = [
        f"bare-host capability shapes — {observation.probed_at}",
        f"{observation.reachable_count}/{observation.host_count} hosts answered "
        "(yes=observed, no=absent, ?=not observable)",
        "",
        f"{'HOST':<{width}}" + "".join(f"{n[:9]:>10}" for n in names),
    ]
    for host_index, host in enumerate(hosts):
        lines.append(
            f"{host:<{width}}"
            + "".join(f"{grid.get((host_index, n), '?'):>10}" for n in names)
        )
    return "\n".join(lines)
