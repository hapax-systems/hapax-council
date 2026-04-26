"""Per-source helper modules for the operator-awareness aggregator.

Each module under this package exposes a single ``collect_*`` function
that returns a typed sub-block. The main ``Aggregator.collect()``
composes them into one ``AwarenessState`` per tick. Helpers must be
defensive — never raise — so a broken source produces an empty block
rather than crashing the runner.
"""
