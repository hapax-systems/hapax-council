"""Re-export from hapax-demo package for backwards compatibility."""

from demo.pipeline.dossier import *  # noqa: F401, F403
from demo.pipeline.dossier import (  # noqa: F401
    gather_dossier_interactive,
    record_relationship_facts,
    save_dossier,
)
