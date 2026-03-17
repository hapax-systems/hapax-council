import { createContext, useContext, useCallback, useState, type ReactNode } from "react";
import { X } from "lucide-react";

interface Toast {
  id: number;
  message: string;
  variant: "info" | "warn" | "error" | "success";
}

interface ToastContextValue {
  addToast: (message: string, variant?: Toast["variant"]) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

// eslint-disable-next-line react-refresh/only-export-components
export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}

let nextId = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((message: string, variant: Toast["variant"] = "info") => {
    const id = nextId++;
    setToasts((prev) => [...prev, { id, message, variant }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 5000);
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const variantStyles: Record<Toast["variant"], string> = {
    info: "border-zinc-600 bg-zinc-800 text-zinc-200",
    warn: "border-yellow-500/50 bg-yellow-500/10 text-yellow-300",
    error: "border-red-500/50 bg-red-500/10 text-red-300",
    success: "border-green-500/50 bg-green-500/10 text-green-300",
  };

  return (
    <ToastContext.Provider value={{ addToast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`flex items-center gap-2 rounded border px-3 py-2 text-xs shadow-lg animate-in slide-in-from-right duration-200 ${variantStyles[t.variant]}`}
          >
            <span className="max-w-[300px]">{t.message}</span>
            <button onClick={() => dismiss(t.id)} className="shrink-0 text-zinc-500 hover:text-zinc-300">
              <X className="h-3 w-3" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
