/**
 * TimeDisplay — clock + activity label for Ground region.
 */

import { useEffect, useState } from "react";

interface TimeDisplayProps {
  activityLabel: string;
  activityDetail: string;
  displayState: string;
}

export function TimeDisplay({ activityLabel, activityDetail, displayState }: TimeDisplayProps) {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const isAlert = displayState === "alert";
  const isPerformative = displayState === "performative";

  return (
    <>
      {/* Time — top right */}
      <div className="absolute top-3 right-4">
        <div className="text-white/15 text-3xl font-extralight tracking-wider">
          {time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </div>
        <div className="text-white/8 text-[10px] mt-0.5 text-right">
          {time.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" })}
        </div>
      </div>

      {/* State + activity — top left */}
      <div className="absolute top-3 left-4">
        <div
          className={`text-[10px] tracking-[0.4em] uppercase ${
            isAlert
              ? "text-red-400/50"
              : isPerformative
                ? "text-purple-400/50"
                : displayState === "informational"
                  ? "text-amber-400/30"
                  : "text-white/10"
          }`}
        >
          {displayState === "ambient" ? "hapax" : displayState}
        </div>
        <div className="text-white/12 text-xs tracking-wider mt-1">
          {activityLabel}
          {activityDetail && <span className="text-white/6 ml-2">{activityDetail}</span>}
        </div>
      </div>
    </>
  );
}
