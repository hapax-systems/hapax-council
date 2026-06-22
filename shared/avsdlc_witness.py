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


def intent_fields_from_record_and_frame(
    declared_record: Mapping[str, Any] | str,
    frame: Any,
    pov_label: str,
) -> tuple[str, bool]:
    """Compute ``(intent_hash, intent_pass)`` for a declared ``VisualIntentRecord``
    against the REALIZED per-region vector derived from one captured frame.

    The independent runtime-witness calls this to bind the prediction's verdict
    into the receipt: ``intent_hash`` is the canonical hash of the declared record
    (the gate re-derives it from the frontmatter and demands equality, so a verdict
    minted against a different prediction cannot replay in), and ``intent_pass`` is
    the witness's verdict — did the realized vector satisfy the pre-authored
    predicates? Returns ``("", False)`` when the record is unparseable (the witness
    binds no intent; under ``require_intent`` the gate then treats it as unconfirmed).

    ``frame`` is a numpy array (HxWx3/4); numpy is imported lazily so this
    dependency-light module stays importable without it."""
    from shared.avsdlc_realized_vector import realized_vector_from_frame
    from shared.avsdlc_visual_intent import (
        intent_hash_from_record,
        intent_pass,
        parse_intent_record,
    )

    record = parse_intent_record(declared_record)
    if record is None:
        return "", False
    declared_hash = intent_hash_from_record(record)
    try:
        realized = realized_vector_from_frame(frame, pov_label)
    except Exception:  # noqa: BLE001 — a malformed/missing frame must never crash the observe path.
        return declared_hash, False
    return declared_hash, intent_pass(record, realized)


def build_receipt_from_witness(
    manifest: Mapping[str, Any],
    *,
    content_hash: str,
    active_source_head: str,
    ttl_s: float,
    key: bytes,
    now: float,
    intent_hash: str = "",
    intent_pass: bool = False,
) -> AVWitnessReceipt:
    """Build (mint) a signed receipt from a witness manifest + deployed-bytes
    binding. The witness daemon is the only legitimate caller. ``intent_hash`` +
    ``intent_pass`` bind the independent witness's verdict on the declared
    VisualIntentRecord (empty/False when no record was declared for this release)."""
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
        intent_hash=intent_hash,
        intent_pass=intent_pass,
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
    intent_hash: str = "",
    intent_pass: bool = False,
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
        intent_hash=intent_hash,
        intent_pass=intent_pass,
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(serialize_av_receipt(receipt), encoding="utf-8")
    return receipt
