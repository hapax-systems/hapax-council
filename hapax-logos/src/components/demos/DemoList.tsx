import { Film, FileText, Trash2 } from "lucide-react";
import { useState } from "react";
import { useDemos, useDeleteDemo } from "../../api/hooks";
import { DemoDetail } from "./DemoDetail";
import type { Demo } from "../../api/types";

const FORMAT_ICON: Record<string, typeof Film> = {
  video: Film,
  slides: FileText,
  "markdown-only": FileText,
};

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function DemoList() {
  const { data: demos, isLoading } = useDemos();
  const deleteDemo = useDeleteDemo();
  const [selected, setSelected] = useState<Demo | null>(null);

  if (isLoading) {
    return <div className="text-xs text-zinc-500">Loading demos...</div>;
  }

  if (!demos?.length) {
    return (
      <div className="rounded border border-zinc-800 p-6 text-center">
        <p className="text-xs text-zinc-400 mb-1">No demos have been generated yet.</p>
        <p className="text-[11px] text-zinc-600">Create one via the demo agent or command line.</p>
      </div>
    );
  }

  return (
    <>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {demos.map((demo) => {
          const Icon = FORMAT_ICON[demo.format] ?? FileText;
          return (
            <div
              key={demo.id}
              className="group cursor-pointer rounded border border-zinc-700 p-3 text-xs transition-colors hover:border-zinc-500 hover:bg-zinc-800/50"
              onClick={() => setSelected(demo)}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Icon className="h-4 w-4 text-zinc-400" />
                  <span className="font-medium text-zinc-200">{demo.title}</span>
                </div>
                <button
                  className="rounded p-1 text-zinc-600 opacity-0 transition-opacity hover:bg-zinc-700 hover:text-red-400 group-hover:opacity-100"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (confirm(`Delete "${demo.title}"?`)) {
                      deleteDemo.mutate(demo.id);
                    }
                  }}
                  title="Delete demo"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-zinc-400">{demo.audience}</span>
                <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-zinc-400">{demo.format}</span>
                <span className="text-zinc-500">{demo.scenes} scenes</span>
                <span className="text-zinc-500">{formatDuration(demo.duration)}</span>
              </div>
              <div className="mt-1.5 text-zinc-600">{demo.timestamp}</div>
            </div>
          );
        })}
      </div>
      {selected && <DemoDetail demo={selected} onClose={() => setSelected(null)} />}
    </>
  );
}
