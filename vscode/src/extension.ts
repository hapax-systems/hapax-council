import * as vscode from "vscode";
import { ChatViewProvider } from "./chat-view";
import { setupStatusBar } from "./status-bar";
import { isWorkVault } from "./vault";
import { enforceWorkVaultProvider } from "./settings";
import { prepare1on1 } from "./commands/prepare-1on1";
import { teamSnapshot } from "./commands/team-snapshot";
import { openKnowledgeSearch } from "./commands/search";
import { openNudges } from "./commands/nudges";
import { viewProfile } from "./commands/profile";
import { captureDecision } from "./commands/capture-decision";

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  const isWork = await isWorkVault();
  vscode.commands.executeCommand("setContext", "hapax.isWorkVault", isWork);

  // Enforce provider allowlist for work vaults
  await enforceWorkVaultProvider(isWork);

  // Chat sidebar
  const chatProvider = new ChatViewProvider(context.extensionUri, context, isWork);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(ChatViewProvider.viewType, chatProvider)
  );

  // Universal commands
  context.subscriptions.push(
    vscode.commands.registerCommand("hapax.openChat", () => {
      vscode.commands.executeCommand("hapax.chatView.focus");
    })
  );

  // Work-only commands (always registered to avoid "command not found", gated by isWork)
  const workOnlyWarning = "This command is only available in work vaults.";
  context.subscriptions.push(
    vscode.commands.registerCommand("hapax.prepare1on1", () => {
      if (!isWork) { vscode.window.showWarningMessage(workOnlyWarning); return; }
      prepare1on1(context, chatProvider);
    }),
    vscode.commands.registerCommand("hapax.teamSnapshot", () => {
      if (!isWork) { vscode.window.showWarningMessage(workOnlyWarning); return; }
      teamSnapshot(context, chatProvider);
    }),
    vscode.commands.registerCommand("hapax.searchKnowledge", () => {
      if (!isWork) { vscode.window.showWarningMessage(workOnlyWarning); return; }
      openKnowledgeSearch(context);
    }),
    vscode.commands.registerCommand("hapax.viewNudges", () => {
      if (!isWork) { vscode.window.showWarningMessage(workOnlyWarning); return; }
      openNudges(context);
    }),
    vscode.commands.registerCommand("hapax.viewProfile", () => {
      if (!isWork) { vscode.window.showWarningMessage(workOnlyWarning); return; }
      viewProfile(context);
    }),
    vscode.commands.registerCommand("hapax.captureDecision", () => {
      if (!isWork) { vscode.window.showWarningMessage(workOnlyWarning); return; }
      captureDecision(context);
    }),
  );

  // Status bar
  setupStatusBar(context, isWork);
}

export function deactivate(): void {
  // Cleanup handled by context.subscriptions
}
