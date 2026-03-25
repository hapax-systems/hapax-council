#!/usr/bin/env bash
# backup.sh — Backup critical LLM stack configuration and state
# Run weekly via cron or manually.
# Usage: backup.sh [backup_dir]
set -euo pipefail

BACKUP_ROOT="${1:-$HOME/backups/llm-stack}"
BACKUP_DIR="$BACKUP_ROOT/$(date +%Y%m%d-%H%M%S)"

log() { echo "[Backup] $*"; }

mkdir -p "$BACKUP_DIR"
log "Backup target: $BACKUP_DIR"

# ── Claude Code config ───────────────────────────────────────────────────────
if [[ -d "$HOME/.claude" ]]; then
    cp -r "$HOME/.claude" "$BACKUP_DIR/claude-config"
    log "✓ Claude Code config"
fi

# ── aichat config ────────────────────────────────────────────────────────────
if [[ -f "$HOME/.config/aichat/config.yaml" ]]; then
    mkdir -p "$BACKUP_DIR/aichat"
    cp "$HOME/.config/aichat/config.yaml" "$BACKUP_DIR/aichat/"
    log "✓ aichat config"
fi

# ── Langfuse prompts ─────────────────────────────────────────────────────────
LANGFUSE_HOST="${LANGFUSE_HOST:-http://localhost:3000}"
LANGFUSE_PK="${LANGFUSE_PUBLIC_KEY:-}"
LANGFUSE_SK="${LANGFUSE_SECRET_KEY:-}"

if [[ -n "$LANGFUSE_PK" && -n "$LANGFUSE_SK" ]]; then
    AUTH=$(echo -n "${LANGFUSE_PK}:${LANGFUSE_SK}" | base64)
    curl -sf "$LANGFUSE_HOST/api/public/v2/prompts" \
        -H "Authorization: Basic $AUTH" \
        --max-time 10 \
        > "$BACKUP_DIR/langfuse-prompts.json" 2>/dev/null && \
        log "✓ Langfuse prompts" || \
        log "⚠ Langfuse prompts export failed"
else
    log "○ Langfuse: no credentials, skipping prompt backup"
fi

# ── Qdrant snapshots ─────────────────────────────────────────────────────────
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
mkdir -p "$BACKUP_DIR/qdrant"

for collection in documents profile-facts axiom-precedents operator-episodes studio-moments operator-corrections; do
    if curl -sf "$QDRANT_URL/collections/$collection" -o /dev/null --max-time 3 2>/dev/null; then
        SNAP=$(curl -sf -X POST "$QDRANT_URL/collections/$collection/snapshots" \
            --max-time 30 2>/dev/null || echo "")
        if [[ -n "$SNAP" ]]; then
            echo "$SNAP" > "$BACKUP_DIR/qdrant/${collection}-snapshot.json"
            log "✓ Qdrant: $collection snapshot"
        else
            log "⚠ Qdrant: $collection snapshot failed"
        fi
    else
        log "○ Qdrant: $collection not found"
    fi
done

COMPOSE_FILE="${COMPOSE_FILE:-$HOME/llm-stack/docker-compose.yml}"

# ── n8n workflows ────────────────────────────────────────────────────────────
if docker compose -f "$COMPOSE_FILE" ps n8n --format json 2>/dev/null | grep -q running; then
    mkdir -p "$BACKUP_DIR/n8n"
    docker compose -f "$COMPOSE_FILE" exec -T n8n \
        n8n export:workflow --all 2>/dev/null \
        > "$BACKUP_DIR/n8n/workflows.json" && \
        log "✓ n8n workflows" || \
        log "⚠ n8n workflow export failed"
    docker compose -f "$COMPOSE_FILE" exec -T n8n \
        n8n export:credentials --all 2>/dev/null \
        > "$BACKUP_DIR/n8n/credentials.json" && \
        log "✓ n8n credentials" || \
        log "⚠ n8n credential export failed"
else
    log "○ n8n not running, skipping workflow backup"
fi

# ── PostgreSQL databases ──────────────────────────────────────────────────────
if docker compose -f "$COMPOSE_FILE" ps postgres --format json 2>/dev/null | grep -q running; then
    mkdir -p "$BACKUP_DIR/postgres"
    for db in litellm langfuse ragdb; do
        docker compose -f "$COMPOSE_FILE" exec -T postgres \
            pg_dump -U postgres "$db" 2>/dev/null \
            > "$BACKUP_DIR/postgres/${db}.sql" && \
            log "✓ PostgreSQL: $db" || \
            log "⚠ PostgreSQL: $db dump failed"
    done
else
    log "○ PostgreSQL not running, skipping database backup"
fi

# ── Systemd service files ────────────────────────────────────────────────────
if [[ -d "$HOME/.config/systemd/user" ]]; then
    mkdir -p "$BACKUP_DIR/systemd"
    cp "$HOME/.config/systemd/user/"*.service "$BACKUP_DIR/systemd/" 2>/dev/null || true
    cp "$HOME/.config/systemd/user/"*.timer "$BACKUP_DIR/systemd/" 2>/dev/null || true
    log "✓ Systemd user units"
fi

# ── Agent profiles ────────────────────────────────────────────────────────────
if [[ -d "$HOME/projects/ai-agents/profiles" ]]; then
    cp -r "$HOME/projects/ai-agents/profiles" "$BACKUP_DIR/profiles"
    log "✓ Agent profiles"
fi

# ── Cache state (not covered by Docker volume backups) ──────────────────────
mkdir -p "$BACKUP_DIR/cache-state"

if [ -d "$HOME/.cache/axiom-audit" ]; then
    cp -r "$HOME/.cache/axiom-audit" "$BACKUP_DIR/cache-state/axiom-audit"
    log "✓ axiom-audit"
else
    log "○ axiom-audit (not found)"
fi

if [ -d "$HOME/.cache/logos" ]; then
    cp -r "$HOME/.cache/logos" "$BACKUP_DIR/cache-state/logos"
    log "✓ logos"
else
    log "○ logos (not found)"
fi

if [ -f "$HOME/.cache/rag-ingest/processed.json" ]; then
    mkdir -p "$BACKUP_DIR/cache-state/rag-ingest"
    cp "$HOME/.cache/rag-ingest/processed.json" "$BACKUP_DIR/cache-state/rag-ingest/"
    log "✓ rag-ingest dedup tracker"
else
    log "○ rag-ingest (not found)"
fi

if [ -d "$HOME/.cache/takeout-ingest" ]; then
    cp -r "$HOME/.cache/takeout-ingest" "$BACKUP_DIR/cache-state/takeout-ingest"
    log "✓ takeout-ingest"
else
    log "○ takeout-ingest (not found)"
fi

# Sync agent state (cursors, page tokens, processed IDs — loss triggers full re-sync)
for sync_dir in gdrive-sync gcalendar-sync gmail-sync youtube-sync claude-code-sync obsidian-sync chrome-sync; do
    if [ -d "$HOME/.cache/$sync_dir" ]; then
        cp -r "$HOME/.cache/$sync_dir" "$BACKUP_DIR/cache-state/$sync_dir"
        log "✓ $sync_dir"
    fi
done

# ── Hotkey scripts ───────────────────────────────────────────────────────────
if [[ -d "$HOME/.local/bin/llm-hotkeys" ]]; then
    cp -r "$HOME/.local/bin/llm-hotkeys" "$BACKUP_DIR/hotkeys"
    log "✓ Hotkey scripts"
fi

# ── Summary ──────────────────────────────────────────────────────────────────
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)
log ""
log "Backup complete: $BACKUP_DIR ($TOTAL_SIZE)"

# ── Cleanup old backups (keep last 8) ────────────────────────────────────────
BACKUP_COUNT=$(ls -d "$BACKUP_ROOT"/20* 2>/dev/null | wc -l)
if [[ $BACKUP_COUNT -gt 8 ]]; then
    ls -d "$BACKUP_ROOT"/20* | head -n -8 | while read -r old; do
        rm -rf "$old"
        log "  Pruned: $(basename "$old")"
    done
fi
