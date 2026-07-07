"""Durable public-gate receipt reference validation.

Public-gate receipts are data-plane receipts. Their review authority evidence
must resolve through the trusted cc-task review/acceptance plane, not through a
peer file in the receipt root. There is intentionally no module-level bypass for
public egress; emergency correction or takedown must use the owning surface's
incident path and leave a new authority receipt. For publication-bus artifacts,
that incident path is: withhold or reject the artifact through the publication
state machine, repair the source artifact or target policy, then issue a fresh
signed public-gate authority receipt before any retry.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

PUBLIC_GATE_RECEIPT_PREFIXES: tuple[str, ...] = (
    "public-gate:",
    "public_gate:",
    "receipt:public-gate:",
)
PUBLIC_GATE_RECEIPT_SUFFIX_RE = re.compile(r"\A[a-z0-9][a-z0-9_.+/-]{0,239}\Z", re.IGNORECASE)
PUBLIC_GATE_RECEIPT_EXTENSIONS = frozenset({".json", ".md", ".yaml", ".yml"})
PUBLIC_GATE_AUTHORITY_ROOTS: tuple[Path, ...] = (
    Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active",
    Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "closed",
)
PUBLIC_GATE_REVIEW_DOSSIER_SUFFIX = ".review-dossier.yaml"
PUBLIC_GATE_ACCEPTANCE_RECEIPT_SUFFIX = ".acceptance.yaml"
PUBLIC_GATE_AUTHORITY_SECRET_ENV = "HAPAX_PUBLIC_GATE_AUTHORITY_HMAC_KEY"
PUBLIC_GATE_ID_KEYS = frozenset(
    {
        "gate",
        "gate_id",
        "public_gate",
        "public_gate_id",
        "publication_gate",
        "publication_gate_id",
        "required_gate",
        "required_gate_id",
    }
)
PUBLIC_GATE_LIST_KEYS = frozenset(
    {
        "gates",
        "gate_ids",
        "public_gates",
        "public_gate_ids",
        "publication_gates",
        "publication_gate_ids",
        "required_gates",
        "required_gate_ids",
    }
)
PUBLIC_GATE_OUTCOME_KEYS = frozenset(
    {
        "cleared",
        "decision",
        "outcome",
        "pass",
        "passed",
        "result",
        "status",
        "verdict",
    }
)
PUBLIC_GATE_AUTHORITY_CASE_KEYS = frozenset({"authority_case"})
PUBLIC_GATE_ACCEPTOR_KEYS = frozenset(
    {
        "acceptor",
        "accepted_by",
        "approved_by",
        "authority_acceptor",
        "review_acceptor",
        "reviewed_by",
    }
)
PUBLIC_GATE_REVIEW_PROFILE_KEYS = frozenset(
    {
        "claim_review_profile",
        "quality_floor",
        "review_floor",
        "review_profile",
        "review_required",
    }
)
PUBLIC_GATE_EVIDENCE_REF_KEYS = frozenset(
    {
        "claim_review_evidence_ref",
        "claim_review_evidence_refs",
        "dossier_ref",
        "dossier_refs",
        "evidence_ref",
        "evidence_refs",
        "review_receipt",
        "review_receipts",
    }
)
PUBLIC_GATE_EVIDENCE_RECEIPT_REF_KEYS = frozenset(
    {
        "authorized_public_gate_receipt",
        "authorized_public_gate_receipts",
        "authorized_receipt",
        "authorized_receipts",
        "public_gate_receipt",
        "public_gate_receipts",
        "publication_gate_receipt",
        "publication_gate_receipts",
        "receipt_ref",
        "receipt_refs",
    }
)
PUBLIC_GATE_AUTHORITY_ISSUER_KEYS = frozenset(
    {
        "authority_issuer",
        "issued_by",
        "issuer",
        "signed_by",
    }
)
PUBLIC_GATE_AUTHORITY_SIGNATURE_KEYS = frozenset(
    {
        "authority_signature",
        "hmac_sha256",
        "signature",
        "signature_hmac_sha256",
    }
)
PUBLIC_GATE_TRUSTED_AUTHORITY_ISSUERS = frozenset(
    {
        "claim-verification-council",
        "claim verification council",
    }
)
PUBLIC_GATE_AUTHORITY_SIGNATURE_PREFIX = "hmac-sha256:"
PUBLIC_GATE_AUTHORITY_CASE_RE = re.compile(r"\A(?:CASE|REQ)-[A-Za-z0-9][A-Za-z0-9_.:-]{2,}\Z")
PUBLIC_GATE_REVIEW_HEAD_RE = re.compile(r"\A[0-9a-f]{40}\Z", re.IGNORECASE)
PUBLIC_GATE_SELF_AUTHORITY_VALUES = frozenset(
    {
        "codex",
        "claude",
        "local",
        "manual",
        "operator",
        "oudepode",
        "self",
        "self-minted",
        "test",
        "unknown",
    }
)
PUBLIC_GATE_EVIDENCE_REF_PREFIXES = (
    "acceptance-receipt:",
    "claim-review:",
    "cvc:",
    "dossier:",
    "relay-receipt:",
    "review:",
    "review-dossier:",
    "review-team:",
)
PUBLIC_GATE_INDEPENDENT_ACCEPTOR_PREFIXES = ("review-team:",)
PUBLIC_GATE_INDEPENDENT_ACCEPTOR_VALUES = frozenset(
    {
        "claim-verification-council",
        "claim verification council",
    }
)
PUBLIC_GATE_PASS_VALUES = frozenset(
    {
        "accept",
        "accepted",
        "allow",
        "allowed",
        "approve",
        "approved",
        "clear",
        "cleared",
        "complete",
        "completed",
        "ok",
        "pass",
        "passed",
        "success",
        "succeeded",
        "true",
        "valid",
        "yes",
    }
)
PUBLIC_GATE_FAIL_VALUES = frozenset(
    {
        "block",
        "blocked",
        "deny",
        "denied",
        "error",
        "fail",
        "failed",
        "false",
        "invalid",
        "no",
        "reject",
        "rejected",
    }
)
_MISSING_AUTHORITY_SECRET_WARNED = False


def public_gate_receipt_value_present(
    value: object,
    *,
    expected_gate: str,
    roots: Iterable[Path],
    bindings: Mapping[str, object] | None = None,
    authority_roots: Iterable[Path] | None = None,
    authority_secret: str | None = None,
) -> bool:
    """Return true when ``value`` contains a durable receipt for ``expected_gate``."""
    if isinstance(value, str):
        return public_gate_receipt_ref_exists(
            value,
            expected_gate=expected_gate,
            roots=roots,
            bindings=bindings,
            authority_roots=authority_roots,
            authority_secret=authority_secret,
        )
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, str, Mapping)):
        return any(
            public_gate_receipt_value_present(
                item,
                expected_gate=expected_gate,
                roots=roots,
                bindings=bindings,
                authority_roots=authority_roots,
                authority_secret=authority_secret,
            )
            for item in value
        )
    return False


def public_gate_receipt_ref_exists(
    ref: str,
    *,
    expected_gate: str,
    roots: Iterable[Path],
    bindings: Mapping[str, object] | None = None,
    authority_roots: Iterable[Path] | None = None,
    authority_secret: str | None = None,
) -> bool:
    """Validate that ``ref`` names an existing receipt mapped to ``expected_gate``."""
    suffix = _public_gate_receipt_suffix(ref)
    if suffix is None:
        return False

    candidates = _receipt_candidate_paths(suffix)
    resolved_authority_roots = (
        PUBLIC_GATE_AUTHORITY_ROOTS if authority_roots is None else tuple(authority_roots)
    )
    resolved_authority_secret = (
        _public_gate_authority_secret() if authority_secret is None else authority_secret
    )
    if authority_secret is None and not resolved_authority_secret:
        _warn_missing_authority_secret()
    for root in roots:
        root = root.expanduser()
        for candidate in candidates:
            path = root / candidate
            if _path_is_inside_root(path, root) and _receipt_file_maps_to_gate(
                path,
                expected_gate,
                root,
                resolved_authority_roots,
                resolved_authority_secret,
                bindings,
            ):
                return True
    return False


def _public_gate_receipt_suffix(ref: str) -> str | None:
    stripped = ref.strip()
    lowered = stripped.casefold()
    for prefix in PUBLIC_GATE_RECEIPT_PREFIXES:
        if not lowered.startswith(prefix):
            continue
        suffix = stripped[len(prefix) :].strip()
        path = Path(suffix)
        if (
            suffix
            and PUBLIC_GATE_RECEIPT_SUFFIX_RE.fullmatch(suffix)
            and not path.is_absolute()
            and ".." not in path.parts
        ):
            return suffix
    return None


def _receipt_candidate_paths(suffix: str) -> tuple[Path, ...]:
    base = Path(suffix)
    if base.suffix:
        candidates = [base] if base.suffix.casefold() in PUBLIC_GATE_RECEIPT_EXTENSIONS else []
    else:
        candidates = [
            Path(f"{suffix}{extension}") for extension in (".yaml", ".yml", ".json", ".md")
        ]
    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.as_posix()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return tuple(deduped)


def _path_is_inside_root(path: Path, root: Path) -> bool:
    try:
        resolved_root = root.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
    except OSError:
        return False
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError:
        return False
    return resolved_path.is_file()


def _receipt_file_maps_to_gate(
    path: Path,
    expected_gate: str,
    root: Path,
    authority_roots: tuple[Path, ...],
    authority_secret: str,
    bindings: Mapping[str, object] | None = None,
) -> bool:
    data = _load_receipt_data(path)
    return (
        not _receipt_has_failed_outcome(data)
        and not _receipt_has_gate_contradiction(data, expected_gate)
        and _gate_receipt_object_allows(
            data,
            expected_gate,
            root,
            authority_roots,
            authority_secret,
            bindings,
            receipt_path=path,
        )
    )


def _load_receipt_data(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    except OSError:
        return None

    if path.suffix.casefold() == ".md":
        frontmatter = _markdown_frontmatter(text)
        if frontmatter is not None:
            return frontmatter

    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return None


def _markdown_frontmatter(text: str) -> Any:
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() != "---":
            continue
        frontmatter = "\n".join(lines[1:index])
        try:
            return yaml.safe_load(frontmatter)
        except yaml.YAMLError:
            return None
    return None


def _gate_receipt_object_allows(
    data: Any,
    expected_gate: str,
    root: Path,
    authority_roots: tuple[Path, ...],
    authority_secret: str,
    bindings: Mapping[str, object] | None = None,
    receipt_path: Path | None = None,
) -> bool:
    return any(
        _receipt_mapping_has_required_authority(
            candidate,
            root,
            authority_roots,
            authority_secret,
            expected_gate=expected_gate,
            bindings=bindings,
            receipt_path=receipt_path,
        )
        and _receipt_candidate_mapping_allows(candidate, expected_gate, bindings)
        for candidate in _iter_receipt_candidate_mappings(data)
    )


def _iter_receipt_candidate_mappings(data: Any) -> Iterable[Mapping[Any, Any]]:
    """Yield only root/top-level records; receipt success never recurses."""
    if isinstance(data, Mapping):
        yield data
        return
    if isinstance(data, (list, tuple, set)):
        for item in data:
            if isinstance(item, Mapping):
                yield item


def _receipt_candidate_mapping_allows(
    data: Mapping[Any, Any],
    expected_gate: str,
    bindings: Mapping[str, object] | None,
) -> bool:
    # These predicates inspect direct keys on this one candidate mapping only;
    # child mappings cannot supply gate, outcome, or artifact-binding evidence.
    return (
        _mapping_contains_expected_gate(data, expected_gate)
        and _mapping_outcome_allows(data)
        and _receipt_mapping_has_required_bindings(data, bindings)
    )


def _mapping_contains_expected_gate(data: Mapping[Any, Any], expected_gate: str) -> bool:
    for raw_key, value in data.items():
        key = str(raw_key).strip().casefold()
        if key in PUBLIC_GATE_ID_KEYS and _gate_value_matches(value, expected_gate):
            return True
        if key in PUBLIC_GATE_LIST_KEYS and _gate_value_contains(value, expected_gate):
            return True
        if _gate_value_matches(raw_key, expected_gate) and _outcome_value_allows(value) is True:
            return True
    return False


def _mapping_outcome_allows(data: Mapping[Any, Any]) -> bool:
    outcomes = [
        _outcome_value_allows(value)
        for raw_key, value in data.items()
        if str(raw_key).strip().casefold() in PUBLIC_GATE_OUTCOME_KEYS
    ]
    if any(outcome is False for outcome in outcomes):
        return False
    return any(outcome is True for outcome in outcomes)


def _gate_value_contains(value: Any, expected_gate: str) -> bool:
    if isinstance(value, Mapping):
        return any(
            _gate_value_matches(key, expected_gate) and _outcome_value_allows(item) is True
            for key, item in value.items()
        )
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, str)):
        return any(_gate_value_matches(item, expected_gate) for item in value)
    return _gate_value_matches(value, expected_gate)


def _gate_value_matches(value: Any, expected_gate: str) -> bool:
    return isinstance(value, str) and value.strip() == expected_gate


def _receipt_has_failed_outcome(data: Any) -> bool:
    return any(outcome is False for outcome in _iter_receipt_outcomes(data))


def _receipt_mapping_has_required_bindings(
    data: Any,
    bindings: Mapping[str, object] | None,
) -> bool:
    # Bindings must live on the same mapping as the gate/outcome record. Do not
    # recurse here, or stale gate evidence can be spliced with child/sibling bindings.
    if not bindings:
        return True
    return all(_receipt_mapping_has_binding(data, key, value) for key, value in bindings.items())


def _receipt_mapping_has_required_authority(
    data: Mapping[Any, Any],
    root: Path,
    authority_roots: tuple[Path, ...],
    authority_secret: str,
    *,
    expected_gate: str,
    bindings: Mapping[str, object] | None,
    receipt_path: Path | None = None,
) -> bool:
    return (
        _mapping_has_authority_case(data)
        and _mapping_has_non_self_text(data, PUBLIC_GATE_ACCEPTOR_KEYS)
        and _mapping_has_nonblank_text(data, PUBLIC_GATE_REVIEW_PROFILE_KEYS)
        and _mapping_has_evidence_ref(
            data,
            root,
            authority_roots,
            authority_secret,
            expected_gate=expected_gate,
            bindings=bindings,
            receipt_path=receipt_path,
        )
    )


def _mapping_has_authority_case(data: Mapping[Any, Any]) -> bool:
    return any(
        PUBLIC_GATE_AUTHORITY_CASE_RE.fullmatch(value) is not None
        for value in _iter_direct_text_values(data, PUBLIC_GATE_AUTHORITY_CASE_KEYS)
    )


def _mapping_has_non_self_text(data: Mapping[Any, Any], keys: frozenset[str]) -> bool:
    return any(
        value.strip().casefold() not in PUBLIC_GATE_SELF_AUTHORITY_VALUES
        for value in _iter_direct_text_values(data, keys)
    )


def _mapping_has_nonblank_text(data: Mapping[Any, Any], keys: frozenset[str]) -> bool:
    return any(True for _ in _iter_direct_text_values(data, keys))


def _mapping_has_evidence_ref(
    data: Mapping[Any, Any],
    root: Path,
    authority_roots: tuple[Path, ...],
    authority_secret: str,
    *,
    expected_gate: str,
    bindings: Mapping[str, object] | None,
    receipt_path: Path | None = None,
) -> bool:
    for value in _iter_direct_text_values(data, PUBLIC_GATE_EVIDENCE_REF_KEYS):
        normalized = value.strip()
        lowered = normalized.casefold()
        if any(lowered.startswith(prefix) for prefix in PUBLIC_GATE_RECEIPT_PREFIXES):
            continue
        if lowered in PUBLIC_GATE_SELF_AUTHORITY_VALUES:
            continue
        if _evidence_ref_resolves(
            normalized,
            root,
            authority_roots,
            authority_secret,
            expected_gate=expected_gate,
            bindings=bindings,
            receipt_path=receipt_path,
        ):
            return True
    return False


def _evidence_ref_resolves(
    ref: str,
    root: Path,
    authority_roots: tuple[Path, ...],
    authority_secret: str,
    *,
    expected_gate: str,
    bindings: Mapping[str, object] | None,
    receipt_path: Path | None = None,
) -> bool:
    lowered = ref.casefold()
    for prefix in PUBLIC_GATE_EVIDENCE_REF_PREFIXES:
        if not lowered.startswith(prefix):
            continue
        suffix = ref[len(prefix) :].strip()
        if not suffix:
            return False
        suffix_path = Path(suffix)
        if (
            not PUBLIC_GATE_RECEIPT_SUFFIX_RE.fullmatch(suffix)
            or suffix_path.is_absolute()
            or ".." in suffix_path.parts
        ):
            return False
        receipt_refs = _public_gate_receipt_refs_for_path(receipt_path, root.expanduser())
        for evidence_root in authority_roots:
            evidence_root = evidence_root.expanduser()
            if any(
                _path_is_inside_root(path, evidence_root)
                and not _path_is_inside_root(path, root.expanduser())
                and not _same_resolved_path(path, receipt_path)
                and _evidence_file_is_independent(
                    path,
                    expected_gate=expected_gate,
                    bindings=bindings,
                    receipt_refs=receipt_refs,
                    authority_secret=authority_secret,
                )
                for path in (
                    evidence_root / candidate
                    for candidate in _evidence_candidate_paths(suffix, prefix)
                )
            ):
                return True
        return False
    return False


def _evidence_candidate_paths(suffix: str, prefix: str) -> tuple[Path, ...]:
    base = Path(suffix)
    if base.suffix:
        if base.name.endswith(
            (PUBLIC_GATE_REVIEW_DOSSIER_SUFFIX, PUBLIC_GATE_ACCEPTANCE_RECEIPT_SUFFIX)
        ):
            return (base,)
        return ()
    if prefix == "acceptance-receipt:":
        return (Path(f"{suffix}{PUBLIC_GATE_ACCEPTANCE_RECEIPT_SUFFIX}"),)
    return (
        Path(f"{suffix}{PUBLIC_GATE_REVIEW_DOSSIER_SUFFIX}"),
        Path(f"{suffix}{PUBLIC_GATE_ACCEPTANCE_RECEIPT_SUFFIX}"),
    )


def _same_resolved_path(left: Path, right: Path | None) -> bool:
    if right is None:
        return False
    try:
        return left.resolve(strict=True) == right.resolve(strict=True)
    except OSError:
        return False


def _evidence_file_is_independent(
    path: Path,
    *,
    expected_gate: str,
    bindings: Mapping[str, object] | None,
    receipt_refs: frozenset[str],
    authority_secret: str,
) -> bool:
    data = _load_receipt_data(path)
    return _review_dossier_evidence_allows(
        data,
        path=path,
        expected_gate=expected_gate,
        bindings=bindings,
        receipt_refs=receipt_refs,
        authority_secret=authority_secret,
    ) or _acceptance_receipt_evidence_allows(
        data,
        path=path,
        expected_gate=expected_gate,
        bindings=bindings,
        receipt_refs=receipt_refs,
        authority_secret=authority_secret,
    )


def _review_dossier_evidence_allows(
    data: Any,
    *,
    path: Path,
    expected_gate: str,
    bindings: Mapping[str, object] | None,
    receipt_refs: frozenset[str],
    authority_secret: str,
) -> bool:
    if not isinstance(data, Mapping):
        return False
    if not path.name.endswith(PUBLIC_GATE_REVIEW_DOSSIER_SUFFIX):
        return False
    if data.get("dossier_schema") != 1:
        return False
    task_id = _direct_text_value(data, "task_id")
    if not task_id or task_id != path.name[: -len(PUBLIC_GATE_REVIEW_DOSSIER_SUFFIX)]:
        return False
    if PUBLIC_GATE_REVIEW_HEAD_RE.fullmatch(_direct_text_value(data, "head_sha")) is None:
        return False
    if not _mapping_has_trusted_authority_signature(data, authority_secret):
        return False
    if not _evidence_mapping_authorizes_receipt(data, expected_gate, bindings, receipt_refs):
        return False
    verdict = _direct_text_value(data, "review_team_verdict").casefold()
    if verdict != "quorum-accept":
        return False
    quorum_required = _direct_int_value(data, "quorum_required")
    accept_count = _direct_int_value(data, "accept_count")
    if quorum_required is None or accept_count is None or accept_count < quorum_required:
        return False
    reviewers = data.get("reviewers")
    if not isinstance(reviewers, list):
        return False
    accepted_families = {
        str(reviewer.get("family") or "").strip().casefold()
        for reviewer in reviewers
        if isinstance(reviewer, Mapping)
        and str(reviewer.get("verdict") or "").strip().casefold()
        in {"accept", "accept-with-findings"}
    }
    return len(accepted_families - PUBLIC_GATE_SELF_AUTHORITY_VALUES) >= 1


def _acceptance_receipt_evidence_allows(
    data: Any,
    *,
    path: Path,
    expected_gate: str,
    bindings: Mapping[str, object] | None,
    receipt_refs: frozenset[str],
    authority_secret: str,
) -> bool:
    if not isinstance(data, Mapping):
        return False
    if not path.name.endswith(PUBLIC_GATE_ACCEPTANCE_RECEIPT_SUFFIX):
        return False
    if _outcome_value_allows(data.get("verdict")) is not True:
        return False
    if _direct_text_value(data, "timestamp") == "" or _direct_text_value(data, "artifact") == "":
        return False
    if PUBLIC_GATE_REVIEW_HEAD_RE.fullmatch(_direct_text_value(data, "head_sha")) is None:
        return False
    if not _mapping_has_trusted_authority_signature(data, authority_secret):
        return False
    if not _evidence_mapping_authorizes_receipt(data, expected_gate, bindings, receipt_refs):
        return False
    review_team_verdict = _direct_text_value(data, "review_team_verdict")
    if review_team_verdict and review_team_verdict.casefold() != "quorum-accept":
        return False
    return _mapping_has_independent_acceptor(data)


def _evidence_mapping_authorizes_receipt(
    data: Mapping[Any, Any],
    expected_gate: str,
    bindings: Mapping[str, object] | None,
    receipt_refs: frozenset[str],
) -> bool:
    return (
        _mapping_contains_expected_gate(data, expected_gate)
        and _receipt_mapping_has_required_bindings(data, bindings)
        and _evidence_mapping_contains_receipt_ref(data, receipt_refs)
    )


def public_gate_authority_signature(data: Mapping[Any, Any], secret: str) -> str:
    """Return the HMAC signature value for public-gate authority evidence."""

    return (
        PUBLIC_GATE_AUTHORITY_SIGNATURE_PREFIX
        + hmac.new(
            secret.encode("utf-8"),
            _authority_signature_payload_bytes(data),
            hashlib.sha256,
        ).hexdigest()
    )


def _public_gate_authority_secret() -> str:
    return os.environ.get(PUBLIC_GATE_AUTHORITY_SECRET_ENV, "").strip()


def _warn_missing_authority_secret() -> None:
    global _MISSING_AUTHORITY_SECRET_WARNED
    if _MISSING_AUTHORITY_SECRET_WARNED:
        return
    _MISSING_AUTHORITY_SECRET_WARNED = True
    log.warning(
        "public-gate authority evidence cannot be verified because the signing "
        "credential is unset; next action: restore the public-gate authority signing "
        "credential from pass before validating public-gate receipts",
    )


def _mapping_has_trusted_authority_signature(
    data: Mapping[Any, Any],
    authority_secret: str,
) -> bool:
    if not authority_secret:
        return False
    if not _mapping_has_trusted_authority_issuer(data):
        return False
    expected = public_gate_authority_signature(data, authority_secret)
    return any(
        hmac.compare_digest(value.strip(), expected)
        for value in _iter_direct_text_values(data, PUBLIC_GATE_AUTHORITY_SIGNATURE_KEYS)
    )


def _mapping_has_trusted_authority_issuer(data: Mapping[Any, Any]) -> bool:
    for value in _iter_direct_text_values(data, PUBLIC_GATE_AUTHORITY_ISSUER_KEYS):
        normalized = value.strip().casefold()
        if normalized in PUBLIC_GATE_TRUSTED_AUTHORITY_ISSUERS:
            return True
        if normalized.startswith("review-team:"):
            return True
    return False


def _authority_signature_payload_bytes(data: Mapping[Any, Any]) -> bytes:
    payload = _authority_signature_payload(data)
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _authority_signature_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _authority_signature_payload(item)
            for key, item in value.items()
            if str(key).strip().casefold() not in PUBLIC_GATE_AUTHORITY_SIGNATURE_KEYS
        }
    if _is_non_string_iterable(value):
        return [_authority_signature_payload(item) for item in value]
    return value


def _public_gate_receipt_refs_for_path(
    receipt_path: Path | None,
    root: Path,
) -> frozenset[str]:
    if receipt_path is None:
        return frozenset()
    try:
        relative = receipt_path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return frozenset()
    suffixes = {relative.as_posix()}
    if relative.suffix.casefold() in PUBLIC_GATE_RECEIPT_EXTENSIONS:
        suffixes.add(relative.with_suffix("").as_posix())
    return frozenset(
        f"{prefix}{suffix}" for prefix in PUBLIC_GATE_RECEIPT_PREFIXES for suffix in suffixes
    )


def _evidence_mapping_contains_receipt_ref(
    data: Mapping[Any, Any],
    receipt_refs: frozenset[str],
) -> bool:
    if not receipt_refs:
        return False
    for raw_key, value in data.items():
        key = str(raw_key).strip().casefold()
        if key not in PUBLIC_GATE_EVIDENCE_RECEIPT_REF_KEYS:
            continue
        if _receipt_ref_value_contains(value, receipt_refs):
            return True
    return False


def _receipt_ref_value_contains(value: Any, receipt_refs: frozenset[str]) -> bool:
    if isinstance(value, str):
        return value.strip() in receipt_refs
    if isinstance(value, Mapping):
        return any(_receipt_ref_value_contains(item, receipt_refs) for item in value.values())
    if _is_non_string_iterable(value):
        return any(_receipt_ref_value_contains(item, receipt_refs) for item in value)
    return False


def _mapping_has_independent_acceptor(data: Mapping[Any, Any]) -> bool:
    for value in _iter_direct_text_values(data, PUBLIC_GATE_ACCEPTOR_KEYS):
        normalized = value.strip().casefold()
        if normalized in PUBLIC_GATE_INDEPENDENT_ACCEPTOR_VALUES:
            return True
        if any(
            normalized.startswith(prefix) for prefix in PUBLIC_GATE_INDEPENDENT_ACCEPTOR_PREFIXES
        ):
            return True
    return False


def _direct_text_value(data: Mapping[Any, Any], key: str) -> str:
    for raw_key, value in data.items():
        if str(raw_key).strip().casefold() == key and isinstance(value, str):
            return value.strip()
    return ""


def _direct_int_value(data: Mapping[Any, Any], key: str) -> int | None:
    for raw_key, value in data.items():
        if str(raw_key).strip().casefold() != key:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def _iter_direct_text_values(data: Mapping[Any, Any], keys: frozenset[str]) -> Iterable[str]:
    for value in _iter_direct_binding_values(data, keys):
        if isinstance(value, str) and value.strip():
            yield value.strip()
        elif _is_non_string_iterable(value):
            for item in value:
                if isinstance(item, str) and item.strip():
                    yield item.strip()


def _receipt_mapping_has_binding(data: Any, key: str, expected: object) -> bool:
    if not isinstance(data, Mapping):
        return False
    return any(
        _binding_value_matches(value, expected)
        for value in _iter_direct_binding_values(data, _binding_key_aliases(key))
    )


def _iter_direct_binding_values(data: Any, keys: frozenset[str]) -> Iterable[Any]:
    for raw_key, value in data.items():
        if str(raw_key).strip().casefold() in keys:
            yield value


def _binding_key_aliases(key: str) -> frozenset[str]:
    normalized = key.strip().casefold()
    aliases = {
        "artifact_slug": {"artifact_slug", "publication_artifact_slug", "slug"},
        "artifact_fingerprint": {
            "artifact_fingerprint",
            "publication_artifact_fingerprint",
        },
        "target_surfaces": {
            "target_surfaces",
            "surfaces",
            "surfaces_targeted",
        },
    }
    return frozenset(aliases.get(normalized, {normalized}))


def _binding_value_matches(value: Any, expected: object) -> bool:
    if _is_non_string_iterable(expected):
        expected_items = {str(item).strip() for item in expected if str(item).strip()}
        if not expected_items:
            return False
        if _is_non_string_iterable(value):
            actual_items = {str(item).strip() for item in value if str(item).strip()}
            return actual_items == expected_items
        return False
    return isinstance(value, str) and value.strip() == str(expected).strip()


def _is_non_string_iterable(value: object) -> bool:
    return isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, str, Mapping))


def _receipt_has_gate_contradiction(data: Any, expected_gate: str) -> bool:
    if isinstance(data, Mapping):
        for raw_key, value in data.items():
            key = str(raw_key).strip().casefold()
            if (
                _gate_value_matches(raw_key, expected_gate)
                and _outcome_value_allows(value) is not True
            ):
                return True
            if key in PUBLIC_GATE_LIST_KEYS and isinstance(value, Mapping):
                for gate_key, gate_value in value.items():
                    if (
                        _gate_value_matches(gate_key, expected_gate)
                        and _outcome_value_allows(gate_value) is not True
                    ):
                        return True
            if _receipt_has_gate_contradiction(value, expected_gate):
                return True
    elif isinstance(data, (list, tuple, set)):
        return any(_receipt_has_gate_contradiction(item, expected_gate) for item in data)
    return False


def _iter_receipt_outcomes(data: Any) -> Iterable[bool | None]:
    if isinstance(data, Mapping):
        for raw_key, value in data.items():
            key = str(raw_key).strip().casefold()
            if key in PUBLIC_GATE_OUTCOME_KEYS:
                yield _outcome_value_allows(value)
            yield from _iter_receipt_outcomes(value)
    elif isinstance(data, (list, tuple, set)):
        for item in data:
            yield from _iter_receipt_outcomes(item)


def _outcome_value_allows(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float) and value in {0, 1}:
        return bool(value)
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold().replace("_", "-")
    if normalized in PUBLIC_GATE_PASS_VALUES:
        return True
    if normalized in PUBLIC_GATE_FAIL_VALUES:
        return False
    return None
