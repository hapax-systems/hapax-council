import { lazy, Suspense } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Clock, Cpu, Loader2 } from "lucide-react";

const MermaidBlock = lazy(() =>
  import("./MermaidBlock").then((m) => ({ default: m.MermaidBlock })),
);

interface QueryResultProps {
  query: string;
  markdown: string;
  isStreaming: boolean;
  metadata?: {
    agent_used: string;
    tokens_in: number;
    tokens_out: number;
    elapsed_ms: number;
  };
}

export function QueryResult({
  query,
  markdown,
  isStreaming,
  metadata,
}: QueryResultProps) {
  return (
    <div className="space-y-3">
      <div className="flex items-start gap-2 text-sm">
        <span className="mt-0.5 shrink-0 text-zinc-500">Q:</span>
        <span className="text-zinc-300">{query}</span>
      </div>

      <div className="flex items-center gap-2 rounded-md bg-zinc-800/50 px-3 py-1.5 text-[11px]">
        {isStreaming ? (
          <>
            <Loader2 className="h-3 w-3 animate-spin text-green-400" />
            <span className="text-green-400">Querying...</span>
          </>
        ) : metadata ? (
          <>
            <Cpu className="h-3 w-3 text-zinc-500" />
            <span className="text-zinc-400">{metadata.agent_used}</span>
            <span className="text-zinc-600">·</span>
            <Clock className="h-3 w-3 text-zinc-500" />
            <span className="text-zinc-400">
              {(metadata.elapsed_ms / 1000).toFixed(1)}s
            </span>
            <span className="text-zinc-600">·</span>
            <span className="text-zinc-500">
              {(
                (metadata.tokens_in + metadata.tokens_out) /
                1000
              ).toFixed(0)}
              k tokens
            </span>
          </>
        ) : null}
      </div>

      {markdown && (
        <div className="max-w-none space-y-3">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              code: ({ children, className, ...props }) => {
                if (className === "language-mermaid") {
                  return (
                    <Suspense
                      fallback={
                        <div className="my-3 flex items-center justify-center rounded-lg border border-zinc-700 bg-zinc-800 p-8">
                          <Loader2 className="h-5 w-5 animate-spin text-zinc-500" />
                        </div>
                      }
                    >
                      <MermaidBlock source={String(children)} />
                    </Suspense>
                  );
                }
                const isInline = !className;
                return isInline ? (
                  <code
                    className="rounded bg-zinc-800 px-1 py-0.5 text-xs text-zinc-300"
                    {...props}
                  >
                    {children}
                  </code>
                ) : (
                  <code className={`${className ?? ""} text-xs`} {...props}>
                    {children}
                  </code>
                );
              },
              pre: ({ children }) => (
                <pre className="overflow-x-auto rounded bg-zinc-800 p-3 text-xs">
                  {children}
                </pre>
              ),
              table: ({ children }) => (
                <table className="w-full border-collapse text-xs">
                  {children}
                </table>
              ),
              th: ({ children }) => (
                <th className="border border-zinc-700 bg-zinc-800 px-2 py-1 text-left font-medium text-zinc-300">
                  {children}
                </th>
              ),
              td: ({ children }) => (
                <td className="border border-zinc-700 px-2 py-1 text-zinc-400">
                  {children}
                </td>
              ),
              a: ({ children, href }) => (
                <a
                  href={href}
                  className="text-blue-400 no-underline hover:text-blue-300"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {children}
                </a>
              ),
              h1: ({ children }) => (
                <h1 className="text-lg font-bold text-zinc-200">{children}</h1>
              ),
              h2: ({ children }) => {
                const id = String(children)
                  .toLowerCase()
                  .replace(/[^a-z0-9]+/g, "-")
                  .replace(/(^-|-$)/g, "");
                return (
                  <h2
                    id={id}
                    className="scroll-mt-4 text-base font-semibold text-zinc-200"
                  >
                    {children}
                  </h2>
                );
              },
              h3: ({ children }) => {
                const id = String(children)
                  .toLowerCase()
                  .replace(/[^a-z0-9]+/g, "-")
                  .replace(/(^-|-$)/g, "");
                return (
                  <h3
                    id={id}
                    className="scroll-mt-4 text-sm font-semibold text-zinc-300"
                  >
                    {children}
                  </h3>
                );
              },
              p: ({ children }) => (
                <p className="leading-relaxed text-zinc-400">{children}</p>
              ),
              ul: ({ children }) => (
                <ul className="list-disc space-y-1 pl-5">{children}</ul>
              ),
              ol: ({ children }) => (
                <ol className="list-decimal space-y-1 pl-5">{children}</ol>
              ),
              li: ({ children }) => (
                <li className="text-zinc-400">{children}</li>
              ),
              blockquote: ({ children }) => (
                <blockquote className="rounded-r border-l-2 border-green-700 bg-green-950/20 py-1 pl-3 italic text-zinc-400">
                  {children}
                </blockquote>
              ),
            }}
          >
            {markdown}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
}
