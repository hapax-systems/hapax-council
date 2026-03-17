import { useState } from "react";
import { Copy, Check } from "lucide-react";
import { MarkdownContent } from "../shared/MarkdownContent";

interface AssistantMessageProps {
  content: string;
  variant?: "assistant" | "interviewer";
  timestamp?: number;
}

export function AssistantMessage({ content, variant = "assistant", timestamp }: AssistantMessageProps) {
  const [copied, setCopied] = useState(false);
  const borderColor = variant === "interviewer" ? "border-fuchsia-500/60" : "border-green-500/60";

  function handleCopy() {
    navigator.clipboard.writeText(content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  return (
    <div className={`group relative rounded-lg border-l-2 ${borderColor} bg-zinc-900/50 px-3 py-2`}>
      <MarkdownContent content={content} className="text-sm" />
      <div className="mt-1 flex items-center justify-between">
        {timestamp && (
          <span className="text-[10px] text-zinc-600">
            {new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </span>
        )}
        <button
          onClick={handleCopy}
          className="rounded p-0.5 text-zinc-600 opacity-0 transition-opacity hover:text-zinc-400 group-hover:opacity-100"
          title="Copy"
        >
          {copied ? (
            <span className="flex items-center gap-1">
              <Check className="h-3 w-3 text-green-400" />
              <span className="text-[10px] text-green-400">Copied</span>
            </span>
          ) : (
            <Copy className="h-3 w-3" />
          )}
        </button>
      </div>
    </div>
  );
}
