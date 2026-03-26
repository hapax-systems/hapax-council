// ─── Types ───────────────────────────────────────────────────────────────────

export interface ArgDef {
  type: "string" | "number" | "boolean";
  required?: boolean;
  enum?: string[];
  description?: string;
}

export interface CommandResult {
  ok: boolean;
  error?: string;
  state?: unknown;
}

export interface CommandDef {
  path: string;
  description: string;
  args?: Record<string, ArgDef>;
  execute: (args: Record<string, unknown>) => CommandResult | Promise<CommandResult>;
}

export interface CommandEvent {
  path: string;
  args: Record<string, unknown>;
  result: CommandResult;
  timestamp: number;
  source?: string;
}

export interface SequenceStep {
  command: string;
  args?: Record<string, unknown>;
  /** Optional settle time (ms) between steps */
  settle?: number;
}

export interface SequenceOptions {
  /** Stop at the first successful step instead of the first failure */
  stopOnSuccess?: boolean;
}

// ─── Internal subscriber record ──────────────────────────────────────────────

interface Subscriber {
  id: number;
  pattern: string | RegExp;
  callback: (event: CommandEvent) => void;
}

// ─── CommandRegistry ─────────────────────────────────────────────────────────

export interface CommandRegistryOptions {
  debug?: boolean;
}

export class CommandRegistry {
  private commands = new Map<string, CommandDef>();
  private queries = new Map<string, () => unknown>();
  private subscribers: Subscriber[] = [];
  private nextSubId = 0;
  debug: boolean;

  constructor(options: CommandRegistryOptions = {}) {
    this.debug = options.debug ?? false;
  }

  // ── Command registration ──────────────────────────────────────────────────

  register(def: CommandDef): void {
    this.commands.set(def.path, def);
  }

  unregister(path: string): void {
    this.commands.delete(path);
  }

  // ── Query registration ────────────────────────────────────────────────────

  registerQuery(path: string, fn: () => unknown): void {
    this.queries.set(path, fn);
  }

  unregisterQuery(path: string): void {
    this.queries.delete(path);
  }

  query(path: string): unknown {
    const fn = this.queries.get(path);
    return fn ? fn() : undefined;
  }

  getState(): Record<string, unknown> {
    const state: Record<string, unknown> = {};
    for (const [path, fn] of this.queries) {
      state[path] = fn();
    }
    return state;
  }

  // ── Execution ─────────────────────────────────────────────────────────────

  async execute(
    path: string,
    args: Record<string, unknown> = {},
    source?: string,
  ): Promise<CommandResult> {
    const def = this.commands.get(path);

    if (!def) {
      const result: CommandResult = {
        ok: false,
        error: `Command not found: ${path}`,
      };
      return result;
    }

    const result = await def.execute(args);

    const event: CommandEvent = {
      path,
      args,
      result,
      timestamp: Date.now(),
      source,
    };

    this._emit(event);

    return result;
  }

  // ── Listing ───────────────────────────────────────────────────────────────

  list(domain?: string): CommandDef[] {
    const defs = Array.from(this.commands.values());
    if (!domain) return defs;
    return defs.filter((d) => d.path === domain || d.path.startsWith(`${domain}.`));
  }

  // ── Subscriptions ─────────────────────────────────────────────────────────

  subscribe(
    pattern: string | RegExp,
    callback: (event: CommandEvent) => void,
  ): () => void {
    const id = this.nextSubId++;
    this.subscribers.push({ id, pattern, callback });
    return () => {
      this.subscribers = this.subscribers.filter((s) => s.id !== id);
    };
  }

  // ── Sequences ─────────────────────────────────────────────────────────────

  sequence(path: string, steps: SequenceStep[], options: SequenceOptions = {}): void {
    const { stopOnSuccess = false } = options;

    const execute = async (args: Record<string, unknown>): Promise<CommandResult> => {
      void args; // sequences ignore top-level args; each step carries its own
      let lastResult: CommandResult = { ok: false, error: "No steps in sequence" };

      for (const step of steps) {
        await Promise.resolve(); // microtask flush between steps
        const stepArgs = step.args ?? {};
        lastResult = await this.execute(step.command, stepArgs);

        if (stopOnSuccess) {
          if (lastResult.ok) return lastResult;
          // continue on failure — looking for first success
        } else {
          if (!lastResult.ok) return lastResult;
          // continue on success — stop on first failure
        }

        if (step.settle && step.settle > 0) {
          await new Promise((resolve) => setTimeout(resolve, step.settle));
        }
      }

      return lastResult;
    };

    this.register({
      path,
      description: `Sequence: ${path} (${steps.length} steps)`,
      execute,
    });
  }

  // ── Internal ──────────────────────────────────────────────────────────────

  private _emit(event: CommandEvent): void {
    if (this.debug) {
      console.log("[CommandRegistry]", event.path, event);
    }

    for (const sub of this.subscribers) {
      if (typeof sub.pattern === "string") {
        if (sub.pattern === event.path) sub.callback(event);
      } else {
        if (sub.pattern.test(event.path)) sub.callback(event);
      }
    }
  }
}
