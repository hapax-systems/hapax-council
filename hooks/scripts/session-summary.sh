#!/usr/bin/env bash
# session-summary.sh — Stop hook for axiom audit summary
# Shows a one-line summary of axiom audit activity for the session.

AUDIT_FILE="$HOME/.cache/axiom-audit/$(date +%Y-%m-%d).jsonl"
if [ -f "$AUDIT_FILE" ]; then
  TOTAL=$(wc -l < "$AUDIT_FILE")
  echo "Axiom audit: $TOTAL edits tracked."
else
  echo "Axiom audit: no activity logged this session."
fi
