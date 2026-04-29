"""Role-scoped audio source evidence ledger.

The unified reactivity bus says which DSP sources are moving right now. This
module turns that raw signal snapshot into evidence rows that preserve source
role, route policy, public/private posture, egress separation, WCS refs, and
legacy alias compatibility. The ledger is a runtime witness surface: route
existence and process activity never become audio activity or public-audible
claims by themselves.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER_PATH = Path(
    os.environ.get(
        "HAPAX_AUDIO_SOURCE_LEDGER_PATH",
        "/dev/shm/hapax-compositor/audio-source-ledger.json",
    )
)
DEFAULT_DURABLE_DIR = Path(
    os.environ.get(
        "HAPAX_AUDIO_SOURCE_LEDGER_DIR",
        str(Path.home() / "hapax-state" / "audio" / "source-ledger"),
    )
)
DEFAULT_YT_AUDIO_STATE = Path("/dev/shm/hapax-compositor/yt-audio-state.json")
DEFAULT_SCHEMA_REF = "schemas/audio-source-evidence-ledger.schema.json"
DEFAULT_SOURCE_TTL_S = 2.0
DEFAULT_LEDGER_PUBLISH_MIN_PERIOD_S = 1.0
ACTIVITY_FLOOR_RMS = 1e-4

log = logging.getLogger(__name__)


class AudioSourceEvidenceError(ValueError):
    """Raised when an audio source ledger cannot be loaded or written safely."""


class AudioSourceRole(StrEnum):
    LEGACY_MIXER = "legacy_mixer"
    DESK_CONTACT = "desk_contact"
    MUSIC = "music"
    YOUTUBE = "youtube"
    TTS = "tts"
    OPERATOR_VOICE = "operator_voice"
    INSTRUMENT = "instrument"
    MULTIMEDIA = "multimedia"
    ASSISTANT = "assistant"
    NOTIFICATION = "notification"
    BROADCAST_EGRESS = "broadcast_egress"
    UNKNOWN = "unknown"


class FreshnessState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    UNKNOWN = "unknown"


class ActivityBasis(StrEnum):
    MEASURED_SIGNAL = "measured_signal"
    EXPLICIT_MARKER = "explicit_marker"
    PROCESS_ACTIVITY = "process_activity"
    ROUTE_POLICY = "route_policy"
    BROADCAST_HEALTH = "broadcast_health"
    MISSING = "missing"


class RoutePostureState(StrEnum):
    WITNESSED = "witnessed"
    ROUTE_ONLY = "route_only"
    BLOCKED = "blocked"
    STALE = "stale"
    MISSING = "missing"
    UNKNOWN = "unknown"


class EgressPostureState(StrEnum):
    WITNESSED_PUBLIC = "witnessed_public"
    QUIET = "quiet"
    BLOCKED = "blocked"
    NOT_EGRESS = "not_egress"
    UNKNOWN = "unknown"


class PublicPrivatePosture(StrEnum):
    PUBLIC_CANDIDATE = "public_candidate"
    PRIVATE_ONLY = "private_only"
    INTERNAL_HEALTH = "internal_health"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class AudioReactiveOutcome(StrEnum):
    VERIFIED = "verified"
    BLOCKED = "blocked"
    STALE = "stale"
    NO_OP = "no_op"
    DRY_RUN = "dry_run"


class LedgerModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SignalMetrics(LedgerModel):
    rms: float = Field(ge=0.0, le=1.0)
    onset: float = Field(ge=0.0, le=1.0)
    centroid: float = Field(ge=0.0, le=1.0)
    zcr: float = Field(ge=0.0, le=1.0)
    bpm_estimate: float = Field(ge=0.0, le=300.0)
    energy_delta: float = Field(ge=-1.0, le=1.0)
    bass_band: float = Field(ge=0.0, le=1.0)
    mid_band: float = Field(ge=0.0, le=1.0)
    treble_band: float = Field(ge=0.0, le=1.0)
    loudness_lufs_i: float | None = None
    true_peak_dbtp: float | None = None
    measurement_present: bool = False
    measured_non_silent: bool = False

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if self.measured_non_silent and not self.measurement_present:
            raise ValueError("measured_non_silent requires measurement_present")

    @classmethod
    def zero(cls) -> SignalMetrics:
        return cls(
            rms=0.0,
            onset=0.0,
            centroid=0.0,
            zcr=0.0,
            bpm_estimate=0.0,
            energy_delta=0.0,
            bass_band=0.0,
            mid_band=0.0,
            treble_band=0.0,
        )

    @classmethod
    def from_audio_signals(cls, signals: Any) -> SignalMetrics:
        rms = _float_attr(signals, "rms")
        return cls(
            rms=rms,
            onset=_float_attr(signals, "onset"),
            centroid=_float_attr(signals, "centroid"),
            zcr=_float_attr(signals, "zcr"),
            bpm_estimate=_float_attr(signals, "bpm_estimate"),
            energy_delta=_float_attr(signals, "energy_delta"),
            bass_band=_float_attr(signals, "bass_band"),
            mid_band=_float_attr(signals, "mid_band"),
            treble_band=_float_attr(signals, "treble_band"),
            measurement_present=True,
            measured_non_silent=rms > ACTIVITY_FLOOR_RMS,
        )

    def can_mark_active(self) -> bool:
        return self.measurement_present and self.measured_non_silent


class Freshness(LedgerModel):
    state: FreshnessState
    ttl_s: float = Field(ge=0.0)
    observed_age_s: float | None = Field(default=None, ge=0.0)
    checked_at: str
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class RoutePosture(LedgerModel):
    state: RoutePostureState
    route_exists: bool = False
    route_witnessed: bool = False
    egress_verified: bool = False
    public_audible: bool = False
    private_monitor_verified: bool = False
    no_leak_verified: bool = False
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class EgressPosture(LedgerModel):
    state: EgressPostureState
    health_safe: bool = False
    public_audible: bool = False
    quiet: bool = False
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class DownstreamPermissions(LedgerModel):
    visual_modulation: bool = False
    director_move: bool = False
    semantic_fx: bool = False
    public_claim: bool = False
    clip_candidate: bool = False
    artifact_release: bool = False


class AudioActivityMarker(LedgerModel):
    source_id: str
    role: AudioSourceRole
    active: bool
    basis: ActivityBasis
    observed_at: str
    ttl_s: float = Field(default=DEFAULT_SOURCE_TTL_S, ge=0.0)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    producer: str = "runtime-marker"

    def freshness(self, *, now: float) -> Freshness:
        observed_epoch = _parse_iso_epoch(self.observed_at)
        age = max(0.0, now - observed_epoch) if observed_epoch is not None else None
        if age is None:
            state = FreshnessState.UNKNOWN
        elif age > self.ttl_s:
            state = FreshnessState.STALE
        else:
            state = FreshnessState.FRESH
        return Freshness(
            state=state,
            ttl_s=self.ttl_s,
            observed_age_s=round(age, 3) if age is not None else None,
            checked_at=_iso_from_epoch(now),
            evidence_refs=self.evidence_refs,
        )


class AudioSourceEvidence(LedgerModel):
    row_id: str
    source_id: str
    role: AudioSourceRole
    producer: str
    semantic_surface_id: str
    route_policy_ref: str | None = None
    pipewire_node: str | None = None
    target_chain: tuple[str, ...] = Field(default_factory=tuple)
    signal_metrics: SignalMetrics
    freshness: Freshness
    active: bool
    activity_basis: ActivityBasis
    marker_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    route_posture: RoutePosture
    egress_posture: EgressPosture
    public_private_posture: PublicPrivatePosture
    wcs_refs: tuple[str, ...] = Field(min_length=1)
    evidence_envelope_refs: tuple[str, ...] = Field(min_length=1)
    egress_refs: tuple[str, ...] = Field(default_factory=tuple)
    provenance_refs: tuple[str, ...] = Field(default_factory=tuple)
    rights_refs: tuple[str, ...] = Field(default_factory=tuple)
    privacy_refs: tuple[str, ...] = Field(default_factory=tuple)
    programme_id: str | None = None
    run_id: str | None = None
    downstream_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    compatibility_aliases: tuple[str, ...] = Field(default_factory=tuple)
    permissions: DownstreamPermissions
    blocking_reasons: tuple[str, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        explicit_marker_active = self.activity_basis is ActivityBasis.EXPLICIT_MARKER and bool(
            self.marker_evidence_refs
        )
        if self.active:
            if self.freshness.state is not FreshnessState.FRESH:
                raise ValueError("active source evidence requires fresh evidence")
            if not (self.signal_metrics.can_mark_active() or explicit_marker_active):
                raise ValueError(
                    "active source requires measured signal or explicit marker evidence"
                )
            if self.activity_basis is ActivityBasis.PROCESS_ACTIVITY:
                raise ValueError("process activity cannot mark an audio source active")

        if self.permissions.public_claim:
            if not self.egress_posture.public_audible:
                raise ValueError("public_claim permission requires public-audible egress evidence")
            if not self.evidence_envelope_refs:
                raise ValueError("public_claim permission requires evidence envelope refs")

        public_release = self.permissions.clip_candidate or self.permissions.artifact_release
        if public_release and not self.permissions.public_claim:
            raise ValueError("clip/artifact release requires public_claim permission")


class AudioReactiveRecruitmentDecision(LedgerModel):
    requested_roles: tuple[AudioSourceRole, ...]
    outcome: AudioReactiveOutcome
    selected_source_ids: tuple[str, ...] = Field(default_factory=tuple)
    reason: str
    evidence_envelope_refs: tuple[str, ...] = Field(default_factory=tuple)
    blocked_reasons: tuple[str, ...] = Field(default_factory=tuple)


class AudioSourceLedger(LedgerModel):
    schema_version: Literal[1] = 1
    ledger_id: str
    schema_ref: Literal["schemas/audio-source-evidence-ledger.schema.json"] = DEFAULT_SCHEMA_REF
    generated_at: str
    source_rows: tuple[AudioSourceEvidence, ...] = Field(min_length=1)
    compatibility_aliases: dict[str, str] = Field(default_factory=dict)

    def audio_reactive_decision(
        self,
        roles: Iterable[AudioSourceRole | str] | None = None,
        *,
        require_public: bool = False,
        dry_run: bool = False,
    ) -> AudioReactiveRecruitmentDecision:
        requested = tuple(AudioSourceRole(role) for role in roles) if roles is not None else ()
        candidates = self.source_rows
        if requested:
            requested_set = set(requested)
            candidates = tuple(row for row in candidates if row.role in requested_set)

        if dry_run:
            return AudioReactiveRecruitmentDecision(
                requested_roles=requested,
                outcome=AudioReactiveOutcome.DRY_RUN,
                reason="dry_run_requested",
            )

        eligible = tuple(
            row
            for row in candidates
            if row.active
            and row.permissions.visual_modulation
            and (not require_public or row.permissions.public_claim)
        )
        if eligible:
            return AudioReactiveRecruitmentDecision(
                requested_roles=requested,
                outcome=AudioReactiveOutcome.VERIFIED,
                selected_source_ids=tuple(row.source_id for row in eligible),
                reason="fresh_role_scoped_audio_source_verified",
                evidence_envelope_refs=tuple(
                    ref for row in eligible for ref in row.evidence_envelope_refs
                ),
            )

        stale = tuple(row for row in candidates if row.freshness.state is FreshnessState.STALE)
        if stale:
            return AudioReactiveRecruitmentDecision(
                requested_roles=requested,
                outcome=AudioReactiveOutcome.STALE,
                reason="audio_source_evidence_stale",
                blocked_reasons=tuple(reason for row in stale for reason in row.blocking_reasons),
            )

        blocked = tuple(row for row in candidates if row.blocking_reasons)
        if blocked:
            return AudioReactiveRecruitmentDecision(
                requested_roles=requested,
                outcome=AudioReactiveOutcome.BLOCKED,
                reason="audio_source_evidence_blocked",
                blocked_reasons=tuple(reason for row in blocked for reason in row.blocking_reasons),
            )

        return AudioReactiveRecruitmentDecision(
            requested_roles=requested,
            outcome=AudioReactiveOutcome.NO_OP,
            reason="no_fresh_relevant_audio_source",
        )


def build_audio_source_ledger(
    *,
    snapshot: Any | None,
    policy: Any | None = None,
    broadcast_health: Any | None = None,
    markers: Sequence[AudioActivityMarker] = (),
    now: float | None = None,
    programme_id: str | None = None,
    run_id: str | None = None,
) -> AudioSourceLedger:
    current = time.time() if now is None else now
    generated_at = _iso_from_epoch(current)
    rows: list[AudioSourceEvidence] = []
    used_signal_keys: set[str] = set()
    marker_by_source = {marker.source_id: marker for marker in markers}

    for route in tuple(getattr(policy, "routes", ()) if policy is not None else ()):
        row, signal_key = _row_from_route(
            route=route,
            snapshot=snapshot,
            marker=marker_by_source.get(route.source_id),
            now=current,
            programme_id=programme_id,
            run_id=run_id,
        )
        rows.append(row)
        if signal_key is not None:
            used_signal_keys.add(signal_key)

    for source_id, signals in _snapshot_per_source(snapshot).items():
        if source_id in used_signal_keys:
            continue
        if source_id in {"mixer", "desk"}:
            rows.append(
                _legacy_row(
                    source_id=source_id,
                    signals=signals,
                    now=current,
                    programme_id=programme_id,
                    run_id=run_id,
                )
            )

    if broadcast_health is not None:
        rows.append(_broadcast_egress_row(broadcast_health, now=current))

    if not rows:
        rows.append(_missing_row(now=current))

    aliases: dict[str, str] = {}
    for row in rows:
        for alias in row.compatibility_aliases:
            aliases.setdefault(alias, row.source_id)

    return AudioSourceLedger(
        ledger_id=f"audio-source-ledger:{generated_at}",
        generated_at=generated_at,
        source_rows=tuple(rows),
        compatibility_aliases=aliases,
    )


def write_audio_source_ledger(
    ledger: AudioSourceLedger,
    *,
    path: Path = DEFAULT_LEDGER_PATH,
    durable_dir: Path = DEFAULT_DURABLE_DIR,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(ledger.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    durable_dir.mkdir(parents=True, exist_ok=True)
    summary_path = durable_dir / f"{ledger.generated_at[:10]}.jsonl"
    with summary_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_ledger_summary(ledger), sort_keys=True) + "\n")


def read_audio_source_ledger(path: Path = DEFAULT_LEDGER_PATH) -> AudioSourceLedger | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise AudioSourceEvidenceError(f"invalid audio source ledger at {path}: {exc}") from exc
    try:
        return AudioSourceLedger.model_validate(payload)
    except ValidationError as exc:
        raise AudioSourceEvidenceError(f"invalid audio source ledger at {path}: {exc}") from exc


class AudioSourceLedgerPublisher:
    """Throttled runtime publisher used by ``UnifiedReactivityBus``."""

    def __init__(
        self,
        *,
        ledger_path: Path = DEFAULT_LEDGER_PATH,
        durable_dir: Path = DEFAULT_DURABLE_DIR,
        policy_path: Path | None = None,
        yt_audio_state_path: Path = DEFAULT_YT_AUDIO_STATE,
        broadcast_state_path: Path | None = None,
        min_period_s: float = DEFAULT_LEDGER_PUBLISH_MIN_PERIOD_S,
        clock: Any | None = None,
    ) -> None:
        self._ledger_path = ledger_path
        self._durable_dir = durable_dir
        self._policy_path = policy_path
        self._yt_audio_state_path = yt_audio_state_path
        self._broadcast_state_path = broadcast_state_path
        self._min_period_s = min_period_s
        self._clock = clock or time.time
        self._last_publish: float | None = None
        self._policy_cache: Any | None = None
        self._policy_cache_mtime: float | None = None

    def maybe_publish(self, snapshot: Any, *, force: bool = False) -> AudioSourceLedger | None:
        now = float(self._clock())
        if (
            not force
            and self._last_publish is not None
            and now - self._last_publish < self._min_period_s
        ):
            return None

        try:
            ledger = build_audio_source_ledger(
                snapshot=snapshot,
                policy=self._load_policy(),
                broadcast_health=self._read_broadcast_health(now=now),
                markers=self._read_markers(now=now),
                now=now,
            )
            write_audio_source_ledger(
                ledger,
                path=self._ledger_path,
                durable_dir=self._durable_dir,
            )
        except Exception:
            log.debug("audio-source-ledger publish failed", exc_info=True)
            return None

        self._last_publish = now
        return ledger

    def _load_policy(self) -> Any | None:
        try:
            from shared.audio_routing_policy import DEFAULT_POLICY_PATH, load_audio_routing_policy

            path = self._policy_path or DEFAULT_POLICY_PATH
            mtime = path.stat().st_mtime
            if self._policy_cache is None or self._policy_cache_mtime != mtime:
                self._policy_cache = load_audio_routing_policy(path)
                self._policy_cache_mtime = mtime
            return self._policy_cache
        except Exception:
            log.debug("audio-source-ledger policy load failed", exc_info=True)
            return None

    def _read_broadcast_health(self, *, now: float) -> Any | None:
        try:
            from shared.broadcast_audio_health import (
                DEFAULT_STATE_PATH,
                read_broadcast_audio_health_state,
            )

            return read_broadcast_audio_health_state(
                self._broadcast_state_path or DEFAULT_STATE_PATH,
                now=now,
            )
        except Exception:
            log.debug("audio-source-ledger broadcast health read failed", exc_info=True)
            return None

    def _read_markers(self, *, now: float) -> tuple[AudioActivityMarker, ...]:
        marker = _read_yt_audio_marker(self._yt_audio_state_path, now=now)
        return (marker,) if marker is not None else ()


def _row_from_route(
    *,
    route: Any,
    snapshot: Any | None,
    marker: AudioActivityMarker | None,
    now: float,
    programme_id: str | None,
    run_id: str | None,
) -> tuple[AudioSourceEvidence, str | None]:
    source_id = str(route.source_id)
    role = _role_for_route(route)
    signal_key, signals = _signals_for_route(route, snapshot)
    metrics = (
        SignalMetrics.from_audio_signals(signals) if signals is not None else SignalMetrics.zero()
    )
    freshness = _freshness_for_signal(signals=signals, marker=marker, now=now)
    active, basis = _activity_for(metrics=metrics, marker=marker, freshness=freshness)
    blocking = list(_blocking_reasons(metrics=metrics, marker=marker, freshness=freshness))
    if not bool(route.broadcast_eligible):
        blocking.append("route_not_broadcast_eligible")
    if marker is not None and marker.basis is ActivityBasis.PROCESS_ACTIVITY and marker.active:
        blocking.append("process_activity_not_signal_evidence")

    public_candidate = bool(route.broadcast_eligible)
    posture = (
        PublicPrivatePosture.PUBLIC_CANDIDATE
        if public_candidate
        else PublicPrivatePosture.PRIVATE_ONLY
    )
    if not bool(route.public_claim_allowed):
        posture = (
            PublicPrivatePosture.PRIVATE_ONLY
            if str(route.route_class) in {"private", "notification", "monitor_bridge"}
            else posture
        )

    permissions = _permissions_for_role(
        active=active,
        public_claim=False,
        private_only=posture is PublicPrivatePosture.PRIVATE_ONLY,
    )
    evidence_ref = _evidence_ref(source_id, now)
    row = AudioSourceEvidence(
        row_id=f"audio-source:{source_id}:{int(now)}",
        source_id=source_id,
        role=role,
        producer=str(route.producer),
        semantic_surface_id=f"audio.{role.value}",
        route_policy_ref=f"config/audio-routing.yaml#{source_id}",
        pipewire_node=str(route.pipewire_node),
        target_chain=tuple(str(target) for target in route.target_chain),
        signal_metrics=metrics,
        freshness=freshness,
        active=active,
        activity_basis=basis,
        marker_evidence_refs=marker.evidence_refs if marker is not None else (),
        route_posture=RoutePosture(
            state=RoutePostureState.ROUTE_ONLY
            if route.broadcast_eligible
            else RoutePostureState.BLOCKED,
            route_exists=True,
            route_witnessed=False,
            egress_verified=False,
            public_audible=False,
            private_monitor_verified=str(route.route_class) in {"private", "notification"},
            no_leak_verified=False,
            evidence_refs=tuple(str(ref) for ref in route.evidence_refs),
        ),
        egress_posture=EgressPosture(state=EgressPostureState.NOT_EGRESS),
        public_private_posture=posture,
        wcs_refs=(f"wcs:audio.{role.value}",),
        evidence_envelope_refs=(evidence_ref,),
        egress_refs=(),
        provenance_refs=tuple(str(ref) for ref in route.provenance_refs),
        rights_refs=tuple(str(ref) for ref in route.provenance_refs)
        if route.rights_required
        else (),
        privacy_refs=(f"privacy:audio-route:{source_id}",),
        programme_id=programme_id,
        run_id=run_id,
        downstream_evidence_refs=(evidence_ref,),
        compatibility_aliases=_route_aliases(route, role),
        permissions=permissions,
        blocking_reasons=tuple(dict.fromkeys(blocking)),
    )
    return row, signal_key


def _legacy_row(
    *,
    source_id: str,
    signals: Any,
    now: float,
    programme_id: str | None,
    run_id: str | None,
) -> AudioSourceEvidence:
    role = AudioSourceRole.LEGACY_MIXER if source_id == "mixer" else AudioSourceRole.DESK_CONTACT
    metrics = SignalMetrics.from_audio_signals(signals)
    active = metrics.can_mark_active()
    evidence_ref = _evidence_ref(source_id, now)
    return AudioSourceEvidence(
        row_id=f"audio-source:{source_id}:{int(now)}",
        source_id=source_id,
        role=role,
        producer="shared.audio_reactivity",
        semantic_surface_id=f"audio.{role.value}",
        signal_metrics=metrics,
        freshness=Freshness(
            state=FreshnessState.FRESH,
            ttl_s=DEFAULT_SOURCE_TTL_S,
            observed_age_s=0.0,
            checked_at=_iso_from_epoch(now),
            evidence_refs=("shm:hapax-compositor/unified-reactivity.json",),
        ),
        active=active,
        activity_basis=ActivityBasis.MEASURED_SIGNAL if active else ActivityBasis.MISSING,
        route_posture=RoutePosture(
            state=RoutePostureState.UNKNOWN,
            evidence_refs=("legacy-alias:no-route-policy-row",),
        ),
        egress_posture=EgressPosture(state=EgressPostureState.NOT_EGRESS),
        public_private_posture=PublicPrivatePosture.UNKNOWN,
        wcs_refs=(f"wcs:audio.{role.value}",),
        evidence_envelope_refs=(evidence_ref,),
        programme_id=programme_id,
        run_id=run_id,
        downstream_evidence_refs=(evidence_ref,),
        compatibility_aliases=_legacy_aliases(source_id),
        permissions=_permissions_for_role(active=active, public_claim=False, private_only=False),
        blocking_reasons=() if active else ("source_signal_silent",),
        warnings=("legacy_compatibility_row_no_route_policy",),
    )


def _broadcast_egress_row(health: Any, *, now: float) -> AudioSourceEvidence:
    evidence = getattr(health, "evidence", {}) or {}
    loudness = evidence.get("loudness", {}) if isinstance(evidence, dict) else {}
    integrated = _float_or_none(loudness.get("integrated_lufs_i"))
    true_peak = _float_or_none(loudness.get("true_peak_dbtp"))
    within_target = bool(loudness.get("within_target_band"))
    safe = bool(getattr(health, "safe", False))
    active = safe and within_target and integrated is not None
    metrics = SignalMetrics(
        rms=0.0,
        onset=0.0,
        centroid=0.0,
        zcr=0.0,
        bpm_estimate=0.0,
        energy_delta=0.0,
        bass_band=0.0,
        mid_band=0.0,
        treble_band=0.0,
        loudness_lufs_i=integrated,
        true_peak_dbtp=true_peak,
        measurement_present=integrated is not None,
        measured_non_silent=active,
    )
    blocking = [reason.code for reason in getattr(health, "blocking_reasons", ())]
    if not active:
        blocking.append("broadcast_egress_not_public_audible")
    evidence_ref = _evidence_ref("broadcast-egress", now)
    return AudioSourceEvidence(
        row_id=f"audio-source:broadcast-egress:{int(now)}",
        source_id="broadcast-egress",
        role=AudioSourceRole.BROADCAST_EGRESS,
        producer="shared.broadcast_audio_health",
        semantic_surface_id="audio.broadcast_egress",
        signal_metrics=metrics,
        freshness=Freshness(
            state=FreshnessState.FRESH,
            ttl_s=30.0,
            observed_age_s=float(getattr(health, "freshness_s", 0.0) or 0.0),
            checked_at=str(getattr(health, "checked_at", _iso_from_epoch(now))),
            evidence_refs=("shm:hapax-broadcast/audio-safe-for-broadcast.json",),
        ),
        active=active,
        activity_basis=ActivityBasis.BROADCAST_HEALTH if active else ActivityBasis.MISSING,
        route_posture=RoutePosture(
            state=RoutePostureState.WITNESSED if safe else RoutePostureState.BLOCKED,
            route_exists=True,
            route_witnessed=safe,
            egress_verified=safe,
            public_audible=active,
            no_leak_verified=safe,
            evidence_refs=("shm:hapax-broadcast/audio-safe-for-broadcast.json",),
        ),
        egress_posture=EgressPosture(
            state=EgressPostureState.WITNESSED_PUBLIC if active else EgressPostureState.QUIET,
            health_safe=safe,
            public_audible=active,
            quiet=not active,
            evidence_refs=("shm:hapax-broadcast/audio-safe-for-broadcast.json",),
        ),
        public_private_posture=PublicPrivatePosture.INTERNAL_HEALTH,
        wcs_refs=("wcs:audio.broadcast_egress", "wcs:audio.broadcast_health"),
        evidence_envelope_refs=(evidence_ref,),
        egress_refs=("broadcast-health:audio-safe-for-broadcast",),
        provenance_refs=("shared:broadcast_audio_health",),
        rights_refs=("rights:broadcast-egress-health-only",),
        privacy_refs=("privacy:no-private-leak-witness-required",),
        downstream_evidence_refs=(evidence_ref,),
        compatibility_aliases=("broadcast.rms", "broadcast.lufs_i", "broadcast_egress"),
        permissions=_permissions_for_role(active=active, public_claim=active, private_only=False),
        blocking_reasons=tuple(dict.fromkeys(blocking)),
    )


def _missing_row(*, now: float) -> AudioSourceEvidence:
    evidence_ref = _evidence_ref("missing", now)
    return AudioSourceEvidence(
        row_id=f"audio-source:missing:{int(now)}",
        source_id="missing",
        role=AudioSourceRole.UNKNOWN,
        producer="shared.audio_source_evidence",
        semantic_surface_id="audio.unknown",
        signal_metrics=SignalMetrics.zero(),
        freshness=Freshness(
            state=FreshnessState.MISSING,
            ttl_s=DEFAULT_SOURCE_TTL_S,
            checked_at=_iso_from_epoch(now),
        ),
        active=False,
        activity_basis=ActivityBasis.MISSING,
        route_posture=RoutePosture(state=RoutePostureState.MISSING),
        egress_posture=EgressPosture(state=EgressPostureState.UNKNOWN),
        public_private_posture=PublicPrivatePosture.UNKNOWN,
        wcs_refs=("wcs:audio.unknown",),
        evidence_envelope_refs=(evidence_ref,),
        permissions=DownstreamPermissions(),
        blocking_reasons=("no_audio_sources_registered",),
    )


def _snapshot_per_source(snapshot: Any | None) -> Mapping[str, Any]:
    if snapshot is None:
        return {}
    per_source = getattr(snapshot, "per_source", None)
    return per_source if isinstance(per_source, Mapping) else {}


def _signals_for_route(route: Any, snapshot: Any | None) -> tuple[str | None, Any | None]:
    per_source = _snapshot_per_source(snapshot)
    for candidate in _signal_key_candidates(route):
        if candidate in per_source:
            return candidate, per_source[candidate]
    return None, None


def _signal_key_candidates(route: Any) -> tuple[str, ...]:
    source_id = str(route.source_id)
    role = str(route.role)
    explicit = {
        "broadcast-tts": ("tts", "hapax_tts", "voice"),
        "music-bed": ("music", "programme_music"),
        "youtube-bed": ("youtube", "yt"),
        "l12-evilpet-capture": ("l12", "evilpet"),
        "s4-content": ("s4",),
        "m8-instrument": ("m8",),
    }.get(source_id, ())
    return (*explicit, source_id, role)


def _role_for_route(route: Any) -> AudioSourceRole:
    source_id = str(route.source_id)
    role = str(route.role)
    if source_id == "broadcast-tts":
        return AudioSourceRole.TTS
    if role == "assistant":
        return AudioSourceRole.ASSISTANT
    if role == "notification":
        return AudioSourceRole.NOTIFICATION
    if role == "music":
        return AudioSourceRole.MUSIC
    if role == "youtube":
        return AudioSourceRole.YOUTUBE
    if role == "instrument":
        return AudioSourceRole.INSTRUMENT
    if role == "multimedia":
        return AudioSourceRole.MULTIMEDIA
    return AudioSourceRole.UNKNOWN


def _route_aliases(route: Any, role: AudioSourceRole) -> tuple[str, ...]:
    source_id = str(route.source_id)
    role_value = role.value
    aliases = {
        source_id,
        f"{role_value}.rms",
        f"{role_value}.onset",
        f"{role_value}.bass",
        f"{role_value}.mid",
        f"{role_value}.treble",
    }
    if source_id == "youtube-bed":
        aliases |= {"yt.rms", "yt.energy", "youtube.rms"}
    if source_id == "music-bed":
        aliases |= {"music.rms", "programme_music.rms"}
    if source_id == "broadcast-tts":
        aliases |= {"tts.rms", "hapax_tts.rms"}
    return tuple(sorted(aliases))


def _legacy_aliases(source_id: str) -> tuple[str, ...]:
    if source_id == "mixer":
        return (
            "audio_beat",
            "audio_rms",
            "mixer",
            "mixer_bass",
            "mixer_energy",
            "mixer_high",
            "mixer_master",
            "mixer_mid",
            "onset_hat",
            "onset_kick",
            "onset_snare",
        )
    return ("contact_mic", "desk", "desk_activity", "desk_energy", "desk_onset_rate")


def _freshness_for_signal(
    *,
    signals: Any | None,
    marker: AudioActivityMarker | None,
    now: float,
) -> Freshness:
    if marker is not None:
        return marker.freshness(now=now)
    if signals is not None:
        return Freshness(
            state=FreshnessState.FRESH,
            ttl_s=DEFAULT_SOURCE_TTL_S,
            observed_age_s=0.0,
            checked_at=_iso_from_epoch(now),
            evidence_refs=("shm:hapax-compositor/unified-reactivity.json",),
        )
    return Freshness(
        state=FreshnessState.MISSING,
        ttl_s=DEFAULT_SOURCE_TTL_S,
        checked_at=_iso_from_epoch(now),
    )


def _activity_for(
    *,
    metrics: SignalMetrics,
    marker: AudioActivityMarker | None,
    freshness: Freshness,
) -> tuple[bool, ActivityBasis]:
    if freshness.state is not FreshnessState.FRESH:
        return False, ActivityBasis.MISSING
    if metrics.can_mark_active():
        return True, ActivityBasis.MEASURED_SIGNAL
    if marker is None:
        return False, ActivityBasis.MISSING
    if marker.active and marker.basis is ActivityBasis.EXPLICIT_MARKER:
        return True, ActivityBasis.EXPLICIT_MARKER
    return False, marker.basis


def _blocking_reasons(
    *,
    metrics: SignalMetrics,
    marker: AudioActivityMarker | None,
    freshness: Freshness,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if freshness.state is FreshnessState.STALE:
        reasons.append("source_evidence_stale")
    elif freshness.state in {FreshnessState.MISSING, FreshnessState.UNKNOWN}:
        reasons.append("source_signal_missing")
    elif not metrics.can_mark_active() and not (
        marker is not None and marker.active and marker.basis is ActivityBasis.EXPLICIT_MARKER
    ):
        reasons.append("source_signal_silent")
    return tuple(reasons)


def _permissions_for_role(
    *,
    active: bool,
    public_claim: bool,
    private_only: bool,
) -> DownstreamPermissions:
    return DownstreamPermissions(
        visual_modulation=active,
        director_move=active,
        semantic_fx=active and not private_only,
        public_claim=public_claim,
        clip_candidate=public_claim,
        artifact_release=public_claim,
    )


def _read_yt_audio_marker(path: Path, *, now: float) -> AudioActivityMarker | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        stat = path.stat()
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None
    return AudioActivityMarker(
        source_id="youtube-bed",
        role=AudioSourceRole.YOUTUBE,
        active=bool(raw.get("yt_audio_active")),
        basis=ActivityBasis.PROCESS_ACTIVITY,
        observed_at=_iso_from_epoch(stat.st_mtime),
        ttl_s=2.0,
        evidence_refs=("shm:hapax-compositor/yt-audio-state.json",),
        producer="scripts/youtube-player.py",
    )


def _ledger_summary(ledger: AudioSourceLedger) -> dict[str, Any]:
    return {
        "ledger_id": ledger.ledger_id,
        "generated_at": ledger.generated_at,
        "audio_reactive_outcome": ledger.audio_reactive_decision().outcome.value,
        "active_source_ids": [row.source_id for row in ledger.source_rows if row.active],
        "blocked_count": sum(1 for row in ledger.source_rows if row.blocking_reasons),
        "rows": [
            {
                "source_id": row.source_id,
                "role": row.role.value,
                "active": row.active,
                "freshness": row.freshness.state.value,
                "rms": row.signal_metrics.rms,
                "loudness_lufs_i": row.signal_metrics.loudness_lufs_i,
                "visual_modulation": row.permissions.visual_modulation,
                "public_claim": row.permissions.public_claim,
                "blocking_reasons": list(row.blocking_reasons),
            }
            for row in ledger.source_rows
        ],
    }


def _evidence_ref(source_id: str, now: float) -> str:
    return f"evidence-envelope:audio-source:{source_id}:{int(now)}"


def _float_attr(obj: Any, name: str) -> float:
    return _bounded_float(getattr(obj, name, 0.0))


def _bounded_float(value: Any, *, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return lo
    if number != number:
        return lo
    return min(max(number, lo), hi)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _iso_from_epoch(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso_epoch(value: str) -> float | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


__all__ = [
    "ACTIVITY_FLOOR_RMS",
    "AudioActivityMarker",
    "AudioReactiveOutcome",
    "AudioReactiveRecruitmentDecision",
    "AudioSourceEvidence",
    "AudioSourceEvidenceError",
    "AudioSourceLedger",
    "AudioSourceLedgerPublisher",
    "AudioSourceRole",
    "ActivityBasis",
    "DEFAULT_DURABLE_DIR",
    "DEFAULT_LEDGER_PATH",
    "DownstreamPermissions",
    "EgressPosture",
    "EgressPostureState",
    "Freshness",
    "FreshnessState",
    "PublicPrivatePosture",
    "RoutePosture",
    "RoutePostureState",
    "SignalMetrics",
    "build_audio_source_ledger",
    "read_audio_source_ledger",
    "write_audio_source_ledger",
]
