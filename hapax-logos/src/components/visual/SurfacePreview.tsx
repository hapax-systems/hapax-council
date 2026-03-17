import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

const IS_TAURI = "__TAURI_INTERNALS__" in window;

export function SurfacePreview() {
  const [imgSrc, setImgSrc] = useState<string | null>(null);

  useEffect(() => {
    if (!IS_TAURI) return;

    let active = true;
    const poll = async () => {
      while (active) {
        try {
          const bytes = await invoke<number[]>("get_visual_surface_snapshot");
          const blob = new Blob([new Uint8Array(bytes)], { type: "image/jpeg" });
          const url = URL.createObjectURL(blob);
          setImgSrc((prev) => {
            if (prev) URL.revokeObjectURL(prev);
            return url;
          });
        } catch {
          // No snapshot available
        }
        await new Promise((r) => setTimeout(r, 500));
      }
    };
    poll();
    return () => {
      active = false;
    };
  }, []);

  if (!IS_TAURI) {
    return (
      <div className="flex items-center justify-center rounded border border-zinc-700 bg-zinc-900 p-8 text-xs text-zinc-500">
        Surface preview requires Tauri runtime
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <h3 className="text-xs font-medium text-zinc-400 uppercase tracking-wider">
        Surface Preview
      </h3>
      {imgSrc ? (
        <img
          src={imgSrc}
          alt="Visual surface"
          className="w-full rounded border border-zinc-700"
        />
      ) : (
        <div className="flex items-center justify-center rounded border border-zinc-700 bg-zinc-900 p-8 text-xs text-zinc-500">
          Waiting for visual surface...
        </div>
      )}
    </div>
  );
}
