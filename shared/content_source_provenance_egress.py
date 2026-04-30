"""Broadcast provenance manifest and egress kill-switch.

The manifest is an audit/control surface, not an authority source. It records
which audio and visual assets are present at egress and lets the gate fail
closed on missing provenance or a tier above the active programme ceiling.
It never grants public, rights, safety, truth, or monetization status.
"""

from __future__ import annotations

import fcntl
import os
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from shared.affordance import ContentRisk
from shared.impingement import Impingement, ImpingementType

DEFAULT_BROADCAST_MANIFEST_PATH = Path("/dev/shm/hapax-broadcast-manifest.json")
DEFAULT_KILL_SWITCH_PATH = Path("/dev/shm/hapax-egress-kill-switch.json")
DEFAULT_IMPINGEMENT_PATH = Path("/dev/shm/hapax-dmn/impingements.jsonl")
DEFAULT_MUSIC_PROVENANCE_PATH = Path("/dev/shm/hapax-compositor/music-provenance.json")
DEFAULT_PROGRAMME_MAX_CONTENT_RISK: ContentRisk = "tier_1_platform_cleared"
PROGRAMME_MAX_CONTENT_RISK_ENV = "HAPAX_BROADCAST_MAX_CONTENT_RISK"
LEGACY_PRODUCER_ID = "__legacy_shared_kill_switch__"

ContentMedium = Literal["audio", "visual"]
AudioAction = Literal["pass_through", "duck_to_negative_infinity"]
VisualAction = Literal["pass_through", "crossfade_to_tier0_fallback_shader"]

_CONTENT_RISK_RANK: dict[ContentRisk, int] = {
    "tier_0_owned": 0,
    "tier_1_platform_cleared": 1,
    "tier_2_provenance_known": 2,
    "tier_3_uncertain": 3,
    "tier_4_risky": 4,
    "unknown": 99,
}
_CONTENT_RISK_VALUES = frozenset(_CONTENT_RISK_RANK)
_SAFE_SOURCE_KINDS = frozenset({"camera", "cairo", "shader", "external_rgba", "generative", "text"})
_SAFE_BACKENDS = frozenset({"cairo", "shm_rgba", "wgsl_render", "pango_text", "v4l2_camera"})


class BroadcastAuthorityCeiling(BaseModel):
    """Explicit non-authority ceiling carried by every manifest."""

    model_config = ConfigDict(extra="forbid")

    grants_public_status: Literal[False] = False
    grants_monetization_status: Literal[False] = False
    grants_truth_status: Literal[False] = False
    grants_rights_status: Literal[False] = False
    grants_safety_status: Literal[False] = False


class BroadcastManifestAsset(BaseModel):
    """One asset present at the broadcast boundary."""

    model_config = ConfigDict(extra="forbid")

    token: str | None = Field(
        default=None,
        description="Stable provenance token. Missing tokens fail closed at egress.",
    )
    tier: ContentRisk = Field(description="Broadcast provenance risk tier.")
    source: str = Field(min_length=1, description="Source registry or producer label.")
    medium: ContentMedium
    label: str | None = Field(default=None, description="Optional operator-readable asset label.")
    broadcast_safe: bool = Field(
        default=True,
        description="Producer-local safety posture. False fails closed at egress.",
    )


class BroadcastProvenanceManifest(BaseModel):
    """Per-tick manifest written to ``/dev/shm/hapax-broadcast-manifest.json``."""

    model_config = ConfigDict(extra="forbid")

    tick_id: str
    ts: float
    max_content_risk: ContentRisk = DEFAULT_PROGRAMME_MAX_CONTENT_RISK
    audio_assets: tuple[BroadcastManifestAsset, ...] = Field(default_factory=tuple)
    visual_assets: tuple[BroadcastManifestAsset, ...] = Field(default_factory=tuple)
    authority_ceiling: BroadcastAuthorityCeiling = Field(default_factory=BroadcastAuthorityCeiling)


class EgressOffender(BaseModel):
    """Why one manifest asset tripped the kill-switch."""

    model_config = ConfigDict(extra="forbid")

    token: str | None
    tier: ContentRisk
    source: str
    medium: ContentMedium
    reason: Literal["missing_token", "over_tier", "not_broadcast_safe"]


class EgressNotification(BaseModel):
    """High-priority operator notification payload."""

    model_config = ConfigDict(extra="forbid")

    title: str
    body: str
    priority: Literal["high"] = "high"
    tags: tuple[str, ...] = ("warning",)


class EgressGateDecision(BaseModel):
    """Pure gate verdict plus the side-effect payloads to apply."""

    model_config = ConfigDict(extra="forbid")

    kill_switch_fired: bool
    max_content_risk: ContentRisk
    offenders: tuple[EgressOffender, ...] = Field(default_factory=tuple)
    audio_action: AudioAction
    visual_action: VisualAction
    impingement: Impingement | None = None
    notification: EgressNotification | None = None


class EgressProducerKillSwitchState(BaseModel):
    """One producer's durable kill-switch contribution."""

    model_config = ConfigDict(extra="forbid")

    producer_id: str = Field(min_length=1)
    active: bool
    updated_at: float
    audio_action: AudioAction
    visual_action: VisualAction
    offenders: tuple[EgressOffender, ...] = Field(default_factory=tuple)


class EgressKillSwitchState(BaseModel):
    """Durable global rollup consumed by egress control surfaces."""

    model_config = ConfigDict(extra="forbid")

    active: bool
    updated_at: float
    audio_action: AudioAction
    visual_action: VisualAction
    fallback_visual_token: str = "visual:fallback:tier0-wgpu-shader"
    offenders: tuple[EgressOffender, ...] = Field(default_factory=tuple)
    producer_states: dict[str, EgressProducerKillSwitchState] = Field(default_factory=dict)


def content_risk_rank(tier: ContentRisk) -> int:
    """Return the ordered broadcast-provenance rank for ``tier``."""

    return _CONTENT_RISK_RANK[tier]


def max_content_risk_from_env(env: dict[str, str] | None = None) -> ContentRisk:
    """Return programme egress ceiling from env, failing closed on typos."""

    raw = (env or os.environ).get(PROGRAMME_MAX_CONTENT_RISK_ENV, "").strip().lower()
    if raw in _CONTENT_RISK_VALUES and raw != "unknown":
        return cast("ContentRisk", raw)
    return DEFAULT_PROGRAMME_MAX_CONTENT_RISK


def build_broadcast_manifest(
    *,
    audio_assets: Sequence[BroadcastManifestAsset] = (),
    visual_assets: Sequence[BroadcastManifestAsset] = (),
    tick_id: str | None = None,
    ts: float | None = None,
    max_content_risk: ContentRisk | None = None,
) -> BroadcastProvenanceManifest:
    """Build a manifest without expanding any authority claims."""

    return BroadcastProvenanceManifest(
        tick_id=tick_id or uuid.uuid4().hex[:12],
        ts=ts if ts is not None else time.time(),
        max_content_risk=max_content_risk or max_content_risk_from_env(),
        audio_assets=tuple(audio_assets),
        visual_assets=tuple(visual_assets),
    )


def audio_asset_from_music_manifest(asset: Any) -> BroadcastManifestAsset:
    """Project ``MusicManifestAsset`` into the broadcast manifest shape."""

    return BroadcastManifestAsset(
        token=asset.token,
        tier=asset.tier,
        source=str(asset.source or "music"),
        medium="audio",
        label=str(getattr(asset, "track_id", "") or asset.source or "music"),
        broadcast_safe=bool(asset.broadcast_safe),
    )


def visual_asset_from_visual_pool_asset(
    asset: Any,
    *,
    source_id: str | None = None,
) -> BroadcastManifestAsset:
    """Project a ``VisualPoolAsset`` into the broadcast manifest shape."""

    metadata = asset.metadata
    return BroadcastManifestAsset(
        token=asset.provenance_token,
        tier=metadata.content_risk,
        source=source_id or f"visual-pool:{metadata.source}",
        medium="visual",
        label=str(getattr(asset, "path", "") or metadata.source),
        broadcast_safe=bool(metadata.broadcast_safe),
    )


def visual_asset_from_source_schema(source: Any) -> BroadcastManifestAsset:
    """Project a compositor layout source into the manifest.

    Locally generated/captured source kinds get deterministic tier-0 tokens.
    Media-like source kinds must declare both ``provenance_token`` and
    ``content_risk`` inside ``params`` or they fail closed.
    """

    params = getattr(source, "params", {}) or {}
    source_id = str(getattr(source, "id", "unknown-source"))
    kind = str(getattr(source, "kind", "unknown"))
    backend = str(getattr(source, "backend", "unknown"))
    token = params.get("provenance_token")
    tier = _coerce_content_risk(params.get("content_risk"))
    if token is None and (kind in _SAFE_SOURCE_KINDS or backend in _SAFE_BACKENDS):
        token = _stable_token("visual:source", source_id, kind, backend)
        tier = "tier_0_owned"
    return BroadcastManifestAsset(
        token=str(token) if token else None,
        tier=tier,
        source=f"compositor:{source_id}",
        medium="visual",
        label=source_id,
        broadcast_safe=bool(params.get("broadcast_safe", token is not None)),
    )


def visual_asset_from_camera_role(role: str) -> BroadcastManifestAsset:
    """Return a tier-0 hardware-capture token for a configured camera role."""

    return BroadcastManifestAsset(
        token=_stable_token("visual:camera", role),
        tier="tier_0_owned",
        source=f"camera:{role}",
        medium="visual",
        label=role,
        broadcast_safe=True,
    )


def read_music_provenance_asset(
    path: Path = DEFAULT_MUSIC_PROVENANCE_PATH,
) -> BroadcastManifestAsset | None:
    """Read current music provenance sidecar, if one exists."""

    if not path.exists():
        return None
    try:
        from shared.music.provenance import MusicManifestAsset

        asset = MusicManifestAsset.model_validate_json(path.read_text(encoding="utf-8"))
        return audio_asset_from_music_manifest(asset)
    except Exception:
        return BroadcastManifestAsset(
            token=None,
            tier="tier_4_risky",
            source=f"music-provenance:{path}",
            medium="audio",
            label="invalid-music-provenance",
            broadcast_safe=False,
        )


def write_broadcast_manifest(
    manifest: BroadcastProvenanceManifest,
    path: Path = DEFAULT_BROADCAST_MANIFEST_PATH,
) -> None:
    """Atomically write the broadcast provenance manifest."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)


def read_broadcast_manifest(
    path: Path = DEFAULT_BROADCAST_MANIFEST_PATH,
) -> BroadcastProvenanceManifest | None:
    """Read a manifest, returning ``None`` when no manifest has been published."""

    if not path.exists():
        return None
    return BroadcastProvenanceManifest.model_validate_json(path.read_text(encoding="utf-8"))


class EgressManifestGate:
    """Fail-closed gate for broadcast provenance manifests."""

    def __init__(
        self,
        *,
        manifest_path: Path = DEFAULT_BROADCAST_MANIFEST_PATH,
        kill_switch_path: Path = DEFAULT_KILL_SWITCH_PATH,
        impingement_path: Path = DEFAULT_IMPINGEMENT_PATH,
        producer_id: str = "egress_manifest_gate",
        notify_fn: Callable[..., Any] | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self.manifest_path = manifest_path
        self.kill_switch_path = kill_switch_path
        self.impingement_path = impingement_path
        self.producer_id = producer_id
        self.notify_fn = notify_fn
        self.now_fn = now_fn or time.time

    def evaluate(self, manifest: BroadcastProvenanceManifest) -> EgressGateDecision:
        """Return the fail-closed decision for ``manifest`` without I/O."""

        offenders = tuple(_offenders(manifest))
        if not offenders:
            return EgressGateDecision(
                kill_switch_fired=False,
                max_content_risk=manifest.max_content_risk,
                audio_action="pass_through",
                visual_action="pass_through",
            )
        return EgressGateDecision(
            kill_switch_fired=True,
            max_content_risk=manifest.max_content_risk,
            offenders=offenders,
            audio_action="duck_to_negative_infinity",
            visual_action="crossfade_to_tier0_fallback_shader",
            impingement=self._impingement(manifest, offenders),
            notification=_notification(offenders),
        )

    def apply(self, decision: EgressGateDecision) -> None:
        """Apply the decision's side effects."""

        already_active = self._already_active_for(decision)
        self._write_kill_switch(decision)
        if not decision.kill_switch_fired:
            return
        if already_active:
            return
        if decision.impingement is not None:
            self._write_impingement(decision.impingement)
        if decision.notification is not None:
            self._notify(decision.notification)

    def tick(
        self,
        manifest: BroadcastProvenanceManifest | None = None,
    ) -> EgressGateDecision | None:
        """Read/evaluate/apply one egress gate tick."""

        current = manifest or read_broadcast_manifest(self.manifest_path)
        if current is None:
            return None
        decision = self.evaluate(current)
        self.apply(decision)
        return decision

    def _impingement(
        self,
        manifest: BroadcastProvenanceManifest,
        offenders: tuple[EgressOffender, ...],
    ) -> Impingement:
        return Impingement(
            timestamp=self.now_fn(),
            source="egress_manifest_gate",
            type=ImpingementType.ABSOLUTE_THRESHOLD,
            strength=1.0,
            interrupt_token="egress.kill_switch_fired",
            content={
                "metric": "egress.kill_switch_fired",
                "tick_id": manifest.tick_id,
                "producer_id": self.producer_id,
                "max_content_risk": manifest.max_content_risk,
                "audio_action": "duck_to_negative_infinity",
                "visual_action": "crossfade_to_tier0_fallback_shader",
                "offenders": [offender.model_dump(mode="json") for offender in offenders],
            },
            context={
                "manifest_path": str(self.manifest_path),
                "authority_ceiling": manifest.authority_ceiling.model_dump(mode="json"),
            },
        )

    def _write_kill_switch(self, decision: EgressGateDecision) -> None:
        self.kill_switch_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.kill_switch_path.with_suffix(self.kill_switch_path.suffix + ".lock")
        with lock_path.open("a+", encoding="utf-8") as lock_fh:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            try:
                producer_states = self._read_producer_states()
                now = self.now_fn()
                producer_states[self.producer_id] = EgressProducerKillSwitchState(
                    producer_id=self.producer_id,
                    active=decision.kill_switch_fired,
                    updated_at=now,
                    audio_action=decision.audio_action,
                    visual_action=decision.visual_action,
                    offenders=decision.offenders,
                )
                state = self._global_kill_switch_state(producer_states, updated_at=now)
                tmp = self.kill_switch_path.with_suffix(self.kill_switch_path.suffix + ".tmp")
                tmp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
                tmp.replace(self.kill_switch_path)
            finally:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)

    def _already_active_for(self, decision: EgressGateDecision) -> bool:
        if not decision.kill_switch_fired or not self.kill_switch_path.exists():
            return False
        try:
            previous = self._read_producer_states().get(self.producer_id)
        except Exception:
            return False
        return bool(previous and previous.active and previous.offenders == decision.offenders)

    def _read_producer_states(self) -> dict[str, EgressProducerKillSwitchState]:
        if not self.kill_switch_path.exists():
            return {}
        state = EgressKillSwitchState.model_validate_json(
            self.kill_switch_path.read_text(encoding="utf-8")
        )
        if state.producer_states:
            return dict(state.producer_states)
        if not state.active:
            return {}
        return {
            LEGACY_PRODUCER_ID: EgressProducerKillSwitchState(
                producer_id=LEGACY_PRODUCER_ID,
                active=state.active,
                updated_at=state.updated_at,
                audio_action=state.audio_action,
                visual_action=state.visual_action,
                offenders=state.offenders,
            )
        }

    @staticmethod
    def _global_kill_switch_state(
        producer_states: dict[str, EgressProducerKillSwitchState],
        *,
        updated_at: float,
    ) -> EgressKillSwitchState:
        ordered_states = {
            producer_id: producer_states[producer_id] for producer_id in sorted(producer_states)
        }
        active_states = tuple(state for state in ordered_states.values() if state.active)
        active = bool(active_states)
        return EgressKillSwitchState(
            active=active,
            updated_at=updated_at,
            audio_action="duck_to_negative_infinity" if active else "pass_through",
            visual_action="crossfade_to_tier0_fallback_shader" if active else "pass_through",
            offenders=tuple(
                offender
                for producer_state in active_states
                for offender in producer_state.offenders
            ),
            producer_states=ordered_states,
        )

    def _write_impingement(self, impingement: Impingement) -> None:
        self.impingement_path.parent.mkdir(parents=True, exist_ok=True)
        with self.impingement_path.open("a", encoding="utf-8") as fh:
            fh.write(impingement.model_dump_json() + "\n")

    def _notify(self, notification: EgressNotification) -> None:
        notify_fn = self.notify_fn
        if notify_fn is None:
            try:
                from shared.notify import send_notification

                notify_fn = send_notification
            except Exception:
                return
        try:
            notify_fn(
                notification.title,
                notification.body,
                priority=notification.priority,
                tags=list(notification.tags),
            )
        except Exception:
            return


def _offenders(manifest: BroadcastProvenanceManifest) -> list[EgressOffender]:
    max_rank = content_risk_rank(manifest.max_content_risk)
    offenders: list[EgressOffender] = []
    for asset in (*manifest.audio_assets, *manifest.visual_assets):
        reason: Literal["missing_token", "over_tier", "not_broadcast_safe"] | None = None
        if not asset.token:
            reason = "missing_token"
        elif not asset.broadcast_safe:
            reason = "not_broadcast_safe"
        elif content_risk_rank(asset.tier) > max_rank:
            reason = "over_tier"
        if reason is None:
            continue
        offenders.append(
            EgressOffender(
                token=asset.token,
                tier=asset.tier,
                source=asset.source,
                medium=asset.medium,
                reason=reason,
            )
        )
    return offenders


def _notification(offenders: tuple[EgressOffender, ...]) -> EgressNotification:
    first = offenders[0]
    token = first.token or "<missing>"
    extra = f" (+{len(offenders) - 1} more)" if len(offenders) > 1 else ""
    return EgressNotification(
        title="Egress provenance kill-switch fired",
        body=(
            f"{first.medium} source {first.source} blocked: {first.reason}; "
            f"token={token}; tier={first.tier}{extra}"
        ),
    )


def _stable_token(prefix: str, *parts: str) -> str:
    payload = "\x00".join(part.strip() for part in parts)
    digest = uuid.uuid5(uuid.NAMESPACE_URL, payload).hex[:20]
    return f"{prefix}:{digest}"


def _coerce_content_risk(raw: Any) -> ContentRisk:
    if raw in _CONTENT_RISK_VALUES:
        return cast("ContentRisk", raw)
    return "tier_4_risky"


__all__ = [
    "DEFAULT_BROADCAST_MANIFEST_PATH",
    "DEFAULT_IMPINGEMENT_PATH",
    "DEFAULT_KILL_SWITCH_PATH",
    "DEFAULT_MUSIC_PROVENANCE_PATH",
    "DEFAULT_PROGRAMME_MAX_CONTENT_RISK",
    "PROGRAMME_MAX_CONTENT_RISK_ENV",
    "BroadcastAuthorityCeiling",
    "BroadcastManifestAsset",
    "BroadcastProvenanceManifest",
    "ContentMedium",
    "EgressGateDecision",
    "EgressKillSwitchState",
    "EgressManifestGate",
    "EgressNotification",
    "EgressOffender",
    "EgressProducerKillSwitchState",
    "audio_asset_from_music_manifest",
    "build_broadcast_manifest",
    "content_risk_rank",
    "max_content_risk_from_env",
    "read_broadcast_manifest",
    "read_music_provenance_asset",
    "visual_asset_from_camera_role",
    "visual_asset_from_source_schema",
    "visual_asset_from_visual_pool_asset",
    "write_broadcast_manifest",
]
