"""Auto-consume Jr/Spark packets into senior-owned work artefacts."""

from agents.jr_spark_auto_consumer.consumer import (
    AppliedAction,
    Artefact,
    AutoConsumerConfig,
    Classification,
    Packet,
    RecordingStateMachineClient,
    classify_packet,
    load_cc_task_artefacts,
    main,
    run_once,
)

__all__ = [
    "AppliedAction",
    "Artefact",
    "AutoConsumerConfig",
    "Classification",
    "Packet",
    "RecordingStateMachineClient",
    "classify_packet",
    "load_cc_task_artefacts",
    "main",
    "run_once",
]
