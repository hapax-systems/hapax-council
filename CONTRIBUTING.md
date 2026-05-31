# Contributing

`hapax-council` is source-available research infrastructure for one operator. It is not a product, not a service, and not seeking contributors.

The repository is published for inspection, citation, audit, and archival evidence. External patches, feature requests, support requests, issue intake, discussions, community governance, and contributor onboarding are refused by design under the `single_user` constitutional axiom.

Useful public entry points:

- [`START_HERE.md`](START_HERE.md) for reviewer orientation.
- [`NOTICE.md`](NOTICE.md) for project posture and license.
- [`CITATION.cff`](CITATION.cff) for citation metadata.
- [Refusal Brief](https://hapax.weblog.lol/refusal-brief) for the refusal-as-data stance.

## CI Gates and Module Verification

To maintain codebase health and prevent dead code, any newly added Python module must have at least one import reference in a non-test source file. If your pull request introduces a module that has zero non-test consumers, the `new-module-consumer-check` gate will fail.

To satisfy the gate:
1. **Add a Real Consumer**: Import and use the module in at least one non-test source file (e.g., under `agents/`, `logos/`, `shared/`, or `scripts/`).
2. **Use the Entry-point Allowlist**: If the module is a library entry-point intended for future or dynamic use, add the module name or its path to the allowlist in [`config/new-module-allowlist.json`](config/new-module-allowlist.json). You can use glob patterns (e.g., `shared.my_lib.*`).
