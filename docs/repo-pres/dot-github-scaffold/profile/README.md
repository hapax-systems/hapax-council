# Superseded Profile Copy

This file is no longer a publish source.

Hapax Systems public GitHub frontmatter now lives under the organization
profile repository:

`hapax-systems/.github/profile/README.md`

Generate it from `hapax-constitution`:

```bash
python -m sdlc.render --org-profile
```

Renderer and CLI coverage live in `hapax-constitution`:

```bash
uv run pytest tests/test_render.py::test_cli_dry_run_prints_org_profile tests/test_render.py::test_cli_org_profile_write_creates_nested_profile_readme -q
```

This scaffold no longer carries historical personal-account copy. That prevents
future public-surface drift back to a non-organization owner.
