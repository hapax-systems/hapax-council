"""hapax-velocity-meter — measure development velocity from any git history."""

from hapax_velocity_meter.bibtex import bibtex_self_citation
from hapax_velocity_meter.measurement import VelocityReport, measure_repo

__all__ = ["VelocityReport", "bibtex_self_citation", "measure_repo"]
__version__ = "0.1.0"
