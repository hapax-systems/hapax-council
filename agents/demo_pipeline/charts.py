"""Re-export from hapax-demo package for backwards compatibility."""

from pathlib import Path

from demo.pipeline import charts as _charts
from demo.pipeline.charts import *  # noqa: F401, F403
from demo.pipeline.charts import _normalize_chart_spec  # noqa: F401

# Eagerly set MPLSTYLE_PATH so tests can access it at import time
_profiles = Path(__file__).resolve().parent.parent.parent / "profiles"
MPLSTYLE_PATH = _profiles / "gruvbox.mplstyle"
_charts.MPLSTYLE_PATH = MPLSTYLE_PATH
