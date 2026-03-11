# hapax-council

The deliberative body: a full operational agent platform implementing externalized
executive function infrastructure. Reactive cockpit, voice daemon, sync pipeline,
Claude Code integration — all governed by constitutional axioms.

Built on the architectural pattern defined in [hapax-constitution](https://github.com/ryanklee/hapax-constitution).
See [hapax-officium](https://github.com/ryanklee/hapax-officium) for a management domain instantiation.

## Architecture

- **Agents**: 26+ Pydantic AI agents across management, sync/RAG, analysis, system, and content categories
- **Agent Packages**: hapax_voice (voice daemon), demo_pipeline (demo generation), dev_story (development narrative)
- **Cockpit API**: FastAPI backend with reactive engine (inotify → rule evaluation → phased execution)
- **Dashboard**: React SPA (council-web)
- **VS Code Extension**: Chat, RAG search, management integration
- **Claude Code Integration**: Skills, hooks, and rules for Claude Code sessions

## Quick Start

```bash
uv sync
uv run python -m agents.<agent_name> [flags]
```

## License

Apache 2.0 — see [LICENSE](LICENSE).
