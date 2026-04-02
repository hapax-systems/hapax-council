import { requestUrl } from "obsidian";
import type { SprintState, Measure, Gate, StimmungState, Nudge } from "./types";

interface CacheEntry<T> {
  data: T;
  fetchedAt: number;
}

export interface HealthState {
  status: string;
  healthy: string[];
  degraded: string[];
  failed: string[];
}

export class LogosClient {
  private baseUrl: string;
  private cache: Map<string, CacheEntry<unknown>> = new Map();

  /** True after at least one successful API call; false after a failure. */
  apiAvailable = false;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  updateBaseUrl(url: string): void {
    this.baseUrl = url.replace(/\/$/, "");
    this.cache.clear();
  }

  private async get<T>(path: string, ttlMs: number): Promise<T> {
    const cached = this.cache.get(path);
    if (cached && Date.now() - cached.fetchedAt < ttlMs) {
      return cached.data as T;
    }
    try {
      const resp = await requestUrl({ url: `${this.baseUrl}${path}` });
      const data = resp.json as T;
      this.cache.set(path, { data, fetchedAt: Date.now() });
      this.apiAvailable = true;
      return data;
    } catch (err) {
      this.apiAvailable = false;
      throw err;
    }
  }

  private invalidatePrefix(prefix: string): void {
    for (const key of this.cache.keys()) {
      if (key.startsWith(prefix)) {
        this.cache.delete(key);
      }
    }
  }

  private async post<T>(path: string, body?: unknown): Promise<T> {
    const resp = await requestUrl({
      url: `${this.baseUrl}${path}`,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    return resp.json as T;
  }

  getSprint(): Promise<SprintState> {
    return this.get<SprintState>("/api/sprint", 30_000);
  }

  getMeasures(): Promise<Measure[]> {
    return this.get<Measure[]>("/api/sprint/measures", 60_000);
  }

  getMeasure(id: string): Promise<Measure> {
    return this.get<Measure>(`/api/sprint/measures/${id}`, 30_000);
  }

  getGates(): Promise<Gate[]> {
    return this.get<Gate[]>("/api/sprint/gates", 60_000);
  }

  getGate(id: string): Promise<Gate> {
    return this.get<Gate>(`/api/sprint/gates/${id}`, 30_000);
  }

  getStimmung(): Promise<StimmungState> {
    return this.get<StimmungState>("/api/stimmung", 15_000);
  }

  getHealth(): Promise<HealthState> {
    return this.get<HealthState>("/api/health", 30_000);
  }

  getNudges(): Promise<Nudge[]> {
    return this.get<Nudge[]>("/api/nudges", 60_000);
  }

  async transitionMeasure(
    id: string,
    status: string,
    resultSummary?: string,
  ): Promise<unknown> {
    const body: Record<string, string> = { status };
    if (resultSummary !== undefined) {
      body["result_summary"] = resultSummary;
    }
    const result = await this.post(`/api/sprint/measures/${id}/transition`, body);
    this.invalidatePrefix("/api/sprint");
    this.cache.delete(`/api/sprint/measures/${id}`);
    return result;
  }

  async acknowledgeGate(id: string): Promise<unknown> {
    const result = await this.post(`/api/sprint/gates/${id}/acknowledge`);
    this.invalidatePrefix("/api/sprint");
    this.cache.delete(`/api/sprint/gates/${id}`);
    return result;
  }

  async dismissNudge(sourceId: string): Promise<unknown> {
    const result = await this.post(`/api/nudges/${sourceId}/dismiss`);
    this.invalidatePrefix("/api/nudges");
    return result;
  }

  async actOnNudge(sourceId: string): Promise<unknown> {
    const result = await this.post(`/api/nudges/${sourceId}/act`);
    this.invalidatePrefix("/api/nudges");
    return result;
  }

  invalidateAll(): void {
    this.cache.clear();
  }
}
