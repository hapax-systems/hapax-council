import { memo, useEffect, useState } from "react";
import type { WatershedEvent } from "../../../api/types";

/** Category → Gruvbox color mapping (matches CATEGORY_HEX in ClassificationOverlayContext). */
const CATEGORY_COLORS: Record<string, string> = {
  context_time: "#83a598",
  governance: "#d3869b",
  work_tasks: "#fe8019",
  health_infra: "#fb4934",
  profile_state: "#b8bb26",
  ambient_sensor: "#8ec07c",
  voice_session: "#fabd2f",
  system_state: "#bdae93",
};

/** A single ephemeral event rendered as a decaying ripple. */
export const EventRipple = memo(function EventRipple({
  event,
  now,
}: {
  event: WatershedEvent;
  now: number;
}) {
  const age = now - event.emitted_at;
  const progress = Math.min(1, age / event.ttl_s);
  const opacity = Math.max(0, 1 - progress * progress); // quadratic decay
  const color = CATEGORY_COLORS[event.category] ?? "#bdae93";

  if (opacity <= 0.02) return null;

  return (
    <div
      className="flex items-start gap-1.5 px-2 py-1 transition-opacity duration-500"
      style={{ opacity }}
    >
      {/* Severity dot with breathing on arrival */}
      <div
        className="shrink-0 rounded-full mt-[3px]"
        style={{
          width: event.severity >= 0.7 ? 8 : 6,
          height: event.severity >= 0.7 ? 8 : 6,
          backgroundColor: color,
          animation: progress < 0.3 ? "signal-breathe-fast 1.5s ease-in-out infinite" : undefined,
        }}
      />
      <div className="min-w-0 flex-1">
        <div
          className="text-[9px] font-medium leading-tight truncate"
          style={{ color }}
        >
          {event.title}
        </div>
        {event.detail && progress < 0.5 && (
          <div className="text-[8px] text-zinc-500 leading-tight truncate">
            {event.detail}
          </div>
        )}
      </div>
    </div>
  );
});

/** Renders a stack of watershed event ripples, auto-refreshing for decay animation. */
export const EventRippleStack = memo(function EventRippleStack({
  events,
}: {
  events: WatershedEvent[];
}) {
  const [now, setNow] = useState(() => Date.now() / 1000);

  // Tick every 500ms to animate decay — only when events exist
  useEffect(() => {
    if (events.length === 0) return;
    const id = setInterval(() => setNow(Date.now() / 1000), 500);
    return () => clearInterval(id);
  }, [events.length]);

  if (events.length === 0) return null;

  // Sort by emitted_at descending (newest first), show max 4
  const sorted = [...events]
    .sort((a, b) => b.emitted_at - a.emitted_at)
    .slice(0, 4);

  return (
    <div className="flex flex-col gap-0.5">
      {sorted.map((event, i) => (
        <EventRipple key={`${event.emitted_at}-${i}`} event={event} now={now} />
      ))}
    </div>
  );
});
