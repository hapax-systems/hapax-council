import { MarkdownContent } from "../shared/MarkdownContent";

interface StreamingMessageProps {
  text: string;
}

export function StreamingMessage({ text }: StreamingMessageProps) {
  return (
    <div className="rounded-lg border-l-2 border-green-500/50 bg-zinc-900/50 px-3 py-2">
      <MarkdownContent content={text} className="text-sm" />
      <span className="inline-block h-3 w-0.5 animate-pulse bg-green-400/70" />
    </div>
  );
}
