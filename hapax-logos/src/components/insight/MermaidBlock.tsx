import { useEffect, useRef, useState } from "react";
import DOMPurify from "dompurify";
import { Copy, AlertTriangle } from "lucide-react";

let mermaidInstance: typeof import("mermaid") | null = null;
let initPromise: Promise<void> | null = null;
let renderCounter = 0;

async function getMermaid() {
  if (mermaidInstance) return mermaidInstance;
  if (!initPromise) {
    initPromise = (async () => {
      const m = await import("mermaid");
      m.default.initialize({
        startOnLoad: false,
        theme: "dark",
        themeVariables: {
          primaryColor: "#3c3836",
          primaryTextColor: "#ebdbb2",
          primaryBorderColor: "#b8bb26",
          lineColor: "#665c54",
          secondaryColor: "#282828",
          tertiaryColor: "#504945",
          fontFamily: "JetBrains Mono, monospace",
          fontSize: "12px",
        },
      });
      mermaidInstance = m;
    })();
  }
  await initPromise;
  return mermaidInstance!;
}

interface MermaidBlockProps {
  source: string;
}

export function MermaidBlock({ source }: MermaidBlockProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const id = `mermaid-${++renderCounter}`;

    (async () => {
      try {
        const mermaid = await getMermaid();
        const { svg } = await mermaid.default.render(id, source.trim());
        if (!cancelled && containerRef.current) {
          // Safe: SVG from mermaid is sanitized through DOMPurify before insertion
          const sanitized = DOMPurify.sanitize(svg, {
            USE_PROFILES: { svg: true, svgFilters: true },
          });
          containerRef.current.innerHTML = sanitized;
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [source]);

  const handleCopy = () => {
    navigator.clipboard.writeText(source.trim());
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (error) {
    return (
      <div className="my-3 rounded-lg border border-yellow-800 bg-yellow-950/30 p-4">
        <div className="mb-2 flex items-center gap-2 text-xs text-yellow-500">
          <AlertTriangle className="h-3.5 w-3.5" />
          <span>Diagram parse error</span>
        </div>
        <pre className="overflow-x-auto text-xs text-zinc-400">{source.trim()}</pre>
      </div>
    );
  }

  return (
    <div className="my-3 rounded-lg border border-zinc-700 bg-zinc-800 p-4">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-wider text-zinc-500">
          Diagram
        </span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 rounded border border-zinc-700 px-2 py-0.5 text-[10px] text-zinc-500 hover:bg-zinc-700 hover:text-zinc-300"
        >
          <Copy className="h-3 w-3" />
          {copied ? "Copied" : "Copy source"}
        </button>
      </div>
      <div ref={containerRef} className="flex justify-center [&>svg]:max-w-full" />
    </div>
  );
}
