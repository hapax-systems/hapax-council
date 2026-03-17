interface SystemMessageProps {
  content: string;
}

export function SystemMessage({ content }: SystemMessageProps) {
  const isMultiline = content.includes("\n");

  if (isMultiline) {
    return (
      <div className="rounded border border-zinc-700/50 bg-zinc-800/50 px-3 py-2 text-xs">
        <pre className="whitespace-pre-wrap font-mono text-zinc-400 leading-relaxed">{content}</pre>
      </div>
    );
  }

  return (
    <div className="rounded bg-zinc-800/30 px-3 py-1.5 text-xs text-zinc-500">
      {content}
    </div>
  );
}
