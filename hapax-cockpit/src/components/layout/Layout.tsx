import { useState, useEffect } from "react";
import { Outlet } from "react-router-dom";
import { Header } from "../Header";
import { ManualDrawer } from "./ManualDrawer";
import { CommandPalette } from "../shared/CommandPalette";
import { ErrorBoundary } from "../shared/ErrorBoundary";
import { ToastProvider } from "../shared/ToastProvider";
import { useKeyboardShortcuts } from "../../hooks/useKeyboardShortcuts";
import { HealthToastWatcher } from "./HealthToastWatcher";
import { AgentRunProvider } from "../../contexts/AgentRunContext";

export function Layout() {
  const [manualOpen, setManualOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  useKeyboardShortcuts({
    onManual: () => setManualOpen((prev) => !prev),
  });

  // Ctrl+P for command palette
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "p") {
        e.preventDefault();
        setPaletteOpen((prev) => !prev);
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <ToastProvider>
      <AgentRunProvider>
      <div className="flex h-screen flex-col bg-zinc-950 text-zinc-100">
        <Header onManualToggle={() => setManualOpen((prev) => !prev)} />
        <ErrorBoundary>
          <div className="flex flex-1 overflow-hidden">
            <Outlet />
          </div>
        </ErrorBoundary>
        <ManualDrawer open={manualOpen} onClose={() => setManualOpen(false)} />
        <CommandPalette
          open={paletteOpen}
          onClose={() => setPaletteOpen(false)}
          onManualToggle={() => setManualOpen((prev) => !prev)}
        />
        <HealthToastWatcher />
      </div>
      </AgentRunProvider>
    </ToastProvider>
  );
}
