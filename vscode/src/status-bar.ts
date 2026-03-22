import * as vscode from "vscode";

let statusBarItem: vscode.StatusBarItem | undefined;

export function setupStatusBar(
  context: vscode.ExtensionContext,
  isWork: boolean
): void {
  if (!isWork) return;

  statusBarItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100
  );
  statusBarItem.text = "$(pulse) Hapax";
  statusBarItem.tooltip = "Hapax system status";
  statusBarItem.command = "hapax.openChat";
  statusBarItem.show();
  context.subscriptions.push(statusBarItem);

  // Periodic health ping (if logos API reachable)
  checkHealth();
  const interval = setInterval(checkHealth, 5 * 60 * 1000);
  context.subscriptions.push({ dispose: () => clearInterval(interval) });
}

async function checkHealth(): Promise<void> {
  if (!statusBarItem) return;
  try {
    const resp = await fetch("http://localhost:8051/api/health", {
      signal: AbortSignal.timeout(3000),
    });
    if (resp.ok) {
      const data = (await resp.json()) as {
        summary?: { healthy?: number; total?: number };
      };
      const h = data.summary?.healthy ?? 0;
      const t = data.summary?.total ?? 0;
      statusBarItem.text = `$(pulse) ${h}/${t}`;
      statusBarItem.tooltip = `Hapax: ${h} of ${t} checks healthy`;
    } else {
      statusBarItem.text = "$(pulse) Hapax";
      statusBarItem.tooltip = "Hapax: logos unreachable";
    }
  } catch {
    // Degrade silently per corporate_boundary axiom
    statusBarItem.text = "$(pulse) Hapax";
    statusBarItem.tooltip = "Hapax: logos unreachable";
  }
}
