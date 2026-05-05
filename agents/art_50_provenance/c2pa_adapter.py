"""Optional c2pa-python binding for Article 50 credentials.

The default CI/runtime path does not require ``c2pa-python`` or private signer
material. Production bootstrap can pass signer paths after the operator has
procured/provisioned the C2PA claim-signing substrate. Until then, the adapter
returns explicit blocked states instead of silently pretending an unsigned
manifest is a trusted Content Credential.
"""

from __future__ import annotations

import importlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.art_50_provenance.models import C2paBinding, C2paSigningState


@dataclass(frozen=True)
class SignerMaterial:
    """Filesystem references for claim-signing material.

    Paths are references only. This package never stores key bytes in a
    certificate packet, log message, or task note.
    """

    cert_chain_path: Path
    private_key_path: Path
    algorithm: str = "ES256"
    timestamp_authority_url: str | None = None


def c2pa_python_available() -> bool:
    """Return True when the optional ``c2pa`` Python module is importable."""

    return importlib.util.find_spec("c2pa") is not None


def sign_with_c2pa_python(
    *,
    manifest: dict[str, Any],
    mime_type: str,
    asset_bytes: bytes,
    signer: SignerMaterial | None,
) -> tuple[C2paBinding, bytes]:
    """Sign ``asset_bytes`` with ``c2pa-python`` when runtime prerequisites exist.

    Returns ``(binding, output_bytes)``. On blocked paths, ``output_bytes`` is the
    input asset so callers can still write a visibly watermarked dry-run packet.
    """

    manifest_json = json.dumps(manifest, sort_keys=True)
    if not c2pa_python_available():
        return (
            C2paBinding(
                status=C2paSigningState.BLOCKED_MISSING_C2PA,
                manifest=manifest,
                detail="c2pa-python is not installed in this runtime",
            ),
            asset_bytes,
        )

    if signer is None:
        return (
            C2paBinding(
                status=C2paSigningState.BLOCKED_MISSING_SIGNER,
                manifest=manifest,
                detail="claim-signing certificate/private key material not configured",
            ),
            asset_bytes,
        )

    if not signer.cert_chain_path.is_file() or not signer.private_key_path.is_file():
        return (
            C2paBinding(
                status=C2paSigningState.BLOCKED_MISSING_SIGNER,
                manifest=manifest,
                detail="claim-signing certificate/private key path is missing",
            ),
            asset_bytes,
        )

    try:
        c2pa = importlib.import_module("c2pa")
        certs = signer.cert_chain_path.read_bytes()
        key = signer.private_key_path.read_bytes()
        alg = getattr(c2pa.C2paSigningAlg, signer.algorithm)
        signer_info = c2pa.C2paSignerInfo(
            alg=alg,
            sign_cert=certs,
            private_key=key,
            ta_url=(
                signer.timestamp_authority_url.encode("utf-8")
                if signer.timestamp_authority_url
                else None
            ),
        )
        c2pa_signer = c2pa.Signer.from_info(signer_info)
        context = c2pa.Context.from_dict(
            {"builder": {"thumbnail": {"enabled": True}}},
            signer=c2pa_signer,
        )
        builder = c2pa.Builder(manifest_json, context=context)
        src = io.BytesIO(asset_bytes)
        dst = io.BytesIO()
        builder.sign(mime_type, src, dst)
    except Exception as exc:  # pragma: no cover - exercised only with c2pa installed
        return (
            C2paBinding(
                status=C2paSigningState.SIGNING_ERROR,
                manifest=manifest,
                detail=f"c2pa-python signing failed: {type(exc).__name__}",
            ),
            asset_bytes,
        )

    signed = dst.getvalue()
    return (
        C2paBinding(
            status=C2paSigningState.SIGNED_EMBEDDED,
            manifest=manifest,
            signed_asset_sha256=None,
            detail="signed and embedded with c2pa-python",
        ),
        signed,
    )


__all__ = ["SignerMaterial", "c2pa_python_available", "sign_with_c2pa_python"]
