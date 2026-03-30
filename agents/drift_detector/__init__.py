"""Agent package for drift_detector."""

from .agent import (  # noqa: F401
    detect_drift,
    format_human,
)
from .docs import (  # noqa: F401
    HAPAX_REPO_DIRS,
    load_docs,
)
from .fix_context import (  # noqa: F401
    REGISTRY_CATEGORIES,
    _build_fix_context,
)
from .fixes import (  # noqa: F401
    FIX_SYSTEM_PROMPT,
    fix_agent,
    format_fixes,
    generate_fixes,
)
from .models import (  # noqa: F401
    ApplyResult,
    ContainerInfo,
    DiskInfo,
    DocFix,
    DriftItem,
    DriftReport,
    FixReport,
    GpuInfo,
    InfrastructureManifest,
    LiteLLMRoute,
    OllamaModel,
    QdrantCollection,
    SystemdUnit,
)
from .scanners import (  # noqa: F401
    check_doc_freshness,
    check_project_memory,
    check_screen_context_drift,
    scan_axiom_violations,
    scan_sufficiency_gaps,
)
