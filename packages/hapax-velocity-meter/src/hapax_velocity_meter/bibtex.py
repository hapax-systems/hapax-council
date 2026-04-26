"""BibTeX self-citation emitter."""

from __future__ import annotations

METHODOLOGY_BIBTEX = """\
@misc{hapax_velocity_2026,
  title        = {{Hapax Velocity Report 2026-04-25: Single-Operator Multi-Session Coordination}},
  author       = {Hapax (Oudepode) and {Claude Code}},
  year         = {2026},
  month        = apr,
  howpublished = {\\url{https://hapax.weblog.lol/velocity-report-2026-04-25}},
  note         = {Methodology source for hapax-velocity-meter; arXiv preprint forthcoming},
}

@software{hapax_velocity_meter_2026,
  title        = {{hapax-velocity-meter: Measure development velocity from any git history}},
  author       = {Hapax (Oudepode) and {Claude Code}},
  year         = {2026},
  url          = {https://github.com/ryanklee/hapax-council},
  license      = {PolyForm Strict 1.0.0},
  note         = {arXiv preprint, Zenodo DOI, and SWHID pending; see CITATION.cff},
}
"""


def bibtex_self_citation() -> str:
    return METHODOLOGY_BIBTEX
