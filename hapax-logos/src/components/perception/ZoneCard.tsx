import type { SignalEntry } from "../../api/types";

/** Severity → left-border color + text accent */
function severityStyle(severity: number): { border: string; dot: string; text: string } {
  if (severity >= 0.85) return { border: "border-l-red-400", dot: "bg-red-400", text: "text-red-300" };
  if (severity >= 0.7) return { border: "border-l-orange-400", dot: "bg-orange-400", text: "text-orange-300" };
  if (severity >= 0.4) return { border: "border-l-yellow-400", dot: "bg-yellow-400", text: "text-yellow-200" };
  if (severity >= 0.2) return { border: "border-l-zinc-400", dot: "bg-zinc-400", text: "text-zinc-200" };
  return { border: "border-l-zinc-500", dot: "bg-zinc-500", text: "text-zinc-300" };
}

/** Map source_id to a compact icon character for quick visual scanning */
function sourceIcon(sourceId: string): string {
  if (sourceId.startsWith("emotion")) return "\u{1F3AD}";  // emotion
  if (sourceId.startsWith("speech-emotion")) return "\u{1F399}";  // speech
  if (sourceId.startsWith("gaze")) return "\u{1F441}";     // eye
  if (sourceId.startsWith("hand-gesture")) return "\u{270B}";  // hand
  if (sourceId.startsWith("posture")) return "\u{1F9CD}";  // person
  if (sourceId.startsWith("pose")) return "\u{1F9CE}";     // kneeling
  if (sourceId.startsWith("person-distance")) return "\u{1F4CF}";  // ruler
  if (sourceId.startsWith("vision-consent")) return "\u{26A0}";  // warning
  if (sourceId.startsWith("vision-objects")) return "\u{1F4E6}";  // package
  if (sourceId.startsWith("scene-type")) return "\u{1F3E0}";  // house
  if (sourceId.startsWith("action")) return "\u{26A1}";    // activity
  if (sourceId.startsWith("music")) return "\u{1F3B5}";    // music
  if (sourceId.startsWith("audio")) return "\u{1F50A}";    // speaker
  if (sourceId.startsWith("speech-lang")) return "\u{1F310}";  // globe
  if (sourceId.startsWith("ambient-bright")) return "\u{2600}";  // sun
  if (sourceId.startsWith("consent")) return "\u{1F512}";  // lock
  if (sourceId.startsWith("health")) return "\u{1F6E1}";   // shield
  if (sourceId.startsWith("gpu")) return "\u{1F4BB}";      // laptop
  if (sourceId.startsWith("drift")) return "\u{1F4D0}";    // compass
  if (sourceId.startsWith("nudge")) return "\u{1F4CC}";    // pin
  if (sourceId.startsWith("briefing")) return "\u{1F4CB}"; // clipboard
  if (sourceId.startsWith("copilot")) return "\u{1F916}";  // robot
  if (sourceId.startsWith("goals")) return "\u{1F3AF}";    // target
  return "";
}

export function ZoneCard({ signal }: { signal: SignalEntry }) {
  const sev = severityStyle(signal.severity);
  const isCritical = signal.severity >= 0.85;
  const icon = sourceIcon(signal.source_id);

  return (
    <div
      className={`flex items-start gap-1.5 rounded-sm border-l-2 px-1.5 py-0.5 backdrop-blur-sm ${sev.border} ${isCritical ? "animate-pulse bg-red-950/40" : "bg-black/30"}`}
    >
      {/* Severity dot */}
      <span className={`mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full ${sev.dot}`} />
      <div className="min-w-0 flex-1">
        <div className={`truncate text-[10px] font-medium leading-tight ${sev.text}`}>
          {icon && <span className="mr-1">{icon}</span>}
          {signal.title}
        </div>
        {signal.detail && (
          <div className="truncate text-[8px] leading-tight text-white/40">{signal.detail}</div>
        )}
      </div>
    </div>
  );
}
