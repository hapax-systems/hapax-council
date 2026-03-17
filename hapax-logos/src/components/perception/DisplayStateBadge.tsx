const STATE_STYLES: Record<string, { bg: string; text: string; dot: string; label: string }> = {
  ambient: { bg: "bg-zinc-800/80", text: "text-zinc-300", dot: "bg-zinc-400", label: "Ambient" },
  peripheral: { bg: "bg-sky-950/60", text: "text-sky-300", dot: "bg-sky-400", label: "Peripheral" },
  informational: { bg: "bg-amber-950/60", text: "text-amber-300", dot: "bg-amber-400", label: "Info" },
  alert: { bg: "bg-red-950/60", text: "text-red-300", dot: "bg-red-400", label: "Alert" },
  performative: { bg: "bg-violet-950/60", text: "text-violet-300", dot: "bg-violet-400", label: "Live" },
};

export function DisplayStateBadge({ state }: { state: string }) {
  const s = STATE_STYLES[state] ?? STATE_STYLES.ambient;
  const pulse = state === "alert" || state === "performative";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border border-white/5 px-2.5 py-0.5 text-[10px] font-bold tracking-wide backdrop-blur-sm ${s.bg} ${s.text}`}
    >
      <span className={`h-2 w-2 rounded-full ${s.dot} ${pulse ? "animate-pulse" : ""}`} />
      {s.label}
    </span>
  );
}
