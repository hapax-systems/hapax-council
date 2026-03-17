import { useState, useRef, useEffect } from "react";
import { Search, ArrowRight, Loader2 } from "lucide-react";

interface QueryInputProps {
  onSubmit: (query: string) => void;
  isLoading: boolean;
  placeholder?: string;
}

export function QueryInput({ onSubmit, isLoading, placeholder }: QueryInputProps) {
  const [query, setQuery] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!isLoading && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [isLoading]);

  const handleSubmit = () => {
    const trimmed = query.trim();
    if (!trimmed || isLoading) return;
    onSubmit(trimmed);
    setQuery("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="flex items-start gap-3 rounded-lg border border-zinc-700 bg-zinc-800 p-3">
      <Search className="mt-1 h-4 w-4 shrink-0 text-zinc-500" />
      <textarea
        ref={textareaRef}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={
          placeholder ??
          "Ask about development history, system patterns, architecture..."
        }
        disabled={isLoading}
        rows={1}
        className="flex-1 resize-none bg-transparent text-sm text-zinc-200 placeholder-zinc-500 outline-none disabled:opacity-50"
        style={{ maxHeight: "120px" }}
      />
      <button
        onClick={handleSubmit}
        disabled={!query.trim() || isLoading}
        className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-green-700 text-zinc-100 transition-colors hover:bg-green-600 disabled:bg-zinc-700 disabled:text-zinc-500"
      >
        {isLoading ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <ArrowRight className="h-3.5 w-3.5" />
        )}
      </button>
    </div>
  );
}
