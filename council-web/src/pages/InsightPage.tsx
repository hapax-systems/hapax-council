import { useState, useCallback, useRef } from "react";
import { QueryInput } from "../components/insight/QueryInput";
import {
  QueryResultList,
  type ResultEntry,
} from "../components/insight/QueryResultList";
import { RefinementInput } from "../components/insight/RefinementInput";
import { connectSSE } from "../api/sse";
import { sseUrl } from "../api/client";
import { Sparkles } from "lucide-react";

export function InsightPage() {
  const [results, setResults] = useState<ResultEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);

  const runQuery = useCallback(
    (
      query: string,
      refine?: { prior_result: string; agent_type: string },
    ) => {
      setIsLoading(true);

      const id = `q-${Date.now()}`;
      const entry: ResultEntry = {
        id,
        query,
        markdown: "",
        isStreaming: true,
      };

      setResults((prev) => [...prev, entry]);

      const url = refine ? sseUrl("/query/refine") : sseUrl("/query/run");
      const body = refine
        ? {
            query,
            prior_result: refine.prior_result,
            agent_type: refine.agent_type,
          }
        : { query };

      controllerRef.current = connectSSE(url, {
        body,
        onEvent: (event) => {
          try {
            const data = JSON.parse(event.data) as Record<string, unknown>;

            if (event.event === "text_delta") {
              setResults((prev) =>
                prev.map((r) =>
                  r.id === id
                    ? { ...r, markdown: r.markdown + String(data.content ?? "") }
                    : r,
                ),
              );
            } else if (event.event === "done") {
              setResults((prev) =>
                prev.map((r) =>
                  r.id === id
                    ? {
                        ...r,
                        isStreaming: false,
                        metadata: data as ResultEntry["metadata"],
                      }
                    : r,
                ),
              );
              setIsLoading(false);
            } else if (event.event === "error") {
              setResults((prev) =>
                prev.map((r) =>
                  r.id === id
                    ? {
                        ...r,
                        isStreaming: false,
                        markdown:
                          r.markdown +
                          `\n\n> **Error:** ${String(data.message ?? "Unknown error")}`,
                      }
                    : r,
                ),
              );
              setIsLoading(false);
            }
          } catch {
            // Ignore malformed events
          }
        },
        onDone: () => setIsLoading(false),
        onError: (err) => {
          setResults((prev) =>
            prev.map((r) =>
              r.id === id
                ? {
                    ...r,
                    isStreaming: false,
                    markdown: `> **Error:** ${err.message}`,
                  }
                : r,
            ),
          );
          setIsLoading(false);
        },
      });
    },
    [],
  );

  const handleQuery = useCallback(
    (query: string) => runQuery(query),
    [runQuery],
  );

  const handleRefine = useCallback(
    (query: string) => {
      const lastDone = [...results]
        .reverse()
        .find((r) => !r.isStreaming && r.metadata);
      if (!lastDone) return;
      runQuery(query, {
        prior_result: lastDone.markdown,
        agent_type: lastDone.metadata!.agent_used,
      });
    },
    [results, runQuery],
  );

  const lastResult = results[results.length - 1];
  const showRefinement =
    lastResult && !lastResult.isStreaming && lastResult.metadata;

  return (
    <div className="flex flex-1 flex-col">
      <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-4 p-6">
        <QueryInput onSubmit={handleQuery} isLoading={isLoading} />

        {results.length === 0 && !isLoading && (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 text-zinc-600">
            <Sparkles className="h-8 w-8" />
            <p className="text-sm">
              Ask about development history, system patterns, or architecture
            </p>
          </div>
        )}

        <div className="flex-1 overflow-y-auto">
          <QueryResultList results={results} />
          {showRefinement && (
            <RefinementInput onSubmit={handleRefine} isLoading={isLoading} />
          )}
        </div>
      </div>
    </div>
  );
}
