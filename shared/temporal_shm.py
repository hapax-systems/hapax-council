"""Render WCS-gated temporal prompt context.

Single implementation used by all operator prompt builders
(shared/operator.py, logos/_operator.py, agents/_operator.py).

Temporal prompt context used to read raw shared-memory XML directly. The WCS
gate now renders only temporal/perceptual ``WorldSurfaceHealthRecord`` rows so
prompt text can orient a model without becoming unverified temporal authority.
"""

from __future__ import annotations

from pathlib import Path

from shared.temporal_prompt_wcs_gate import render_default_temporal_prompt_block

TEMPORAL_FILE = Path("/dev/shm/hapax-temporal/bands.json")


def read_temporal_block() -> str:
    """Render the temporal prompt block through WCS health rows.

    The ``TEMPORAL_FILE`` constant is retained for compatibility with older
    tests and importers, but this function no longer treats raw shared-memory
    XML as prompt authority. Missing or invalid WCS health data fails closed to
    an empty block.
    """
    try:
        return render_default_temporal_prompt_block()
    except Exception:
        return ""
