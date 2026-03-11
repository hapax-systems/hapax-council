import * as vscode from "vscode";
import * as fs from "fs/promises";
import * as path from "path";
import * as os from "os";
import { writeVaultFile, vaultRoot } from "../vault";

/**
 * Capture a quick decision for the profiler's behavioral analysis.
 * Uses sequential input boxes to gather context, decision, and reasoning,
 * then saves to the filesystem (desktop) or vault.
 */
export async function captureDecision(
  _context: vscode.ExtensionContext
): Promise<void> {
  // Gather inputs via sequential input boxes
  const context = await vscode.window.showInputBox({
    prompt: "What situation prompted this decision?",
    placeHolder: "e.g., nudge about stale goal",
    ignoreFocusOut: true,
  });
  if (context === undefined) return; // cancelled
  if (!context) {
    vscode.window.showWarningMessage("Context is required.");
    return;
  }

  const decision = await vscode.window.showInputBox({
    prompt: "What did you decide?",
    placeHolder: "e.g., dismissed -- already in progress",
    ignoreFocusOut: true,
  });
  if (decision === undefined) return; // cancelled
  if (!decision) {
    vscode.window.showWarningMessage("Decision is required.");
    return;
  }

  const reasoning = await vscode.window.showInputBox({
    prompt: "Why? (optional -- press Enter to skip)",
    placeHolder: "e.g., updated last week, just not reflected yet",
    ignoreFocusOut: true,
  });
  if (reasoning === undefined) return; // cancelled

  try {
    // Try filesystem first (preferred for desktop), fall back to vault
    try {
      await saveToFilesystem(context, decision, reasoning || undefined);
    } catch {
      await saveToVault(context, decision, reasoning || undefined);
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    vscode.window.showErrorMessage(`Failed to save: ${msg}`);
  }
}

async function saveToFilesystem(
  ctx: string,
  decision: string,
  reasoning: string | undefined
): Promise<void> {
  const decisionsPath = path.join(
    os.homedir(),
    ".cache",
    "cockpit",
    "decisions.jsonl"
  );

  const entry = {
    timestamp: new Date().toISOString(),
    source: "hapax-vscode",
    context: ctx,
    decision,
    reasoning,
  };

  await fs.mkdir(path.dirname(decisionsPath), { recursive: true });
  await fs.appendFile(decisionsPath, JSON.stringify(entry) + "\n", "utf-8");
  vscode.window.showInformationMessage("Decision captured");
}

async function saveToVault(
  ctx: string,
  decision: string,
  reasoning: string | undefined
): Promise<void> {
  const date = new Date().toISOString().slice(0, 10);
  const slug = ctx
    .slice(0, 40)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  const folder = "10-work/decisions";
  const filename = `${folder}/${date}-${slug}.md`;

  const lines: string[] = [
    "---",
    "type: decision",
    `date: ${date}`,
    "source: hapax-vscode",
    "---",
    "",
    "## Context",
    "",
    ctx,
    "",
    "## Decision",
    "",
    decision,
  ];

  if (reasoning) {
    lines.push("", "## Reasoning", "", reasoning);
  }

  const content = lines.join("\n") + "\n";

  // Check for filename collision
  let target = filename;
  let counter = 1;
  while (true) {
    try {
      const uri = vscode.Uri.joinPath(vaultRoot(), target);
      await vscode.workspace.fs.stat(uri);
      // File exists, try next
      target = `${folder}/${date}-${slug}-${counter}.md`;
      counter++;
    } catch {
      // File doesn't exist, use this path
      break;
    }
  }

  await writeVaultFile(target, content);
  vscode.window.showInformationMessage("Decision captured to vault");
}
