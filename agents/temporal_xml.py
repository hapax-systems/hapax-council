"""Temporal bands XML formatter — renders TemporalBands as XML for LLM injection.

Exploits RoPE geometry: high-surprise impression fields render last (near
protention) for natural recency-attention boost. Multi-scale sections
appear between tick retention and impression.
"""

from __future__ import annotations

from agents.temporal_models import SurpriseField, TemporalBands


def format_temporal_xml(bands: TemporalBands) -> str:
    """Format bands as XML tags for LLM context injection."""
    parts: list[str] = ["<temporal_context>"]

    # Tick-level retention (50s window)
    if bands.retention:
        parts.append('  <retention scale="tick">')
        for r in bands.retention:
            attrs = f'age_s="{r.age_s:.0f}" flow="{r.flow_state}" activity="{r.activity}"'
            if r.presence:
                attrs += f' presence="{r.presence}"'
            parts.append(f"    <memory {attrs}>{r.summary}</memory>")
        parts.append("  </retention>")

    # Multi-scale: minute retention (last 5 minutes)
    if bands.minute_summaries:
        parts.append('  <retention scale="minute">')
        for m in bands.minute_summaries:
            act = m.get("activity", "")
            flow = m.get("flow_state", "idle")
            hr = m.get("hr_mean", 0)
            parts.append(f'    <minute activity="{act}" flow="{flow}" hr="{hr:.0f}" />')
        parts.append("  </retention>")

    # Multi-scale: session context
    if bands.current_session or bands.recent_sessions:
        parts.append("  <session_context>")
        if bands.current_session:
            s = bands.current_session
            dur = float(s.get("duration_s", 0)) / 60
            parts.append(
                f'    <current activity="{s.get("activity", "")}" '
                f'flow="{s.get("flow_state", "idle")}" '
                f'duration_m="{dur:.0f}" />'
            )
        for s in bands.recent_sessions:
            dur = float(s.get("duration_s", 0)) / 60
            parts.append(
                f'    <past activity="{s.get("activity", "")}" '
                f'flow="{s.get("flow_state", "idle")}" '
                f'duration_m="{dur:.0f}" />'
            )
        parts.append("  </session_context>")

    # Multi-scale: circadian/day context
    if bands.day_context and bands.day_context.total_minutes > 0:
        d = bands.day_context
        top_acts = sorted(d.activities.items(), key=lambda x: -x[1])[:3]
        acts_str = ", ".join(f"{k}:{v}m" for k, v in top_acts)
        parts.append(
            f'  <circadian sessions="{d.session_count}" '
            f'flow_m="{d.total_flow_minutes}" '
            f'dominant="{d.dominant_activity}" activities="{acts_str}" />'
        )

    # Impression — fields sorted by surprise (low→high) so high-surprise
    # fields appear last, exploiting RoPE recency-attention boost
    if bands.impression:
        parts.append('  <impression scale="tick">')
        surprise_map = {s.field: s for s in bands.surprises}
        _null_sf = SurpriseField(field="", observed="", expected="", surprise=0.0)
        sorted_items = sorted(
            bands.impression.items(),
            key=lambda kv: surprise_map.get(kv[0], _null_sf).surprise,
        )
        for key, val in sorted_items:
            sf = surprise_map.get(key)
            if sf and sf.surprise > 0.3:
                parts.append(
                    f'    <{key} surprise="{sf.surprise:.2f}" '
                    f'expected="{sf.expected}">{val}</{key}>'
                )
            else:
                parts.append(f"    <{key}>{val}</{key}>")
        parts.append("  </impression>")

    # Protention (end of context — highest RoPE attention)
    if bands.protention:
        parts.append('  <protention scale="tick">')
        for p in bands.protention:
            # precision AFTER confidence: phenomenal_parsing matches
            # state-then-confidence; never insert attrs between them.
            parts.append(
                f'    <prediction state="{p.predicted_state}" '
                f'confidence="{p.confidence:.2f}" '
                f'precision="{p.precision:.2f}">{p.basis}</prediction>'
            )
        parts.append("  </protention>")

    parts.append("</temporal_context>")
    return "\n".join(parts)
