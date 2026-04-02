"""Tool recruitment gate — AffordancePipeline selects tools for each utterance."""

from __future__ import annotations

import logging
import time

from shared.affordance import CapabilityRecord, OperationalProperties, SelectionCandidate
from shared.impingement import Impingement, ImpingementType

log = logging.getLogger("tool.recruitment")


class ToolRecruitmentGate:
    """Converts utterances to impingements and recruits tools via the pipeline.

    The gate sits between the operator's utterance and the LLM's tool menu.
    Only tools the pipeline recruits for the current utterance are presented
    to the LLM for execution. Thompson sampling learns from success/failure
    to improve recruitment over time.
    """

    def __init__(self, pipeline, tool_names: set[str]) -> None:
        self._pipeline = pipeline
        self._tool_names = tool_names

    def recruit(self, utterance: str) -> list[str]:
        """Recruit tools for the given utterance via affordance selection."""
        imp = self._utterance_to_impingement(utterance)
        candidates: list[SelectionCandidate] = self._pipeline.select(imp)
        recruited = [c.capability_name for c in candidates if c.capability_name in self._tool_names]
        if recruited:
            log.info("Recruited tools for '%s': %s", utterance[:50], recruited)
        return recruited

    def record_outcome(self, tool_name: str, success: bool) -> None:
        """Record whether a recruited tool was used successfully."""
        self._pipeline.record_outcome(tool_name, success=success)

    @staticmethod
    def _utterance_to_impingement(utterance: str) -> Impingement:
        """Convert an operator utterance into an impingement for pipeline selection."""
        return Impingement(
            source="operator.utterance",
            type=ImpingementType.SALIENCE_INTEGRATION,
            timestamp=time.time(),
            strength=1.0,
            content={"narrative": utterance},
        )

    @staticmethod
    def register_tools(pipeline, affordances: list[tuple[str, str]]) -> int:
        """Register all tool affordances into the pipeline's vector index.

        Returns the number of tools successfully indexed.
        """
        registered = 0
        for name, desc in affordances:
            ok = pipeline.index_capability(
                CapabilityRecord(
                    name=name,
                    description=desc,
                    daemon="hapax_daimonion",
                    operational=OperationalProperties(latency_class="fast"),
                )
            )
            if ok:
                registered += 1
        log.info("Registered %d/%d tool affordances", registered, len(affordances))
        return registered
