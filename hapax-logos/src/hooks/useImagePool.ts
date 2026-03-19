/**
 * Module-scoped HTMLImageElement pool.
 * Eliminates GC pressure from ~30-100 new Image() allocations/sec
 * during snapshot polling across camera grid views.
 */

const MAX_POOL_SIZE = 8;
const pool: HTMLImageElement[] = [];

/** Acquire an Image element from the pool, or create a new one. */
export function acquireImage(): HTMLImageElement {
  const img = pool.pop();
  if (img) return img;
  return new Image();
}

/** Release an Image element back to the pool. Clears handlers and src. */
export function releaseImage(img: HTMLImageElement): void {
  img.onload = null;
  img.onerror = null;
  img.src = "";
  if (pool.length < MAX_POOL_SIZE) {
    pool.push(img);
  }
  // Excess images are left for GC
}
