import { useRef, useEffect, useState } from "react";
import { useChatContext, type ChatMessage } from "./ChatProvider";
import { UserMessage } from "./UserMessage";
import { AssistantMessage } from "./AssistantMessage";
import { ToolCallMessage } from "./ToolCallMessage";
import { StreamingMessage } from "./StreamingMessage";
import { SystemMessage } from "./SystemMessage";
import { ChevronDown, ChevronRight, Wrench } from "lucide-react";

/** Group consecutive tool_call/tool_result messages together. */
function groupMessages(messages: ChatMessage[]): (ChatMessage | ChatMessage[])[] {
  const result: (ChatMessage | ChatMessage[])[] = [];
  let toolGroup: ChatMessage[] = [];

  for (const msg of messages) {
    if (msg.role === "tool_call" || msg.role === "tool_result") {
      toolGroup.push(msg);
    } else {
      if (toolGroup.length > 0) {
        result.push(toolGroup);
        toolGroup = [];
      }
      result.push(msg);
    }
  }
  if (toolGroup.length > 0) result.push(toolGroup);
  return result;
}

export function MessageList() {
  const { state } = useChatContext();
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [state.messages, state.streamingText]);

  const grouped = groupMessages(state.messages);

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4">
      <div className="mx-auto max-w-3xl space-y-3">
        {state.messages.length === 0 && !state.isStreaming && <EmptyState />}

        {grouped.map((item, i) => {
          const prev = i > 0 ? grouped[i - 1] : null;
          const currentTs = Array.isArray(item) ? item[0].timestamp : item.timestamp;
          const prevTs = prev
            ? Array.isArray(prev) ? prev[prev.length - 1].timestamp : prev.timestamp
            : null;
          const showSeparator = prevTs != null && currentTs - prevTs > 5 * 60 * 1000;

          return (
            <div key={Array.isArray(item) ? `tg-${i}` : item.id}>
              {showSeparator && <TimeSeparator timestamp={currentTs} />}
              {Array.isArray(item) ? (
                <ToolGroup messages={item} />
              ) : (
                <MessageComponent message={item} />
              )}
            </div>
          );
        })}

        {state.isStreaming && !state.streamingText && (
          <div className="flex items-center gap-2 rounded-lg border-l-2 border-green-500/30 bg-zinc-900/50 px-3 py-2">
            <div className="flex gap-1">
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-green-400 [animation-delay:0ms]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-green-400 [animation-delay:150ms]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-green-400 [animation-delay:300ms]" />
            </div>
            <span className="text-xs text-zinc-500">
              {state.currentToolName
                ? `Calling ${state.currentToolName}...`
                : "Thinking..."}
            </span>
          </div>
        )}

        {state.isStreaming && state.streamingText && (
          <StreamingMessage text={state.streamingText} />
        )}

        {state.error && (
          <div className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
            {state.error}
          </div>
        )}
      </div>
    </div>
  );
}

function EmptyState() {
  const { sendMessage, state } = useChatContext();
  const suggestions = [
    "System health",
    "Run briefing",
    "Search documents",
    "What changed today?",
  ];

  return (
    <div className="py-12 text-center">
      <p className="text-sm text-zinc-500">What would you like to do?</p>
      <div className="mt-4 flex flex-wrap justify-center gap-2">
        {suggestions.map((s) => (
          <button
            key={s}
            onClick={() => sendMessage(s)}
            disabled={state.isStreaming}
            className="rounded-full border border-zinc-700 px-3 py-1.5 text-xs text-zinc-400 transition-colors hover:border-zinc-500 hover:text-zinc-200 active:scale-[0.97]"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

function TimeSeparator({ timestamp }: { timestamp: number }) {
  return (
    <div className="flex items-center gap-3 py-1">
      <div className="h-px flex-1 bg-zinc-800" />
      <span className="text-[10px] text-zinc-600">
        {new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
      </span>
      <div className="h-px flex-1 bg-zinc-800" />
    </div>
  );
}

function ToolGroup({ messages }: { messages: ChatMessage[] }) {
  const [expanded, setExpanded] = useState(false);
  const toolNames = [...new Set(messages.filter((m) => m.toolName).map((m) => m.toolName!))];
  const callCount = messages.filter((m) => m.role === "tool_call").length;

  return (
    <div className="rounded border border-zinc-700/50 bg-zinc-800/30">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-zinc-500 hover:text-zinc-400"
      >
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <Wrench className="h-3 w-3" />
        <span>{callCount} tool call{callCount !== 1 ? "s" : ""}</span>
        <span className="truncate text-zinc-600">{toolNames.join(", ")}</span>
      </button>
      {expanded && (
        <div className="space-y-2 border-t border-zinc-800 px-1 py-2">
          {messages.map((msg) => (
            <MessageComponent key={msg.id} message={msg} />
          ))}
        </div>
      )}
    </div>
  );
}

function MessageComponent({ message }: { message: ChatMessage }) {
  switch (message.role) {
    case "user":
      return <UserMessage content={message.content} timestamp={message.timestamp} />;
    case "assistant":
      return <AssistantMessage content={message.content} timestamp={message.timestamp} />;
    case "interviewer":
      return <AssistantMessage content={message.content} variant="interviewer" timestamp={message.timestamp} />;
    case "tool_call":
      return <ToolCallMessage name={message.toolName ?? ""} args={message.toolArgs ?? ""} />;
    case "tool_result":
      return <ToolCallMessage name={message.toolName ?? ""} args={message.content} isResult />;
    case "system":
      return <SystemMessage content={message.content} />;
    default:
      return null;
  }
}
