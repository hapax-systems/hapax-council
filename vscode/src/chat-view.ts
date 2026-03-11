import * as vscode from "vscode";
import { randomBytes } from "crypto";
import { marked } from "marked";
import type { ChatMessage } from "./types";
import { LLMClient } from "./llm-client";
import { getSettings } from "./settings";
import { InterviewEngine } from "./interview/engine";
import { matchCommands } from "./slash-commands";
import { readVaultFile, parseFrontmatter } from "./vault";

// Configure marked for safe output
marked.setOptions({ breaks: true, gfm: true });

/** Strip HTTP response bodies and URLs from error messages shown in the UI. */
function sanitizeErrorForDisplay(msg: string): string {
  // Extract just the HTTP status if present (e.g. "HTTP 401: {long body}")
  const statusMatch = msg.match(/\b(HTTP|status)\s*(\d{3})/i);
  if (statusMatch) {
    const code = statusMatch[2];
    const hints: Record<string, string> = {
      "401": "Check your API key in settings.",
      "403": "Access denied. Check your API key.",
      "429": "Rate limit exceeded. Try again shortly.",
      "500": "Provider server error. Try again.",
      "503": "Provider unavailable. Try again later.",
    };
    return `Request failed (${code}). ${hints[code] || "Check settings and try again."}`;
  }
  // Strip URLs to avoid exposing infrastructure
  const cleaned = msg.replace(/https?:\/\/[^\s)]+/g, "[url]");
  // Truncate long messages
  return cleaned.length > 150 ? cleaned.slice(0, 150) + "..." : cleaned;
}

const HISTORY_KEY = "hapax.chatHistory";
const MAX_HISTORY = 50;

export class ChatViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "hapax.chatView";

  private view?: vscode.WebviewView;
  private messages: ChatMessage[] = [];
  private llmClient: LLMClient;
  private abortController: AbortController | null = null;
  private isStreaming = false;
  private interviewEngine: InterviewEngine | null = null;
  private readonly isWorkVault: boolean;

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly context: vscode.ExtensionContext,
    isWorkVault: boolean,
  ) {
    const settings = getSettings();
    this.llmClient = new LLMClient(settings);
    this.isWorkVault = isWorkVault;
    this.loadHistory();
  }

  async resolveWebviewView(webviewView: vscode.WebviewView): Promise<void> {
    this.view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this.extensionUri],
    };

    webviewView.webview.html = this.getHtml();

    webviewView.webview.onDidReceiveMessage(async (message) => {
      switch (message.type) {
        case "send":
          await this.handleUserMessage(message.text);
          break;
        case "stop":
          this.abortController?.abort();
          break;
        case "clear":
          this.messages = [];
          this.saveHistory();
          this.postMessage({ type: "cleared" });
          break;
        case "slashQuery": {
          const matched = matchCommands(message.text, this.isWorkVault);
          this.postMessage({
            type: "suggestions",
            items: matched.map((cmd) => ({
              name: cmd.name,
              description: cmd.description,
              template: cmd.template,
            })),
          });
          break;
        }
        case "setupStart":
          await this.handleSetupStart();
          break;
        case "setupSkip":
          await this.handleSetupSkip();
          break;
      }
    });

    // Restore history to webview
    for (const msg of this.messages) {
      const html = msg.role === "assistant" ? marked.parse(msg.content) : "";
      this.postMessage({ type: "message", role: msg.role, content: msg.content, html });
    }

    // Initialize interview engine (work vault only)
    if (this.isWorkVault) {
      const settings = getSettings();
      this.interviewEngine = new InterviewEngine(this.context, settings);
      await this.interviewEngine.load();

      // Show setup banner if foundational gaps exist
      if (await this.interviewEngine.hasFoundationalGaps()) {
        this.postMessage({ type: "showSetupBanner" });
      }
    }
  }

  /** Public API for commands to inject a message and trigger an LLM response. */
  public injectMessage(label: string, content: string): void {
    if (this.isStreaming) {
      vscode.window.showWarningMessage(
        "Wait for the current response to finish before running a command.",
      );
      return;
    }
    // Show label in UI, send full content to LLM
    this.postMessage({ type: "message", role: "user", content: label, html: "" });
    const userMsg: ChatMessage = {
      role: "user",
      content,
      timestamp: Date.now(),
    };
    this.messages.push(userMsg);
    this.saveHistory();
    this.streamResponse().catch((err: unknown) =>
      console.error("Hapax: injectMessage stream failed:", err),
    );
  }

  private async handleUserMessage(text: string): Promise<void> {
    const trimmed = text.trim();
    if (!trimmed || this.isStreaming) return;

    // Intercept setup magic strings
    if (trimmed === "__SETUP_START__") {
      await this.handleSetupStart();
      return;
    }
    if (trimmed === "__SETUP_SKIP__") {
      await this.handleSetupSkip();
      return;
    }
    if (trimmed === "__SETUP_STATUS__") {
      await this.showSetupProgress();
      return;
    }

    // If interview is active, route answer to interview engine
    if (this.interviewEngine?.isActive()) {
      this.isStreaming = true;

      // Show user message
      const userMsg: ChatMessage = { role: "user", content: trimmed, timestamp: Date.now() };
      this.messages.push(userMsg);
      this.saveHistory();
      this.postMessage({ type: "message", role: "user", content: trimmed, html: "" });

      try {
        const result = await this.interviewEngine.processAnswer(trimmed);

        // Show result message
        const resultMsg: ChatMessage = {
          role: "assistant",
          content: result.message,
          timestamp: Date.now(),
        };
        this.messages.push(resultMsg);
        this.saveHistory();
        this.postMessage({
          type: "message",
          role: "assistant",
          content: result.message,
          html: marked.parse(result.message),
        });

        if (result.nextQuestion) {
          // Show next question
          const nextMsg: ChatMessage = {
            role: "assistant",
            content: result.nextQuestion.question,
            timestamp: Date.now(),
          };
          this.messages.push(nextMsg);
          this.saveHistory();
          this.postMessage({
            type: "message",
            role: "assistant",
            content: result.nextQuestion.question,
            html: marked.parse(result.nextQuestion.question),
          });
        } else if (result.success) {
          // Interview complete
          const doneMsg: ChatMessage = {
            role: "assistant",
            content: "Setup interview complete! All acquirable requirements satisfied.",
            timestamp: Date.now(),
          };
          this.messages.push(doneMsg);
          this.saveHistory();
          this.postMessage({
            type: "message",
            role: "assistant",
            content: doneMsg.content,
            html: marked.parse(doneMsg.content),
          });

          // Check if foundational complete
          const progress = await this.interviewEngine.getProgress();
          if (progress.foundationalComplete) {
            this.postMessage({ type: "hideSetupBanner" });
            const opMsg: ChatMessage = {
              role: "assistant",
              content: "Management system is now operational. All foundational data is in place.",
              timestamp: Date.now(),
            };
            this.messages.push(opMsg);
            this.saveHistory();
            this.postMessage({
              type: "message",
              role: "assistant",
              content: opMsg.content,
              html: marked.parse(opMsg.content),
            });
          }
        }
      } catch (err: unknown) {
        const fullMsg = err instanceof Error ? err.message : String(err);
        console.error("Hapax: interview processAnswer error:", fullMsg);
        this.postMessage({ type: "error", content: sanitizeErrorForDisplay(fullMsg) });
      } finally {
        this.isStreaming = false;
      }
      return;
    }

    const userMsg: ChatMessage = {
      role: "user",
      content: trimmed,
      timestamp: Date.now(),
    };
    this.messages.push(userMsg);
    this.saveHistory();

    this.postMessage({ type: "message", role: "user", content: trimmed, html: "" });

    await this.streamResponse();
  }

  private async streamResponse(): Promise<void> {
    this.isStreaming = true;
    this.abortController = new AbortController();

    try {
      // Refresh settings in case they changed
      const settings = getSettings();
      this.llmClient.updateSettings(settings);

      // Build API messages
      const apiMessages: Array<{ role: string; content: string }> = [];

      // System prompt + vault context + note-type prefix + editor content
      let systemContent = settings.systemPrompt;

      const vaultContext = await this.loadVaultContext();
      if (vaultContext) {
        systemContent += `\n\n${vaultContext}`;
      }

      const noteType = this.getNoteTypeFromActiveEditor();
      if (noteType) {
        const editor = vscode.window.activeTextEditor;
        const fileName = editor ? editor.document.fileName : "";
        const prefix = this.buildContextPrefix(noteType, fileName);
        if (prefix) {
          systemContent += `\n\n${prefix}`;
        }
      }

      const editorContent = this.getActiveEditorContent(settings.maxContextLength);
      if (editorContent) {
        systemContent += `\n\nCurrent file context:\n${editorContent}`;
      }

      apiMessages.push({ role: "system", content: systemContent });

      // Conversation history
      for (const msg of this.messages) {
        apiMessages.push({ role: msg.role, content: msg.content });
      }

      this.postMessage({ type: "streamStart" });

      const assistantMsg: ChatMessage = {
        role: "assistant",
        content: "",
        timestamp: Date.now(),
      };

      try {
        for await (const chunk of this.llmClient.streamChat(
          apiMessages,
          this.abortController.signal,
        )) {
          assistantMsg.content += chunk;
          this.postMessage({ type: "streamChunk", content: chunk });
        }

        this.postMessage({ type: "streamEnd", html: marked.parse(assistantMsg.content) });
        this.messages.push(assistantMsg);
        this.saveHistory();
      } catch (err: unknown) {
        if (err instanceof Error && err.name === "AbortError") {
          assistantMsg.content += "\n\n[Stopped]";
          this.postMessage({ type: "streamChunk", content: "\n\n[Stopped]" });
          this.postMessage({ type: "streamEnd", html: marked.parse(assistantMsg.content) });
          this.messages.push(assistantMsg);
          this.saveHistory();
        } else {
          const fullMsg = err instanceof Error ? err.message : String(err);
          console.error("Hapax: LLM error:", fullMsg);
          this.postMessage({
            type: "error",
            content: sanitizeErrorForDisplay(fullMsg),
          });
        }
      }
    } catch (err: unknown) {
      console.error("Hapax: streamResponse error:", err);
      const fullMsg = err instanceof Error ? err.message : String(err);
      this.postMessage({
        type: "error",
        content: sanitizeErrorForDisplay(fullMsg),
      });
    } finally {
      this.isStreaming = false;
      this.abortController = null;
    }
  }

  // ── Interview UI ────────────────────────────────────────────

  private async handleSetupStart(): Promise<void> {
    if (!this.interviewEngine) return;

    const q = await this.interviewEngine.start();
    if (!q) {
      const doneMsg: ChatMessage = {
        role: "assistant",
        content: "All interview-acquirable requirements are satisfied! Your management system is operational.",
        timestamp: Date.now(),
      };
      this.messages.push(doneMsg);
      this.saveHistory();
      this.postMessage({
        type: "message",
        role: "assistant",
        content: doneMsg.content,
        html: marked.parse(doneMsg.content),
      });
      this.postMessage({ type: "hideSetupBanner" });
      return;
    }

    await this.showSetupProgress();

    const questionMsg: ChatMessage = {
      role: "assistant",
      content: q.question,
      timestamp: Date.now(),
    };
    this.messages.push(questionMsg);
    this.saveHistory();
    this.postMessage({
      type: "message",
      role: "assistant",
      content: q.question,
      html: marked.parse(q.question),
    });
  }

  private async handleSetupSkip(): Promise<void> {
    if (!this.interviewEngine) return;

    const next = await this.interviewEngine.skip();
    if (next) {
      const msg: ChatMessage = {
        role: "assistant",
        content: `Skipped. Next question:\n\n${next.question}`,
        timestamp: Date.now(),
      };
      this.messages.push(msg);
      this.saveHistory();
      this.postMessage({
        type: "message",
        role: "assistant",
        content: msg.content,
        html: marked.parse(msg.content),
      });
    } else {
      const msg: ChatMessage = {
        role: "assistant",
        content: "No more questions. Setup complete!",
        timestamp: Date.now(),
      };
      this.messages.push(msg);
      this.saveHistory();
      this.postMessage({
        type: "message",
        role: "assistant",
        content: msg.content,
        html: marked.parse(msg.content),
      });
      this.postMessage({ type: "hideSetupBanner" });
    }
  }

  private async showSetupProgress(): Promise<void> {
    if (!this.interviewEngine) return;
    const progress = await this.interviewEngine.getProgress();
    const text = `**Setup Progress**\n` +
      `- Foundational: ${progress.foundational.done}/${progress.foundational.total}\n` +
      `- Structural: ${progress.structural.done}/${progress.structural.total}\n` +
      `- Enrichment: ${progress.enrichment.done}/${progress.enrichment.total}`;

    const statusMsg: ChatMessage = {
      role: "assistant",
      content: text,
      timestamp: Date.now(),
    };
    this.messages.push(statusMsg);
    this.saveHistory();
    this.postMessage({
      type: "message",
      role: "assistant",
      content: text,
      html: marked.parse(text),
    });
  }

  // ── Vault context & note-type awareness ─────────────────

  private vaultContextCache: string | null | undefined = undefined;

  private async loadVaultContext(): Promise<string | null> {
    if (this.vaultContextCache !== undefined) return this.vaultContextCache;
    try {
      this.vaultContextCache = await readVaultFile("30-system/hapax-context.md");
    } catch {
      // File doesn't exist or workspace not open — degrade gracefully
      this.vaultContextCache = null;
    }
    return this.vaultContextCache;
  }

  private getNoteTypeFromActiveEditor(): string | null {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return null;

    const text = editor.document.getText();
    try {
      const { data } = parseFrontmatter(text);
      if (typeof data.type === "string") return data.type;
    } catch {
      // Not valid frontmatter — ignore
    }
    return null;
  }

  private buildContextPrefix(noteType: string, _fileName: string): string {
    const prefixes: Record<string, string> = {
      person:
        "The user has a person/team member note open. Focus on management context — coaching, growth, feedback, cognitive load. Do not draft feedback language or coaching hypotheses directly; instead provide signal aggregation and context synthesis.",
      "meeting-1on1":
        "The user has a meeting note open. Help with preparation (key topics, questions to ask, context review) and post-meeting follow-up synthesis (action items, decisions, observations).",
      "meeting-ceremony":
        "The user has a meeting note open. Help with preparation (key topics, questions to ask, context review) and post-meeting follow-up synthesis (action items, decisions, observations).",
      briefing:
        "The user is viewing a system-generated briefing or digest. Help interpret findings, prioritize action items, and suggest next steps. Reference specific items from the note content.",
      digest:
        "The user is viewing a system-generated briefing or digest. Help interpret findings, prioritize action items, and suggest next steps. Reference specific items from the note content.",
      daily:
        "The user has their daily note open. Help with day planning, task prioritization, energy-aware scheduling, and end-of-day review. Be concrete and actionable.",
      weekly:
        "The user has their weekly review open. Help with team health assessment, pattern recognition across the week, cognitive load evaluation, and next-week focus setting.",
      decision:
        "The user has a decision record open. Help evaluate options, identify trade-offs, surface relevant precedents, and ensure the decision is well-documented.",
      project:
        "The user has a project note open. Help with project status assessment, risk identification, blocker resolution, and stakeholder communication.",
      coaching:
        "The user has a coaching hypothesis note open. Help assess the hypothesis against observable evidence, suggest what to look for, and track experiment outcomes. Do NOT generate coaching advice or suggest what to say — surface patterns only.",
      feedback:
        "The user has a feedback record open. Help organize factual observations and context. Do NOT draft feedback language or evaluate the person — record observed behaviors only.",
      "1on1-prep":
        "The user has a 1:1 prep document open. Help review talking points, identify gaps in preparation, and surface relevant context from recent meetings and coaching notes.",
      "team-state":
        "The user has a team state snapshot open. Help interpret team-level signals — capacity, cognitive load distribution, Larson state, topology alignment. Flag patterns and risks from observable data.",
      "management-overview":
        "The user has the management overview open. Help with cross-team pattern recognition, portfolio-level capacity assessment, and identifying systemic risks across all teams.",
      "weekly-review":
        "The user has a weekly review open. Help assess the week's cognitive load trends, meeting effectiveness, coaching progress, and identify focus areas for next week. Stick to data-backed observations.",
    };

    return prefixes[noteType] ?? "";
  }

  private getActiveEditorContent(maxLen: number): string | null {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return null;

    const doc = editor.document;
    let content = doc.getText();
    if (content.length > maxLen) {
      content = content.slice(0, maxLen) + "\n\n[... truncated]";
    }
    return `File: ${doc.fileName}\n\n${content}`;
  }

  private postMessage(message: Record<string, unknown>): void {
    this.view?.webview.postMessage(message);
  }

  private loadHistory(): void {
    try {
      const stored = this.context.globalState.get<ChatMessage[]>(HISTORY_KEY);
      if (stored && Array.isArray(stored)) {
        this.messages = stored;
      }
    } catch (err: unknown) {
      console.error("Hapax: failed to load chat history:", err);
    }
  }

  private saveHistory(): void {
    try {
      const toSave = this.messages.slice(-MAX_HISTORY);
      this.context.globalState.update(HISTORY_KEY, toSave);
    } catch (err: unknown) {
      console.error("Hapax: failed to save chat history:", err);
    }
  }

  private getNonce(): string {
    return randomBytes(16).toString("hex");
  }

  private getHtml(): string {
    const nonce = this.getNonce();
    return /*html*/ `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size);
      color: var(--vscode-foreground);
      background: var(--vscode-sideBar-background);
      display: flex;
      flex-direction: column;
      height: 100vh;
      overflow: hidden;
    }

    .header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 8px 12px;
      border-bottom: 1px solid var(--vscode-panel-border);
    }

    .header-title {
      font-weight: 600;
      font-size: 13px;
    }

    .clear-btn {
      background: none;
      border: none;
      color: var(--vscode-foreground);
      cursor: pointer;
      padding: 4px;
      border-radius: 4px;
      font-size: 12px;
    }

    .clear-btn:hover {
      background: var(--vscode-toolbar-hoverBackground);
    }

    .messages {
      flex: 1;
      overflow-y: auto;
      padding: 8px 12px;
    }

    .message {
      margin-bottom: 12px;
      padding: 8px 10px;
      border-radius: 6px;
      word-wrap: break-word;
    }

    .message-user {
      white-space: pre-wrap;
    }

    .message-label {
      font-weight: 600;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 4px;
      opacity: 0.7;
    }

    .message-user {
      background: var(--vscode-input-background);
      border: 1px solid var(--vscode-input-border, transparent);
    }

    .message-assistant {
      background: var(--vscode-editor-background);
      border: 1px solid var(--vscode-panel-border, transparent);
    }

    .message-error {
      background: var(--vscode-inputValidation-errorBackground, #5a1d1d);
      border: 1px solid var(--vscode-inputValidation-errorBorder, #be1100);
      color: var(--vscode-errorForeground, #f48771);
      white-space: pre-wrap;
    }

    .message-content h1, .message-content h2, .message-content h3 { margin: 8px 0 4px; }
    .message-content p { margin: 4px 0; }
    .message-content code { background: var(--vscode-textCodeBlock-background); padding: 1px 4px; border-radius: 3px; font-family: var(--vscode-editor-font-family); font-size: 0.9em; }
    .message-content pre { background: var(--vscode-textCodeBlock-background); padding: 8px; border-radius: 4px; overflow-x: auto; margin: 8px 0; }
    .message-content pre code { background: none; padding: 0; }
    .message-content ul, .message-content ol { margin: 4px 0; padding-left: 20px; }
    .message-content blockquote { border-left: 3px solid var(--vscode-textBlockQuote-border); padding-left: 8px; margin: 4px 0; opacity: 0.8; }
    .message-content a { color: var(--vscode-textLink-foreground); }

    .input-area {
      padding: 8px 12px;
      border-top: 1px solid var(--vscode-panel-border);
    }

    textarea {
      width: 100%;
      min-height: 60px;
      max-height: 150px;
      resize: vertical;
      background: var(--vscode-input-background);
      color: var(--vscode-input-foreground);
      border: 1px solid var(--vscode-input-border, var(--vscode-panel-border));
      border-radius: 4px;
      padding: 8px;
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size);
      outline: none;
    }

    textarea:focus {
      border-color: var(--vscode-focusBorder);
    }

    .button-row {
      display: flex;
      gap: 6px;
      margin-top: 6px;
    }

    button.send-btn, button.stop-btn {
      padding: 4px 12px;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 12px;
    }

    button.send-btn {
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
    }

    button.send-btn:hover {
      background: var(--vscode-button-hoverBackground);
    }

    button.stop-btn {
      background: var(--vscode-button-secondaryBackground);
      color: var(--vscode-button-secondaryForeground);
    }

    button.stop-btn:hover {
      background: var(--vscode-button-secondaryHoverBackground);
    }

    .setup-banner {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 8px 12px;
      background: var(--vscode-editorInfo-background, rgba(0, 120, 212, 0.1));
      border-bottom: 1px solid var(--vscode-panel-border);
      font-size: 12px;
    }

    .setup-banner-text {
      flex: 1;
    }

    .setup-banner-actions {
      display: flex;
      gap: 6px;
      flex-shrink: 0;
    }

    .setup-banner button {
      padding: 2px 8px;
      border: none;
      border-radius: 3px;
      cursor: pointer;
      font-size: 11px;
    }

    .setup-start-btn {
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
    }

    .setup-start-btn:hover {
      background: var(--vscode-button-hoverBackground);
    }

    .setup-skip-btn {
      background: var(--vscode-button-secondaryBackground);
      color: var(--vscode-button-secondaryForeground);
    }

    .setup-skip-btn:hover {
      background: var(--vscode-button-secondaryHoverBackground);
    }

    .setup-banner.hidden {
      display: none;
    }

    .suggestions {
      position: relative;
      background: var(--vscode-editorSuggestWidget-background, var(--vscode-editor-background));
      border: 1px solid var(--vscode-editorSuggestWidget-border, var(--vscode-panel-border));
      border-radius: 4px;
      margin-bottom: 4px;
      max-height: 180px;
      overflow-y: auto;
      z-index: 10;
    }

    .suggestions.hidden {
      display: none;
    }

    .suggestion-item {
      padding: 6px 10px;
      cursor: pointer;
      border-bottom: 1px solid var(--vscode-panel-border);
    }

    .suggestion-item:last-child {
      border-bottom: none;
    }

    .suggestion-item.is-selected {
      background: var(--vscode-editorSuggestWidget-selectedBackground, var(--vscode-list-activeSelectionBackground));
      color: var(--vscode-editorSuggestWidget-selectedForeground, var(--vscode-list-activeSelectionForeground));
    }

    .suggestion-item:hover {
      background: var(--vscode-list-hoverBackground);
    }

    .suggestion-name {
      font-weight: 600;
      font-size: 12px;
    }

    .suggestion-desc {
      font-size: 11px;
      opacity: 0.7;
      margin-top: 2px;
    }
  </style>
</head>
<body>
  <div class="header">
    <span class="header-title">Hapax Chat</span>
    <button class="clear-btn" id="clearBtn" title="Clear chat">Clear</button>
  </div>
  <div class="setup-banner hidden" id="setupBanner">
    <span class="setup-banner-text">Your management system needs setup data</span>
    <div class="setup-banner-actions">
      <button class="setup-start-btn" id="setupStartBtn">Start Setup</button>
      <button class="setup-skip-btn" id="setupSkipBtn">Skip</button>
    </div>
  </div>
  <div class="messages" id="messages"></div>
  <div class="input-area">
    <div class="suggestions hidden" id="suggestions"></div>
    <textarea id="input" placeholder="Ask anything... (Shift+Enter for newline)" rows="3"></textarea>
    <div class="button-row">
      <button class="send-btn" id="sendBtn">Send</button>
      <button class="stop-btn" id="stopBtn">Stop</button>
    </div>
  </div>

  <script nonce="${nonce}">
    (function() {
      const vscode = acquireVsCodeApi();
      const messagesEl = document.getElementById("messages");
      const inputEl = document.getElementById("input");
      const sendBtn = document.getElementById("sendBtn");
      const stopBtn = document.getElementById("stopBtn");
      const clearBtn = document.getElementById("clearBtn");
      const setupBanner = document.getElementById("setupBanner");
      const setupStartBtn = document.getElementById("setupStartBtn");
      const setupSkipBtn = document.getElementById("setupSkipBtn");
      const suggestionsEl = document.getElementById("suggestions");

      let streamingEl = null;
      let currentSuggestions = [];
      let selectedIndex = -1;

      function renderMarkdown(container, html) {
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, "text/html");
        container.textContent = "";
        while (doc.body.firstChild) {
          container.appendChild(doc.body.firstChild);
        }
      }

      function addMessage(role, content, html) {
        const msgDiv = document.createElement("div");
        const roleClass = role === "user" ? "message-user" : "message-assistant";
        msgDiv.className = "message " + roleClass;

        const labelDiv = document.createElement("div");
        labelDiv.className = "message-label";
        labelDiv.textContent = role === "user" ? "You" : "Assistant";
        msgDiv.appendChild(labelDiv);

        const contentDiv = document.createElement("div");
        contentDiv.className = "message-content";
        if (role === "assistant" && html) {
          renderMarkdown(contentDiv, html);
        } else {
          contentDiv.textContent = content;
        }
        msgDiv.appendChild(contentDiv);

        messagesEl.appendChild(msgDiv);
        messagesEl.scrollTop = messagesEl.scrollHeight;
        return msgDiv;
      }

      function addError(content) {
        const msgDiv = document.createElement("div");
        msgDiv.className = "message message-error";

        const labelDiv = document.createElement("div");
        labelDiv.className = "message-label";
        labelDiv.textContent = "Error";
        msgDiv.appendChild(labelDiv);

        const contentDiv = document.createElement("div");
        contentDiv.textContent = content;
        msgDiv.appendChild(contentDiv);

        messagesEl.appendChild(msgDiv);
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }

      function sendMessage() {
        const text = inputEl.value.trim();
        if (!text) return;
        inputEl.value = "";
        vscode.postMessage({ type: "send", text: text });
      }

      sendBtn.addEventListener("click", sendMessage);

      stopBtn.addEventListener("click", function() {
        vscode.postMessage({ type: "stop" });
      });

      clearBtn.addEventListener("click", function() {
        vscode.postMessage({ type: "clear" });
      });

      setupStartBtn.addEventListener("click", function() {
        vscode.postMessage({ type: "setupStart" });
      });

      setupSkipBtn.addEventListener("click", function() {
        vscode.postMessage({ type: "setupSkip" });
      });

      function showSuggestions(items) {
        currentSuggestions = items;
        selectedIndex = items.length > 0 ? 0 : -1;
        suggestionsEl.textContent = "";

        for (let i = 0; i < items.length; i++) {
          const item = document.createElement("div");
          item.className = "suggestion-item" + (i === 0 ? " is-selected" : "");

          const nameDiv = document.createElement("div");
          nameDiv.className = "suggestion-name";
          nameDiv.textContent = items[i].name;
          item.appendChild(nameDiv);

          const descDiv = document.createElement("div");
          descDiv.className = "suggestion-desc";
          descDiv.textContent = items[i].description;
          item.appendChild(descDiv);

          item.addEventListener("click", function() {
            applySuggestion(items[i]);
          });
          suggestionsEl.appendChild(item);
        }

        suggestionsEl.classList.remove("hidden");
      }

      function hideSuggestions() {
        suggestionsEl.classList.add("hidden");
        suggestionsEl.textContent = "";
        currentSuggestions = [];
        selectedIndex = -1;
      }

      function updateSuggestionSelection() {
        const items = suggestionsEl.querySelectorAll(".suggestion-item");
        for (let i = 0; i < items.length; i++) {
          if (i === selectedIndex) {
            items[i].classList.add("is-selected");
          } else {
            items[i].classList.remove("is-selected");
          }
        }
      }

      function applySuggestion(cmd) {
        inputEl.value = cmd.template;
        hideSuggestions();
        inputEl.focus();
        // Trigger send immediately for magic strings, let user edit otherwise
        if (cmd.template.startsWith("__") && cmd.template.endsWith("__")) {
          sendMessage();
        }
      }

      inputEl.addEventListener("input", function() {
        const value = inputEl.value.trim();
        if (value.startsWith("/") && (!value.includes(" ") || value.startsWith("/setup"))) {
          vscode.postMessage({ type: "slashQuery", text: value });
        } else {
          hideSuggestions();
        }
      });

      inputEl.addEventListener("keydown", function(e) {
        // Handle suggestion navigation when visible
        if (currentSuggestions.length > 0 && !suggestionsEl.classList.contains("hidden")) {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            selectedIndex = Math.min(selectedIndex + 1, currentSuggestions.length - 1);
            updateSuggestionSelection();
            return;
          }
          if (e.key === "ArrowUp") {
            e.preventDefault();
            selectedIndex = Math.max(selectedIndex - 1, 0);
            updateSuggestionSelection();
            return;
          }
          if (e.key === "Enter" && selectedIndex >= 0) {
            e.preventDefault();
            applySuggestion(currentSuggestions[selectedIndex]);
            return;
          }
          if (e.key === "Escape") {
            e.preventDefault();
            hideSuggestions();
            return;
          }
        }

        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          sendMessage();
        }
      });

      window.addEventListener("message", function(event) {
        const msg = event.data;
        switch (msg.type) {
          case "message":
            addMessage(msg.role, msg.content, msg.html);
            break;

          case "streamStart": {
            const msgDiv = document.createElement("div");
            msgDiv.className = "message message-assistant";

            const labelDiv = document.createElement("div");
            labelDiv.className = "message-label";
            labelDiv.textContent = "Assistant";
            msgDiv.appendChild(labelDiv);

            const contentDiv = document.createElement("div");
            contentDiv.className = "message-content";
            contentDiv.textContent = "";
            msgDiv.appendChild(contentDiv);

            messagesEl.appendChild(msgDiv);
            streamingEl = contentDiv;
            messagesEl.scrollTop = messagesEl.scrollHeight;
            break;
          }

          case "streamChunk":
            if (streamingEl) {
              streamingEl.textContent += msg.content;
              messagesEl.scrollTop = messagesEl.scrollHeight;
            }
            break;

          case "streamEnd":
            if (streamingEl && msg.html) {
              renderMarkdown(streamingEl, msg.html);
            }
            streamingEl = null;
            break;

          case "error":
            addError(msg.content);
            streamingEl = null;
            break;

          case "cleared":
            messagesEl.replaceChildren();
            break;

          case "showSetupBanner":
            setupBanner.classList.remove("hidden");
            break;

          case "hideSetupBanner":
            setupBanner.classList.add("hidden");
            break;

          case "suggestions":
            if (msg.items && msg.items.length > 0) {
              showSuggestions(msg.items);
            } else {
              hideSuggestions();
            }
            break;
        }
      });
    })();
  </script>
</body>
</html>`;
  }
}
