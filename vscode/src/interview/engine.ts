/**
 * Interview engine — state machine for guided knowledge acquisition (VS Code port).
 *
 * Manages the interview lifecycle: detecting gaps, presenting questions,
 * extracting answers, writing to vault, and tracking progress.
 *
 * State persists via vscode.ExtensionContext.globalState (never syncs).
 */
import * as vscode from "vscode";
import type { HapaxSettings } from "../types";
import {
  readVaultFile,
  listVaultFiles,
  parseFrontmatter,
  vaultRoot,
} from "../vault";
import {
  REQUIREMENTS,
  getInterviewableRequirements,
  type Requirement,
} from "./knowledge-model";
import {
  getNextQuestion,
  buildQuestion,
  type QuestionContext,
} from "./questions";
import { extractFromAnswer, type ExtractionResult } from "./extractor";
import {
  createPersonNote,
  createReferenceDoc,
  updateFrontmatter,
  type PersonData,
  type ReferenceDocData,
} from "./vault-writer";

// ── State ───────────────────────────────────────────────────────

export interface InterviewState {
  active: boolean;
  currentRequirement: string | null;
  /** The person being asked about (for person-scoped questions). */
  currentPerson: string | null;
  completed: string[];
  skipped: string[];
  lastUpdated: string;
}

const EMPTY_STATE: InterviewState = {
  active: false,
  currentRequirement: null,
  currentPerson: null,
  completed: [],
  skipped: [],
  lastUpdated: new Date().toISOString(),
};

// ── Progress ────────────────────────────────────────────────────

export interface InterviewProgress {
  foundational: { done: number; total: number };
  structural: { done: number; total: number };
  enrichment: { done: number; total: number };
  foundationalComplete: boolean;
}

// ── Engine ──────────────────────────────────────────────────────

export class InterviewEngine {
  private context: vscode.ExtensionContext;
  private settings: HapaxSettings;
  private state: InterviewState;
  private scanCache: { result: Set<string>; time: number } | null = null;
  private static readonly SCAN_CACHE_TTL = 30_000; // 30 seconds
  private static readonly STATE_KEY = "hapax.interviewState";

  constructor(context: vscode.ExtensionContext, settings: HapaxSettings) {
    this.context = context;
    this.settings = settings;
    this.state = { ...EMPTY_STATE };
  }

  // ── State persistence ───────────────────────────────────────

  async load(): Promise<void> {
    const stored = this.context.globalState.get<InterviewState>(
      InterviewEngine.STATE_KEY,
    );
    if (stored) {
      this.state = { ...EMPTY_STATE, ...stored };
    }
  }

  async save(): Promise<void> {
    await this.context.globalState.update(InterviewEngine.STATE_KEY, {
      ...this.state,
      lastUpdated: new Date().toISOString(),
    });
  }

  // ── Vault scanning (local sufficiency check) ────────────────

  async scanVaultSatisfaction(): Promise<Set<string>> {
    const now = Date.now();
    if (
      this.scanCache &&
      now - this.scanCache.time < InterviewEngine.SCAN_CACHE_TTL
    ) {
      // Return cached result merged with current completed state
      const merged = new Set(this.scanCache.result);
      for (const id of this.state.completed) merged.add(id);
      return merged;
    }

    const satisfied = new Set<string>(this.state.completed);

    for (const req of REQUIREMENTS) {
      if (satisfied.has(req.id)) continue;
      if (await this.checkRequirement(req)) {
        satisfied.add(req.id);
      }
    }

    this.scanCache = { result: new Set(satisfied), time: now };
    return satisfied;
  }

  /** Invalidate the scan cache (e.g. after writing to vault). */
  invalidateScanCache(): void {
    this.scanCache = null;
  }

  private async checkRequirement(req: Requirement): Promise<boolean> {
    const check = req.check;

    if (check.type === "file_exists" && check.path) {
      try {
        const content = await readVaultFile(check.path);
        // Strip frontmatter, check body length
        const body = content.replace(/^---[\s\S]*?---\n?/, "").trim();
        return body.length > 50;
      } catch {
        return false;
      }
    }

    if (check.type === "min_count" && check.path) {
      const files = await listVaultFiles(check.path, "*.md");
      if (files.length === 0) return false;

      let count = 0;
      for (const fileUri of files) {
        try {
          const relativePath = vscode.workspace.asRelativePath(fileUri);
          const raw = await readVaultFile(relativePath);
          const { data: fm } = parseFrontmatter(raw);
          const filter = check.filter || {};
          const matches = Object.entries(filter).every(
            ([k, v]) =>
              String(fm[k] ?? "").toLowerCase() === String(v).toLowerCase(),
          );
          if (matches) count++;
        } catch {
          continue;
        }
      }
      return count >= (check.min || 1);
    }

    if (check.type === "field_populated" && check.path && check.field) {
      const files = await listVaultFiles(check.path, "*.md");
      const matching: Array<Record<string, unknown>> = [];
      for (const fileUri of files) {
        try {
          const relativePath = vscode.workspace.asRelativePath(fileUri);
          const raw = await readVaultFile(relativePath);
          const { data: fm } = parseFrontmatter(raw);
          const filter = check.filter || {};
          const matches = Object.entries(filter).every(
            ([k, v]) =>
              String(fm[k] ?? "").toLowerCase() === String(v).toLowerCase(),
          );
          if (matches) matching.push(fm);
        } catch {
          continue;
        }
      }
      if (matching.length === 0) return true; // vacuously true
      return matching.every((fm) => {
        const val = fm[check.field!];
        return val != null && String(val).trim() !== "";
      });
    }

    if (check.type === "field_coverage" && check.path && check.field) {
      const files = await listVaultFiles(check.path, "*.md");
      const matching: Array<Record<string, unknown>> = [];
      for (const fileUri of files) {
        try {
          const relativePath = vscode.workspace.asRelativePath(fileUri);
          const raw = await readVaultFile(relativePath);
          const { data: fm } = parseFrontmatter(raw);
          const filter = check.filter || {};
          const matches = Object.entries(filter).every(
            ([k, v]) =>
              String(fm[k] ?? "").toLowerCase() === String(v).toLowerCase(),
          );
          if (matches) matching.push(fm);
        } catch {
          continue;
        }
      }
      if (matching.length === 0) return false; // no data = unsatisfied
      const populated = matching.filter((fm) => {
        const val = fm[check.field!];
        return val != null && String(val).trim() !== "";
      }).length;
      return (populated / matching.length) * 100 >= (check.threshold || 50);
    }

    return false;
  }

  /**
   * For a person-scoped requirement, find the first person missing the required field.
   * Returns the person's display name (from frontmatter or filename), or null if all satisfied.
   */
  private async findPersonMissingField(
    req: Requirement,
  ): Promise<string | null> {
    const check = req.check;
    if (!check.path || !check.field) return null;

    const files = await listVaultFiles(check.path, "*.md");

    for (const fileUri of files) {
      try {
        const relativePath = vscode.workspace.asRelativePath(fileUri);
        const raw = await readVaultFile(relativePath);
        const { data: fm } = parseFrontmatter(raw);

        // Apply filter (e.g. type: person, status: active)
        const filter = check.filter || {};
        const matches = Object.entries(filter).every(
          ([k, v]) =>
            String(fm[k] ?? "").toLowerCase() === String(v).toLowerCase(),
        );
        if (!matches) continue;

        // Check if field is missing/empty
        const val = fm[check.field!];
        if (val == null || String(val).trim() === "") {
          // Get display name: prefer frontmatter alias, fall back to filename
          const aliases = fm.aliases as string[] | undefined;
          const basename = fileUri.path
            .split("/")
            .pop()
            ?.replace(/\.md$/, "") || "";
          const name =
            aliases?.[0] ||
            basename
              .replace(/-/g, " ")
              .replace(/\b\w/g, (c: string) => c.toUpperCase());
          return name;
        }
      } catch {
        continue;
      }
    }

    return null;
  }

  // ── Interview control ───────────────────────────────────────

  async start(): Promise<QuestionContext | null> {
    this.state.active = true;
    await this.save();
    return this.nextQuestion();
  }

  async stop(): Promise<void> {
    this.state.active = false;
    this.state.currentRequirement = null;
    this.state.currentPerson = null;
    await this.save();
  }

  async skip(): Promise<QuestionContext | null> {
    if (this.state.currentRequirement) {
      this.state.skipped.push(this.state.currentRequirement);
      this.state.currentRequirement = null;
      this.state.currentPerson = null;
      await this.save();
    }
    return this.nextQuestion();
  }

  async nextQuestion(): Promise<QuestionContext | null> {
    const satisfied = await this.scanVaultSatisfaction();
    const skippedSet = new Set(this.state.skipped);

    const q = getNextQuestion(satisfied, skippedSet);
    if (!q) {
      this.state.active = false;
      this.state.currentRequirement = null;
      this.state.currentPerson = null;
      await this.save();
      return null;
    }

    this.state.currentRequirement = q.requirement.id;
    this.state.currentPerson = null;

    // For person-scoped questions, find the specific person missing data
    if (q.requirement.acquisition.personScoped) {
      const person = await this.findPersonMissingField(q.requirement);
      if (person) {
        this.state.currentPerson = person;
        // Re-build question with the person's name substituted
        const resolved = buildQuestion(q.requirement, { name: person });
        await this.save();
        return resolved;
      }
    }

    await this.save();
    return q;
  }

  // ── Answer processing ───────────────────────────────────────

  async processAnswer(answer: string): Promise<{
    success: boolean;
    message: string;
    nextQuestion: QuestionContext | null;
  }> {
    if (!this.state.currentRequirement) {
      return {
        success: false,
        message: "No active question.",
        nextQuestion: null,
      };
    }

    const req = REQUIREMENTS.find(
      (r) => r.id === this.state.currentRequirement,
    );
    if (!req) {
      return {
        success: false,
        message: "Requirement not found.",
        nextQuestion: null,
      };
    }

    // Build question with person context if available
    const questionContext = this.state.currentPerson
      ? { name: this.state.currentPerson }
      : undefined;
    const qCtx = buildQuestion(req, questionContext);

    // Extract structured data from answer
    const extraction = await extractFromAnswer(
      answer,
      qCtx.extractionPrompt,
      this.settings,
    );
    if ("error" in extraction) {
      return {
        success: false,
        message: extraction.error,
        nextQuestion: null,
      };
    }

    // Write to vault based on output type
    const writeResult = await this.writeToVault(req, extraction);
    if (!writeResult.success) {
      return {
        success: false,
        message: writeResult.message,
        nextQuestion: null,
      };
    }

    // Invalidate scan cache since vault content changed
    this.invalidateScanCache();

    // Mark completed — only for non-person-scoped requirements.
    // Person-scoped requirements may need to be asked for each person;
    // scanVaultSatisfaction determines when they're fully satisfied.
    if (!req.acquisition.personScoped) {
      this.state.completed.push(req.id);
    }
    this.state.currentRequirement = null;
    this.state.currentPerson = null;
    await this.save();

    // Get next question
    const next = await this.nextQuestion();

    return {
      success: true,
      message: writeResult.message,
      nextQuestion: next,
    };
  }

  private async writeToVault(
    req: Requirement,
    extraction: ExtractionResult,
  ): Promise<{ success: boolean; message: string }> {
    const data = extraction.data;
    const outputType = req.acquisition.outputType;

    try {
      if (outputType === "person_note") {
        const people: PersonData[] = this.extractPeopleArray(data);

        if (people.length === 0) {
          console.warn(
            "Hapax: no people found in extraction data:",
            JSON.stringify(data),
          );
          return {
            success: false,
            message:
              "No person notes created — the extraction didn't find any people with names. Try listing names clearly.",
          };
        }

        const created: string[] = [];
        for (const person of people) {
          const file = await createPersonNote(person);
          if (file) created.push(person.name);
        }
        return {
          success: created.length > 0,
          message:
            created.length > 0
              ? `Created person notes: ${created.join(", ")}`
              : "No person notes created — vault write failed.",
        };
      }

      if (outputType === "reference_doc") {
        // Build reference doc content from extracted data
        const title = req.description.trim().split(".")[0];
        const content =
          typeof data === "object"
            ? Object.entries(data)
                .filter(([k]) => k !== "incomplete")
                .map(([k, v]) => {
                  if (Array.isArray(v)) {
                    return `## ${k}\n\n${v
                      .map((item) =>
                        typeof item === "object"
                          ? Object.entries(item as Record<string, unknown>)
                              .map(([ik, iv]) => `- **${ik}**: ${iv}`)
                              .join("\n")
                          : `- ${item}`,
                      )
                      .join("\n\n")}`;
                  }
                  return `## ${k}\n\n${v}`;
                })
                .join("\n\n")
            : String(data);

        const file = await createReferenceDoc({
          id: req.id,
          title,
          content,
        });
        return {
          success: file !== null,
          message: file
            ? `Created reference doc: ${title}`
            : "Failed to create reference doc.",
        };
      }

      if (outputType === "frontmatter_update") {
        const person =
          (data as Record<string, unknown>).person as string ||
          this.state.currentPerson;
        if (!person) {
          return {
            success: false,
            message: "No person name in extracted data.",
          };
        }
        const fields: Record<string, string | number | boolean> = {};
        for (const [k, v] of Object.entries(data)) {
          if (k === "person" || k === "incomplete") continue;
          fields[k] = v as string | number | boolean;
        }
        const ok = await updateFrontmatter(person, fields);
        return {
          success: ok,
          message: ok
            ? `Updated ${person}: ${Object.keys(fields).join(", ")}`
            : `Failed to update ${person}.`,
        };
      }

      return { success: false, message: `Unknown output type: ${outputType}` };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      return { success: false, message: `Vault write error: ${msg}` };
    }
  }

  /**
   * Extract an array of PersonData from LLM output, regardless of key name.
   * Handles: { people: [...] }, { direct_reports: [...] }, [...], or { name: "..." }.
   */
  private extractPeopleArray(data: Record<string, unknown>): PersonData[] {
    // Direct array
    if (Array.isArray(data)) {
      return (data as PersonData[]).filter((p) => p.name);
    }

    // Find any array property containing objects with "name" fields
    for (const value of Object.values(data)) {
      if (
        Array.isArray(value) &&
        value.length > 0 &&
        typeof value[0] === "object" &&
        value[0]?.name
      ) {
        return (value as PersonData[]).filter((p) => p.name);
      }
    }

    // Single person object
    if (typeof data.name === "string" && data.name.trim()) {
      return [data as unknown as PersonData];
    }

    return [];
  }

  // ── Progress ────────────────────────────────────────────────

  async getProgress(): Promise<InterviewProgress> {
    const satisfied = await this.scanVaultSatisfaction();
    const interviewable = getInterviewableRequirements();

    const count = (cat: string) => {
      const reqs = interviewable.filter((r) => r.category === cat);
      const done = reqs.filter((r) => satisfied.has(r.id)).length;
      return { done, total: reqs.length };
    };

    const foundational = count("foundational");

    return {
      foundational,
      structural: count("structural"),
      enrichment: count("enrichment"),
      foundationalComplete: foundational.done === foundational.total,
    };
  }

  // ── Status ──────────────────────────────────────────────────

  isActive(): boolean {
    return this.state.active;
  }

  async hasFoundationalGaps(): Promise<boolean> {
    const satisfied = await this.scanVaultSatisfaction();
    const foundational = REQUIREMENTS.filter(
      (r) => r.category === "foundational",
    );
    return foundational.some((r) => !satisfied.has(r.id));
  }

  getState(): InterviewState {
    return { ...this.state };
  }
}
