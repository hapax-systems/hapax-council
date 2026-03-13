"""tracing.py -- OTel tracing for hapax-voice.

All voice submodules should use this tracer for spans:
    from agents.hapax_voice.tracing import tracer
"""

from opentelemetry.trace import get_tracer

tracer = get_tracer("hapax_voice")
