"""Crossref data/software citation depositor — Phase 1.

Per cc-task ``leverage-attrib-crossref-research-nexus``. Crossref's
software-citation rails accept structured XML deposits for software
DOIs; combined with DataCite + Zenodo, the deposit reaches most
academic citation indexes.

Phase 1 ships:

  - ``CrossrefDepositor(login_id, login_passwd)`` — wraps the legacy
    deposit servlet at ``https://doi.crossref.org/servlet/deposit``
  - ``submit_deposit(xml)`` — POSTs XML deposit, returns
    :class:`DepositResult` reflecting outcome
  - ``log_deposit(doi, outcome)`` — append-only JSONL log at
    ``~/hapax-state/attribution/crossref-deposits.jsonl``
  - Counter ``hapax_leverage_crossref_deposits_total{outcome}``

Phase 2 wires this into the citation-metadata builder
(``leverage-attrib-cff-codemeta-zenodo-rollout-6-repos``); operator
action: ``pass insert crossref/depositor-credentials`` (Crossref
membership-required; per cc-task spec).

The Crossref deposit servlet uses URL-encoded form parameters
(``login_id``, ``login_passwd``, ``operation=doMDUpload``) with the
XML payload as a multi-part file upload. This module uses the modern
``requests`` `files` parameter to handle that shape.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Final

from prometheus_client import Counter

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

CROSSREF_DEPOSIT_ENDPOINT: str = "https://doi.crossref.org/servlet/deposit"
"""Crossref deposit servlet (legacy, but the canonical XML upload path).
Modern REST API at https://api.crossref.org/ is read-only metadata."""

CROSSREF_REQUEST_TIMEOUT_S: float = 60.0
"""Crossref deposits accept large XML batches; 60s is generous."""

DEFAULT_DEPOSIT_LOG_PATH: Final[Path] = (
    Path.home() / "hapax-state" / "attribution" / "crossref-deposits.jsonl"
)
"""Append-only log of every deposit attempt, mirroring the cold-contact
touch-log pattern. Daemon reads this for cadence policy / operator
dashboard surfacing."""


class DepositOutcome(Enum):
    """Outcome categories for one deposit submission.

    ``OK`` — Crossref accepted the deposit (HTTP 200).
    ``REFUSED`` — Crossref rejected (4xx; e.g., 403 forbidden,
        409 conflict, 422 schema-invalid).
    ``ERROR`` — transport / 5xx / server-side failure; retry-eligible.
    ``MISSING_CREDS`` — operator credentials not configured;
        refusal-as-data on the publication-bus convention.
    """

    OK = "ok"
    REFUSED = "refused"
    ERROR = "error"
    MISSING_CREDS = "missing-creds"


@dataclass(frozen=True)
class DepositResult:
    """One deposit submission's outcome.

    ``submission_id`` is parsed from the Crossref response body when
    available (Crossref returns ``submission-id=N`` on success).
    """

    outcome: DepositOutcome
    submission_id: str | None = None
    error: str | None = None


crossref_deposits_total = Counter(
    "hapax_leverage_crossref_deposits_total",
    "Crossref deposit-submission outcomes per result.",
    ["outcome"],
)


class CrossrefDepositor:
    """Wraps the Crossref deposit servlet with operator credentials.

    One instance per operator credential pair. Multiple instances
    (e.g., test + production deposits) compose without sharing state.
    """

    def __init__(
        self,
        *,
        login_id: str,
        login_passwd: str,
        endpoint: str = CROSSREF_DEPOSIT_ENDPOINT,
        timeout_s: float = CROSSREF_REQUEST_TIMEOUT_S,
    ) -> None:
        self.login_id = login_id
        self.login_passwd = login_passwd
        self.endpoint = endpoint
        self.timeout_s = timeout_s

    def submit_deposit(self, xml: str) -> DepositResult:
        """POST one XML deposit; return :class:`DepositResult`.

        Returns :data:`DepositOutcome.MISSING_CREDS` immediately when
        either credential field is empty — Crossref membership-required
        flow means missing creds is a hard refusal-as-data, not a
        transient error.
        """
        if not (self.login_id and self.login_passwd):
            crossref_deposits_total.labels(outcome=DepositOutcome.MISSING_CREDS.value).inc()
            return DepositResult(
                outcome=DepositOutcome.MISSING_CREDS,
                error=(
                    "missing Crossref credentials "
                    "(operator-action: pass insert crossref/depositor-credentials)"
                ),
            )
        if requests is None:
            return DepositResult(
                outcome=DepositOutcome.ERROR,
                error="requests library not available",
            )

        params = {
            "login_id": self.login_id,
            "login_passwd": self.login_passwd,
            "operation": "doMDUpload",
        }
        files = {"fname": ("deposit.xml", xml, "text/xml")}
        try:
            response = requests.post(
                self.endpoint,
                params=params,
                files=files,
                timeout=self.timeout_s,
            )
        except requests.RequestException as exc:
            log.warning("crossref deposit raised: %s", exc)
            crossref_deposits_total.labels(outcome=DepositOutcome.ERROR.value).inc()
            return DepositResult(
                outcome=DepositOutcome.ERROR,
                error=f"transport failure: {exc}",
            )

        if response.status_code == 200:
            crossref_deposits_total.labels(outcome=DepositOutcome.OK.value).inc()
            return DepositResult(
                outcome=DepositOutcome.OK,
                submission_id=_parse_submission_id(response.text),
            )
        if 400 <= response.status_code < 500:
            crossref_deposits_total.labels(outcome=DepositOutcome.REFUSED.value).inc()
            return DepositResult(
                outcome=DepositOutcome.REFUSED,
                error=f"Crossref refused HTTP {response.status_code}: {response.text[:160]}",
            )
        crossref_deposits_total.labels(outcome=DepositOutcome.ERROR.value).inc()
        return DepositResult(
            outcome=DepositOutcome.ERROR,
            error=f"Crossref HTTP {response.status_code}: {response.text[:160]}",
        )


def log_deposit(
    *,
    doi: str,
    outcome: DepositOutcome,
    log_path: Path = DEFAULT_DEPOSIT_LOG_PATH,
    submission_id: str | None = None,
    error: str | None = None,
    now: datetime | None = None,
) -> None:
    """Append one deposit-attempt record to the JSONL log."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "doi": doi,
        "outcome": outcome.value,
        "submission_id": submission_id,
        "error": error,
        "timestamp": (now or datetime.now(UTC)).isoformat(),
    }
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _parse_submission_id(response_text: str) -> str | None:
    """Best-effort parse of Crossref's `submission-id=N` line."""
    for line in response_text.splitlines():
        line = line.strip()
        if line.startswith("submission-id="):
            return line.split("=", 1)[1].strip()
    return None


__all__ = [
    "CROSSREF_DEPOSIT_ENDPOINT",
    "CROSSREF_REQUEST_TIMEOUT_S",
    "DEFAULT_DEPOSIT_LOG_PATH",
    "CrossrefDepositor",
    "DepositOutcome",
    "DepositResult",
    "crossref_deposits_total",
    "log_deposit",
]
