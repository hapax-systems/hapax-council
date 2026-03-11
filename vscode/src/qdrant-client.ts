import type { HapaxSettings, QdrantSearchResult, QdrantSearchResponse } from "./types";

export class QdrantClient {
  private settings: HapaxSettings;

  constructor(settings: HapaxSettings) {
    this.settings = settings;
  }

  updateSettings(settings: HapaxSettings): void {
    this.settings = settings;
  }

  /**
   * Embed text using Ollama's nomic-embed-text-v2-moe model.
   * Applies the "search_query: " prefix required by nomic v2.
   */
  async embed(text: string): Promise<number[]> {
    const prefixed = `search_query: ${text}`;
    const response = await fetch(`${this.settings.ollamaUrl}/api/embed`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "nomic-embed-text-v2-moe",
        input: prefixed,
      }),
      signal: AbortSignal.timeout(10_000),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Ollama embed failed (${response.status}): ${errorText}`);
    }

    const data = await response.json() as { embeddings: number[][] };
    // Ollama /api/embed returns { embeddings: [number[][]] }
    const embeddings: number[][] = data.embeddings;
    if (!embeddings || embeddings.length === 0 || embeddings[0].length === 0) {
      throw new Error("Ollama returned empty embeddings");
    }
    return embeddings[0];
  }

  /**
   * Search a Qdrant collection by embedding a query and performing vector similarity search.
   */
  async search(
    query: string,
    collection?: string,
    limit?: number
  ): Promise<QdrantSearchResult[]> {
    const col = collection || this.settings.qdrantCollection;
    const vector = await this.embed(query);

    const response = await fetch(
      `${this.settings.qdrantUrl}/collections/${encodeURIComponent(col)}/points/search`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          vector,
          limit: limit || 10,
          with_payload: true,
        }),
        signal: AbortSignal.timeout(10_000),
      }
    );

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Qdrant search failed (${response.status}): ${errorText}`);
    }

    const data = await response.json() as QdrantSearchResponse;
    return data.result;
  }

  /**
   * Search across multiple Qdrant collections and merge results by score.
   */
  async searchMulti(
    query: string,
    collections: string[],
    limitPerCollection = 5
  ): Promise<(QdrantSearchResult & { collection: string })[]> {
    const vector = await this.embed(query);
    const allResults: (QdrantSearchResult & { collection: string })[] = [];

    await Promise.all(
      collections.map(async (col) => {
        try {
          const response = await fetch(
            `${this.settings.qdrantUrl}/collections/${encodeURIComponent(col)}/points/search`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                vector,
                limit: limitPerCollection,
                with_payload: true,
              }),
              signal: AbortSignal.timeout(10_000),
            }
          );
          if (!response.ok) return;
          const data = await response.json() as QdrantSearchResponse;
          for (const r of data.result) {
            allResults.push({ ...r, collection: col });
          }
        } catch (err: unknown) {
          console.warn(`Hapax: Qdrant collection '${col}' unavailable:`, err);
        }
      })
    );

    // Sort by score descending
    allResults.sort((a, b) => b.score - a.score);
    return allResults;
  }
}
