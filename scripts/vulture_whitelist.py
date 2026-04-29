# pyright: reportUnusedExpression=false
"""Justified dynamic-entrypoint references for scripts/check-unused-functions.py.

Keep this file narrow. Add names here only when a callable is invoked by a
framework, subprocess entrypoint, import string, or other dynamic path that
vulture cannot see. Do not use this as a baseline for ordinary dead code.
"""

from logos.api.routes.studio import studio_audio_safe_for_broadcast, studio_egress_state
from shared.audio_topology_inspector import check_l12_forward_invariant
from shared.director_control_audit import DirectorControlMoveAuditRecord
from shared.director_vocabulary import DirectorVocabulary, SpectacleLaneState

# FastAPI registers this route by decorator; vulture does not follow APIRouter.
studio_egress_state
studio_audio_safe_for_broadcast

# Invoked by the extensionless scripts/hapax-audio-topology CLI and subprocess
# CLI tests; vulture scans scripts as Python modules but does not see that
# entrypoint as a static importer.
check_l12_forward_invariant

# Director vocabulary is a contract surface for future programme scheduler and
# content runner consumers. Pydantic calls validators dynamically; exported view
# methods are public API, not internal dead code.
SpectacleLaneState._known_director_verbs
DirectorVocabulary.for_programme_scheduler
DirectorVocabulary.for_content_runner

# Pydantic invokes model validators dynamically during model validation.
DirectorControlMoveAuditRecord._validate_boundary_and_evidence
