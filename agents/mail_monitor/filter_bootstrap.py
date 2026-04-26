"""Idempotent installer for the four Hapax/* server-side Gmail filters.

Spec: ``docs/specs/2026-04-25-mail-monitor.md`` §2 / §5.1.

A filter in :file:`filters.yaml` is considered already-installed iff an
existing Gmail filter on the account has both:

- the *exact same* ``criteria.query``, and
- the same ``addLabelIds`` / ``removeLabelIds`` set after resolving
  Hapax label names to ids.

When no match is found, the missing filter is created via
``users.settings.filters.create``. This bootstrap **never deletes**
operator-managed filters; it only adds Hapax-owned ones. Removal is
operator intent — the daemon respects that and refuses to auto-restore.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from prometheus_client import Counter

from agents.mail_monitor.label_bootstrap import HAPAX_LABEL_NAMES

log = logging.getLogger(__name__)

FILTERS_YAML_PATH = Path(__file__).parent / "filters.yaml"

FILTER_INSTALLS_COUNTER = Counter(
    "hapax_mail_monitor_filter_installs_total",
    "Hapax filter install attempts by filter id and outcome.",
    labelnames=("filter", "result"),
)


class FilterBootstrapError(RuntimeError):
    """Raised when a Hapax filter cannot be installed or read."""


def load_filter_specs(path: Path = FILTERS_YAML_PATH) -> list[dict[str, Any]]:
    """Parse :file:`filters.yaml`; return a list of filter specs.

    Each spec is a dict with keys ``id``, ``query``, ``add_labels``,
    ``remove_labels``. Tests pass a custom ``path`` to a tmp file.
    """
    raw = yaml.safe_load(path.read_text())
    return list(raw["filters"])


def _resolve_label_id(name: str, label_ids: dict[str, str]) -> str:
    """Resolve ``name`` to a Gmail label id.

    Hapax labels are looked up via ``label_ids``. Gmail system labels
    (``INBOX``, ``SPAM``, ``TRASH``, etc.) are their own id — pass the
    literal name through unchanged.
    """
    return label_ids.get(name, name)


def _spec_matches_existing(
    spec: dict[str, Any],
    existing: dict[str, Any],
    label_name_to_id: dict[str, str],
) -> bool:
    """Return True iff ``existing`` is the Gmail-side version of ``spec``.

    Match criteria:

    - ``criteria.query`` must be byte-equal,
    - ``addLabelIds`` set must equal the ids resolved from
      ``spec.add_labels``,
    - ``removeLabelIds`` set must equal the ids resolved from
      ``spec.remove_labels``.
    """
    if existing.get("criteria", {}).get("query") != spec["query"]:
        return False
    expected_add = {_resolve_label_id(name, label_name_to_id) for name in spec["add_labels"]}
    expected_remove = {_resolve_label_id(name, label_name_to_id) for name in spec["remove_labels"]}
    actual_add = set(existing.get("action", {}).get("addLabelIds", []))
    actual_remove = set(existing.get("action", {}).get("removeLabelIds", []))
    return expected_add == actual_add and expected_remove == actual_remove


def bootstrap_filters(
    service: Any,
    label_ids: dict[str, str],
    *,
    specs_path: Path = FILTERS_YAML_PATH,
) -> dict[str, str]:
    """Install missing Hapax filters; return ``{spec_id: filter_id}``.

    ``label_ids`` is the ``{name: id}`` mapping returned by
    :func:`agents.mail_monitor.label_bootstrap.bootstrap_labels`. All four
    Hapax label names must be present.

    Each call enumerates existing filters via
    ``users.settings.filters.list``, performs the per-spec match, and
    creates only the missing ones.
    """
    from googleapiclient.errors import HttpError

    missing_labels = [n for n in HAPAX_LABEL_NAMES if n not in label_ids]
    if missing_labels:
        raise FilterBootstrapError(
            f"label_ids missing names: {missing_labels}; run bootstrap_labels first."
        )

    specs = load_filter_specs(specs_path)

    try:
        existing_resp = service.users().settings().filters().list(userId="me").execute()
    except HttpError as exc:
        for spec in specs:
            FILTER_INSTALLS_COUNTER.labels(filter=spec["id"], result="error").inc()
        raise FilterBootstrapError(f"filters.list failed: {exc}") from exc

    existing_filters = existing_resp.get("filter", [])
    result_map: dict[str, str] = {}

    for spec in specs:
        match = next(
            (f for f in existing_filters if _spec_matches_existing(spec, f, label_ids)),
            None,
        )
        if match is not None:
            FILTER_INSTALLS_COUNTER.labels(filter=spec["id"], result="exists").inc()
            result_map[spec["id"]] = match["id"]
            continue

        body = {
            "criteria": {"query": spec["query"]},
            "action": {
                "addLabelIds": [_resolve_label_id(name, label_ids) for name in spec["add_labels"]],
                "removeLabelIds": [
                    _resolve_label_id(name, label_ids) for name in spec["remove_labels"]
                ],
            },
        }
        try:
            created = service.users().settings().filters().create(userId="me", body=body).execute()
        except HttpError as exc:
            FILTER_INSTALLS_COUNTER.labels(filter=spec["id"], result="error").inc()
            raise FilterBootstrapError(f"filters.create({spec['id']!r}) failed: {exc}") from exc

        FILTER_INSTALLS_COUNTER.labels(filter=spec["id"], result="created").inc()
        result_map[spec["id"]] = created["id"]
        log.info("created Gmail filter %s (id=%s)", spec["id"], created["id"])

    return result_map


# Pre-touch outcome labels per known spec ids so Prometheus emits a 0
# series for each before any traffic. Module-load is the only place we
# know the ids without parsing yaml at import time, so we do parse it.
for _spec in load_filter_specs():
    for _result in ("exists", "created", "error"):
        FILTER_INSTALLS_COUNTER.labels(filter=_spec["id"], result=_result)
