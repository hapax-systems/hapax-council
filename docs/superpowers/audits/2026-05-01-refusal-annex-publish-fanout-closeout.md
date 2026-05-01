# Refusal Annex Publish Fanout Closeout

Generated: 2026-05-01T00:34:44Z
Task: `refusal-annex-publish-fanout-closeout`

## Inventory

Render path:

- `agents/marketing/refusal_annex_renderer.py` reads `/dev/shm/hapax-refusals/log.jsonl`, groups matching refusal surfaces into annex slugs, writes local markdown via `RefusalAnnexPublisher`, and can enqueue approved `PreprintArtifact` records for the publish orchestrator.
- `agents/marketing/refusal_annex_publisher.py` is the local-file publisher for `~/hapax-state/publications/refusal-annex-{slug}.md`.

Publish path:

- `agents/publish_orchestrator/orchestrator.py` watches `~/hapax-state/publish/inbox/*.json`, dispatches every targeted surface in parallel, writes per-surface logs to `~/hapax-state/publish/log/{slug}.{surface}.json`, and moves artifacts to `published/` only when every target returns `ok`.
- `agents/refusal_brief_zenodo_adapter/__init__.py` handles `zenodo-refusal-deposit` and requires `HAPAX_ZENODO_TOKEN` at runtime.
- `agents/omg_weblog_publisher/publisher.py` handles `omg-weblog` through `pass show omg-lol/api-key`.

Fanout path:

- `agents/publication_bus/bridgy_publisher.py` is a generic wired Bridgy webmention publisher for normal omg.lol weblog artifacts.
- `agents/bridgy_adapter/__init__.py` constructs `https://hapax.omg.lol/weblog/{slug}` source URLs for generic weblog artifacts.
- `agents/marketing/refusal_annex_bridgy_daemon.py` is dry-run inventory only. It must not issue a refusal-annex Bridgy POST until source URL witness/sequencing is committed.
- `shared/publication_artifact_public_event.py` already holds refusal-annex Bridgy targets as dry-run public-event truth.

## Runtime Evidence

- `systemctl --user is-active hapax-publish-orchestrator.service`: `active`.
- `systemctl --user is-enabled hapax-publish-orchestrator.service`: `enabled`.
- `pass show zenodo/api-token >/dev/null`: present.
- `pass show omg-lol/api-key >/dev/null`: present.
- Current shell has `HAPAX_ZENODO_TOKEN` unset; `/run/user/1000/hapax-secrets.env` contains matched publish keys for the service.
- `~/hapax-state/publications/` has no `refusal-annex-*.md` files at this snapshot.
- `~/hapax-state/publish/log/` has no refusal-annex logs at this snapshot.

## Blocker

Zenodo and omg.lol weblog publication can be enqueued as committed surfaces.
Refusal-annex Bridgy fanout is blocked because the current orchestrator
dispatches surfaces in parallel, while Bridgy must only POST after the
omg.lol weblog source URL exists and can be witnessed. Without that witness,
including `bridgy-webmention-publish` in the same refusal-annex target set can
present a dormant path as live or race the weblog publish.

## Closeout Decision

This PR keeps default refusal-annex enqueue limited to committed Zenodo and
omg.lol weblog surfaces, rejects refusal-annex Bridgy targets at the renderer,
blocks accidental refusal-annex Bridgy adapter POSTs, and keeps the dry-run
daemon explicitly blocked. Generic Bridgy webmention remains wired for normal
weblog artifacts.
