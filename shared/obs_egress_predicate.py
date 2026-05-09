"""Read-only OBS audio egress predicate.

This module does not connect to OBS, mutate PipeWire, or read secrets. It
classifies already-collected evidence so downstream health code can distinguish
upstream silence, OBS detachment, wrong source binding, unavailable OBS API
capability, public egress uncertainty, health predicate drift, and analyzer
internal failures without turning any repair attempt into proof of health.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

EXPECTED_OBS_SOURCE = "hapax-obs-broadcast-remap"
EXPECTED_OBS_SOURCE_CAPTURE = f"{EXPECTED_OBS_SOURCE}:capture"
EXPECTED_REMAP_CAPTURE = "hapax-obs-broadcast-remap-capture:input"
EXPECTED_BROADCAST_NORMALIZED = "hapax-broadcast-normalized:capture"
DEFAULT_SIGNAL_RMS_FLOOR_DBFS = -55.0
DEFAULT_SIGNAL_SILENCE_RATIO_MAX = 0.85

_SECRET_KEY_NAMES = {
    "auth",
    "authentication",
    "challenge",
    "key",
    "password",
    "salt",
    "secret",
    "token",
}
_SECRET_KEY_SUFFIXES = ("_auth", "_authentication", "_key", "_password", "_secret", "_token")


class ObsEgressState(StrEnum):
    UNKNOWN = "unknown"
    UPSTREAM_SILENT = "upstream_silent"
    REMAP_MISSING = "remap_missing"
    OBS_ABSENT = "obs_absent"
    OBS_DETACHED = "obs_detached"
    OBS_WRONG_SOURCE = "obs_wrong_source"
    OBS_BOUND_UNVERIFIED = "obs_bound_unverified"
    PUBLIC_EGRESS_UNKNOWN = "public_egress_unknown"
    HEALTH_PREDICATE_DRIFT = "health_predicate_drift"
    ANALYZER_INTERNAL_FAILURE = "analyzer_internal_failure"
    HEALTHY = "healthy"


class HealthImpact(StrEnum):
    SAFE = "safe"
    DEGRADED = "degraded"
    BLOCKING = "blocking"


class EvidenceStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    UNKNOWN = "unknown"


class PipeWireLinkEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    available: bool
    links: frozenset[tuple[str, str]] = Field(default_factory=frozenset)
    ports: frozenset[str] = Field(default_factory=frozenset)
    error: str | None = None


class ObsApiEvidence(BaseModel):
    """Sanitized, caller-supplied OBS WebSocket read-only evidence."""

    model_config = ConfigDict(frozen=True)

    available: bool = False
    input_present: bool | None = None
    input_name: str | None = None
    input_kind: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    muted: bool | None = None
    volume_mul: float | None = None
    audio_tracks: dict[str, bool] | None = None
    stream_active: bool | None = None
    stream_reconnecting: bool | None = None
    error: str | None = None


class SignalEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    available: bool = False
    rms_dbfs: float | None = None
    peak_dbfs: float | None = None
    silence_ratio: float | None = None
    checked_at: str | None = None
    max_age_s: float | None = None
    error: str | None = None

    def stale(self, now: float | None = None) -> bool:
        if self.checked_at is None or self.max_age_s is None:
            return False
        parsed = _parse_iso_epoch(self.checked_at)
        if parsed is None:
            return True
        current = time.time() if now is None else now
        return current - parsed > self.max_age_s

    def has_signal(
        self,
        *,
        rms_floor_dbfs: float = DEFAULT_SIGNAL_RMS_FLOOR_DBFS,
        silence_ratio_max: float = DEFAULT_SIGNAL_SILENCE_RATIO_MAX,
    ) -> bool | None:
        if not self.available or self.error:
            return None
        if self.rms_dbfs is None and self.silence_ratio is None:
            return None
        rms_ok = self.rms_dbfs is None or self.rms_dbfs >= rms_floor_dbfs
        silence_ok = self.silence_ratio is None or self.silence_ratio <= silence_ratio_max
        return rms_ok and silence_ok


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    status: EvidenceStatus
    message: str
    observed: dict[str, Any] = Field(default_factory=dict)
    timestamp: str | None = None
    max_age_s: float | None = None
    stale: bool = False


class ObsEgressPredicateResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: ObsEgressState
    health_impact: HealthImpact
    safe: bool
    remediation_allowed: bool
    checked_at: str
    freshness_s: float = 0.0
    reason_codes: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    capabilities: dict[str, bool] = Field(default_factory=dict)


def parse_pw_link_output(text: str | None, *, error: str | None = None) -> PipeWireLinkEvidence:
    """Parse `pw-link -l` text into directed `(source, target)` links."""

    if error is not None:
        return PipeWireLinkEvidence(available=False, error=error)
    if text is None:
        return PipeWireLinkEvidence(available=False, error="pw-link output missing")

    links: set[tuple[str, str]] = set()
    ports: set[str] = set()
    current: str | None = None
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        stripped = raw_line.strip()
        if not raw_line.startswith((" ", "\t")):
            current = stripped
            ports.add(stripped)
            continue
        if current is None:
            continue
        if stripped.startswith("|->"):
            target = stripped.removeprefix("|->").strip()
            if target:
                links.add((current, target))
                ports.add(target)
        elif stripped.startswith("|<-"):
            source = stripped.removeprefix("|<-").strip()
            if source:
                links.add((source, current))
                ports.add(source)

    return PipeWireLinkEvidence(available=True, links=frozenset(links), ports=frozenset(ports))


def sanitize_obs_payload(value: Any) -> Any:
    """Redact secret-bearing OBS payload fields before evidence storage."""

    if isinstance(value, Mapping):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_secret_key(key_text):
                clean[key_text] = "<redacted>"
            else:
                clean[key_text] = sanitize_obs_payload(item)
        return clean
    if isinstance(value, list):
        return [sanitize_obs_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_obs_payload(item) for item in value)
    return value


def classify_obs_egress(
    *,
    pipewire: PipeWireLinkEvidence,
    obs_api: ObsApiEvidence | None = None,
    remap_signal: SignalEvidence | None = None,
    upstream_signal: SignalEvidence | None = None,
    analyzer_failures: Sequence[str] = (),
    health_predicate_drift: Sequence[str] = (),
    now: float | None = None,
) -> ObsEgressPredicateResult:
    """Resolve the OBS egress state from non-mutating evidence."""

    current = time.time() if now is None else now
    checked_at = _iso_from_epoch(current)
    evidence: list[EvidenceRecord] = []
    reasons: list[str] = []
    capabilities = {
        "pipewire": pipewire.available,
        "obs_websocket": bool(obs_api and obs_api.available),
    }

    if analyzer_failures:
        evidence.append(
            _record(
                "analyzer",
                EvidenceStatus.FAIL,
                "analyzer loop reported internal failure",
                {"failures": list(analyzer_failures)},
            )
        )
        return _result(
            ObsEgressState.ANALYZER_INTERNAL_FAILURE,
            HealthImpact.BLOCKING,
            False,
            False,
            checked_at,
            ["analyzer_internal_failure"],
            evidence,
            capabilities,
        )

    if health_predicate_drift:
        evidence.append(
            _record(
                "health_predicates",
                EvidenceStatus.FAIL,
                "health predicates are stale or contradictory",
                {"drift": list(health_predicate_drift)},
            )
        )
        return _result(
            ObsEgressState.HEALTH_PREDICATE_DRIFT,
            HealthImpact.BLOCKING,
            False,
            False,
            checked_at,
            ["health_predicate_drift"],
            evidence,
            capabilities,
        )

    if not pipewire.available:
        evidence.append(
            _record(
                "pipewire",
                EvidenceStatus.UNKNOWN,
                "PipeWire link graph unavailable",
                {"error": pipewire.error},
            )
        )
        return _result(
            ObsEgressState.UNKNOWN,
            HealthImpact.BLOCKING,
            False,
            False,
            checked_at,
            ["pipewire_unavailable"],
            evidence,
            capabilities,
        )

    graph = _graph_status(pipewire.links, pipewire.ports)
    evidence.append(
        _record(
            "pipewire",
            EvidenceStatus.PASS if graph["remap_to_obs_complete"] else EvidenceStatus.FAIL,
            "PipeWire OBS egress links inspected",
            graph,
        )
    )

    if upstream_signal is not None:
        upstream_signal_state = _signal_record("upstream_signal", upstream_signal, current)
        evidence.append(upstream_signal_state)
        upstream_has_signal = upstream_signal.has_signal()
        if upstream_has_signal is False:
            return _result(
                ObsEgressState.UPSTREAM_SILENT,
                HealthImpact.BLOCKING,
                False,
                False,
                checked_at,
                ["upstream_silent"],
                evidence,
                capabilities,
            )

    if remap_signal is not None:
        remap_signal_state = _signal_record("remap_signal", remap_signal, current)
        evidence.append(remap_signal_state)
        remap_has_signal = remap_signal.has_signal()
        if remap_has_signal is False:
            return _result(
                ObsEgressState.UPSTREAM_SILENT,
                HealthImpact.BLOCKING,
                False,
                False,
                checked_at,
                ["remap_silent"],
                evidence,
                capabilities,
            )

    if not graph["remap_present"] or not graph["normalized_to_remap_complete"]:
        reasons = ["remap_missing"]
        if not graph["normalized_to_remap_complete"]:
            reasons.append("broadcast_normalized_to_remap_incomplete")
        return _result(
            ObsEgressState.REMAP_MISSING,
            HealthImpact.BLOCKING,
            False,
            False,
            checked_at,
            reasons,
            evidence,
            capabilities,
        )

    if not graph["obs_present"]:
        return _result(
            ObsEgressState.OBS_ABSENT,
            HealthImpact.BLOCKING,
            False,
            True,
            checked_at,
            ["obs_absent"],
            evidence,
            capabilities,
        )

    if graph["wrong_obs_sources"]:
        return _result(
            ObsEgressState.OBS_WRONG_SOURCE,
            HealthImpact.BLOCKING,
            False,
            True,
            checked_at,
            ["obs_wrong_source"],
            evidence,
            capabilities,
        )

    if not graph["remap_to_obs_complete"]:
        return _result(
            ObsEgressState.OBS_DETACHED,
            HealthImpact.BLOCKING,
            False,
            True,
            checked_at,
            ["obs_detached"],
            evidence,
            capabilities,
        )

    obs_api = obs_api or ObsApiEvidence()
    if not obs_api.available:
        evidence.append(
            _record(
                "obs_websocket",
                EvidenceStatus.UNKNOWN,
                "OBS WebSocket read-only capability unavailable",
                {"available": False, "error": obs_api.error},
            )
        )
        return _result(
            ObsEgressState.OBS_BOUND_UNVERIFIED,
            HealthImpact.DEGRADED,
            False,
            False,
            checked_at,
            ["obs_websocket_unavailable"],
            evidence,
            capabilities,
        )

    obs_record, obs_reason = _classify_obs_api(obs_api)
    evidence.append(obs_record)
    if obs_reason == "obs_input_missing":
        return _result(
            ObsEgressState.OBS_DETACHED,
            HealthImpact.BLOCKING,
            False,
            True,
            checked_at,
            [obs_reason],
            evidence,
            capabilities,
        )
    if obs_reason == "obs_wrong_source":
        return _result(
            ObsEgressState.OBS_WRONG_SOURCE,
            HealthImpact.BLOCKING,
            False,
            True,
            checked_at,
            [obs_reason],
            evidence,
            capabilities,
        )
    if obs_reason in {"obs_input_muted", "obs_input_no_audio_tracks"}:
        return _result(
            ObsEgressState.OBS_BOUND_UNVERIFIED,
            HealthImpact.BLOCKING,
            False,
            True,
            checked_at,
            [obs_reason],
            evidence,
            capabilities,
        )

    if obs_api.stream_active is not True or obs_api.stream_reconnecting is True:
        return _result(
            ObsEgressState.PUBLIC_EGRESS_UNKNOWN,
            HealthImpact.DEGRADED,
            False,
            False,
            checked_at,
            ["public_egress_unknown"],
            evidence,
            capabilities,
        )

    return _result(
        ObsEgressState.HEALTHY,
        HealthImpact.SAFE,
        True,
        False,
        checked_at,
        [],
        evidence,
        capabilities,
    )


def _graph_status(links: frozenset[tuple[str, str]], ports: frozenset[str]) -> dict[str, Any]:
    normalized_links = {
        channel: (
            f"{EXPECTED_BROADCAST_NORMALIZED}_{channel}",
            f"{EXPECTED_REMAP_CAPTURE}_{channel}",
        )
        in links
        for channel in ("FL", "FR")
    }
    remap_links = {
        channel: any(
            source == f"{EXPECTED_OBS_SOURCE_CAPTURE}_{channel}" and _is_obs_input(target, channel)
            for source, target in links
        )
        for channel in ("FL", "FR")
    }
    obs_inputs = sorted(port for port in ports if port.startswith("OBS") and ":input_" in port)
    wrong_obs_sources = sorted(
        {
            source
            for source, target in links
            if _is_obs_input(target, "FL") or _is_obs_input(target, "FR")
            if not source.startswith(EXPECTED_OBS_SOURCE_CAPTURE)
        }
    )
    remap_present = any(EXPECTED_OBS_SOURCE in port for port in ports)
    return {
        "expected_source": EXPECTED_OBS_SOURCE,
        "normalized_to_remap": normalized_links,
        "normalized_to_remap_complete": all(normalized_links.values()),
        "remap_to_obs": remap_links,
        "remap_to_obs_complete": all(remap_links.values()),
        "remap_present": remap_present,
        "obs_present": bool(obs_inputs),
        "obs_inputs": obs_inputs,
        "wrong_obs_sources": wrong_obs_sources,
    }


def _classify_obs_api(obs_api: ObsApiEvidence) -> tuple[EvidenceRecord, str | None]:
    observed = sanitize_obs_payload(
        {
            "available": obs_api.available,
            "input_present": obs_api.input_present,
            "input_name": obs_api.input_name,
            "input_kind": obs_api.input_kind,
            "settings": obs_api.settings,
            "muted": obs_api.muted,
            "volume_mul": obs_api.volume_mul,
            "audio_tracks": obs_api.audio_tracks,
            "stream_active": obs_api.stream_active,
            "stream_reconnecting": obs_api.stream_reconnecting,
            "error": obs_api.error,
        }
    )
    if obs_api.input_present is False:
        return _record(
            "obs_websocket", EvidenceStatus.FAIL, "expected OBS input missing", observed
        ), ("obs_input_missing")
    device_id = _settings_device_id(obs_api.settings)
    if device_id is not None and device_id != EXPECTED_OBS_SOURCE:
        return _record(
            "obs_websocket", EvidenceStatus.FAIL, "OBS input points at wrong source", observed
        ), ("obs_wrong_source")
    if obs_api.muted is True:
        return _record("obs_websocket", EvidenceStatus.FAIL, "OBS input is muted", observed), (
            "obs_input_muted"
        )
    if obs_api.audio_tracks is not None and not any(obs_api.audio_tracks.values()):
        return _record(
            "obs_websocket",
            EvidenceStatus.FAIL,
            "OBS input has no enabled audio tracks",
            observed,
        ), "obs_input_no_audio_tracks"
    return _record(
        "obs_websocket", EvidenceStatus.PASS, "OBS input state inspected", observed
    ), None


def _settings_device_id(settings: Mapping[str, Any]) -> str | None:
    value = settings.get("device_id")
    if isinstance(value, str):
        return value
    nested = settings.get("inputSettings")
    if isinstance(nested, Mapping):
        nested_value = nested.get("device_id")
        if isinstance(nested_value, str):
            return nested_value
    return None


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return (
        lowered in _SECRET_KEY_NAMES
        or lowered.endswith(_SECRET_KEY_SUFFIXES)
        or "password" in lowered
    )


def _signal_record(source: str, signal: SignalEvidence, now: float) -> EvidenceRecord:
    has_signal = signal.has_signal()
    stale = signal.stale(now)
    if signal.error:
        status = EvidenceStatus.UNKNOWN
        message = "signal witness reported an error"
    elif stale:
        status = EvidenceStatus.UNKNOWN
        message = "signal witness is stale"
    elif has_signal is True:
        status = EvidenceStatus.PASS
        message = "signal witness shows audio present"
    elif has_signal is False:
        status = EvidenceStatus.FAIL
        message = "signal witness is silent"
    else:
        status = EvidenceStatus.UNKNOWN
        message = "signal witness is inconclusive"
    return _record(
        source,
        status,
        message,
        {
            "available": signal.available,
            "rms_dbfs": signal.rms_dbfs,
            "peak_dbfs": signal.peak_dbfs,
            "silence_ratio": signal.silence_ratio,
            "error": signal.error,
        },
        timestamp=signal.checked_at,
        max_age_s=signal.max_age_s,
        stale=stale,
    )


def _is_obs_input(port: str, channel: str) -> bool:
    if not port.endswith(f":input_{channel}"):
        return False
    node = port.split(":", 1)[0]
    return "OBS" in node


def _record(
    source: str,
    status: EvidenceStatus,
    message: str,
    observed: Mapping[str, Any] | None = None,
    *,
    timestamp: str | None = None,
    max_age_s: float | None = None,
    stale: bool = False,
) -> EvidenceRecord:
    return EvidenceRecord(
        source=source,
        status=status,
        message=message,
        observed=dict(observed or {}),
        timestamp=timestamp,
        max_age_s=max_age_s,
        stale=stale,
    )


def _result(
    state: ObsEgressState,
    health_impact: HealthImpact,
    safe: bool,
    remediation_allowed: bool,
    checked_at: str,
    reason_codes: Sequence[str],
    evidence: Sequence[EvidenceRecord],
    capabilities: Mapping[str, bool],
) -> ObsEgressPredicateResult:
    return ObsEgressPredicateResult(
        state=state,
        health_impact=health_impact,
        safe=safe,
        remediation_allowed=remediation_allowed,
        checked_at=checked_at,
        reason_codes=list(reason_codes),
        evidence=list(evidence),
        capabilities=dict(capabilities),
    )


def _iso_from_epoch(value: float) -> str:
    return datetime.fromtimestamp(value, tz=UTC).isoformat().replace("+00:00", "Z")


def _parse_iso_epoch(value: str) -> float | None:
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return None


__all__ = [
    "DEFAULT_SIGNAL_RMS_FLOOR_DBFS",
    "DEFAULT_SIGNAL_SILENCE_RATIO_MAX",
    "EXPECTED_OBS_SOURCE",
    "EvidenceRecord",
    "EvidenceStatus",
    "HealthImpact",
    "ObsApiEvidence",
    "ObsEgressPredicateResult",
    "ObsEgressState",
    "PipeWireLinkEvidence",
    "SignalEvidence",
    "classify_obs_egress",
    "parse_pw_link_output",
    "sanitize_obs_payload",
]
