import { useCallback, useRef, useState } from "react";
import { PanelRightClose, PanelRightOpen } from "lucide-react";
import { ChannelStrip } from "./ChannelStrip";
import { DisplayStateBadge } from "./DisplayStateBadge";
import {
  SIGNAL_CATEGORIES,
  type OverlayMode,
  type SignalCategory,
  useOverlay,
} from "../../contexts/ClassificationOverlayContext";
import type { SignalEntry } from "../../api/types";

interface PerceptionSidebarProps {
  activeZone: SignalCategory | null;
  onZoneSelect: (cat: SignalCategory) => void;
}

const MODE_OPTIONS: { value: OverlayMode; label: string }[] = [
  { value: "off", label: "Off" },
  { value: "minimal", label: "Min" },
  { value: "full", label: "Full" },
];

export function PerceptionSidebar({ activeZone, onZoneSelect }: PerceptionSidebarProps) {
  const {
    visualLayer,
    overlayMode,
    setOverlayMode,
    channelVisibility,
    toggleChannel,
  } = useOverlay();

  const [collapsed, setCollapsed] = useState(false);
  const [expandedGroup, setExpandedGroup] = useState<SignalCategory | null>(null);
  const groupRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const handleZoneClick = useCallback(
    (cat: SignalCategory) => {
      onZoneSelect(cat);
      setExpandedGroup(cat);
      // Scroll to the group
      const el = groupRefs.current[cat];
      if (el) el.scrollIntoView({ behavior: "smooth", block: "nearest" });
    },
    [onZoneSelect],
  );

  // Collapsed icon strip
  if (collapsed) {
    return (
      <div className="flex w-10 shrink-0 flex-col items-center gap-3 border-l border-zinc-800 bg-zinc-900/50 py-3">
        <button
          onClick={() => setCollapsed(false)}
          className="text-zinc-500 hover:text-zinc-300"
          title="Expand sidebar"
        >
          <PanelRightClose className="h-3.5 w-3.5" />
        </button>
      </div>
    );
  }

  const displayState = visualLayer?.display_state ?? "ambient";
  const allSignals = visualLayer?.signals ?? {};

  return (
    <div className="flex w-60 shrink-0 flex-col border-l border-zinc-800 bg-zinc-900/50 text-xs">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-zinc-800/50 px-3 py-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
          Channels
        </span>
        <button
          onClick={() => setCollapsed(true)}
          className="text-zinc-500 hover:text-zinc-300"
          title="Collapse sidebar"
        >
          <PanelRightOpen className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto">
        {/* Display state + overlay mode */}
        <section className="border-b border-zinc-800/50 px-3 py-2.5">
          <div className="mb-2 flex items-center justify-between">
            <DisplayStateBadge state={displayState} />
          </div>
          <h3 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
            Overlay
          </h3>
          <div className="flex gap-1">
            {MODE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setOverlayMode(opt.value)}
                className={`flex-1 rounded px-1.5 py-1 text-[10px] font-medium transition-colors ${
                  overlayMode === opt.value
                    ? "bg-zinc-700 text-zinc-100"
                    : "bg-zinc-800/50 text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </section>

        {/* Channel strips */}
        {SIGNAL_CATEGORIES.map((cat) => {
          const signals: SignalEntry[] = allSignals[cat] ?? [];
          return (
            <div key={cat} ref={(el) => { groupRefs.current[cat] = el; }}>
              <ChannelStrip
                category={cat}
                visible={channelVisibility[cat]}
                onToggle={() => toggleChannel(cat)}
                signals={signals}
                expanded={expandedGroup === cat}
                onExpand={() => setExpandedGroup(expandedGroup === cat ? null : cat)}
                active={activeZone === cat}
                onClick={() => handleZoneClick(cat)}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
