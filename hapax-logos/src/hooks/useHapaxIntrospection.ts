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
 *   hapax:detection-highlight — pulse a detection overlay halo
 *   hapax:detection-annotate  — annotate a detection entity
 *   hapax:detection-layer     — toggle detection layer visibility/tier
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

    // Track whether we've been cleaned up (handles race between async setup and unmount)
    let disposed = false;
    const cleanups: Array<() => void> = [];

    (async () => {
      const { listen } = await import("@tauri-apps/api/event");
      if (disposed) return; // Component unmounted before import resolved

      const reg = async <T,>(event: string, handler: (e: { payload: T }) => void) => {
        const unlisten = await listen<T>(event, handler);
        if (disposed) {
          unlisten(); // Immediately clean up if we raced unmount
        } else {
          cleanups.push(unlisten);
        }
      };

      await reg<string>("hapax:navigate", (e) => navigate(e.payload));

      await reg<{ panel: string; open: boolean }>("hapax:toggle-panel", (e) => {
        window.dispatchEvent(new CustomEvent("hapax-panel-toggle", { detail: e.payload }));
      });

      await reg<{ message: string; level: string; duration_ms: number }>("hapax:toast", (e) => {
        window.dispatchEvent(new CustomEvent("hapax-toast", { detail: e.payload }));
      });

      await reg<{ title: string; content: string; dismissable: boolean; action: string }>(
        "hapax:modal",
        (e) => {
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
        },
      );

      await reg<{ selector: string; duration_ms: number }>("hapax:highlight", (e) => {
        const el = document.querySelector(e.payload.selector);
        if (el instanceof HTMLElement) {
          el.classList.add("hapax-highlight");
          setTimeout(() => el.classList.remove("hapax-highlight"), e.payload.duration_ms);
        }
      });

      await reg<{ text: string; level: string }>("hapax:status", (e) => {
        setStatus(e.payload);
        setTimeout(() => setStatus(null), 10000);
      });

      await reg<{ entity_id: string; annotation?: string; duration_s?: number }>(
        "hapax:detection-highlight",
        (e) => window.dispatchEvent(new CustomEvent("hapax:detection-highlight", { detail: e.payload })),
      );

      await reg<{ entity_id: string; annotation?: string; duration_s?: number }>(
        "hapax:detection-annotate",
        (e) => window.dispatchEvent(new CustomEvent("hapax:detection-annotate", { detail: e.payload })),
      );

      await reg<{ visible: boolean; tier?: number }>(
        "hapax:detection-layer",
        (e) => window.dispatchEvent(new CustomEvent("hapax:detection-layer", { detail: e.payload })),
      );
    })();

    return () => {
      disposed = true;
      cleanups.forEach((fn) => fn());
    };
  }, [navigate]);

  return { modal, dismissModal, status };
}
