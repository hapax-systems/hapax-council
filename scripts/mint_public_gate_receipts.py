#!/usr/bin/env python3
"""Mint the per-gate public-gate receipts for a vault artifact from its signed quorum acceptance.

An immutable prepared draft can omit clearance and receipt claims. ``--receipt-map``
provides only external gate-to-ref mint destinations; the current signed dossier must
still authorize every gate and ref for this exact path, bytes and public projection.
The same read-only validation supports the publisher's external-clearance mode.

Its review authority is the review team's signed ``.review-dossier.yaml`` over the artifact's
manifest head (``artifact-sha256:<64-hex>``). It refuses before writing anything on an acceptance
that is unsigned, below quorum, or whose accepting families distinct from the writer's do not meet
the quorum, or whose head, bindings, or gate authorizations do not hold.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

import yaml

from scripts import publish_vault_artifact as publish
from shared import public_gate_receipts
from shared.review_artifact_manifest import (
    ARTIFACT_HEAD_PREFIX,
    artifact_head_sha,
    changed_manifest_paths,
)
from shared.secrets import SecretUnavailable, get_secret

AUTHORITY_SECRET_NAME = "hapax-public-gate-authority-hmac-key"  # pragma: allowlist secret
DOSSIER_SUFFIX = ".review-dossier.yaml"
DEFAULT_REVIEW_PROFILE = "claim_verification_council_public_egress"
ACCEPTING_VERDICTS = frozenset({"accept", "accept-with-findings"})


class MintError(RuntimeError):
    """The receipts cannot be minted; messages retain reason codes and repair guidance."""


def _texts(data: Mapping, key: str) -> list[str]:
    value = data.get(key)
    value = [value] if isinstance(value, str) else value
    if not isinstance(value, Iterable) or isinstance(value, (bytes, bytearray, Mapping)):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _receipt_suffix(ref: str) -> str:
    text = ref.strip()
    for prefix in public_gate_receipts.PUBLIC_GATE_RECEIPT_PREFIXES:
        if text.casefold().startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    else:
        raise MintError(f"mint_public_gate_receipt_ref_malformed:{text}")
    suffix = Path(text).suffix.casefold()
    if public_gate_receipts.PUBLIC_GATE_RECEIPT_SUFFIX_RE.fullmatch(text) is None or (
        suffix and suffix not in public_gate_receipts.PUBLIC_GATE_RECEIPT_EXTENSIONS
    ):
        raise MintError(f"mint_public_gate_receipt_ref_malformed:{text}")
    return text if suffix else f"{text}.yaml"


def _write_receipt(path: Path, payload: Mapping) -> str:
    text = yaml.safe_dump(dict(payload), sort_keys=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.read_text(encoding="utf-8") == text:
            return "unchanged"
        raise MintError(f"mint_public_gate_receipt_exists:{path.name}") from None
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(text)
    return "written"


def _validate(dossier: Mapping, secret: str, artifact_root: Path) -> tuple[str, dict]:
    if dossier.get("dossier_schema") != 1:
        raise MintError("mint_public_gate_dossier_schema")
    if not public_gate_receipts.public_gate_authority_evidence_signed(dossier, secret):
        raise MintError("mint_public_gate_acceptance_unsigned")
    if str(dossier.get("review_team_verdict") or "").strip().casefold() != "quorum-accept":
        raise MintError("mint_public_gate_not_quorum_accept")
    quorum, count = dossier.get("quorum_required"), dossier.get("accept_count")
    if not isinstance(quorum, int) or not isinstance(count, int) or count < quorum:
        raise MintError(f"mint_public_gate_quorum_not_met:{count}/{quorum}")
    if quorum < 1:
        # The validator refuses quorum_required < 1 (shared.public_gate_receipts, the dossier
        # evidence rule). A minter that accepted it would write zero-independence receipts
        # create-once and the validator would then refuse the dossier, wedging the refs. Refuse
        # here, before the independence check, so the floor matches the validator's.
        raise MintError(f"mint_public_gate_quorum_below_floor:{quorum}")
    accepting = [
        str(r.get("family") or "").strip().casefold()
        for r in dossier.get("reviewers") or []
        if isinstance(r, Mapping) and str(r.get("verdict") or "").casefold() in ACCEPTING_VERDICTS
    ]
    accepting = [family for family in accepting if family]
    writer = str(dossier.get("writer_family") or "").strip().casefold()
    if not accepting or not writer:
        raise MintError("mint_public_gate_acceptor_unresolved")
    # Independence counts the validator's allowlist, imported rather than copied: a family alias,
    # typo or seat id must not count where the validator would not count it. The writer's family is
    # refused outright when it is outside the allowlist, so "the writer counts nowhere" cannot be
    # dodged by an alias.
    allowlisted = public_gate_receipts.PUBLIC_GATE_INDEPENDENT_REVIEW_FAMILIES
    if writer not in allowlisted:
        raise MintError(f"mint_public_gate_writer_family_not_allowlisted:{writer}")
    # A public-gate receipt must not let the writer's family contribute to quorum.
    independent = {family for family in accepting if family in allowlisted and family != writer}
    if len(independent) < quorum:
        raise MintError(f"mint_public_gate_quorum_not_independent:{len(independent)}/{quorum}")
    head = str(dossier.get("head_sha") or "").strip().casefold()
    review = dossier.get("artifact_review")
    manifest = review.get("manifest") if isinstance(review, Mapping) else None
    if not head.startswith(ARTIFACT_HEAD_PREFIX):
        raise MintError("mint_public_gate_head_not_an_artifact_head")
    if not isinstance(manifest, list) or not manifest:
        raise MintError("mint_public_gate_manifest_missing")
    signed_root = review.get("artifact_root")
    try:
        if not isinstance(signed_root, str) or not Path(signed_root).is_absolute():
            raise ValueError("signed root must be an absolute path")
        reviewed_root = Path(signed_root).resolve(strict=True)
        caller_root = artifact_root.expanduser().resolve(strict=True)
        if not reviewed_root.is_dir() or reviewed_root != caller_root:
            raise ValueError("caller root differs from signed root")
    except (OSError, RuntimeError, ValueError) as exc:
        raise MintError(
            f"mint_public_gate_artifact_root_mismatch:{artifact_root}; next action: use the "
            "signed artifact_review.artifact_root and reviewed path, or obtain fresh "
            "exact-root acceptance; preserve existing receipts"
        ) from exc
    if artifact_head_sha(manifest) != head:
        raise MintError("mint_public_gate_head_manifest_mismatch")
    changed = changed_manifest_paths(manifest, artifact_root)
    if changed:
        raise MintError("mint_public_gate_artifact_changed:" + ",".join(changed))
    bindings = {
        "artifact_slug": str(dossier.get("artifact_slug") or "").strip(),
        "artifact_fingerprint": str(dossier.get("artifact_fingerprint") or "").strip(),
        "target_surfaces": sorted(_texts(dossier, "target_surfaces")),
    }
    if not all(bindings.values()):
        raise MintError("mint_public_gate_bindings_missing")
    return head, bindings


def _check_gates(declared: Mapping[str, str], required: Iterable[str], dossier: Mapping) -> None:
    gates = set(_texts(dossier, "required_gates"))
    refs = {_receipt_suffix(ref) for ref in _texts(dossier, "authorized_public_gate_receipts")}
    if not gates or not refs:
        raise MintError("mint_public_gate_acceptance_unbound")
    suffixes = [_receipt_suffix(ref) for ref in declared.values()]
    if len(set(suffixes)) != len(suffixes):
        # Two gates sharing one ref would pass the set comparisons below and then write the first
        # receipt, hold on the second (different bytes, same path) and leave a partial mint. Refuse
        # the pairing before any write.
        raise MintError("mint_public_gate_receipt_pairing_not_injective")
    missing = sorted(gate for gate in required if gate not in gates)
    if missing:
        raise MintError("mint_public_gate_missing:" + ",".join(missing))
    if sorted(gates) != sorted(declared):
        raise MintError("mint_public_gate_undeclared:" + ",".join(sorted(gates)))
    if {_receipt_suffix(ref) for ref in declared.values()} != refs:
        raise MintError("mint_public_gate_receipt_unauthorized")


def validate_artifact_acceptance(
    *,
    task_id: str,
    artifact: Path,
    artifact_root: Path,
    surfaces: list[str] | None = None,
    authority_roots: Iterable[Path] | None = None,
    receipt_refs: Mapping[str, str] | None = None,
) -> tuple[dict, str, dict, dict[str, str]]:
    """Read and check existing authority; never mint, approve, or mutate the subject."""
    if not task_id or Path(task_id).name != task_id or task_id in {".", ".."}:
        raise MintError(
            "mint_public_gate_task_malformed; next action: provide the review task identifier "
            "without a directory or traversal components"
        )
    dossier_path = None
    for root in authority_roots or public_gate_receipts.PUBLIC_GATE_AUTHORITY_ROOTS:
        candidate = Path(root).expanduser() / f"{task_id}{DOSSIER_SUFFIX}"
        if candidate.is_file():
            dossier_path = candidate
            break
    if dossier_path is None:
        raise MintError("mint_public_gate_acceptance_missing")
    try:
        dossier = yaml.safe_load(dossier_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise MintError(
            f"mint_public_gate_unreadable:{dossier_path.name}; next action: restore the "
            "readable UTF-8 signed dossier from its authority source; do not edit receipts"
        ) from exc
    if not isinstance(dossier, dict):
        raise MintError(f"mint_public_gate_malformed:{dossier_path.name}")
    if str(dossier.get("task_id") or "").strip() != task_id:
        raise MintError("mint_public_gate_task_mismatch")
    try:
        secret = get_secret(
            AUTHORITY_SECRET_NAME,
            env=public_gate_receipts.PUBLIC_GATE_AUTHORITY_SECRET_ENV,
            required=False,
        )
    except SecretUnavailable as exc:
        raise MintError(f"mint_public_gate_authority_secret_unavailable:{exc.name}") from exc
    if not secret or not secret.strip():
        raise MintError(f"mint_public_gate_authority_secret_unavailable:{AUTHORITY_SECRET_NAME}")
    secret = secret.strip()
    head, bindings = _validate(dossier, secret, artifact_root)

    current_head = public_gate_receipts.vault_artifact_expected_head_sha(artifact, artifact_root)
    if current_head != head:
        raise MintError(
            f"mint_public_gate_subject_head_mismatch:{artifact}; next action: select the "
            "accepted path under the signed artifact root or obtain fresh exact-subject "
            "acceptance; preserve existing receipts"
        )
    frontmatter, body = publish._parse_publication_markdown(artifact)
    if receipt_refs is not None:
        try:
            publish._assert_external_clearance_source(frontmatter)
        except publish.PublicationGateError as exc:
            raise MintError(str(exc)) from exc
        declared = dict(receipt_refs)
    else:
        declared = publish._publication_gate_receipts(frontmatter)
    if not declared:
        raise MintError("mint_public_gate_receipts_missing")
    if any(
        not isinstance(g, str) or not g.strip() or not isinstance(r, str) or not r.strip()
        for g, r in declared.items()
    ):
        raise MintError(
            "mint_public_gate_receipt_map_malformed; next action: supply a UTF-8 YAML "
            "mapping of gate ids to receipt-ref strings authorized by the signed dossier"
        )
    if surfaces is not None and not surfaces:
        raise MintError("mint_public_gate_surfaces_empty")
    targets = surfaces or _texts(frontmatter, "surfaces_targeted") or list(publish.DEFAULT_SURFACES)
    required = publish._required_publication_gate_receipts(targets)
    _check_gates(declared, sorted(required), dossier)
    prepared = publish._prepare_artifact(
        body_md=body, frontmatter=frontmatter, surfaces=targets, source_path=artifact
    )
    observed = publish._publication_gate_receipt_bindings(prepared)
    observed["target_surfaces"] = list(observed["target_surfaces"])
    if observed != bindings:
        raise MintError(
            f"mint_public_gate_subject_bindings_mismatch:{artifact}; next action: use the "
            "accepted slug, fingerprint and target surfaces or obtain fresh exact-subject "
            "acceptance; preserve existing receipts"
        )
    return dossier, head, bindings, declared


def mint(
    *,
    task_id: str,
    artifact: Path,
    artifact_root: Path,
    authority_case: str,
    receipt_root: Path,
    review_profile: str = DEFAULT_REVIEW_PROFILE,
    surfaces: list[str] | None = None,
    authority_roots: Iterable[Path] | None = None,
    receipt_refs: Mapping[str, str] | None = None,
) -> dict[str, object]:
    if public_gate_receipts.PUBLIC_GATE_AUTHORITY_CASE_RE.fullmatch(authority_case) is None:
        raise MintError("mint_public_gate_authority_case_malformed")
    dossier, head, bindings, declared = validate_artifact_acceptance(
        task_id=task_id,
        artifact=artifact,
        artifact_root=artifact_root,
        surfaces=surfaces,
        authority_roots=authority_roots,
        receipt_refs=receipt_refs,
    )
    try:
        secret = get_secret(
            AUTHORITY_SECRET_NAME,
            env=public_gate_receipts.PUBLIC_GATE_AUTHORITY_SECRET_ENV,
            required=False,
        )
    except SecretUnavailable as exc:
        raise MintError(f"mint_public_gate_authority_secret_unavailable:{exc.name}") from exc
    if not secret or not secret.strip():
        raise MintError(f"mint_public_gate_authority_secret_unavailable:{AUTHORITY_SECRET_NAME}")
    secret = secret.strip()
    issuer = str(dossier.get("authority_issuer") or dossier.get("acceptor") or "").strip()
    if not issuer:
        raise MintError("mint_public_gate_acceptor_unresolved")
    summary: dict[str, object] = {"task_id": task_id, "head_sha": head, "receipts": {}}
    for gate, ref in declared.items():
        payload = {
            "gate_id": gate,
            "status": "passed",
            "authority_case": authority_case,
            "acceptor": issuer,
            "review_profile": review_profile,
            "evidence_ref": f"review-dossier:{task_id}",
            "head_sha": head,
            "authority_issuer": issuer,
            **bindings,
        }
        payload["authority_signature"] = public_gate_receipts.public_gate_authority_signature(
            payload, secret
        )
        path = Path(receipt_root).expanduser() / _receipt_suffix(ref)
        summary["receipts"][gate] = {
            "ref": ref,
            "path": str(path),
            "state": _write_receipt(path, payload),
        }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scripts.mint_public_gate_receipts",
        description="Mint per-gate public-gate receipts from a signed vault-artifact acceptance.",
    )
    parser.add_argument("--task-id", required=True, help="cc-task owning the review dossier")
    parser.add_argument("--artifact", type=Path, required=True, help="Vault artifact file")
    parser.add_argument("--artifact-root", type=Path, default=publish.VAULT_ARTIFACT_ROOT)
    parser.add_argument("--authority-case", required=True, help="CASE-/REQ- case")
    parser.add_argument("--receipt-root", type=Path, default=publish.PUBLIC_GATE_RECEIPT_ROOTS[0])
    parser.add_argument(
        "--receipt-map",
        type=Path,
        help="External gate-to-ref YAML declaration for an immutable draft",
    )
    args = parser.parse_args(argv)
    try:
        summary = mint(
            task_id=args.task_id,
            artifact=args.artifact.expanduser(),
            artifact_root=args.artifact_root.expanduser(),
            authority_case=args.authority_case,
            receipt_root=args.receipt_root,
            receipt_refs=publish._read_receipt_map(args.receipt_map) if args.receipt_map else None,
        )
    except (MintError, publish.PublicationGateError) as exc:
        print(f"mint-public-gate-receipts: HOLD — {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
