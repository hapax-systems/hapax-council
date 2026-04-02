import { App, Modal, Notice, Platform, Plugin, TFile, WorkspaceLeaf, ButtonComponent, TextAreaComponent } from "obsidian";
import { DEFAULT_SETTINGS, LOCAL_API_URL, TAILSCALE_API_URL } from "./types";
import type { HapaxSettings, NoteContext } from "./types";
import { NoteKind } from "./types";
import { LogosClient } from "./logos-client";
import { resolveNoteContext } from "./context-resolver";
import { ContextPanel, HAPAX_VIEW_TYPE } from "./context-panel";
import { HapaxSettingTab } from "./settings";

// ─── Result summary modal ─────────────────────────────────────────────────────

class CompleteMeasureModal extends Modal {
  private measureId: string;
  private onConfirm: (resultSummary: string) => Promise<void>;
  private textarea!: TextAreaComponent;

  constructor(
    app: App,
    measureId: string,
    onConfirm: (resultSummary: string) => Promise<void>,
  ) {
    super(app);
    this.measureId = measureId;
    this.onConfirm = onConfirm;
  }

  onOpen(): void {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.createEl("h3", { text: `Complete measure ${this.measureId}` });
    contentEl.createEl("p", {
      text: "Provide a result summary (optional):",
      cls: "hapax-modal-label",
    });

    this.textarea = new TextAreaComponent(contentEl);
    this.textarea.inputEl.addClass("hapax-modal-textarea");
    this.textarea.inputEl.rows = 4;
    this.textarea.inputEl.style.width = "100%";
    this.textarea.setPlaceholder("What was the outcome?");

    const btnRow = contentEl.createDiv({ cls: "hapax-modal-buttons" });

    new ButtonComponent(btnRow)
      .setButtonText("Complete")
      .setCta()
      .onClick(async () => {
        const summary = this.textarea.getValue().trim();
        this.close();
        await this.onConfirm(summary);
      });

    new ButtonComponent(btnRow).setButtonText("Cancel").onClick(() => {
      this.close();
    });
  }

  onClose(): void {
    this.contentEl.empty();
  }
}

// ─── Plugin ───────────────────────────────────────────────────────────────────

export default class HapaxPlugin extends Plugin {
  settings!: HapaxSettings;
  client!: LogosClient;
  private panel: ContextPanel | null = null;
  private refreshTimer: number | null = null;

  async onload(): Promise<void> {
    await this.loadSettings();

    // On mobile, auto-switch to Tailscale URL unless the user has set a custom URL.
    const effectiveUrl =
      Platform.isMobile && this.settings.logosApiUrl === LOCAL_API_URL
        ? TAILSCALE_API_URL
        : this.settings.logosApiUrl;

    this.client = new LogosClient(effectiveUrl);

    // Register view
    this.registerView(HAPAX_VIEW_TYPE, (leaf: WorkspaceLeaf) => {
      this.panel = new ContextPanel(leaf, this.client, (action) =>
        this.handleAction(action),
      );
      return this.panel;
    });

    // Ribbon icon
    this.addRibbonIcon("activity", "Hapax", () => {
      this.activatePanel();
    });

    // Command
    this.addCommand({
      id: "toggle-context-panel",
      name: "Toggle context panel",
      callback: () => {
        this.activatePanel();
      },
    });

    // Active leaf change
    this.registerEvent(
      this.app.workspace.on("active-leaf-change", () => {
        this.onActiveLeafChange();
      }),
    );

    // Settings tab
    this.addSettingTab(new HapaxSettingTab(this.app, this));

    // Start refresh timer
    this.startRefreshTimer();

    // Update panel with current note on load
    this.app.workspace.onLayoutReady(() => {
      this.onActiveLeafChange();
    });
  }

  onunload(): void {
    this.stopRefreshTimer();
    this.app.workspace.detachLeavesOfType(HAPAX_VIEW_TYPE);
  }

  async loadSettings(): Promise<void> {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
  }

  async activatePanel(): Promise<void> {
    const existing = this.app.workspace.getLeavesOfType(HAPAX_VIEW_TYPE);
    if (existing.length > 0) {
      this.app.workspace.revealLeaf(existing[0]);
      return;
    }
    const leaf = this.app.workspace.getRightLeaf(false);
    if (leaf) {
      await leaf.setViewState({ type: HAPAX_VIEW_TYPE, active: true });
      this.app.workspace.revealLeaf(leaf);
    }
  }

  onActiveLeafChange(): void {
    const file = this.app.workspace.getActiveFile();
    if (!file || !(file instanceof TFile)) {
      return;
    }

    const frontmatter =
      this.app.metadataCache.getFileCache(file)?.frontmatter ?? null;
    const metadataTags =
      this.app.metadataCache
        .getFileCache(file)
        ?.tags?.map((t) => t.tag.replace(/^#/, "")) ?? [];

    const ctx = resolveNoteContext(file.path, frontmatter ?? null, metadataTags);

    if (ctx.kind === NoteKind.Unknown && !this.settings.showOnUnknownNotes) {
      return;
    }

    // Open panel if not open, then update
    const leaves = this.app.workspace.getLeavesOfType(HAPAX_VIEW_TYPE);
    if (leaves.length === 0) {
      this.activatePanel().then(() => {
        this.updatePanel(ctx);
      });
    } else {
      this.updatePanel(ctx);
    }
  }

  private updatePanel(ctx: NoteContext): void {
    const leaves = this.app.workspace.getLeavesOfType(HAPAX_VIEW_TYPE);
    if (leaves.length > 0) {
      const view = leaves[0].view;
      if (view instanceof ContextPanel) {
        view.update(ctx).catch((err: unknown) => {
          console.error("[hapax] panel update failed", err);
        });
      }
    }
  }

  startRefreshTimer(): void {
    this.stopRefreshTimer();
    const intervalMs = this.settings.refreshInterval * 1000;
    this.refreshTimer = window.setInterval(() => {
      this.client.invalidateAll();
      const leaves = this.app.workspace.getLeavesOfType(HAPAX_VIEW_TYPE);
      if (leaves.length > 0) {
        const view = leaves[0].view;
        if (view instanceof ContextPanel) {
          view.refresh().catch((err: unknown) => {
            console.error("[hapax] panel refresh failed", err);
          });
        }
      }
    }, intervalMs);
  }

  stopRefreshTimer(): void {
    if (this.refreshTimer !== null) {
      window.clearInterval(this.refreshTimer);
      this.refreshTimer = null;
    }
  }

  restartRefreshTimer(): void {
    this.startRefreshTimer();
  }

  async handleAction(action: string): Promise<void> {
    const colonIdx = action.indexOf(":");
    if (colonIdx === -1) {
      new Notice(`[hapax] Unknown action: ${action}`);
      return;
    }

    const type = action.slice(0, colonIdx);
    const id = action.slice(colonIdx + 1);

    try {
      switch (type) {
        case "measure-start":
          await this.client.transitionMeasure(id, "in-progress");
          new Notice(`Started measure ${id}`);
          break;

        case "measure-complete":
          await this.openCompleteModal(id);
          // Notice is shown inside modal callback
          break;

        case "measure-block":
          await this.client.transitionMeasure(id, "blocked");
          new Notice(`Blocked measure ${id}`);
          break;

        case "measure-skip":
          await this.client.transitionMeasure(id, "skipped");
          new Notice(`Skipped measure ${id}`);
          break;

        case "measure-resume":
          await this.client.transitionMeasure(id, "in-progress");
          new Notice(`Resumed measure ${id}`);
          break;

        case "gate-acknowledge":
          await this.client.acknowledgeGate(id);
          new Notice(`Acknowledged gate ${id}`);
          break;

        case "nudge-act":
          await this.client.actOnNudge(id);
          new Notice(`Acting on nudge ${id}`);
          break;

        case "nudge-dismiss":
          await this.client.dismissNudge(id);
          new Notice(`Dismissed nudge ${id}`);
          break;

        default:
          new Notice(`[hapax] Unknown action type: ${type}`);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      new Notice(`[hapax] Action failed: ${msg}`);
    }
  }

  private openCompleteModal(measureId: string): Promise<void> {
    return new Promise((resolve) => {
      const modal = new CompleteMeasureModal(
        this.app,
        measureId,
        async (resultSummary: string) => {
          await this.client.transitionMeasure(measureId, "completed", resultSummary || undefined);
          new Notice(`Completed measure ${measureId}`);
          resolve();
        },
      );
      modal.open();
      // Resolve immediately — the modal callback handles the actual work.
      // We resolve here so handleAction returns without blocking.
      // The refresh happens in ContextPanel.attachListeners after handleAction settles.
    });
  }
}
