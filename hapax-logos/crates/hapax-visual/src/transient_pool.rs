//! Transient texture pool — frame-local bucketed allocator for intermediates.
//!
//! Followup F1 of the compositor unification epic. Consumes the Phase 4c
//! data plane: each pool key (computed in Python as `hash(TextureDescriptor)`)
//! maps to a bucket of recyclable textures with identical descriptors. Two
//! intermediates with the same `(width, height, format)` share a bucket and
//! recycle GPU memory across frames instead of thrashing the allocator.
//!
//! ## Lifecycle
//!
//! 1. Call [`begin_frame`](TransientTexturePool::begin_frame) at the start
//!    of each render frame. This resets every bucket's `in_use` counter to
//!    zero — previously-allocated textures stay in their buckets and become
//!    available for reuse this frame.
//! 2. Call [`acquire_tracked`](TransientTexturePool::acquire_tracked) once
//!    per intermediate texture needed this frame, passing a factory closure
//!    that allocates a fresh texture if the bucket has none free. The pool
//!    returns the slot index of the acquired texture; the caller borrows
//!    the texture itself via [`get`](TransientTexturePool::get). Returning
//!    a slot rather than a reference sidesteps Rust's borrow checker so
//!    the pool can update its allocation counter on the same call.
//! 3. After the frame, the textures stay in the pool. The next
//!    `begin_frame` recycles them.
//!
//! ## Generic over T
//!
//! The pool is generic over the texture type so unit tests can exercise
//! the bookkeeping logic without a real wgpu device. Production callers
//! instantiate `TransientTexturePool<PoolTexture>` (or similar) and pass
//! a closure that allocates from `device.create_texture(...)`.
//!
//! ## Phase 4c data plane connection
//!
//! The Python compile phase produces `CompiledFrame.transient_textures`
//! with one `TransientTexture` per non-final effect chain stage. Each
//! TransientTexture has a `pool_key: int` derived from
//! `hash((width, height, format))`. F1 lands the Rust-side allocator
//! that the executor wires up when consuming `CompiledFrame` directly.
//! Until that wiring lands, the pool exists as a standalone capability
//! with comprehensive bookkeeping tests.
//!
//! See: docs/superpowers/specs/2026-04-12-phase-4-compile-phase-design.md
//! See: docs/superpowers/specs/2026-04-12-phase-5b-unification-epic.md (followups)

use std::collections::HashMap;

/// One bucket of textures sharing the same pool_key (and therefore the
/// same descriptor — width, height, format).
struct PoolBucket<T> {
    textures: Vec<T>,
    in_use: usize,
}

impl<T> Default for PoolBucket<T> {
    fn default() -> Self {
        Self {
            textures: Vec::new(),
            in_use: 0,
        }
    }
}

/// A frame-local bucketed texture allocator.
///
/// Generic over the texture handle type `T`. Production callers use
/// the wgpu texture-view-or-similar; tests use simple integer handles.
///
/// The pool tracks per-frame `acquire` counts and lifetime allocation
/// counts so callers can compute the reuse ratio for observability.
pub struct TransientTexturePool<T> {
    buckets: HashMap<u64, PoolBucket<T>>,
    total_acquires: u64,
    total_allocations: u64,
}

impl<T> Default for TransientTexturePool<T> {
    fn default() -> Self {
        Self::new()
    }
}

impl<T> TransientTexturePool<T> {
    /// Construct an empty pool. No textures are allocated until the
    /// first `acquire` call.
    pub fn new() -> Self {
        Self {
            buckets: HashMap::new(),
            total_acquires: 0,
            total_allocations: 0,
        }
    }

    /// Reset every bucket's in-use counter to zero.
    ///
    /// Call once at the start of each render frame. Previously-allocated
    /// textures stay in their buckets and become available for reuse.
    pub fn begin_frame(&mut self) {
        for bucket in self.buckets.values_mut() {
            bucket.in_use = 0;
        }
    }

    /// Total number of buckets currently tracked.
    pub fn bucket_count(&self) -> usize {
        self.buckets.len()
    }

    /// Total number of textures across all buckets.
    pub fn total_textures(&self) -> usize {
        self.buckets.values().map(|b| b.textures.len()).sum()
    }

    /// Total number of `acquire` calls since pool construction.
    pub fn total_acquires(&self) -> u64 {
        self.total_acquires
    }

    /// Total number of fresh texture allocations since pool construction.
    /// `total_acquires - total_allocations` is the number of reuse hits.
    pub fn total_allocations(&self) -> u64 {
        self.total_allocations
    }

    /// Reuse ratio in [0.0, 1.0]: 1.0 means every acquire was a reuse,
    /// 0.0 means every acquire allocated fresh. Returns 0.0 (not NaN)
    /// for an empty pool — metric collectors typically prefer a numeric
    /// zero over NaN for "no data yet". Audit fix: previous docstring
    /// claimed NaN, which the implementation never produced.
    pub fn reuse_ratio(&self) -> f64 {
        if self.total_acquires == 0 {
            return 0.0;
        }
        let reuses = self.total_acquires - self.total_allocations;
        reuses as f64 / self.total_acquires as f64
    }

    /// Drop every cached texture and reset all counters.
    ///
    /// Used on viewport resize where the cached textures are no longer
    /// the right dimensions and have to be recreated by future
    /// `acquire` calls. Tests also call this to start from a clean
    /// state without constructing a new pool.
    pub fn clear(&mut self) {
        self.buckets.clear();
        self.total_acquires = 0;
        self.total_allocations = 0;
    }

    /// Number of textures currently in-use within the bucket for
    /// ``pool_key``. Returns 0 if the bucket doesn't exist.
    pub fn in_use_count(&self, pool_key: u64) -> usize {
        self.buckets.get(&pool_key).map(|b| b.in_use).unwrap_or(0)
    }

    /// Number of textures total (in-use + free) in the bucket for
    /// ``pool_key``. Returns 0 if the bucket doesn't exist.
    pub fn bucket_size(&self, pool_key: u64) -> usize {
        self.buckets
            .get(&pool_key)
            .map(|b| b.textures.len())
            .unwrap_or(0)
    }
}

// ---------------------------------------------------------------------------
// Allocation counter — tracked via a separate path because the borrow
// checker won't let us touch self.total_allocations while a reference
// into self.buckets is alive.
// ---------------------------------------------------------------------------

impl<T> TransientTexturePool<T> {
    /// Acquire-and-record helper that returns the texture by clone instead
    /// of by reference. Useful when the caller needs both the texture
    /// and an updated allocation counter, since the counter mutation
    /// would otherwise require dropping the texture borrow first.
    ///
    /// The default `acquire` does NOT increment `total_allocations`
    /// — call this method when you want the counter tracked.
    pub fn acquire_tracked<F>(&mut self, pool_key: u64, factory: F) -> usize
    where
        F: FnOnce() -> T,
    {
        self.total_acquires += 1;
        let bucket = self.buckets.entry(pool_key).or_default();
        let was_new = bucket.in_use >= bucket.textures.len();
        if was_new {
            bucket.textures.push(factory());
        }
        let slot = bucket.in_use;
        bucket.in_use += 1;
        if was_new {
            self.total_allocations += 1;
        }
        slot
    }

    /// Borrow the texture at `(pool_key, slot)` produced by a prior
    /// `acquire_tracked` call. Returns None if either is out of range.
    pub fn get(&self, pool_key: u64, slot: usize) -> Option<&T> {
        self.buckets
            .get(&pool_key)
            .and_then(|b| b.textures.get(slot))
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    /// Test texture: a simple integer handle so we don't need wgpu.
    type TestTex = u32;

    // ----- begin_frame + acquire basics -----

    #[test]
    fn new_pool_is_empty() {
        let pool: TransientTexturePool<TestTex> = TransientTexturePool::new();
        assert_eq!(pool.bucket_count(), 0);
        assert_eq!(pool.total_textures(), 0);
        assert_eq!(pool.total_acquires(), 0);
        assert_eq!(pool.total_allocations(), 0);
    }

    #[test]
    fn first_acquire_allocates_fresh_texture() {
        let mut pool: TransientTexturePool<TestTex> = TransientTexturePool::new();
        let mut counter = 0u32;
        let _slot = pool.acquire_tracked(42, || {
            counter += 1;
            counter
        });
        assert_eq!(pool.total_acquires(), 1);
        assert_eq!(pool.total_allocations(), 1);
        assert_eq!(pool.bucket_count(), 1);
        assert_eq!(pool.bucket_size(42), 1);
    }

    #[test]
    fn second_acquire_in_same_frame_allocates_second_texture() {
        // Two transients with the same pool_key in one frame need two
        // distinct GPU textures because they're alive simultaneously.
        let mut pool: TransientTexturePool<TestTex> = TransientTexturePool::new();
        let mut counter = 0u32;
        let mut allocate = || {
            counter += 1;
            counter
        };
        pool.acquire_tracked(42, &mut allocate);
        pool.acquire_tracked(42, &mut allocate);
        assert_eq!(pool.total_acquires(), 2);
        assert_eq!(pool.total_allocations(), 2);
        assert_eq!(pool.bucket_size(42), 2);
    }

    #[test]
    fn begin_frame_recycles_textures_for_next_frame() {
        // Two acquires in frame 1, then begin_frame, then two acquires
        // in frame 2. Frame 2 should reuse the textures from frame 1
        // — total_allocations should still be 2, not 4.
        let mut pool: TransientTexturePool<TestTex> = TransientTexturePool::new();
        let mut counter = 0u32;
        let mut allocate = || {
            counter += 1;
            counter
        };
        pool.acquire_tracked(42, &mut allocate);
        pool.acquire_tracked(42, &mut allocate);
        pool.begin_frame();
        pool.acquire_tracked(42, &mut allocate);
        pool.acquire_tracked(42, &mut allocate);
        assert_eq!(pool.total_acquires(), 4);
        assert_eq!(pool.total_allocations(), 2);
        assert_eq!(pool.bucket_size(42), 2);
    }

    #[test]
    fn distinct_pool_keys_get_distinct_buckets() {
        let mut pool: TransientTexturePool<TestTex> = TransientTexturePool::new();
        pool.acquire_tracked(1, || 100);
        pool.acquire_tracked(2, || 200);
        pool.acquire_tracked(3, || 300);
        assert_eq!(pool.bucket_count(), 3);
        assert_eq!(pool.bucket_size(1), 1);
        assert_eq!(pool.bucket_size(2), 1);
        assert_eq!(pool.bucket_size(3), 1);
    }

    // ----- get + slot lookup -----

    #[test]
    fn get_returns_acquired_texture() {
        let mut pool: TransientTexturePool<TestTex> = TransientTexturePool::new();
        let slot = pool.acquire_tracked(42, || 999);
        assert_eq!(pool.get(42, slot), Some(&999));
    }

    #[test]
    fn get_unknown_pool_key_returns_none() {
        let pool: TransientTexturePool<TestTex> = TransientTexturePool::new();
        assert_eq!(pool.get(42, 0), None);
    }

    #[test]
    fn get_out_of_range_slot_returns_none() {
        let mut pool: TransientTexturePool<TestTex> = TransientTexturePool::new();
        pool.acquire_tracked(42, || 1);
        assert_eq!(pool.get(42, 5), None);
    }

    // ----- in_use vs bucket_size -----

    #[test]
    fn in_use_count_grows_within_frame_then_resets() {
        let mut pool: TransientTexturePool<TestTex> = TransientTexturePool::new();
        let mut counter = 0u32;
        let mut alloc = || {
            counter += 1;
            counter
        };
        pool.acquire_tracked(42, &mut alloc);
        pool.acquire_tracked(42, &mut alloc);
        pool.acquire_tracked(42, &mut alloc);
        assert_eq!(pool.in_use_count(42), 3);
        pool.begin_frame();
        assert_eq!(pool.in_use_count(42), 0);
        assert_eq!(pool.bucket_size(42), 3); // textures still cached
    }

    #[test]
    fn bucket_size_does_not_decrease_on_begin_frame() {
        // bucket_size is the lifetime allocation count for that bucket;
        // it never shrinks until clear() or pool drop.
        let mut pool: TransientTexturePool<TestTex> = TransientTexturePool::new();
        pool.acquire_tracked(42, || 1);
        pool.acquire_tracked(42, || 2);
        assert_eq!(pool.bucket_size(42), 2);
        pool.begin_frame();
        assert_eq!(pool.bucket_size(42), 2);
        pool.acquire_tracked(42, || 999); // recycles slot 0
        assert_eq!(pool.bucket_size(42), 2);
    }

    // ----- reuse_ratio -----

    #[test]
    fn reuse_ratio_zero_when_every_acquire_allocates() {
        let mut pool: TransientTexturePool<TestTex> = TransientTexturePool::new();
        let mut counter = 0u32;
        let mut alloc = || {
            counter += 1;
            counter
        };
        // Three distinct pool keys → three buckets, each with one
        // texture. Every acquire is a fresh allocation.
        pool.acquire_tracked(1, &mut alloc);
        pool.acquire_tracked(2, &mut alloc);
        pool.acquire_tracked(3, &mut alloc);
        assert_eq!(pool.reuse_ratio(), 0.0);
    }

    #[test]
    fn reuse_ratio_one_when_only_recycled_acquires() {
        let mut pool: TransientTexturePool<TestTex> = TransientTexturePool::new();
        let mut counter = 0u32;
        let mut alloc = || {
            counter += 1;
            counter
        };
        // Frame 1: allocate one texture in bucket 42.
        pool.acquire_tracked(42, &mut alloc);
        // Frame 2 onwards: recycle that one texture every frame.
        for _ in 0..10 {
            pool.begin_frame();
            pool.acquire_tracked(42, &mut alloc);
        }
        // 11 acquires, 1 allocation → reuse ratio = 10/11.
        assert_eq!(pool.total_acquires(), 11);
        assert_eq!(pool.total_allocations(), 1);
        assert!((pool.reuse_ratio() - 10.0 / 11.0).abs() < 1e-9);
    }

    #[test]
    fn reuse_ratio_zero_for_empty_pool() {
        let pool: TransientTexturePool<TestTex> = TransientTexturePool::new();
        assert_eq!(pool.reuse_ratio(), 0.0);
    }

    // ----- clear -----

    #[test]
    fn clear_drops_buckets_and_counters() {
        let mut pool: TransientTexturePool<TestTex> = TransientTexturePool::new();
        pool.acquire_tracked(1, || 10);
        pool.acquire_tracked(2, || 20);
        assert_eq!(pool.bucket_count(), 2);
        pool.clear();
        assert_eq!(pool.bucket_count(), 0);
        assert_eq!(pool.total_textures(), 0);
        assert_eq!(pool.total_acquires(), 0);
        assert_eq!(pool.total_allocations(), 0);
    }

    // ----- generic over T sanity -----

    #[test]
    fn pool_works_with_struct_handle_type() {
        #[derive(Default, PartialEq, Debug)]
        struct FakeTexture {
            id: u32,
            width: u32,
            height: u32,
        }

        let mut pool: TransientTexturePool<FakeTexture> = TransientTexturePool::new();
        let mut next_id = 0u32;
        pool.acquire_tracked(99, || {
            next_id += 1;
            FakeTexture {
                id: next_id,
                width: 1920,
                height: 1080,
            }
        });
        let tex = pool.get(99, 0).unwrap();
        assert_eq!(tex.width, 1920);
        assert_eq!(tex.height, 1080);
        assert_eq!(tex.id, 1);
    }

    #[test]
    fn default_constructor_matches_new() {
        let a: TransientTexturePool<TestTex> = TransientTexturePool::new();
        let b: TransientTexturePool<TestTex> = TransientTexturePool::default();
        assert_eq!(a.bucket_count(), b.bucket_count());
        assert_eq!(a.total_acquires(), b.total_acquires());
    }
}
