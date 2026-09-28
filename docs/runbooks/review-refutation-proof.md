# Proving a review claim false with tests

The `Review refutation proof` Actions workflow observes tests. It does not adjudicate
findings, waive criticals, or produce an acceptance. The independent disposition consumer
is a separate step in the existing dossier admission path.

Prior art: #4896 verifies a narrow literal defect against the reviewed source AST; #4898
provides named symbol definitions to reviewers. This extends their evidence boundary to
an observed behavioral counterexample. A chosen mutation still needs independent judgment:
the harness cannot decide whether an arbitrary change represents a reviewer's claim.

1. Select exact pytest node IDs that pass at the reviewed head. Keep tests in that head.
2. Prepare a separate mutant commit from it, changing only existing Python source under
   `shared/`, `agents/` or `scripts/`. Never change the proving tests, workflow, or harness.
   Preserve the reviewed branch and head. Do not push an accepted PR without the seat's answer.
3. Once this workflow exists on the default branch, dispatch it on the reviewed branch:

   ```bash
   gh workflow run review-refutation-proof.yml --ref <reviewed-branch> \
     -f head_sha=<exact-head> -f mutation_sha=<mutant-commit> \
     -f 'test_ids=["tests/test_example.py::test_claim"]'
   ```

4. The disposable runner executes the named tests green, substitutes mutant source, observes
   each named test fail in its call phase, restores exact original bytes, then observes green
   again. Collection errors, skips, absent/duplicate outcomes and ineffective mutations refuse.
   Every leg has a fresh HOME and Python bytecode cache, with the CI service endpoints disabled.
5. Retain the run ID, `review-refutation-proof` artifact ID and Actions SHA-256 digest. The artifact
   holds observed calls, process exit codes, source hashes and the producer hash. Admission must
   fetch it from Actions and check the exact head; a copied local JSON or green aggregate is not proof.

The workflow has read-only repository permissions and no persisted checkout credential.
It never changes the reviewed branch or a live host. Artifacts may expire; unavailable evidence
cannot support admission. Publish fresh evidence before expiry if the PR is still pending.
This workflow is explicitly dispatched, not an additional required branch-protection check.

Local producer verification:

```bash
uv run pytest --confcutdir=tests tests/test_review_refutation_proof.py -q
```

The CLI refuses outside its disposable Actions workspace. The tests use isolated fixture
repositories and deliberately broken source; no real critical is disposed by the source author.

Artifact binding uses the [Actions artifact API](https://docs.github.com/en/rest/actions/artifacts)
(run/head metadata and SHA-256 digest) and the [upload/download digest contract](https://docs.github.com/en/actions/tutorials/store-and-share-data).
