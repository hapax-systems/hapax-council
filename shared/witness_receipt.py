"""Witness receipt producer: the existing review-dossier shape, bound to one artifact.

A pre-submission record (a lanebus drop) names one artifact by its canonical digest
(``artifact_fingerprint``, the estate's existing binding key) and a nonce, with its audience,
channel, policy ref, validity window, caller-owned expected head, author and evidence. A witness
receipt says that witnesses other than the author, from independent model families, judged the
record ``VALIDATED`` within its window.

The receipt is a ``<task_id>.review-dossier.yaml`` that the existing public-gate resolver
accepts: ``dossier_schema: 1``, the gate, the policy receipt ref, the artifact bindings, a
``quorum-accept`` verdict with ``quorum_required`` (1 for tier B, 2 for tier A) met by distinct
independent families, a ``review-team:`` issuer, and an HMAC signature from the signing holder.

The system checks the witness's identity, independence, timing and signature. It does not check
the witness's judgment. Every refusal writes nothing, and a receipt is written once.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from shared.public_gate_receipts import (
    PUBLIC_GATE_INDEPENDENT_REVIEW_FAMILIES,
    PUBLIC_GATE_RECEIPT_PREFIXES,
    PUBLIC_GATE_REVIEW_DOSSIER_SUFFIX,
)
from shared.signing_holder import SigningRefused, request_signature

GATE = "communication_pathway"
AUTHORITY_ISSUER = "review-team:witness-rota"
VALIDATED = "VALIDATED"
QUORUM = {"A": 2, "B": 1}
_HEX64 = re.compile(r"[0-9a-f]{64}")
_NONCE = re.compile(r"[0-9a-f]{16,64}")
_HEAD = re.compile(r"[0-9a-f]{40}")
_NEXT = "next action: the author re-issues the pre-submission record"


@dataclass(frozen=True)
class Verdict:
    witness: str
    family: str
    semantics: str
    at: datetime
    note: str = ""


@dataclass(frozen=True)
class Produced:
    path: Path | None
    refusals: list[str] = field(default_factory=list)


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _window(record: Mapping[str, Any]) -> tuple[datetime, datetime] | None:
    start, end = _instant(record.get("not_before")), _instant(record.get("not_after"))
    if start is None or end is None:
        return None
    return start, end


def _record_problems(record: Mapping[str, Any]) -> list[str]:
    problems = [
        f"record field {key} is missing"
        for key in ("audience", "channel", "author", "author_family")
        if not isinstance(record.get(key), str) or not record[key].strip()
    ]
    if not _HEX64.fullmatch(str(record.get("artifact_fingerprint", ""))):
        problems.append("artifact_fingerprint is not a sha256 hex digest")
    if not _NONCE.fullmatch(str(record.get("nonce", ""))):
        problems.append("nonce is not 16-64 lowercase hex characters")
    if not _HEAD.fullmatch(str(record.get("expected_head_sha", ""))):
        problems.append("expected_head_sha is not a 40-character commit id")
    if not str(record.get("policy_ref", "")).startswith(PUBLIC_GATE_RECEIPT_PREFIXES):
        problems.append("policy_ref is not a public-gate receipt ref")
    if record.get("tier") not in QUORUM:
        problems.append("tier is not A or B")
    if _window(record) is None:
        problems.append("not_before/not_after is not a valid window")
    return [f"{p}; {_NEXT}" for p in problems]


def _evidence_problems(record: Mapping[str, Any], root: Path) -> list[str]:
    refs = record.get("evidence_refs")
    if not isinstance(refs, list) or not refs:
        return [f"the record names no evidence; {_NEXT}"]
    base = root.resolve()
    problems: list[str] = []
    for ref in refs:
        rel = str(ref.get("path", "")) if isinstance(ref, Mapping) else ""
        path = (base / rel).resolve()
        if not rel or Path(rel).is_absolute() or not path.is_relative_to(base):
            problems.append(f"evidence {rel!r} is outside the evidence root; {_NEXT}")
        elif not path.is_file():
            problems.append(f"evidence {rel} is missing; {_NEXT}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != ref.get("sha256"):
            problems.append(f"evidence {rel} changed since the record; {_NEXT}")
    return problems


def _qualifying(record: Mapping[str, Any], verdicts: Sequence[Verdict]) -> list[Verdict]:
    """VALIDATED verdicts by non-authors from independent families other than the author's."""
    author, author_family = record["author"], record["author_family"].casefold()
    return [
        v
        for v in verdicts
        if v.semantics == VALIDATED
        and v.witness != author
        and v.family.casefold() != author_family
        and v.family.casefold() in PUBLIC_GATE_INDEPENDENT_REVIEW_FAMILIES
    ]


def precheck(record: Mapping[str, Any], *, evidence_root: Path, now: datetime) -> list[str]:
    """Why the record cannot be witnessed now (format, window, evidence); [] when it can."""
    problems = _record_problems(record)
    window = _window(record)
    if problems or window is None:
        return problems
    start, end = window
    if not start <= now <= end:
        return [f"the record's window has closed or not opened; {_NEXT}"]
    return _evidence_problems(record, evidence_root)


def receipt_slot(record: Mapping[str, Any], out_dir: Path) -> tuple[str, Path] | None:
    """The record's task id and receipt path, or None when the record cannot be identified."""
    fingerprint, nonce = str(record.get("artifact_fingerprint", "")), str(record.get("nonce", ""))
    if not _HEX64.fullmatch(fingerprint) or not _NONCE.fullmatch(nonce):
        return None
    task_id = f"witness-{fingerprint[:16]}-{nonce[:16]}"
    return task_id, out_dir / f"{task_id}{PUBLIC_GATE_REVIEW_DOSSIER_SUFFIX}"


def _write_once(path: Path, data: Mapping[str, Any]) -> bool:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        yaml.safe_dump(dict(data), fh, sort_keys=False)
    return True


def record_refusal(
    record: Mapping[str, Any],
    reasons: Sequence[str],
    out_dir: Path,
    *,
    now: datetime,
    execution_identity: Mapping[str, Any] | None = None,
) -> Path | None:
    """Record a refusal (for example "no witness") in the record's receipt slot.

    The resolver never accepts it (the verdict is not ``quorum-accept`` and it is unsigned), and
    it occupies the slot, so a retry needs a new nonce. None when the record cannot be identified
    or the slot is taken.
    """
    slot = receipt_slot(record, out_dir)
    if slot is None:
        return None
    task_id, path = slot
    refusal = {
        "dossier_schema": 1,
        "task_id": task_id,
        "gate": GATE,
        "artifact_fingerprint": record["artifact_fingerprint"],
        "nonce": record["nonce"],
        "author": record.get("author"),
        "review_team_verdict": "refused",
        "refusals": list(reasons),
        "witness_execution": dict(execution_identity or {}),
        "produced_at": now.astimezone(UTC).isoformat(),
    }
    return path if _write_once(path, refusal) else None


def produce(
    record: Mapping[str, Any],
    verdicts: Sequence[Verdict],
    out_dir: Path,
    *,
    evidence_root: Path,
    now: datetime,
    sign: Callable[[Mapping[str, Any]], str] | None = None,
    execution_identity: Mapping[str, Any] | None = None,
) -> Produced:
    """Write one signed witness receipt for the record, or refuse and write nothing."""
    sign = sign or request_signature
    refusals = precheck(record, evidence_root=evidence_root, now=now)
    window = _window(record)
    if refusals or window is None:
        return Produced(None, refusals)
    start, _ = window
    qualifying = _qualifying(record, [v for v in verdicts if start <= v.at <= now])
    families = {v.family.casefold() for v in qualifying}
    quorum = QUORUM[record["tier"]]
    if len(families) < quorum:
        return Produced(
            None,
            [
                f"{len(families)} independent non-author VALIDATED families within the window, "
                f"tier {record['tier']} needs {quorum}; "
                "next action: the rota assigns another witness"
            ],
        )
    fingerprint, nonce = record["artifact_fingerprint"], record["nonce"]
    slot = receipt_slot(record, out_dir)
    if slot is None:
        return Produced(None, [f"the record cannot be identified; {_NEXT}"])
    task_id, path = slot
    dossier: dict[str, Any] = {
        "dossier_schema": 1,
        "task_id": task_id,
        "head_sha": record["expected_head_sha"],
        "gate": GATE,
        "authorized_public_gate_receipts": [record["policy_ref"]],
        "artifact_fingerprint": fingerprint,
        "nonce": nonce,
        "not_before": record["not_before"],
        "not_after": record["not_after"],
        "audience": record["audience"],
        "channel": record["channel"],
        "author": record["author"],
        "author_family": record["author_family"],
        "tier": record["tier"],
        "record_evidence": [dict(ref) for ref in record["evidence_refs"]],
        "review_team_verdict": "quorum-accept",
        "quorum_required": quorum,
        "accept_count": len(families),
        "reviewers": [
            {
                "family": v.family.casefold(),
                "witness": v.witness,
                "verdict": "accept",
                "semantics": v.semantics,
                "at": v.at.astimezone(UTC).isoformat(),
                "note": v.note,
            }
            for v in qualifying
        ],
        "produced_at": now.astimezone(UTC).isoformat(),
        "witness_execution": dict(execution_identity or {}),
        "authority_issuer": AUTHORITY_ISSUER,
    }
    try:
        dossier["authority_signature"] = sign(dossier)
    except (SigningRefused, OSError) as exc:
        return Produced(
            None,
            [f"the signing holder refused: {exc}; next action: run the witness in its rota unit"],
        )
    if not _write_once(path, dossier):
        return Produced(
            None, [f"{path.name} already exists; next action: the author issues a new nonce"]
        )
    return Produced(path)
