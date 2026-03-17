/**
 * React hook that listens for Hapax introspection events from the Rust backend.
 *
 * Hapax agents can programmatically control the UI by emitting events through
 * Tauri commands. This hook wires those events into React state and side effects.
 *
 * Events handled:
 *   hapax:navigate        — route to a page
 *   hapax:toggle-panel    — open/close sidebar panels
 *   hapax:toast           — show a toast notification
 *   hapax:modal           — show/dismiss a modal overlay
 *   hapax:highlight       — pulse a UI element
 *   hapax:status          — set header status text
 *   hapax:stance-override — visual surface stance change
 *   hapax:visual-ping     — visual surface wave event
 */
import { useEffect, useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";

const IS_TAURI = "__TAURI_INTERNALS__" in window;

interface ModalState {
  visible: boolean;
  title: string;
  content: string;
  dismissable: boolean;
}

interface StatusState {
  text: string;
  level: string;
}

export function useHapaxIntrospection() {
  const navigate = useNavigate();
  const [modal, setModal] = useState<ModalState>({
    visible: false,
    title: "",
    content: "",
    dismissable: true,
  });
  const [status, setStatus] = useState<StatusState | null>(null);

  const dismissModal = useCallback(() => {
    setModal((prev) => ({ ...prev, visible: false }));
  }, []);

  useEffect(() => {
    if (!IS_TAURI) return;

    // Dynamic import to avoid breaking non-Tauri builds
    let cleanups: Array<() => void> = [];

    (async () => {
      const { listen } = await import("@tauri-apps/api/event");

      // Navigation
      const u1 = await listen<string>("hapax:navigate", (e) => {
        navigate(e.payload);
      });
      cleanups.push(u1);

      // Panel toggle
      const u2 = await listen<{ panel: string; open: boolean }>(
        "hapax:toggle-panel",
        (e) => {
          // Dispatch a custom DOM event that sidebar components can listen for
          window.dispatchEvent(
            new CustomEvent("hapax-panel-toggle", { detail: e.payload }),
          );
        },
      );
      cleanups.push(u2);

      // Toast
      const u3 = await listen<{
        message: string;
        level: string;
        duration_ms: number;
      }>("hapax:toast", (e) => {
        window.dispatchEvent(
          new CustomEvent("hapax-toast", { detail: e.payload }),
        );
      });
      cleanups.push(u3);

      // Modal
      const u4 = await listen<{
        title: string;
        content: string;
        dismissable: boolean;
        action: string;
      }>("hapax:modal", (e) => {
        if (e.payload.action === "dismiss") {
          setModal((prev) => ({ ...prev, visible: false }));
        } else {
          setModal({
            visible: true,
            title: e.payload.title,
            content: e.payload.content,
            dismissable: e.payload.dismissable,
          });
        }
      });
      cleanups.push(u4);

      // Highlight
      const u5 = await listen<{ selector: string; duration_ms: number }>(
        "hapax:highlight",
        (e) => {
          const el = document.querySelector(e.payload.selector);
          if (el instanceof HTMLElement) {
            el.classList.add("hapax-highlight");
            setTimeout(() => {
              el.classList.remove("hapax-highlight");
            }, e.payload.duration_ms);
          }
        },
      );
      cleanups.push(u5);

      // Status
      const u6 = await listen<{ text: string; level: string }>(
        "hapax:status",
        (e) => {
          setStatus(e.payload);
          // Auto-clear after 10s
          setTimeout(() => setStatus(null), 10000);
        },
      );
      cleanups.push(u6);
    })();

    return () => {
      cleanups.forEach((fn) => fn());
    };
  }, [navigate]);

  return { modal, dismissModal, status };
}
