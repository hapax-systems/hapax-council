import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useAgents } from "../../api/hooks";

interface Command {
  id: string;
  label: string;
  shortcut?: string;
  action: () => void;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  onManualToggle: () => void;
}

export function CommandPalette({ open, onClose, onManualToggle }: CommandPaletteProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: agents } = useAgents();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const staticCommands: Command[] = [
    { id: "dashboard", label: "Go to Dashboard", shortcut: "d", action: () => { navigate("/"); onClose(); } },
    { id: "chat", label: "Go to Chat", shortcut: "c", action: () => { navigate("/chat"); onClose(); } },
    { id: "manual", label: "Toggle Operations Manual", shortcut: "?", action: () => { onManualToggle(); onClose(); } },
    { id: "refresh", label: "Refresh All Data", shortcut: "r", action: () => { queryClient.invalidateQueries(); onClose(); } },
    { id: "new-chat", label: "New Chat Session", action: () => { navigate("/chat"); onClose(); } },
    { id: "health", label: "View Health Detail", action: () => { navigate("/"); onClose(); } },
  ];

  const agentCommands: Command[] = (agents ?? []).map((a) => ({
    id: `agent-${a.name}`,
    label: `Run ${a.name}`,
    action: () => { navigate("/"); onClose(); },
  }));

  const commands = [...staticCommands, ...agentCommands];

  const filtered = query
    ? commands.filter((c) => c.label.toLowerCase().includes(query.toLowerCase()))
    : commands;

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (open) {
      setQuery("");
      setSelected(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  useEffect(() => {
    setSelected(0);
  }, [query]);
  /* eslint-enable react-hooks/set-state-in-effect */

  if (!open) return null;

  function handleKeyDown(e: React.KeyboardEvent) {
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setSelected((s) => Math.min(s + 1, filtered.length - 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        setSelected((s) => Math.max(s - 1, 0));
        break;
      case "Enter":
        e.preventDefault();
        if (filtered[selected]) filtered[selected].action();
        break;
      case "Escape":
        e.preventDefault();
        onClose();
        break;
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh]" onClick={onClose}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
      <div
        className="relative w-full max-w-md rounded-lg border border-zinc-700 bg-zinc-900 shadow-2xl animate-in fade-in zoom-in-95 duration-150"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type a command..."
          className="w-full rounded-t-lg border-b border-zinc-700 bg-transparent px-4 py-3 text-sm text-zinc-200 placeholder-zinc-500 outline-none"
        />
        <div className="max-h-64 overflow-y-auto py-1">
          {filtered.length === 0 ? (
            <p className="px-4 py-3 text-xs text-zinc-500">No matching commands.</p>
          ) : (
            filtered.map((cmd, i) => (
              <button
                key={cmd.id}
                onClick={() => cmd.action()}
                className={`flex w-full items-center justify-between px-4 py-2 text-left text-sm ${
                  i === selected ? "bg-zinc-800 text-zinc-100" : "text-zinc-400 hover:bg-zinc-800/50"
                }`}
              >
                <span>{cmd.label}</span>
                {cmd.shortcut && (
                  <kbd className="rounded border border-zinc-700 px-1.5 py-0.5 text-[10px] text-zinc-500">
                    {cmd.shortcut}
                  </kbd>
                )}
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
