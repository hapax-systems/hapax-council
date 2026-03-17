import { useState, useRef, useEffect, useMemo } from "react";
import { useChatContext } from "./ChatProvider";
import { useInputHistory } from "../../hooks/useInputHistory";
import { Send, StopCircle } from "lucide-react";

const SLASH_COMMANDS = [
  { cmd: "/help", desc: "Show available commands" },
  { cmd: "/clear", desc: "Clear conversation and start new session" },
  { cmd: "/new", desc: "Start a new session" },
  { cmd: "/stop", desc: "Stop generation" },
  { cmd: "/model", desc: "Switch model — /model <name>" },
  { cmd: "/export", desc: "Export chat as markdown" },
  { cmd: "/profile", desc: "View profile — /profile [dim] [correct ...]" },
  { cmd: "/pending", desc: "Show pending facts" },
  { cmd: "/flush", desc: "Flush pending facts to profile" },
  { cmd: "/accommodate", desc: "Manage accommodations — /accommodate [confirm|disable] <id>" },
  { cmd: "/interview", desc: "Start/manage interview — /interview [end|skip|status]" },
];

export function ChatInput() {
  const { state, sendMessage, stopGeneration, clearChat, switchModel, addSystemMessage, exportChat, startInterview, endInterview, skipInterviewTopic, getInterviewStatus } = useChatContext();
  const [input, setInput] = useState("");
  const [selectedSuggestion, setSelectedSuggestion] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const history = useInputHistory();

  // Focus on mount
  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  // Auto-resize textarea
  useEffect(() => {
    const ta = textareaRef.current;
    if (ta) {
      ta.style.height = "auto";
      ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
    }
  }, [input]);

  // Compute suggestions
  const suggestions = useMemo(() => {
    if (!input.startsWith("/") || input.includes(" ") || input.includes("\n")) return [];
    const prefix = input.toLowerCase();
    return SLASH_COMMANDS.filter((c) => c.cmd.startsWith(prefix));
  }, [input]);

  // Reset selection when suggestions change
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    setSelectedSuggestion(0);
  }, [suggestions.length]);
  /* eslint-enable react-hooks/set-state-in-effect */

  function applySuggestion(cmd: string) {
    // If the command takes args, add a space; otherwise submit directly
    const needsArgs = cmd === "/model" || cmd === "/profile" || cmd === "/accommodate" || cmd === "/interview";
    if (needsArgs) {
      setInput(cmd + " ");
      textareaRef.current?.focus();
    } else {
      setInput(cmd);
      // Auto-submit
      const trimmed = cmd.trim();
      if (trimmed) {
        history.addEntry(trimmed);
        const handled = handleSlashCommand(trimmed);
        if (!handled) sendMessage(trimmed);
        setInput("");
      }
    }
  }

  function handleSubmit() {
    const trimmed = input.trim();
    if (!trimmed || state.isStreaming) return;

    // Handle client-side slash commands
    if (trimmed.startsWith("/")) {
      const handled = handleSlashCommand(trimmed);
      if (handled) {
        history.addEntry(trimmed);
        setInput("");
        return;
      }
    }

    history.addEntry(trimmed);
    sendMessage(trimmed);
    setInput("");
  }

  function handleSlashCommand(cmd: string): boolean {
    const parts = cmd.split(/\s+/);
    const command = parts[0].toLowerCase();

    switch (command) {
      case "/clear":
      case "/new":
        clearChat();
        return true;
      case "/stop":
        stopGeneration();
        return true;
      case "/model":
        if (parts[1]) {
          switchModel(parts[1]);
          addSystemMessage(`Model switched to ${parts[1]}`);
        } else {
          addSystemMessage("Usage: /model <name> — available: balanced, fast, reasoning, coding, local-fast");
        }
        return true;
      case "/export":
        exportChat();
        return true;
      case "/profile":
        handleProfileCommand(parts.slice(1));
        return true;
      case "/pending":
        handlePendingCommand();
        return true;
      case "/flush":
        handleFlushCommand();
        return true;
      case "/accommodate":
        handleAccommodateCommand(parts.slice(1));
        return true;
      case "/interview":
        handleInterviewCommand(parts.slice(1));
        return true;
      case "/help":
        addSystemMessage(
          SLASH_COMMANDS.map((c) => `${c.cmd} — ${c.desc}`).join("\n")
        );
        return true;
      default:
        return false;
    }
  }

  async function handleProfileCommand(args: string[]) {
    try {
      if (args[0] === "correct" && args.length >= 4) {
        const [, dim, key, ...rest] = args;
        const res = await fetch(`/api/profile/correct`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ dimension: dim, key, value: rest.join(" ") }),
        });
        const data = await res.json();
        addSystemMessage(`Correction applied: ${data.result}`);
        return;
      }

      const dim = args[0] || "";
      const url = dim ? `/api/profile/${dim}` : "/api/profile";
      const res = await fetch(url);
      const data = await res.json();

      if (data.dimensions) {
        const lines = data.dimensions.map(
          (d: { name: string; fact_count: number }) => `  ${d.name}: ${d.fact_count} facts`
        );
        addSystemMessage(`Profile (${data.total_facts} facts):\n${lines.join("\n")}${data.missing?.length ? `\nMissing: ${data.missing.join(", ")}` : ""}`);
      } else if (data.facts) {
        const lines = data.facts.map(
          (f: { key: string; value: string; confidence: number; source: string }) =>
            `  [${f.confidence.toFixed(1)}] ${f.key}: ${f.value}`
        );
        addSystemMessage(`${data.name} (${data.facts.length} facts):\n${lines.join("\n")}`);
      }
    } catch (err) {
      addSystemMessage(`Profile error: ${err}`);
    }
  }

  async function handlePendingCommand() {
    try {
      const res = await fetch("/api/profile/facts/pending");
      const data = await res.json();
      if (data.count === 0) {
        addSystemMessage("No pending facts.");
      } else {
        const lines = data.facts.map(
          (f: { dimension: string; key: string; value: string }) => `  ${f.dimension}/${f.key}: ${f.value}`
        );
        addSystemMessage(`Pending facts (${data.count}):\n${lines.join("\n")}`);
      }
    } catch (err) {
      addSystemMessage(`Error: ${err}`);
    }
  }

  async function handleFlushCommand() {
    try {
      const res = await fetch("/api/profile/facts/flush", { method: "POST" });
      const data = await res.json();
      addSystemMessage(`Flushed ${data.flushed} facts to profile.`);
    } catch (err) {
      addSystemMessage(`Error: ${err}`);
    }
  }

  async function handleAccommodateCommand(args: string[]) {
    try {
      if (args[0] === "confirm" && args[1]) {
        await fetch(`/api/accommodations/${args[1]}/confirm`, { method: "POST" });
        addSystemMessage(`Accommodation '${args[1]}' activated.`);
        return;
      }
      if (args[0] === "disable" && args[1]) {
        await fetch(`/api/accommodations/${args[1]}/disable`, { method: "POST" });
        addSystemMessage(`Accommodation '${args[1]}' deactivated.`);
        return;
      }
      const res = await fetch("/api/accommodations");
      const data = await res.json();
      if (data.accommodations?.length) {
        const lines = data.accommodations.map(
          (a: { id: string; description: string; active: boolean }) =>
            `  ${a.active ? "[active]" : "[inactive]"} ${a.id}: ${a.description}`
        );
        addSystemMessage(`Accommodations:\n${lines.join("\n")}`);
      } else {
        addSystemMessage("No accommodations configured.");
      }
    } catch (err) {
      addSystemMessage(`Error: ${err}`);
    }
  }

  async function handleInterviewCommand(args: string[]) {
    const sub = args[0]?.toLowerCase();
    try {
      switch (sub) {
        case "end":
          await endInterview();
          return;
        case "skip":
          await skipInterviewTopic();
          return;
        case "status": {
          const status = await getInterviewStatus();
          if (!status || !status.active) {
            addSystemMessage("No active interview.");
          } else {
            addSystemMessage(
              `Interview: ${status.topics_explored}/${status.total_topics} topics explored, ${status.facts_count} facts, ${status.insights_count} insights\n${status.status}`
            );
          }
          return;
        }
        default:
          startInterview();
          return;
      }
    } catch (err) {
      addSystemMessage(`Interview error: ${err}`);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    // Handle suggestion navigation
    if (suggestions.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedSuggestion((prev) => Math.min(prev + 1, suggestions.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedSuggestion((prev) => Math.max(prev - 1, 0));
        return;
      }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
        e.preventDefault();
        applySuggestion(suggestions[selectedSuggestion].cmd);
        return;
      }
      if (e.key === "Escape") {
        setInput("");
        return;
      }
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    } else if (e.key === "ArrowUp" && !input.includes("\n") && suggestions.length === 0) {
      const prev = history.navigateUp(input);
      if (prev !== null) {
        e.preventDefault();
        setInput(prev);
      }
    } else if (e.key === "ArrowDown" && !input.includes("\n") && suggestions.length === 0) {
      const next = history.navigateDown();
      if (next !== null) {
        e.preventDefault();
        setInput(next);
      }
    }
  }

  return (
    <div className="border-t border-zinc-700 bg-zinc-900 px-4 py-3">
      <div className="relative mx-auto max-w-3xl">
        {/* Slash command suggestions */}
        {suggestions.length > 0 && (
          <div className="absolute bottom-full mb-1 w-full rounded border border-zinc-700 bg-zinc-800 py-1 shadow-lg">
            {suggestions.map((s, i) => (
              <button
                key={s.cmd}
                onMouseDown={(e) => { e.preventDefault(); applySuggestion(s.cmd); }}
                className={`flex w-full items-center gap-3 border-l-2 border-cyan-400/30 px-3 py-1.5 text-left text-xs ${
                  i === selectedSuggestion ? "bg-zinc-700 text-zinc-100" : "text-zinc-400 hover:bg-zinc-700/50"
                }`}
              >
                <span className="font-mono text-cyan-400">{s.cmd}</span>
                <span className="text-zinc-500">{s.desc}</span>
              </button>
            ))}
          </div>
        )}

        <div className="flex items-end gap-2">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => { setInput(e.target.value); history.reset(); }}
            onKeyDown={handleKeyDown}
            placeholder={state.isStreaming ? "Generating..." : "Type a message... (/ for commands)"}
            disabled={state.isStreaming}
            rows={1}
            className="flex-1 resize-none rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-200 placeholder-zinc-500 outline-none focus:border-zinc-500 disabled:opacity-50"
          />
          {state.isStreaming ? (
            <button
              onClick={stopGeneration}
              className="rounded border border-red-500/30 p-2 text-red-400 hover:bg-red-500/20 active:scale-[0.97]"
              title="Stop generation"
            >
              <StopCircle className="h-4 w-4" />
            </button>
          ) : (
            <button
              onClick={handleSubmit}
              disabled={!input.trim()}
              className="rounded border border-zinc-700 p-2 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200 disabled:opacity-30 active:scale-[0.97]"
              title="Send"
            >
              <Send className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
