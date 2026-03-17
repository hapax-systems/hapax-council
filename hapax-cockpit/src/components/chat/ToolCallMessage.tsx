import { useState } from "react";
import { ChevronDown, ChevronRight, Wrench, CheckCircle } from "lucide-react";

interface ToolCallMessageProps {
  name: string;
  args: string;
  isResult?: boolean;
}

export function ToolCallMessage({ name, args, isResult }: ToolCallMessageProps) {
  const [expanded, setExpanded] = useState(false);

  const borderColor = isResult ? "border-emerald-500/20" : "border-yellow-500/20";
  const bgColor = isResult ? "bg-emerald-500/5" : "bg-yellow-500/5";
  const textColor = isResult ? "text-emerald-400" : "text-yellow-400";
  const dimColor = isResult ? "text-emerald-400/60" : "text-yellow-400/60";
  const Icon = isResult ? CheckCircle : Wrench;
  const label = isResult ? `${name} result` : name;

  return (
    <div className={`rounded border ${borderColor} ${bgColor} px-3 py-1.5 text-xs`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className={`flex w-full items-center gap-1.5 text-left ${textColor}`}
      >
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <Icon className="h-3 w-3" />
        <span className="font-medium">{label}</span>
        {args && !expanded && (
          <span className={`ml-1 truncate ${dimColor}`}>{args.slice(0, 80)}</span>
        )}
      </button>
      {expanded && args && (
        <pre className={`mt-1 overflow-x-auto whitespace-pre-wrap ${dimColor}`}>{args}</pre>
      )}
    </div>
  );
}
