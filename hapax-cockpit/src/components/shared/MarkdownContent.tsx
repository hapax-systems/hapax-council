import { useEffect, useRef, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MarkdownContentProps {
  content: string;
  className?: string;
  searchQuery?: string;
}

function highlightMatches(root: HTMLElement, query: string) {
  // Clear existing highlights
  root.querySelectorAll("mark[data-search-highlight]").forEach((mark) => {
    const parent = mark.parentNode;
    if (parent) {
      parent.replaceChild(document.createTextNode(mark.textContent ?? ""), mark);
      parent.normalize();
    }
  });

  if (!query.trim()) return;

  const lowerQuery = query.toLowerCase();
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const matches: { node: Text; index: number }[] = [];

  let node: Text | null;
  while ((node = walker.nextNode() as Text | null)) {
    const text = node.textContent ?? "";
    let idx = text.toLowerCase().indexOf(lowerQuery);
    while (idx !== -1) {
      matches.push({ node, index: idx });
      idx = text.toLowerCase().indexOf(lowerQuery, idx + lowerQuery.length);
    }
  }

  // Apply highlights in reverse order to preserve indices
  for (let i = matches.length - 1; i >= 0; i--) {
    const { node: textNode, index } = matches[i];
    const range = document.createRange();
    range.setStart(textNode, index);
    range.setEnd(textNode, index + query.length);
    const mark = document.createElement("mark");
    mark.setAttribute("data-search-highlight", "true");
    mark.className = "rounded-sm bg-yellow-500/30 text-zinc-200";
    range.surroundContents(mark);
  }
}

export function MarkdownContent({ content, className = "", searchQuery }: MarkdownContentProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  const applyHighlights = useCallback(() => {
    if (containerRef.current && searchQuery) {
      highlightMatches(containerRef.current, searchQuery);
    } else if (containerRef.current) {
      highlightMatches(containerRef.current, "");
    }
  }, [searchQuery]);

  useEffect(() => {
    // Small delay to let ReactMarkdown render
    const id = requestAnimationFrame(applyHighlights);
    return () => cancelAnimationFrame(id);
  }, [applyHighlights, content]);

  return (
    <div ref={containerRef} className={`max-w-none space-y-3 ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code: ({ children, className: codeClassName, ...props }) => {
            const isInline = !codeClassName;
            return isInline ? (
              <code className="rounded bg-zinc-800 px-1 py-0.5 text-xs text-zinc-300" {...props}>
                {children}
              </code>
            ) : (
              <code className={`${codeClassName ?? ""} text-xs`} {...props}>
                {children}
              </code>
            );
          },
          pre: ({ children }) => (
            <pre className="overflow-x-auto rounded bg-zinc-800 p-3 text-xs">{children}</pre>
          ),
          table: ({ children }) => (
            <table className="w-full border-collapse text-xs">{children}</table>
          ),
          th: ({ children }) => (
            <th className="border border-zinc-700 bg-zinc-800 px-2 py-1 text-left font-medium text-zinc-300">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border border-zinc-700 px-2 py-1 text-zinc-400">{children}</td>
          ),
          a: ({ children, href }) => (
            <a
              href={href}
              className="text-blue-400 hover:text-blue-300 no-underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              {children}
            </a>
          ),
          h1: ({ children }) => <h1 className="text-lg font-bold text-zinc-200">{children}</h1>,
          h2: ({ children }) => {
            const id = String(children).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
            return <h2 id={id} className="text-base font-semibold text-zinc-200 scroll-mt-4">{children}</h2>;
          },
          h3: ({ children }) => {
            const id = String(children).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
            return <h3 id={id} className="text-sm font-semibold text-zinc-300 scroll-mt-4">{children}</h3>;
          },
          p: ({ children }) => <p className="text-zinc-400 leading-relaxed">{children}</p>,
          ul: ({ children }) => <ul className="list-disc pl-5 space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-5 space-y-1">{children}</ol>,
          li: ({ children }) => <li className="text-zinc-400">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-zinc-600 pl-3 text-zinc-500 italic">
              {children}
            </blockquote>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
