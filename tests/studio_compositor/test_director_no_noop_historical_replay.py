"""Historical-replay regression pin for the director no-op invariant (#158).

Complements the unit-level pin in ``test_director_no_noop_invariant.py`` by
replaying a canned sample of *live* ``director-intent.jsonl`` records taken
from ``~/hapax-state/stream-experiment/`` after the 2026-04-19T00:17Z deploy
of the ``min_length=1`` schema tightening + parser fallback fix.

The fixture lives at::

    tests/fixtures/director/director-intent-live-sample.jsonl

Each line is a JSON envelope written by the director loop's research logger
(see ``agents/studio_compositor/director_loop.py`` — the jsonl writer wraps
``DirectorIntent.model_dump_for_jsonl()`` with ``condition_id`` + ``emitted_at``).
For each record we assert the operator no-vacuum invariant:
``len(compositional_impingements) >= 1``.

The compliance ratio is reported via the test's captured output and, when
``prometheus_client`` is importable, published into a dedicated
``CollectorRegistry`` as ``hapax_director_no_noop_invariant_compliance`` so a
research operator can scrape the number out-of-band. The metric is intentionally
scoped to a local registry so we never pollute the global process registry
during test collection.

Operator quote (2026-04-18):
    "The director loop should be having some kind of actual effect on the
     livestream every time. There is no justifiable context where 'do nothing
     interesting' is acceptable."
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.director_intent import DirectorIntent

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "director"
    / "director-intent-live-sample.jsonl"
)

# Deploy epoch for the ``min_length=1`` schema + parser fallback.
# Unix seconds for 2026-04-19T00:17:00Z. Records with ``emitted_at`` before
# this value predate the fix and must not appear in the replay fixture.
DEPLOY_CUTOFF_EPOCH = 1_776_557_820.0

# Minimum sample size the fixture must carry. The brief
# (``docs/superpowers/plans/2026-04-18-director-no-op-fix-brief.md`` §6)
# requires ">= 20 ticks".
MIN_SAMPLE_TICKS = 20


def _load_fixture() -> list[dict]:
    """Read the canned director-intent sample JSONL fixture."""
    assert FIXTURE_PATH.exists(), (
        f"Historical-replay fixture missing: {FIXTURE_PATH}. "
        "Regenerate from ~/hapax-state/stream-experiment/director-intent.jsonl "
        "(see brief §6)."
    )
    records: list[dict] = []
    with FIXTURE_PATH.open() as handle:
        for line_number, raw in enumerate(handle, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                records.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                raise AssertionError(
                    f"Fixture line {line_number} is not valid JSON: {exc}"
                ) from exc
    return records


def _strip_envelope(record: dict) -> dict:
    """Return the DirectorIntent-shaped subset of an envelope record.

    The research-log envelope wraps the DirectorIntent with ``condition_id``
    and ``emitted_at`` which are not part of the schema.
    """
    payload = dict(record)
    payload.pop("condition_id", None)
    payload.pop("emitted_at", None)
    return payload


def test_fixture_respects_deploy_cutoff() -> None:
    """Fixture must only contain records emitted after the schema-fix deploy."""
    records = _load_fixture()
    assert len(records) >= MIN_SAMPLE_TICKS, (
        f"Historical-replay fixture too small: {len(records)} < {MIN_SAMPLE_TICKS}. "
        "Extend the sample from the live jsonl."
    )
    stale = [r for r in records if r.get("emitted_at", 0.0) < DEPLOY_CUTOFF_EPOCH]
    assert not stale, (
        f"{len(stale)} fixture record(s) predate the 2026-04-19T00:17Z deploy. "
        "The replay must only cover post-fix traffic."
    )


def test_every_record_parses_as_director_intent() -> None:
    """Every fixture record must load cleanly as a DirectorIntent.

    This exercises the real pydantic validator, so a regression in the schema
    (e.g., relaxing ``min_length=1`` on ``compositional_impingements``) would
    surface here even if the raw ``len >= 1`` assertion below were removed.
    """
    records = _load_fixture()
    for idx, record in enumerate(records):
        payload = _strip_envelope(record)
        try:
            DirectorIntent.model_validate(payload)
        except Exception as exc:  # pragma: no cover - failure path reported verbatim
            pytest.fail(
                f"Fixture record {idx} (emitted_at={record.get('emitted_at')}) "
                f"failed DirectorIntent validation: {exc}"
            )


def test_no_noop_invariant_holds_across_replay() -> None:
    """Pin the no-op invariant on every record in the canned live sample.

    Reports the compliance ratio through stdout (visible with ``pytest -s``)
    and, when ``prometheus_client`` is importable, through a local-registry
    Prometheus gauge named ``hapax_director_no_noop_invariant_compliance``.
    """
    records = _load_fixture()
    assert len(records) >= MIN_SAMPLE_TICKS

    noop_indices: list[int] = []
    for idx, record in enumerate(records):
        impingements = record.get("compositional_impingements", [])
        if len(impingements) < 1:
            noop_indices.append(idx)

    compliant = len(records) - len(noop_indices)
    compliance_ratio = compliant / len(records) if records else 0.0
    noop_percent = 100.0 * len(noop_indices) / len(records) if records else 0.0

    # Optional Prometheus metric — published into a local registry so the
    # test never touches the global ``REGISTRY``. If prometheus_client is not
    # importable we silently skip the metric (it is a reporting convenience,
    # not an assertion).
    try:
        from prometheus_client import CollectorRegistry, Gauge, generate_latest

        registry = CollectorRegistry()
        gauge = Gauge(
            "hapax_director_no_noop_invariant_compliance",
            "Ratio of director-intent ticks in the replay sample that carry "
            "at least one compositional_impingement.",
            registry=registry,
        )
        gauge.set(compliance_ratio)
        metric_dump = generate_latest(registry).decode("utf-8").strip()
    except Exception:  # pragma: no cover - exercised only when prometheus_client missing
        metric_dump = "(prometheus_client unavailable — metric not emitted)"

    # Emit a human-readable summary so ``pytest -s`` or CI logs carry the
    # signal even when the assertion passes.
    print(
        "\n[director-no-op replay] "
        f"sample={len(records)} compliant={compliant} "
        f"noops={len(noop_indices)} ({noop_percent:.1f}%) "
        f"ratio={compliance_ratio:.4f}\n"
        f"{metric_dump}"
    )

    assert not noop_indices, (
        f"{len(noop_indices)} director-intent record(s) in the replay sample "
        "violate the no-op invariant (empty compositional_impingements). "
        f"Offending indices: {noop_indices[:10]}{' ...' if len(noop_indices) > 10 else ''}. "
        "This indicates a regression in the schema (min_length=1 on "
        "DirectorIntent.compositional_impingements) or in the parser fallback "
        "paths in agents/studio_compositor/director_loop.py."
    )
