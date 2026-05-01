# InsightFace ArcFace per-person matcher reconcile (2026-05-01)

**cc-task:** `insightface-arcface-enrollment-proof-reconcile` (P2, WSJF 5.5)
**Author:** epsilon
**Predecessor task:** `closed/ef7b-162-insightface-arcface-enrollment-upgrade-for-jason-p.md`
(marked `completed` by Antigravity 2026-04-26T20:20:12Z)

## Premise

The closed task `ef7b-162` titled "InsightFace ArcFace enrollment
upgrade for Jason (per-person face-matcher gate)" claims completion,
but the pipeline-ingress audit flagged that the high-risk
consent-gated ArcFace upgrade was skipped or left for a later runner.
The reconcile task asks whether the ArcFace enrollment upgrade code,
tests, and consent-safe operator enrollment proof actually shipped —
and if not, whether the real implementation work needs to be split
into a new task with explicit consent + privacy gates.

## What actually shipped (operator-side, partial)

The operator-side face enrollment + ReID pipeline is wired and in
production:

- **`agents/hapax_daimonion/face_detector.py`** — InsightFace SCRFD
  with the `buffalo_sc` model (lightweight ArcFace-family detector
  + recognition heads). Initialized with CUDA. Produces 512-dim
  face embeddings and uses cosine similarity for cross-camera
  ReID (`_DEDUP_SIMILARITY_THRESHOLD = 0.6`).
- **`agents/hapax_daimonion/enrollment.py`** — multi-sample voice
  enrollment ceremony (10 prompts × 5s) plus `enroll_face()` which
  captures a single frame from the BRIO camera, runs detection +
  embedding extraction, and saves `~/.local/share/hapax-daimonion/
  operator_face.npy`. Stability report at `enrollment_report.json`
  with pairwise similarity statistics + threshold test (default
  accept threshold 0.60, outlier detection at 0.50).
- **`tests/hapax_daimonion/test_enrollment_validation.py`** —
  unit tests for `compute_pairwise_similarity`, `detect_outliers`,
  `threshold_test`, and `write_stability_report`.

This satisfies the operator-side enrollment proof. The buffalo_sc
recognition head is an ArcFace-family model, so the closed task's
"ArcFace enrollment upgrade" claim is structurally true for the
operator's own face: a 512-d ArcFace-style embedding is produced,
saved, and used by downstream cross-camera ReID.

## What did NOT ship (per-person matcher gate)

The closed task's load-bearing scope — the **per-person face-matcher
gate for Jason** — was not implemented:

- No code references `jason_kleeberger`, `jason`, or
  `per_person_face_matcher` in `agents/`, `shared/`, or `logos/`.
- No enrollment artifact at `~/hapax-state/face-enrollments/
  jason_kleeberger.npz` (the path the consent contract names).
- The consent contract `axioms/contracts/contract-jason-enroll-2026-04-19.yaml`
  exists and authorizes the single-frame capture, but no code path
  loads a Jason embedding or gates a `consent_to_enroll` action on
  it.
- `face_detector.py` carries only one operator embedding slot
  (`_operator_embedding`, `_operator_embedding_loaded`); no
  data structure for a multi-person enrollment registry that would
  let "is this Jason in frame?" return a boolean answer.

The architectural surface for per-person consent (matching a
detected face against a registry of consenting persons before
activating guest-specific scope) does not exist in the codebase.

## Decision

**Split the real implementation task with explicit consent and
privacy gates** — per acceptance criterion #3 of the reconcile.

- This reconcile task closes as `done` with the documented findings.
- A new follow-on cc-task is filed at
  `~/Documents/Personal/20-projects/hapax-cc-tasks/active/
  arcface-per-person-matcher-gate.md` with the per-person matcher
  gate as its scope, gated on the existing consent contract.
- The closed `ef7b-162` task's frontmatter is left intact (it was
  marked completed legitimately for the operator-side portion); a
  reconcile pointer is added in the session log so future readers
  see the partial status.

## Consent + privacy invariants for the follow-on task

These are non-negotiable for the per-person matcher gate
implementation:

1. **No biometric embedding may be created or persisted without an
   active consent contract.** The contract
   `contract-jason-enroll-2026-04-19.yaml` is the authorizing
   instrument; if it expires or is revoked, the per-person
   enrollment for Jason must be deletable on a single command.
2. **Embeddings stay local.** No egress to LiteLLM, no upload to
   any cloud surface, no inclusion in publish-bus artifacts. The
   on-disk path is `~/hapax-state/face-enrollments/<principal>.npz`
   per the contract.
3. **Single-shot capture only.** The contract authorizes
   `single_enrollment_event`, not ongoing tracking. The follow-on
   implementation must capture exactly one frame's embedding per
   enrollment ceremony, not a multi-frame averaging pass that would
   require multiple frames of biometric data.
4. **Match results are non-persistent.** The consent gate's
   downstream effect (e.g., "activate guest-specific scope") may
   persist; the per-tick "is this Jason?" boolean must not be
   logged with biometric metadata.
5. **Failure-closed.** If the matcher cannot decide (low-confidence
   match, no face detected, model unavailable), the gate must
   return `False` (no guest-specific activation). Drift toward
   permissive defaults under uncertainty would silently widen
   scope past consent.
6. **Revocation primitive.** A single `revoke_enrollment(principal)`
   call deletes the on-disk embedding + clears any in-memory
   matcher state. This must be wired before the matcher gate
   ships, not after.

These map directly onto the existing `interpersonal_transparency`
axiom + `it-attribution-001` analogues (consent-to-data-flow as
constitutive, not regulative).

## Acceptance status (this reconcile task)

- [x] Verify whether ArcFace enrollment upgrade code, tests, and
  consent-safe operator enrollment proof actually shipped → yes,
  operator-side; no, per-person Jason gate.
- [x] If shipped, add concrete evidence to the closed task → noted
  here; vault closed task pointer updated separately.
- [x] If not shipped, split the real implementation task with
  explicit consent and privacy gates → new task
  `arcface-per-person-matcher-gate` filed in vault `active/`.
- [x] Do not create or persist biometric embeddings without the
  approved consent path → respected throughout this reconcile;
  invariants 1–6 above carry into the follow-on.

## Pointers

- Operator-side face: `agents/hapax_daimonion/face_detector.py:91`
  (`buffalo_sc` model init).
- Operator-side enrollment: `agents/hapax_daimonion/enrollment.py:204`
  (`enroll_face()`).
- Stability report: `agents/hapax_daimonion/enrollment.py:99`
  (`write_stability_report`).
- Tests: `tests/hapax_daimonion/test_enrollment_validation.py`.
- Consent contract: `axioms/contracts/contract-jason-enroll-2026-04-19.yaml`.
- Closed predecessor: `closed/ef7b-162-insightface-arcface-enrollment-upgrade-for-jason-p.md`.
