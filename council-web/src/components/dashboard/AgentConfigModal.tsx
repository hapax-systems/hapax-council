import { useState } from "react";
import type { AgentInfo, AgentFlag } from "../../api/types";
import { DetailModal } from "../shared/DetailModal";

interface AgentConfigModalProps {
  agent: AgentInfo;
  initialFlags?: Record<string, string>;
  onRun: (agent: AgentInfo, flags: string[]) => void;
  onClose: () => void;
}

export function AgentConfigModal({ agent, initialFlags, onRun, onClose }: AgentConfigModalProps) {
  const [flagState, setFlagState] = useState<Record<string, string | boolean>>(() => {
    const initial: Record<string, string | boolean> = {};
    for (const f of agent.flags) {
      if (initialFlags && f.flag in initialFlags) {
        if (f.flag_type === "bool") {
          initial[f.flag] = true;
        } else {
          initial[f.flag] = initialFlags[f.flag] || f.default || "";
        }
      } else if (f.flag_type === "bool") {
        initial[f.flag] = false;
      } else if (f.flag_type === "value") {
        initial[f.flag] = f.default ?? "";
      } else {
        initial[f.flag] = "";
      }
    }
    return initial;
  });

  function buildFlags(): string[] {
    const flags: string[] = [];
    for (const f of agent.flags) {
      const val = flagState[f.flag];
      if (f.flag_type === "bool" && val === true) {
        flags.push(f.flag);
      } else if (f.flag_type === "value" && typeof val === "string" && val.trim()) {
        flags.push(f.flag, val.trim());
      } else if (f.flag_type === "positional" && typeof val === "string" && val.trim()) {
        flags.push(val.trim());
      }
    }
    return flags;
  }

  return (
    <DetailModal title={`Run ${agent.name}`} open onClose={onClose}>
      <div className="space-y-3 text-xs">
        <p className="text-zinc-400">{agent.description}</p>
        <code className="block text-zinc-500">{agent.command}</code>

        <div className="space-y-2">
          {agent.flags.map((f) => (
            <FlagInput
              key={f.flag}
              flag={f}
              value={flagState[f.flag]}
              onChange={(v) => setFlagState((prev) => ({ ...prev, [f.flag]: v }))}
            />
          ))}
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button
            onClick={onClose}
            className="rounded border border-zinc-700 px-3 py-1.5 text-zinc-400 hover:border-zinc-500"
          >
            Cancel
          </button>
          <button
            onClick={() => onRun(agent, buildFlags())}
            className="rounded bg-blue-600 px-3 py-1.5 font-medium text-white hover:bg-blue-500"
          >
            Run
          </button>
        </div>
      </div>
    </DetailModal>
  );
}

function FlagInput({
  flag,
  value,
  onChange,
}: {
  flag: AgentFlag;
  value: string | boolean;
  onChange: (v: string | boolean) => void;
}) {
  if (flag.flag_type === "bool") {
    return (
      <label className="flex items-center gap-2 text-zinc-300">
        <input
          type="checkbox"
          checked={value === true}
          onChange={(e) => onChange(e.target.checked)}
          className="rounded border-zinc-600"
        />
        <code className="text-zinc-400">{flag.flag}</code>
        <span className="text-zinc-500">— {flag.description}</span>
      </label>
    );
  }

  if (flag.choices) {
    return (
      <div>
        <label className="mb-1 block text-zinc-300">
          <code className="text-zinc-400">{flag.flag}</code>
          <span className="ml-1 text-zinc-500">— {flag.description}</span>
        </label>
        <select
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded border border-zinc-700 bg-zinc-800 px-2 py-1 text-zinc-200"
        >
          <option value="">default</option>
          {flag.choices.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </div>
    );
  }

  return (
    <div>
      <label className="mb-1 block text-zinc-300">
        <code className="text-zinc-400">{flag.flag_type === "positional" ? flag.flag : flag.flag}</code>
        <span className="ml-1 text-zinc-500">— {flag.description}</span>
      </label>
      <input
        type="text"
        value={typeof value === "string" ? value : ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder={flag.metavar ?? flag.default ?? ""}
        className="w-full rounded border border-zinc-700 bg-zinc-800 px-2 py-1 text-zinc-200 placeholder-zinc-600"
      />
    </div>
  );
}
