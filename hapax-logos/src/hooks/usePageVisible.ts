import { useSyncExternalStore } from "react";

function subscribe(callback: () => void): () => void {
  document.addEventListener("visibilitychange", callback);
  return () => document.removeEventListener("visibilitychange", callback);
}

function getSnapshot(): boolean {
  return !document.hidden;
}

function getServerSnapshot(): boolean {
  return true;
}

/** Returns `true` when the page tab is visible, `false` when hidden. */
export function usePageVisible(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
