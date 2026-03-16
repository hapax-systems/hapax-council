import { useEffect } from "react";

interface StudioShortcutHandlers {
  onViewMode: (mode: "grid" | "composite" | "smooth") => void;
  onPreset: (idx: number) => void;
  onFullscreen: () => void;
}

export function useStudioShortcuts({
  onViewMode,
  onPreset,
  onFullscreen,
}: StudioShortcutHandlers) {
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.tagName === "SELECT" ||
        target.isContentEditable
      ) {
        return;
      }

      switch (e.key) {
        case "g":
          e.preventDefault();
          onViewMode("grid");
          break;
        case "x":
          e.preventDefault();
          onViewMode("composite");
          break;
        case "s":
          e.preventDefault();
          onViewMode("smooth");
          break;
        case "f":
          e.preventDefault();
          onFullscreen();
          break;
        case "1":
        case "2":
        case "3":
        case "4":
        case "5":
        case "6":
        case "7":
        case "8":
        case "9":
          e.preventDefault();
          onPreset(Number(e.key) - 1);
          break;
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onViewMode, onPreset, onFullscreen]);
}
