"""Local certificate packet storage for the verification route."""

from __future__ import annotations

import os
from pathlib import Path

from agents.art_50_provenance.models import Art50CredentialCertificate

STATE_ENV = "HAPAX_STATE"
CERT_SUBDIR = "art-50/credentials"


def default_state_root() -> Path:
    env = os.environ.get(STATE_ENV, "").strip()
    return Path(env).expanduser() if env else Path.home() / "hapax-state"


def credential_dir(*, state_root: Path | None = None) -> Path:
    return (state_root or default_state_root()) / CERT_SUBDIR


def credential_path(credential_id: str, *, state_root: Path | None = None) -> Path:
    return credential_dir(state_root=state_root) / f"{credential_id}.json"


def write_certificate(
    certificate: Art50CredentialCertificate,
    *,
    state_root: Path | None = None,
) -> Path:
    target = credential_path(certificate.credential_id, state_root=state_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(certificate.model_dump_json(indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


def load_certificate(
    credential_id: str,
    *,
    state_root: Path | None = None,
) -> Art50CredentialCertificate | None:
    path = credential_path(credential_id, state_root=state_root)
    if not path.is_file():
        return None
    return Art50CredentialCertificate.model_validate_json(path.read_text(encoding="utf-8"))


__all__ = [
    "CERT_SUBDIR",
    "STATE_ENV",
    "credential_dir",
    "credential_path",
    "default_state_root",
    "load_certificate",
    "write_certificate",
]
