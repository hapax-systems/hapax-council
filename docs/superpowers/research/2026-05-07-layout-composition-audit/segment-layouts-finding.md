# Segment-*.json layouts — scope finding

Companion finding to `audit.md` (PR #2844). The layout-composition spec listed `config/compositor-layouts/segment-*.json` as in-scope, but inspection shows the segment layouts are NOT the same compositional problem as `default.json`. This doc records the finding so future audits don't repeatedly chase the same dead end.

## Inventory

8 segment layouts: `segment-{chat,compare,detail,list,poll,programme-context,receipt,tier}.json`. All structurally identical:

```
sources:     1
surfaces:    2  (one rect panel + one video_out target)
assignments: 1
```

Geometry across all 8:
- **Content panel rect:** `(x=240, y=120, w=1440, h=760)`
- **Margins:** L=240, R=240, T=120, B=200
- **z_order:** 900 (panel) over 100 (video_out)

The 8 files differ only in:
- Surface ID (`tier-panel-surface`, `chat-panel-surface`, etc. — content semantic identifier)
- One-line description ("tier-status beats", "chat-response beats", etc.)
- Source ID matching the surface

## Finding 1 — Uniform framing is intentional

The descriptions all use the formula "Responsible hosted segment layout for {beat-type} beats." This is **scripted hosted content framing**: operator reads from the panel, viewer sees consistent visual placement across segment types. Visual surprise in segment mode would be jarring during scripted content.

The Berger critique of "dashboard-style layouts" from the spec applies to **constellation surfaces** (`default.json`, ambient broadcast) — surfaces that should compose tension and depth. Segment mode is the **scripted-content frame** — surfaces that should be predictable and content-focused. Different design context, different criteria.

## Finding 2 — Asymmetric vertical margins are deliberate

L=R=240 (symmetric horizontally) but T=120 / B=200 (asymmetric vertically — panel sits 40 px above true vertical center, leaving 80 extra px below).

Hypothesis: the bottom margin reserves space for captions or a status strip below the panel. (Not verified against runtime; would need an OBS capture during segment-mode playback to confirm.) Either way, this is consistent across all 8 layouts — likely a deliberate house-style margin, not a bug.

## Finding 3 — No per-segment differentiation

Every segment layout looks identical except for the content source. Possible variation axes the operator could explore in a future pass:

- **`segment-tier`** — could lean left (rank list reads top-down + left-aligned by convention)
- **`segment-poll`** — could split vertically: question top half, results bottom half
- **`segment-receipt`** — world-surface artifact could use a portrait-aspect panel
- **`segment-rant`** — dense text format, could use a wider/shorter panel

But all of these would break the "scripted content uniform framing" principle from Finding 1. Whether the principle should yield to per-segment expression is a design question the operator should decide before any PR ships.

## Recommendation

**No code edits this pass.** The segment layouts are well-formed for their scripted-content purpose. The proposed `default.json` deltas A–D in `audit.md` (PR #2844) remain the right target for the layout-composition pass spec — that's where naive symmetry, dashboard packing, z underutilization, and predictable adjacencies actually exist.

If a future pass wants to revisit segments, the design question (per-segment differentiation vs uniform framing) is the gate, not the implementation.
