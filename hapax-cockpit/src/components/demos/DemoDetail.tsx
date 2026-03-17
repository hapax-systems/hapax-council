import { X, Download, Play } from "lucide-react";
import type { Demo } from "../../api/types";

interface DemoDetailProps {
  demo: Demo;
  onClose: () => void;
}

export function DemoDetail({ demo, onClose }: DemoDetailProps) {
  const fileUrl = (path: string) => `/api/demos/${demo.id}/files/${path}`;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-900 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-zinc-100">{demo.title}</h2>
          <button onClick={onClose} className="rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200">
            <X className="h-5 w-5" />
          </button>
        </div>

        {demo.files.includes("demo.html") && (
          <div className="mb-4 flex items-center gap-2">
            <a
              href={fileUrl("demo.html")}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded bg-orange-600 px-4 py-2 text-sm font-medium text-white hover:bg-orange-500"
            >
              <Play className="h-4 w-4" />
              Play Demo
            </a>
            <a
              href={fileUrl("demo.html")}
              download={`${demo.title.replace(/\s+/g, "-").toLowerCase()}.html`}
              className="inline-flex items-center gap-2 rounded bg-zinc-700 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-600"
            >
              <Download className="h-4 w-4" />
              Download HTML
            </a>
          </div>
        )}

        <div className="mb-4 grid grid-cols-2 gap-2 text-xs">
          <div><span className="text-zinc-500">Audience:</span> <span className="text-zinc-300">{demo.audience}</span></div>
          <div><span className="text-zinc-500">Format:</span> <span className="text-zinc-300">{demo.format}</span></div>
          <div><span className="text-zinc-500">Scope:</span> <span className="text-zinc-300">{demo.scope}</span></div>
          <div><span className="text-zinc-500">Duration:</span> <span className="text-zinc-300">{Math.round(demo.duration)}s</span></div>
          <div><span className="text-zinc-500">Scenes:</span> <span className="text-zinc-300">{demo.scenes}</span></div>
          <div><span className="text-zinc-500">Timestamp:</span> <span className="text-zinc-300">{demo.timestamp}</span></div>
        </div>

        {demo.has_video && demo.files.includes("demo.mp4") && (
          <div className="mb-4">
            <video
              controls
              className="w-full rounded border border-zinc-700"
              src={fileUrl("demo.mp4")}
            >
              Your browser does not support video playback.
            </video>
          </div>
        )}

        <div className="mb-2 text-xs font-medium text-zinc-400">Files</div>
        <div className="space-y-1">
          {demo.files.map((f) => (
            <a
              key={f}
              href={fileUrl(f)}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 rounded px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-800"
            >
              <Download className="h-3 w-3 text-zinc-500" />
              {f}
            </a>
          ))}
        </div>

        {demo.primary_file && (
          <div className="mt-4">
            <a
              href={fileUrl(demo.primary_file)}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded bg-zinc-700 px-3 py-1.5 text-xs font-medium text-zinc-200 hover:bg-zinc-600"
            >
              <Play className="h-3.5 w-3.5" />
              Open {demo.primary_file}
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
