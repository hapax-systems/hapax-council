import { useEffect, useState } from "react";
import { useCommandRegistry } from "../../contexts/CommandRegistryContext";

interface Toast {
  id: number;
  message: string;
}

let nextId = 0;

export function CommandFeedback() {
  const registry = useCommandRegistry();
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => {
    return registry.subscribe(/./, (event) => {
      // Only show failures from non-keyboard sources
      if (event.result.ok || event.source === "keyboard") return;

      const id = nextId++;
      setToasts((prev) => [...prev, { id, message: `${event.path}: ${event.result.error}` }]);
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, 3000);
    });
  }, [registry]);

  if (toasts.length === 0) return null;

  return (
    <div
      className="fixed bottom-4 right-4 flex flex-col gap-2"
      style={{ zIndex: 100, pointerEvents: "none" }}
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className="rounded border border-red-800/50 bg-zinc-900/90 px-3 py-2 text-xs text-red-400 backdrop-blur-sm"
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            maxWidth: 400,
            pointerEvents: "auto",
          }}
        >
          {toast.message}
        </div>
      ))}
    </div>
  );
}
