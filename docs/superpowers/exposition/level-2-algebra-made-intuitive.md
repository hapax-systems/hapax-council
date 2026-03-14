# Level 2: The Algebra Made Intuitive

## Why Algebra, Not Just Code

You might reasonably ask: why can't you just write careful code that passes consent data around? Why do you need *algebraic properties*?

Here's the answer by analogy. Imagine you have a function that adds numbers. You test it: `add(2, 3) == 5`. Great. But you haven't proven it's commutative — that `add(a, b) == add(b, a)` for *all* `a` and `b`. If you're building a distributed system where two nodes might add the same numbers in different orders and need to agree on the result, commutativity isn't a nice-to-have — it's the difference between correctness and silent data corruption.

Consent labels have the same issue. When two data streams merge, does it matter which order you combine their labels in? If it does, then the order agents happen to process data determines what consent protections apply — a race condition in your governance. Commutativity of `join` means: no matter what order data arrives, the resulting consent requirements are the same.

Each algebraic property eliminates a specific class of bugs:

| Property | What breaks if it fails |
|----------|------------------------|
| Commutativity of join | Processing order changes consent requirements |
| Associativity of join | Grouping of merge operations changes consent requirements |
| Idempotence of join | Merging data with itself somehow escalates restrictions |
| Bottom as identity | Introducing public data accidentally changes existing restrictions |
| Reflexivity of flow | Data can't flow to a context with its own exact permissions |
| Transitivity of flow | A→B is safe, B→C is safe, but A→C isn't — contradictory |
| Antisymmetry of flow | Two different labels both flow to each other — label distinction is meaningless |

These aren't abstract concerns. Every one of them maps to a specific way consent could leak or be over/under-enforced in a real pipeline.

---

## The Lattice, Visually

Think of consent labels as sets of policies. Visualize them as a Hasse diagram — a graph where more restrictive labels are higher:

```
        {alice, bob}          ← most restrictive: both must consent
        /          \
    {alice}      {bob}        ← one person's consent
        \          /
         {}                   ← bottom: public, no consent needed
```

Data flows **upward** in this diagram. Public data can flow anywhere. Data about Alice can flow to a context that requires Alice's consent, or to one that requires both Alice and Bob. But data about both Alice and Bob *cannot* flow down to a context that only accounts for Alice — Bob's consent would be lost.

The `join` operation takes two labels and produces the label at their shared upper point. `{alice}.join({bob}) = {alice, bob}`. This is set union. It's the **least upper bound** — the smallest label that's at least as restrictive as both inputs.

This is why the lattice structure matters: it gives you a principled answer to "what consent label should fused data have?" The answer is always the join. No judgment call. No case-by-case reasoning. The algebra decides.

---

## Functor: The Consent-Preserving Transformation

`Labeled[T]` is called a functor because of one property: you can transform the value inside without breaking the consent wrapper.

Why is this important? Because your pipeline is a chain of transformations:

```
audio chunk → transcript → extracted facts → profile update
```

At each step, the data changes shape. But the consent obligations don't change — if Alice's voice produced the audio chunk, Alice's consent is still required for the profile update derived from it. The functor property guarantees this: `map` changes `T` but preserves `label` and `provenance`.

The two functor laws:

1. **Identity**: `x.map(lambda v: v) == x` — doing nothing to the value does nothing to the wrapper. This sounds trivial, but it means there's no hidden side effect in the wrapping mechanism itself.

2. **Composition**: `x.map(f).map(g) == x.map(lambda v: g(f(v)))` — mapping two functions one after another is the same as mapping their composition in a single step. This means the pipeline can be refactored (steps merged or split) without changing consent behavior.

Together, these guarantee that the consent wrapper is *transparent* to transformations — it carries consent metadata faithfully regardless of how many processing steps occur or how they're organized.

---

## What "Bottom" Means and Why It's Subtle

`ConsentLabel.bottom()` = `ConsentLabel(frozenset())` — the empty set of policies. This is **public data**. No consent required from anyone.

Bottom has a specific algebraic role: it's the **identity element** for join. `a.join(bottom) == a` for any label `a`. Mixing public data with consented data doesn't change the consent requirements.

There's also `None` — the *absence* of a label. This is different from bottom. `None` means "we don't know whether this data requires consent." Bottom means "we explicitly know this data is public."

This distinction is DD-16 (gradual security typing). During incremental adoption, some parts of the pipeline don't have labels yet. Those parts produce `None`. At enforcement boundaries, `None` is treated as **most restrictive** (DD-3) — unknown consent = no consent = denied. This is the conservative default: you must explicitly label data as public. Unlabeled data is guilty until proven innocent.

This is the same insight from gradual typing in programming languages (Toro, Garcia, Tanter, 2018): you can have a partially-typed program where typed regions enforce invariants and untyped regions are treated with maximum caution at the boundaries.

---

## The "Floating" Label and Why It Prevents Laundering

The LIO pattern solves a subtle problem: **consent laundering**.

Without floating labels, an agent could:
1. Read Alice's high-consent data
2. Compute something based on it
3. Write the result without Alice's label (since the result is "new" data, not Alice's original data)

This is information laundering — stripping consent obligations by transforming data.

LIO prevents this with a floating label. As a computation reads labeled data, its own label **floats upward** to include the observed label. Once you've seen Alice's data, your computation's label includes Alice's policy. You can't write to a destination that doesn't have Alice's consent.

In the implementation: `Behavior[T].update()` joins any incoming consent label with its existing one. The label only moves up, never down. `FusedContext`'s consent label is the join of all Behavior labels it was fused from. The `consent_veto` in VetoChain enforces: if the fused context's label can't flow to the required label for the downstream operation, the operation is denied.

This is why the `can_flow_to` direction matters. Less-restricted data (`{alice}`) can flow to more-restricted contexts (`{alice, bob}`) because the destination already has all the necessary consent plus more. More-restricted data (`{alice, bob}`) cannot flow to less-restricted contexts (`{alice}`) because Bob's consent would be lost.

The flow direction is: `self.policies <= target.policies`. Subset. Fewer policies (less restricted) flows to more policies (more restricted). If this feels backwards at first, think of it as: the destination must *at least* match all the consent requirements of the source.
