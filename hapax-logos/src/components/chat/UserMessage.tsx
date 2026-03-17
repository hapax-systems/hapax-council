interface UserMessageProps {
  content: string;
  timestamp?: number;
}

export function UserMessage({ content, timestamp }: UserMessageProps) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] rounded-lg ring-1 ring-zinc-700/50 bg-zinc-800 px-3 py-2 text-sm text-zinc-200">
        <div className="whitespace-pre-wrap">{content}</div>
        {timestamp && (
          <div className="mt-1 text-right text-[10px] text-zinc-600">
            {new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </div>
        )}
      </div>
    </div>
  );
}
