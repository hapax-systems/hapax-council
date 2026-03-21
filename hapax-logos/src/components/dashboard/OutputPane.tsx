import { useRef, useEffect, useState } from "react";
import { Square, Maximize2, Minimize2 } from "lucide-react";

function lineColor(line: string): string {
  if (line.startsWith("---")) return "text-zinc-500 font-medium";
  if (/ERROR|FAILED|✗/.test(line)) return "text-red-400";
  if (/WARNING|WARN|⚠/.test(line)) return "text-yellow-400";
  if (/✓|PASS(?:ED)?|OK\b/.test(line)) return "text-green-600";
  return "";
}

interface OutputPaneProps {
  lines: string[];
  isRunning: boolean;
  agentName?: string;
  startedAt?: number;
  onCancel: () => void;
}

export function OutputPane({ lines, isRunning, agentName, startedAt, onCancel }: OutputPaneProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines]);

  // Elapsed timer
   
  useEffect(() => {
    if (!isRunning || !startedAt) {
      setElapsed(0);
      return;
    }
    setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [isRunning, startedAt]);
   

  if (lines.length === 0 && !isRunning) return null;

  const maxHeight = expanded ? "max-h-[60vh]" : "max-h-48";

  return (
    <section className="border-t border-zinc-800">
      <div className="flex items-center justify-between bg-zinc-900 px-4 py-1.5">
        <h3 className="flex items-center gap-2 text-xs font-medium text-zinc-400">
          Output
          {agentName && (
            <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-zinc-300">{agentName}</span>
          )}
          {isRunning && (
            <span className="text-blue-400">
              running{elapsed > 0 ? ` ${elapsed}s` : "..."}
            </span>
          )}
        </h3>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setExpanded(!expanded)}
            className="rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300"
            title={expanded ? "Collapse" : "Expand"}
          >
            {expanded ? <Minimize2 className="h-3 w-3" /> : <Maximize2 className="h-3 w-3" />}
          </button>
          {isRunning && (
            <button
              onClick={onCancel}
              className="flex items-center gap-1 rounded px-2 py-0.5 text-xs text-red-400 hover:bg-red-500/20"
            >
              <Square className="h-3 w-3" />
              Cancel
            </button>
          )}
        </div>
      </div>
      <div
        ref={scrollRef}
        className={`${maxHeight} overflow-y-auto bg-zinc-950 px-4 py-2 font-mono text-xs text-zinc-400 transition-[max-height] duration-200`}
      >
        {lines.map((line, i) => (
          <div key={i} className={lineColor(line)}>
            {line || "\u00A0"}
          </div>
        ))}
      </div>
    </section>
  );
}
