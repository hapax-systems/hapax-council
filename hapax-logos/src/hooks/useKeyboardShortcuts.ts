import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

interface ShortcutHandlers {
  onManual?: () => void;
}

export function useKeyboardShortcuts({ onManual }: ShortcutHandlers) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // Ignore when typing in inputs
      const target = e.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable
      ) {
        return;
      }

      switch (e.key) {
        case "?":
          e.preventDefault();
          onManual?.();
          break;
        case "c":
          e.preventDefault();
          navigate("/chat");
          break;
        case "d":
          e.preventDefault();
          navigate("/");
          break;
        case "i":
          e.preventDefault();
          navigate("/insight");
          break;
        case "r":
          e.preventDefault();
          queryClient.invalidateQueries();
          break;
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [navigate, onManual, queryClient]);
}
