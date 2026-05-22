# Contributing

`hapax-council` is source-available research infrastructure for one operator. It is not a product, not a service, and not seeking contributors.

The repository is published for inspection, citation, audit, and archival evidence. External patches, feature requests, support requests, issue intake, discussions, community governance, and contributor onboarding are refused by design under the `single_user` constitutional axiom.

Useful public entry points:

- [`START_HERE.md`](START_HERE.md) for reviewer orientation.
- [`NOTICE.md`](NOTICE.md) for project posture and license.
- [`CITATION.cff`](CITATION.cff) for citation metadata.
- [Refusal Brief](https://hapax.weblog.lol/refusal-brief) for the refusal-as-data stance.

## CI Checks

### New Module Consumer Check

When adding a new module file, the `new-module-consumer-check` CI gate ensures that it has at least one import reference outside the `tests/` directory.

To satisfy the gate:
- Ensure your new module is imported and used by real project code (not just tests).
- Alternatively, if the module is intended as a library entry-point, mark it as exempt by adding its relative path (e.g., `agents/my_new_module.py`) to the allowlist at `scripts/ci_orphan_module_exempt.txt`.
