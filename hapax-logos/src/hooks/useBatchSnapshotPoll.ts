/**
 * Batch snapshot poll — fetches multiple camera snapshots in a single HTTP request.
 *
 * Module-level singleton: starts on first subscriber, stops on last.
 * Parses multipart/mixed response and distributes blob URLs to subscribers.
 */

import { useEffect, useRef, useState } from "react";

type Subscriber = {
  role: string;
  callback: (url: string) => void;
};

const subscribers = new Map<string, Set<Subscriber>>();
let pollTimer: ReturnType<typeof setInterval> | null = null;
let polling = false;
const currentUrls = new Map<string, string>();

function getRoles(): string[] {
  const roles = new Set<string>();
  for (const subs of subscribers.values()) {
    for (const s of subs) roles.add(s.role);
  }
  return [...roles];
}

let pageVisible = true;

function onVisibilityChange() {
  pageVisible = !document.hidden;
  if (pageVisible && subscribers.size > 0 && !pollTimer) {
    startPolling(currentIntervalMs || 250);
  } else if (!pageVisible && pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}
document.addEventListener("visibilitychange", onVisibilityChange);

async function fetchBatch(): Promise<void> {
  if (polling || !pageVisible) return;
  const roles = getRoles();
  if (roles.length === 0) return;

  polling = true;
  try {
    const resp = await fetch(
      `/api/studio/stream/cameras/batch?roles=${roles.join(",")}&_t=${Date.now()}`,
    );
    if (!resp.ok) return;

    const ct = resp.headers.get("content-type") ?? "";
    const boundaryMatch = ct.match(/boundary=(.+)/);
    if (!boundaryMatch) return;
    const boundary = boundaryMatch[1];

    const buf = await resp.arrayBuffer();
    const bytes = new Uint8Array(buf);
    const decoder = new TextDecoder();

    // Parse multipart parts
    const boundaryBytes = encoder.encode(`--${boundary}`);
    const parts = splitMultipart(bytes, boundaryBytes);

    for (const part of parts) {
      const headerEnd = findDoubleNewline(part);
      if (headerEnd < 0) continue;

      const headerStr = decoder.decode(part.slice(0, headerEnd));
      const nameMatch = headerStr.match(/name="([^"]+)"/);
      if (!nameMatch) continue;
      const role = nameMatch[1];

      const bodyStart = headerEnd + 4; // skip \r\n\r\n
      const body = part.slice(bodyStart);
      if (body.length < 100) continue;

      // Revoke previous URL for this role
      const prevUrl = currentUrls.get(role);
      if (prevUrl) URL.revokeObjectURL(prevUrl);

      const blob = new Blob([body], { type: "image/jpeg" });
      const url = URL.createObjectURL(blob);
      currentUrls.set(role, url);

      // Notify subscribers
      for (const subs of subscribers.values()) {
        for (const s of subs) {
          if (s.role === role) s.callback(url);
        }
      }
    }
  } catch {
    // Network error — skip this cycle
  } finally {
    polling = false;
  }
}

function findDoubleNewline(data: Uint8Array): number {
  for (let i = 0; i < data.length - 3; i++) {
    if (data[i] === 13 && data[i + 1] === 10 && data[i + 2] === 13 && data[i + 3] === 10) {
      return i;
    }
  }
  return -1;
}

function splitMultipart(data: Uint8Array, boundary: Uint8Array): Uint8Array[] {
  const parts: Uint8Array[] = [];
  let start = 0;

  while (start < data.length) {
    const idx = indexOf(data, boundary, start);
    if (idx < 0) break;
    if (start > 0 && idx > start + 2) {
      // Trim trailing \r\n from previous part
      let end = idx;
      if (data[end - 2] === 13 && data[end - 1] === 10) end -= 2;
      parts.push(data.slice(start, end));
    }
    // Skip boundary + \r\n
    start = idx + boundary.length;
    if (data[start] === 13 && data[start + 1] === 10) start += 2;
    // Check for terminator --
    if (data[idx + boundary.length] === 45 && data[idx + boundary.length + 1] === 45) break;
  }

  return parts;
}

function indexOf(haystack: Uint8Array, needle: Uint8Array, offset: number): number {
  outer:
  for (let i = offset; i <= haystack.length - needle.length; i++) {
    for (let j = 0; j < needle.length; j++) {
      if (haystack[i + j] !== needle[j]) continue outer;
    }
    return i;
  }
  return -1;
}

const encoder = new TextEncoder();

let currentIntervalMs = 0;

function startPolling(intervalMs: number): void {
  // Restart with faster interval if a new subscriber needs higher fps
  if (pollTimer && intervalMs >= currentIntervalMs) return;
  if (pollTimer) clearInterval(pollTimer);
  currentIntervalMs = intervalMs;
  fetchBatch();
  pollTimer = setInterval(fetchBatch, intervalMs);
}

function stopPolling(): void {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  // Revoke all URLs
  for (const url of currentUrls.values()) URL.revokeObjectURL(url);
  currentUrls.clear();
}

/**
 * Subscribe to batch camera snapshots.
 * Returns a ref to attach to an <img> element and a stale flag.
 */
export function useBatchSnapshot(
  role: string,
  intervalMs = 250,
): { imgRef: React.RefObject<HTMLImageElement | null>; isStale: boolean } {
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [isStale, setIsStale] = useState(false);
  const lastSuccess = useRef(Date.now());
  const idRef = useRef(crypto.randomUUID());

  useEffect(() => {
    const id = idRef.current;
    const sub: Subscriber = {
      role,
      callback: (url: string) => {
        if (imgRef.current) imgRef.current.src = url;
        lastSuccess.current = Date.now();
        setIsStale(false);
      },
    };

    if (!subscribers.has(id)) subscribers.set(id, new Set());
    subscribers.get(id)!.add(sub);

    startPolling(intervalMs);

    const staleTimer = setInterval(() => {
      if (Date.now() - lastSuccess.current > 5_000) setIsStale(true);
    }, 2_000);

    return () => {
      subscribers.get(id)?.delete(sub);
      if (subscribers.get(id)?.size === 0) subscribers.delete(id);
      clearInterval(staleTimer);

      // Stop polling if no subscribers remain
      let total = 0;
      for (const s of subscribers.values()) total += s.size;
      if (total === 0) stopPolling();
    };
  }, [role, intervalMs]);

  return { imgRef, isStale };
}

