import { describe, it, expect, vi, beforeEach } from "vitest";
import { CommandRegistry } from "../commandRegistry";
import type { CommandDef } from "../commandRegistry";

// ─── Helpers ────────────────────────────────────────────────────────────────

function makeCmd(path: string, execute?: CommandDef["execute"]): CommandDef {
  return {
    path,
    description: `Command ${path}`,
    execute: execute ?? (() => ({ ok: true })),
  };
}

// ─── Task 1: Core CommandRegistry ───────────────────────────────────────────

describe("CommandRegistry — register + execute", () => {
  let registry: CommandRegistry;

  beforeEach(() => {
    registry = new CommandRegistry();
  });

  it("executes a registered command and returns ok result", async () => {
    registry.register(makeCmd("test.hello", () => ({ ok: true, state: "hello" })));
    const result = await registry.execute("test.hello");
    expect(result.ok).toBe(true);
    expect(result.state).toBe("hello");
  });

  it("returns error result for unknown command", async () => {
    const result = await registry.execute("unknown.command");
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/not found|unknown/i);
  });

  it("passes args to the command handler", async () => {
    let received: Record<string, unknown> = {};
    registry.register(makeCmd("test.echo", (args) => {
      received = args;
      return { ok: true };
    }));
    await registry.execute("test.echo", { value: 42 });
    expect(received.value).toBe(42);
  });

  it("unregister removes a command", async () => {
    registry.register(makeCmd("test.removable"));
    registry.unregister("test.removable");
    const result = await registry.execute("test.removable");
    expect(result.ok).toBe(false);
  });

  it("handles async execute handlers", async () => {
    registry.register(makeCmd("test.async", async () => {
      await Promise.resolve();
      return { ok: true, state: "async-done" };
    }));
    const result = await registry.execute("test.async");
    expect(result.ok).toBe(true);
    expect(result.state).toBe("async-done");
  });
});

describe("CommandRegistry — list", () => {
  let registry: CommandRegistry;

  beforeEach(() => {
    registry = new CommandRegistry();
    registry.register(makeCmd("ui.open"));
    registry.register(makeCmd("ui.close"));
    registry.register(makeCmd("nav.go"));
    registry.register(makeCmd("nav.back"));
  });

  it("list() returns all registered commands", () => {
    const paths = registry.list().map((c) => c.path);
    expect(paths).toContain("ui.open");
    expect(paths).toContain("nav.go");
    expect(paths.length).toBe(4);
  });

  it("list(domain) filters by prefix", () => {
    const paths = registry.list("ui").map((c) => c.path);
    expect(paths).toEqual(expect.arrayContaining(["ui.open", "ui.close"]));
    expect(paths).not.toContain("nav.go");
  });

  it("list() returns empty array when no commands registered", () => {
    const empty = new CommandRegistry();
    expect(empty.list()).toEqual([]);
  });
});

describe("CommandRegistry — query", () => {
  let registry: CommandRegistry;

  beforeEach(() => {
    registry = new CommandRegistry();
  });

  it("registerQuery + query returns current value", () => {
    let count = 0;
    registry.registerQuery("counter", () => count);
    count = 5;
    expect(registry.query("counter")).toBe(5);
  });

  it("query for unknown path returns undefined", () => {
    expect(registry.query("does.not.exist")).toBeUndefined();
  });

  it("unregisterQuery removes query", () => {
    registry.registerQuery("temp", () => "value");
    registry.unregisterQuery("temp");
    expect(registry.query("temp")).toBeUndefined();
  });

  it("getState aggregates all registered queries", () => {
    registry.registerQuery("a", () => 1);
    registry.registerQuery("b", () => "two");
    registry.registerQuery("c", () => true);
    const state = registry.getState();
    expect(state).toEqual({ a: 1, b: "two", c: true });
  });

  it("getState returns empty object with no queries", () => {
    expect(registry.getState()).toEqual({});
  });
});

describe("CommandRegistry — subscribe / events", () => {
  let registry: CommandRegistry;

  beforeEach(() => {
    registry = new CommandRegistry();
    registry.register(makeCmd("event.fire", () => ({ ok: true, state: "fired" })));
  });

  it("emits event to string-pattern subscriber after execute", async () => {
    const handler = vi.fn();
    registry.subscribe("event.fire", handler);
    await registry.execute("event.fire");
    expect(handler).toHaveBeenCalledOnce();
    const event = handler.mock.calls[0][0];
    expect(event.path).toBe("event.fire");
    expect(event.result.ok).toBe(true);
    expect(typeof event.timestamp).toBe("number");
  });

  it("does not emit to non-matching string subscriber", async () => {
    const handler = vi.fn();
    registry.subscribe("other.cmd", handler);
    await registry.execute("event.fire");
    expect(handler).not.toHaveBeenCalled();
  });

  it("emits event to regex subscriber matching path", async () => {
    const handler = vi.fn();
    registry.subscribe(/^event\./, handler);
    await registry.execute("event.fire");
    expect(handler).toHaveBeenCalledOnce();
  });

  it("unsubscribe stops future event delivery", async () => {
    const handler = vi.fn();
    const unsub = registry.subscribe("event.fire", handler);
    unsub();
    await registry.execute("event.fire");
    expect(handler).not.toHaveBeenCalled();
  });

  it("includes source in event when provided", async () => {
    const handler = vi.fn();
    registry.subscribe("event.fire", handler);
    await registry.execute("event.fire", {}, "keyboard");
    expect(handler.mock.calls[0][0].source).toBe("keyboard");
  });

  it("captures args and result in event", async () => {
    const handler = vi.fn();
    registry.subscribe("event.fire", handler);
    await registry.execute("event.fire", { x: 1 });
    const event = handler.mock.calls[0][0];
    expect(event.args).toEqual({ x: 1 });
    expect(event.result.state).toBe("fired");
  });
});

describe("CommandRegistry — debug flag", () => {
  it("logs to console when debug=true", async () => {
    const registry = new CommandRegistry({ debug: true });
    registry.register(makeCmd("debug.cmd"));
    const spy = vi.spyOn(console, "log").mockImplementation(() => {});
    await registry.execute("debug.cmd");
    expect(spy).toHaveBeenCalled();
    spy.mockRestore();
  });

  it("does not log when debug=false (default)", async () => {
    const registry = new CommandRegistry();
    registry.register(makeCmd("debug.cmd"));
    const spy = vi.spyOn(console, "log").mockImplementation(() => {});
    await registry.execute("debug.cmd");
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});

// ─── Task 2: Sequence support ────────────────────────────────────────────────

describe("CommandRegistry — sequence", () => {
  let registry: CommandRegistry;
  const order: string[] = [];

  beforeEach(() => {
    order.length = 0;
    registry = new CommandRegistry();
    registry.register(makeCmd("step.a", () => { order.push("a"); return { ok: true }; }));
    registry.register(makeCmd("step.b", () => { order.push("b"); return { ok: true }; }));
    registry.register(makeCmd("step.c", () => { order.push("c"); return { ok: true }; }));
    registry.register(makeCmd("step.fail", () => { order.push("fail"); return { ok: false, error: "intentional failure" }; }));
  });

  it("executes steps in order", async () => {
    registry.sequence("seq.abc", [
      { command: "step.a" },
      { command: "step.b" },
      { command: "step.c" },
    ]);
    await registry.execute("seq.abc");
    expect(order).toEqual(["a", "b", "c"]);
  });

  it("stops at first failure by default", async () => {
    registry.sequence("seq.stop-on-fail", [
      { command: "step.a" },
      { command: "step.fail" },
      { command: "step.b" },
    ]);
    const result = await registry.execute("seq.stop-on-fail");
    expect(order).toEqual(["a", "fail"]);
    expect(result.ok).toBe(false);
    // step.b was not run
    expect(order).not.toContain("b");
  });

  it("stopOnSuccess stops at first successful step", async () => {
    registry.sequence(
      "seq.esc",
      [
        { command: "step.fail" },
        { command: "step.a" },
        { command: "step.b" },
      ],
      { stopOnSuccess: true },
    );
    const result = await registry.execute("seq.esc");
    // fail runs, then a runs (ok) → stop
    expect(order).toEqual(["fail", "a"]);
    expect(result.ok).toBe(true);
    expect(order).not.toContain("b");
  });

  it("sequence appears in list()", () => {
    registry.sequence("seq.listed", [{ command: "step.a" }]);
    const paths = registry.list().map((c) => c.path);
    expect(paths).toContain("seq.listed");
  });

  it("sequence appears in list() with domain filter", () => {
    registry.sequence("seq.listed", [{ command: "step.a" }]);
    const paths = registry.list("seq").map((c) => c.path);
    expect(paths).toContain("seq.listed");
  });

  it("passes args from step definition to sub-command", async () => {
    let received: Record<string, unknown> = {};
    registry.register(makeCmd("step.capture", (args) => {
      received = args;
      return { ok: true };
    }));
    registry.sequence("seq.with-args", [
      { command: "step.capture", args: { key: "value" } },
    ]);
    await registry.execute("seq.with-args");
    expect(received.key).toBe("value");
  });

  it("stopOnSuccess with all failing returns last failure result", async () => {
    registry.sequence(
      "seq.all-fail",
      [
        { command: "step.fail" },
        { command: "step.fail" },
      ],
      { stopOnSuccess: true },
    );
    const result = await registry.execute("seq.all-fail");
    expect(result.ok).toBe(false);
  });
});
