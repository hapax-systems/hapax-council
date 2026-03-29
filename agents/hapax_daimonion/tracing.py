"""tracing.py -- OTel tracing for hapax-daimonion.

All voice submodules should use this tracer for spans:
    from agents.hapax_daimonion.tracing import tracer
"""

from opentelemetry.trace import get_tracer

tracer = get_tracer("hapax_daimonion")
