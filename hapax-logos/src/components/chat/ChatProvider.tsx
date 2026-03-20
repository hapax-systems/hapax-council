import { createContext, useContext, useReducer, useCallback, useRef, useEffect, type ReactNode } from "react";
import { connectSSE } from "../../api/sse";
import { api } from "../../api/client";

// ── Types ──────────────────────────────────────────────────────────────

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system" | "tool_call" | "tool_result" | "interviewer";
  content: string;
  toolName?: string;
  toolArgs?: string;
  timestamp: number;
}

interface ChatState {
  sessionId: string | null;
  messages: ChatMessage[];
  isStreaming: boolean;
  streamingText: string;
  currentToolName: string | null;
  model: string;
  mode: "chat" | "interview";
  totalTokens: number;
  lastTurnTokens: number;
  error: string | null;
}

type ChatAction =
  | { type: "SET_SESSION"; sessionId: string; model: string }
  | { type: "ADD_MESSAGE"; message: ChatMessage }
  | { type: "STREAM_START" }
  | { type: "STREAM_DELTA"; content: string }
  | { type: "STREAM_TOOL_CALL"; name: string; args: string; callId: string }
  | { type: "STREAM_TOOL_RESULT"; name: string; content: string }
  | { type: "STREAM_DONE"; fullText: string; turnTokens: number; totalTokens: number }
  | { type: "STREAM_ERROR"; message: string }
  | { type: "CLEAR" }
  | { type: "SET_MODEL"; model: string }
  | { type: "SET_MODE"; mode: "chat" | "interview" }
  | { type: "SET_ERROR"; error: string | null }
  | { type: "STREAM_ABORT" };

// ── Reducer ────────────────────────────────────────────────────────────

const MAX_MESSAGES = 200;
function capMessages(msgs: ChatMessage[]): ChatMessage[] {
  return msgs.length > MAX_MESSAGES ? msgs.slice(-MAX_MESSAGES) : msgs;
}

function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "SET_SESSION":
      return { ...state, sessionId: action.sessionId, model: action.model };
    case "ADD_MESSAGE":
      return { ...state, messages: capMessages([...state.messages, action.message]) };
    case "STREAM_START":
      return { ...state, isStreaming: true, streamingText: "", currentToolName: null, error: null };
    case "STREAM_DELTA":
      return { ...state, streamingText: state.streamingText + action.content };
    case "STREAM_TOOL_CALL": {
      const toolMsg: ChatMessage = {
        id: action.callId,
        role: "tool_call",
        content: "",
        toolName: action.name,
        toolArgs: action.args,
        timestamp: Date.now(),
      };
      return { ...state, messages: capMessages([...state.messages, toolMsg]), currentToolName: action.name };
    }
    case "STREAM_TOOL_RESULT": {
      const resultMsg: ChatMessage = {
        id: `tool-result-${Date.now()}`,
        role: "tool_result",
        content: action.content,
        toolName: action.name,
        timestamp: Date.now(),
      };
      return { ...state, messages: capMessages([...state.messages, resultMsg]) };
    }
    case "STREAM_DONE": {
      const assistantMsg: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: state.mode === "interview" ? "interviewer" : "assistant",
        content: action.fullText,
        timestamp: Date.now(),
      };
      return {
        ...state,
        isStreaming: false,
        streamingText: "",
        currentToolName: null,
        messages: capMessages([...state.messages, assistantMsg]),
        totalTokens: action.totalTokens,
        lastTurnTokens: action.turnTokens,
      };
    }
    case "STREAM_ERROR":
      return { ...state, isStreaming: false, streamingText: "", currentToolName: null, error: action.message };
    case "CLEAR":
      return { ...state, messages: [], totalTokens: 0, lastTurnTokens: 0, error: null, mode: "chat" };
    case "SET_MODEL":
      return { ...state, model: action.model };
    case "SET_MODE":
      return { ...state, mode: action.mode };
    case "SET_ERROR":
      return { ...state, error: action.error };
    case "STREAM_ABORT":
      return { ...state, isStreaming: false, currentToolName: null };
    default:
      return state;
  }
}

const initialState: ChatState = {
  sessionId: null,
  messages: [],
  isStreaming: false,
  streamingText: "",
  currentToolName: null,
  model: "balanced",
  mode: "chat",
  totalTokens: 0,
  lastTurnTokens: 0,
  error: null,
};

// ── Context ────────────────────────────────────────────────────────────

interface InterviewStatus {
  active: boolean;
  status?: string;
  topics_explored?: number;
  total_topics?: number;
  facts_count?: number;
  insights_count?: number;
}

interface ChatContextValue {
  state: ChatState;
  sendMessage: (text: string) => void;
  stopGeneration: () => void;
  clearChat: () => void;
  switchModel: (model: string) => void;
  initSession: () => Promise<void>;
  addSystemMessage: (content: string) => void;
  exportChat: () => Promise<void>;
  startInterview: () => void;
  endInterview: () => Promise<void>;
  skipInterviewTopic: () => Promise<void>;
  getInterviewStatus: () => Promise<InterviewStatus | null>;
}

const ChatContext = createContext<ChatContextValue | null>(null);

// eslint-disable-next-line react-refresh/only-export-components
export function useChatContext() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChatContext must be used within ChatProvider");
  return ctx;
}

// ── Session persistence ────────────────────────────────────────────────

const SESSION_KEY = "cockpit-chat-session";

function saveSession(sessionId: string, model: string) {
  try {
    localStorage.setItem(SESSION_KEY, JSON.stringify({ sessionId, model }));
  } catch { /* quota exceeded — ignore */ }
}

function loadSession(): { sessionId: string; model: string } | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function clearSavedSession() {
  localStorage.removeItem(SESSION_KEY);
}

// ── Provider ───────────────────────────────────────────────────────────

export function ChatProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(chatReducer, initialState);
  const controllerRef = useRef<AbortController | null>(null);

  // Abort any active stream on unmount
  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
    };
  }, []);

  const initSession = useCallback(async () => {
    if (state.sessionId) return;

    // Try to restore a previous session
    const saved = loadSession();
    if (saved) {
      try {
        const info = await fetch(`/api/chat/sessions/${saved.sessionId}`);
        if (info.ok) {
          dispatch({ type: "SET_SESSION", sessionId: saved.sessionId, model: saved.model });
          return;
        }
      } catch { /* session gone — create new */ }
      clearSavedSession();
    }

    try {
      const res = await api.post<{ session_id: string; model: string }>("/chat/sessions", {
        model: "balanced",
      });
      saveSession(res.session_id, res.model);
      dispatch({ type: "SET_SESSION", sessionId: res.session_id, model: res.model });
    } catch (err) {
      dispatch({ type: "SET_ERROR", error: `Failed to create session: ${err}` });
    }
  }, [state.sessionId]);

  const sendMessage = useCallback(
    (text: string) => {
      if (!state.sessionId || state.isStreaming) return;

      // Add user message
      dispatch({
        type: "ADD_MESSAGE",
        message: {
          id: `user-${Date.now()}`,
          role: "user",
          content: text,
          timestamp: Date.now(),
        },
      });

      dispatch({ type: "STREAM_START" });

      controllerRef.current = connectSSE(`/api/chat/sessions/${state.sessionId}/send`, {
        method: "POST",
        body: { message: text },
        onEvent: (event) => {
          try {
            const data = JSON.parse(event.data);
            switch (event.event) {
              case "text_delta":
                dispatch({ type: "STREAM_DELTA", content: data.content });
                break;
              case "tool_call":
                dispatch({
                  type: "STREAM_TOOL_CALL",
                  name: data.name,
                  args: data.args,
                  callId: data.call_id,
                });
                break;
              case "tool_result":
                dispatch({
                  type: "STREAM_TOOL_RESULT",
                  name: data.name,
                  content: data.content,
                });
                break;
              case "done":
                dispatch({
                  type: "STREAM_DONE",
                  fullText: data.full_text,
                  turnTokens: data.turn_tokens,
                  totalTokens: data.total_tokens,
                });
                break;
              case "error":
                dispatch({ type: "STREAM_ERROR", message: data.message });
                break;
            }
          } catch {
            // Ignore non-JSON events
          }
        },
        onError: (err) => dispatch({ type: "STREAM_ERROR", message: err.message }),
        onDone: () => dispatch({ type: "STREAM_ABORT" }),
      });
    },
    [state.sessionId, state.isStreaming],
  );

  const stopGeneration = useCallback(() => {
    controllerRef.current?.abort();
    if (state.sessionId) {
      api.post(`/chat/sessions/${state.sessionId}/stop`).catch(() => {});
    }
  }, [state.sessionId]);

  const clearChat = useCallback(() => {
    if (state.sessionId) {
      api.del(`/chat/sessions/${state.sessionId}`).catch(() => {});
    }
    clearSavedSession();
    dispatch({ type: "CLEAR" });
    api.post<{ session_id: string; model: string }>("/chat/sessions", { model: state.model })
      .then((res) => {
        saveSession(res.session_id, res.model);
        dispatch({ type: "SET_SESSION", sessionId: res.session_id, model: res.model });
      })
      .catch(() => {});
  }, [state.sessionId, state.model]);

  const switchModel = useCallback(
    (model: string) => {
      dispatch({ type: "SET_MODEL", model });
      if (state.sessionId) {
        api.post(`/chat/sessions/${state.sessionId}/model`, { model }).catch(() => {});
      }
    },
    [state.sessionId],
  );

  const addSystemMessage = useCallback((content: string) => {
    dispatch({
      type: "ADD_MESSAGE",
      message: {
        id: `system-${Date.now()}`,
        role: "system",
        content,
        timestamp: Date.now(),
      },
    });
  }, []);

  const exportChat = useCallback(async () => {
    if (!state.sessionId) return;
    try {
      const res = await api.post<{ content: string }>(`/chat/sessions/${state.sessionId}/export`);
      const blob = new Blob([res.content], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `chat-export-${new Date().toISOString().slice(0, 10)}.md`;
      a.click();
      URL.revokeObjectURL(url);
      addSystemMessage("Chat exported.");
    } catch (err) {
      addSystemMessage(`Export failed: ${err}`);
    }
  }, [state.sessionId, addSystemMessage]);

  const startInterview = useCallback(() => {
    if (!state.sessionId || state.isStreaming) return;

    dispatch({ type: "SET_MODE", mode: "interview" });
    dispatch({ type: "STREAM_START" });

    controllerRef.current = connectSSE(`/api/chat/sessions/${state.sessionId}/interview`, {
      method: "POST",
      onEvent: (event) => {
        try {
          const data = JSON.parse(event.data);
          switch (event.event) {
            case "text_delta":
              dispatch({ type: "STREAM_DELTA", content: data.content });
              break;
            case "tool_call":
              dispatch({
                type: "STREAM_TOOL_CALL",
                name: data.name,
                args: data.args,
                callId: data.call_id,
              });
              break;
            case "tool_result":
              dispatch({
                type: "STREAM_TOOL_RESULT",
                name: data.name,
                content: data.content,
              });
              break;
            case "plan_ready":
              addSystemMessage(
                `Interview plan ready: ${data.topic_count} topics. Starting with: ${data.focus}`
              );
              break;
            case "done":
              dispatch({
                type: "STREAM_DONE",
                fullText: data.full_text,
                turnTokens: data.turn_tokens,
                totalTokens: data.total_tokens,
              });
              break;
            case "error":
              dispatch({ type: "STREAM_ERROR", message: data.message });
              break;
          }
        } catch {
          // Ignore non-JSON events
        }
      },
      onError: (err) => dispatch({ type: "STREAM_ERROR", message: err.message }),
      onDone: () => dispatch({ type: "STREAM_ABORT" }),
    });
  }, [state.sessionId, state.isStreaming, addSystemMessage]);

  const endInterview = useCallback(async () => {
    if (!state.sessionId) return;
    try {
      const res = await api.post<{ status: string; summary: string }>(
        `/chat/sessions/${state.sessionId}/interview/end`
      );
      dispatch({ type: "SET_MODE", mode: "chat" });
      addSystemMessage(`Interview ended. ${res.summary}`);
    } catch (err) {
      addSystemMessage(`Failed to end interview: ${err}`);
    }
  }, [state.sessionId, addSystemMessage]);

  const skipInterviewTopic = useCallback(async () => {
    if (!state.sessionId) return;
    try {
      const res = await api.post<{ status: string; message: string }>(
        `/chat/sessions/${state.sessionId}/interview/skip`
      );
      addSystemMessage(res.message);
    } catch (err) {
      addSystemMessage(`Failed to skip topic: ${err}`);
    }
  }, [state.sessionId, addSystemMessage]);

  const getInterviewStatus = useCallback(async (): Promise<InterviewStatus | null> => {
    if (!state.sessionId) return null;
    try {
      const res = await fetch(`/api/chat/sessions/${state.sessionId}/interview/status`);
      if (!res.ok) return null;
      return await res.json() as InterviewStatus;
    } catch {
      return null;
    }
  }, [state.sessionId]);

  return (
    <ChatContext.Provider
      value={{
        state,
        sendMessage,
        stopGeneration,
        clearChat,
        switchModel,
        initSession,
        addSystemMessage,
        exportChat,
        startInterview,
        endInterview,
        skipInterviewTopic,
        getInterviewStatus,
      }}
    >
      {children}
    </ChatContext.Provider>
  );
}
