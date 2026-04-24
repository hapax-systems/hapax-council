"""YouTube Data API v3 quota observability (ytb-001).

Polls Google Cloud Monitoring for ``serviceruntime.googleapis.com``
quota metrics scoped to ``youtube.googleapis.com`` and exports them
as Prometheus gauges on ``http://127.0.0.1:9497/metrics`` for the
existing ``hapax_broadcast_*`` Grafana dashboard.
"""
