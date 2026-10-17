"""Synthetic current-contract GLM receipt fixture; no provider or producer dependency."""

import json
from datetime import datetime, timedelta


def _glmcp_receipt_json(
    *,
    status: str,
    remaining: int,
    age: int,
    now: datetime,
    receipt_stale: bool = False,
) -> str:
    """A complete glmcp platform-capability receipt built through the production model.

    The dispatcher reads this document through its loader (schema, platform, skew, duration syntax,
    freshness), and since round 8 so does the seat refresher, so the fixture must be a receipt the
    loader accepts — not three fields in a dict (review finding on #4624, round 8). The quota
    surface was observed ``age`` seconds ago with ``remaining`` seconds of stale_after left at that
    moment; the receipt itself lives 24 h so that only the quota surface decides freshness.
    """
    from shared.platform_capability_receipts import (
        CliEvidence,
        EvidenceStatus,
        PlatformCapabilityReceipt,
        ProviderDocsEvidence,
        SurfaceEvidence,
        WrapperEvidence,
    )

    observed = now - timedelta(seconds=age)
    observed_ok = status == "observed"
    quota = SurfaceEvidence(
        status=EvidenceStatus(status),
        source="local_receipt_probe",
        observed_at=observed,
        stale_after=f"{remaining}s",
        evidence_refs=[
            "local:glmcp:quota-admission-receipt:glmcp.review.direct:present",
            "platform-capability-registry:glmcp.review.direct:quota:observed",
        ]
        if observed_ok
        else [],
        reason_codes=[] if observed_ok else ["account_live_quota_receipt_absent"],
    )
    # ``receipt_stale`` makes the RECEIPT stale (observed two hours ago, lives one hour) while its
    # quota surface still reads fresh: exactly the document a field-picking guard would trust and
    # the dispatcher's loader drops.
    receipt = PlatformCapabilityReceipt(
        load_sets={"instruction_body": {"status": "unobserved"}},
        receipt_id=f"test-glmcp-{int(observed.timestamp())}",
        platform="glmcp",
        routes=["glmcp.review.direct"],
        observed_at=(now - timedelta(hours=2)) if receipt_stale else observed,
        stale_after="1h" if receipt_stale else "24h",
        cli=CliEvidence(binary="hapax-glmcp-reviewer", available=True, version="test"),
        wrapper=WrapperEvidence(
            path="scripts/hapax-glmcp-reviewer", exists=True, executable=True, sha256="abc123"
        ),
        capability=SurfaceEvidence(
            status=EvidenceStatus.OBSERVED,
            source="test",
            observed_at=observed,
            stale_after="24h",
            evidence_refs=["test:glmcp:capability"],
        ),
        resource=SurfaceEvidence(
            status=EvidenceStatus.OBSERVED,
            source="test",
            observed_at=observed,
            stale_after="24h",
            evidence_refs=["test:glmcp:resource"],
        ),
        quota=quota,
        provider_docs=ProviderDocsEvidence(
            refs=["test:glmcp:provider-docs"], fetched_at=observed, stale_after="30d"
        ),
    )
    return json.dumps(receipt.model_dump(mode="json"))
