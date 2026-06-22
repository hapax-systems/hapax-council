"""AVSDLC runtime-witness receipt emission (Tier-C producer side).

The independent runtime-witness observes the live substrate + OBS, computes a
deterministic content hash over the *deployed* gamedir bytes, and emits an
HMAC-signed :class:`~shared.governance.coord_capabilities.AVWitnessReceipt`.
The release gate VERIFIES that receipt; the witness is the only legitimate
minter (independent-executor parity with CI — the authoring session cannot mint
its own visual verdict).

A genuine PASS binds two facts: the witness ``overall == "PASS"`` (no freeze /
stale producer / causality break) AND the OBS *source* verdict is ``MOVING``
(the change actually reached air). This module is intentionally dependency-light
and importable so the witness script, the daemon, and the gate share one
implementation; the heavy substrate/OBS sampling lives in ``screwm-cns-witness``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from shared.governance.coord_capabilities import (
    AVWitnessReceipt,
    mint_av_witness_receipt,
    serialize_av_receipt,
)

#: Default short freshness for a runtime witness — a receipt is a live signal,
#: not a durable artifact. Verification rejects anything older.
DEFAULT_RECEIPT_TTL_SECONDS = 30 * 60


def gamedir_content_hash(root: str | Path) -> str:
    """Deterministic sha256 over every regular file under ``root`` (sorted by
    relative path, path + bytes folded in). Same bytes -> same hash regardless of
    filesystem iteration order; a renamed or mutated file changes the hash.

    Symlinks are SKIPPED (they could pull bytes from outside the gamedir into the
    binding). Returns "" when the directory is absent OR contains no real deployed
    bytes — an empty result means the witness saw nothing and the caller must
    treat the receipt as unverifiable."""
    base = Path(root)
    if not base.is_dir():
        return ""
    files = sorted(p for p in base.rglob("*") if p.is_file() and not p.is_symlink())
    if not files:
        return ""
    digest = hashlib.sha256()
    for path in files:
        rel = path.relative_to(base).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<unreadable>")
        digest.update(b"\0")
    return digest.hexdigest()


def read_active_source_head(current_json: str | Path) -> str:
    """Read ``active_source_head`` from the deploy ``current.json``. Never
    raises; returns "" when absent/unparseable (the detached/dirty deploy tree
    has no clean SHA, so the content hash is the primary binding)."""
    try:
        data = json.loads(Path(current_json).read_text(encoding="utf-8"))
        return str(data.get("active_source_head", ""))
    except Exception:  # noqa: BLE001 — a missing/malformed file must not raise.
        return ""


def receipt_status_from_manifest(manifest: Mapping[str, Any]) -> tuple[str, bool]:
    """Map a ``screwm-cns-witness`` manifest to ``(status, obs_moving)``.

    ``status`` is "pass" only when the witness overall verdict is PASS. The OBS
    *source* must be MOVING for the change to count as having reached air; a
    frozen / unavailable OBS source is ``obs_moving = False`` even on a PASS."""
    overall = str(manifest.get("overall", "")).strip().upper()
    status = "pass" if overall == "PASS" else "fail"
    obs = manifest.get("obs")
    source = obs.get("source") if isinstance(obs, Mapping) else None
    obs_moving = isinstance(source, Mapping) and str(source.get("verdict", "")).upper() == "MOVING"
    return status, obs_moving


def via_from_manifest(manifest: Mapping[str, Any]) -> str:
    """The capture instrument that produced the OBS verdict (e.g. obs-websocket).
    Empty when OBS was not the capture path — the gate can reject that under
    ``require_via``."""
    obs = manifest.get("obs")
    if isinstance(obs, Mapping):
        return str(obs.get("via", ""))
    return ""


def perceptual_digest_from_manifest(manifest: Mapping[str, Any]) -> str:
    """Deterministic sha256 over the witness's per-region / per-artifact perceptual
    stats — so the receipt BINDS the perceptual evidence instead of discarding it.
    Returns "" when the manifest carries no perceptual stats (nothing to bind)."""
    stats: dict[str, Any] = {}
    substrate = manifest.get("substrate")
    if isinstance(substrate, Mapping):
        for name in sorted(substrate):
            entry = substrate[name]
            if isinstance(entry, Mapping):
                stats[f"substrate.{name}"] = [
                    entry.get("spatial_var"),
                    entry.get("temporal_zone_moving_frac"),
                    entry.get("byte_mad"),
                ]
    obs = manifest.get("obs")
    if isinstance(obs, Mapping):
        for kind in sorted(obs):
            entry = obs[kind]
            if isinstance(entry, Mapping) and "mean_consecutive_delta" in entry:
                stats[f"obs.{kind}"] = [
                    entry.get("mean_consecutive_delta"),
                    entry.get("max_consecutive_delta"),
                    entry.get("distinct"),
                ]
    if not stats:
        return ""
    blob = json.dumps(stats, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def build_receipt_from_witness(
    manifest: Mapping[str, Any],
    *,
    content_hash: str,
    active_source_head: str,
    ttl_s: float,
    key: bytes,
    now: float,
) -> AVWitnessReceipt:
    """Build (mint) a signed receipt from a witness manifest + deployed-bytes
    binding. The witness daemon is the only legitimate caller."""
    status, obs_moving = receipt_status_from_manifest(manifest)
    return mint_av_witness_receipt(
        content_hash=content_hash,
        active_source_head=active_source_head,
        status=status,
        obs_moving=obs_moving,
        ttl_s=ttl_s,
        key=key,
        now=now,
        via=via_from_manifest(manifest),
        perceptual_digest=perceptual_digest_from_manifest(manifest),
    )


def emit_receipt(
    *,
    gamedir: str | Path,
    current_json: str | Path,
    manifest: Mapping[str, Any],
    out_path: str | Path,
    key: bytes,
    ttl_s: float = DEFAULT_RECEIPT_TTL_SECONDS,
    now: float,
) -> AVWitnessReceipt:
    """Compute the gamedir content hash + active source head, mint a signed
    receipt from the witness manifest, write it to ``out_path``, and return it."""
    receipt = build_receipt_from_witness(
        manifest,
        content_hash=gamedir_content_hash(gamedir),
        active_source_head=read_active_source_head(current_json),
        ttl_s=ttl_s,
        key=key,
        now=now,
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(serialize_av_receipt(receipt), encoding="utf-8")
    return receipt
