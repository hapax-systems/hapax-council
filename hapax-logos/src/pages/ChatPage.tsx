import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { ChatProvider, useChatContext } from "../components/chat/ChatProvider";
import { MessageList } from "../components/chat/MessageList";
import { ChatInput } from "../components/chat/ChatInput";
import { StatusBar } from "../components/chat/StatusBar";

export function ChatPage() {
  return (
    <ChatProvider>
      <ChatPageInner />
    </ChatProvider>
  );
}

function ChatPageInner() {
  const { initSession, sendMessage, state } = useChatContext();
  const [searchParams, setSearchParams] = useSearchParams();

  // Initialize session on mount
  useEffect(() => {
    initSession();
  }, [initSession]);

  // Handle ?message= param (command palette, external deep links)
  useEffect(() => {
    const msg = searchParams.get("message");
    if (msg && state.sessionId && !state.isStreaming) {
      sendMessage(msg);
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, state.sessionId, state.isStreaming, sendMessage, setSearchParams]);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <MessageList />
      <StatusBar />
      <ChatInput />
    </div>
  );
}
