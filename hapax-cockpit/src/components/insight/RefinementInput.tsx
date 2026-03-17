import { useState, useRef, useEffect } from "react";
import { RotateCcw, ArrowRight, Loader2 } from "lucide-react";

interface RefinementInputProps {
  onSubmit: (query: string) => void;
  isLoading: boolean;
}

export function RefinementInput({ onSubmit, isLoading }: RefinementInputProps) {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isLoading && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isLoading]);

  const handleSubmit = () => {
    const trimmed = query.trim();
    if (!trimmed || isLoading) return;
    onSubmit(trimmed);
    setQuery("");
  };

  return (
    <div className="mt-4 flex items-center gap-2 border-t border-zinc-800 pt-4">
      <RotateCcw className="h-3.5 w-3.5 shrink-0 text-zinc-600" />
      <input
        ref={inputRef}
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
        placeholder="Refine: zoom in, change perspective, show as diagram..."
        disabled={isLoading}
        className="flex-1 bg-transparent text-xs text-zinc-300 placeholder-zinc-600 outline-none disabled:opacity-50"
      />
      <button
        onClick={handleSubmit}
        disabled={!query.trim() || isLoading}
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-zinc-700 text-zinc-400 hover:bg-zinc-600 hover:text-zinc-200 disabled:opacity-30"
      >
        {isLoading ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : (
          <ArrowRight className="h-3 w-3" />
        )}
      </button>
    </div>
  );
}
