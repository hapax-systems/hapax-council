import { MarkdownContent } from "../shared/MarkdownContent";

interface HapaxModalProps {
  visible: boolean;
  title: string;
  content: string;
  dismissable: boolean;
  onDismiss: () => void;
}

export function HapaxModal({
  visible,
  title,
  content,
  dismissable,
  onDismiss,
}: HapaxModalProps) {
  if (!visible) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={dismissable ? onDismiss : undefined}
    >
      <div
        className="max-h-[80vh] w-full max-w-xl overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-900 p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-medium text-zinc-200">{title}</h2>
          {dismissable && (
            <button
              onClick={onDismiss}
              className="text-xs text-zinc-500 hover:text-zinc-300"
            >
              Dismiss
            </button>
          )}
        </div>
        <div className="prose prose-invert prose-sm max-w-none">
          <MarkdownContent content={content} />
        </div>
      </div>
    </div>
  );
}
