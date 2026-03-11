import * as vscode from "vscode";
import { readVaultFile, vaultRoot } from "../vault";

const NUDGES_PATH = "30-system/nudges.md";

/**
 * Open the active nudges note for interactive review.
 * Nudges use Obsidian Tasks-compatible format -- users can check off items directly.
 */
export async function openNudges(
  _context: vscode.ExtensionContext
): Promise<void> {
  const uri = vscode.Uri.joinPath(vaultRoot(), NUDGES_PATH);

  // Check if file exists
  try {
    await vscode.workspace.fs.stat(uri);
  } catch {
    vscode.window.showWarningMessage(
      "No nudges file found. System may not have generated nudges yet."
    );
    return;
  }

  // Open in the main editor
  const doc = await vscode.workspace.openTextDocument(uri);
  await vscode.window.showTextDocument(doc);

  // Count pending items
  try {
    const content = await readVaultFile(NUDGES_PATH);
    const checkboxes = content.match(/^- \[ \]/gm);
    const count = checkboxes ? checkboxes.length : 0;
    if (count > 0) {
      vscode.window.showInformationMessage(
        `${count} active nudge(s) -- check off completed items`
      );
    } else {
      vscode.window.showInformationMessage("No active nudges");
    }
  } catch {
    // Silently skip count on error
  }
}
