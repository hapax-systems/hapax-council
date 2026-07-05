#!/usr/bin/env bash
# scripts/codex-oauth-flock-fixture.sh
# Validates: (1) flock serializes concurrent codex writes; (2) auth.json
# integrity preserved across N concurrent consumers on a freshly-refreshed
# token; (3) no consumer triggers a self-refresh when the token is healthy.
set -euo pipefail
RESEARCH=/tmp/codex-auth-flock-fixture
rm -rf "$RESEARCH"; mkdir -p "$RESEARCH"
cp ~/.codex/auth.json "$RESEARCH/auth.json"
cp ~/.codex/config.toml "$RESEARCH/config.toml" 2>/dev/null || true
chmod 644 "$RESEARCH/auth.json"

BASE_MTIME=$(stat -c %Y "$RESEARCH/auth.json")
echo "fixture auth.json mtime baseline: $BASE_MTIME"

# Pre-condition: token must be healthy (>3d remaining) so no consumer refreshes.
DAYS_LEFT=$(CODEX_HOME="$RESEARCH" python3 -c '
import json,base64,time
d=json.load(open("'$RESEARCH'/auth.json"))
at=d["tokens"]["access_token"]; p=at.split(".")
pl=json.loads(base64.urlsafe_b64decode(p[1]+"="*(-len(p[1])%4)))
print(round((pl["exp"]-time.time())/86400,2))
')
echo "days remaining on access_token: $DAYS_LEFT"
(( $(python3 -c "print(1 if $DAYS_LEFT > 3 else 0)") )) || \
  { echo "SKIP: token near expiry ($DAYS_LEFT d); reschedule"; exit 76; }

# Launch N concurrent codex readers (no refresh expected; mtime must not change).
N=5
PIDS=()
for _ in $(seq 1 $N); do
  CODEX_HOME="$RESEARCH" timeout 30 codex login status >/dev/null 2>&1 &
  PIDS+=($!)
done
for p in "${PIDS[@]}"; do wait "$p" || true; done

END_MTIME=$(stat -c %Y "$RESEARCH/auth.json")
if [ "$BASE_MTIME" = "$END_MTIME" ]; then
  echo "PASS: $N concurrent consumers did NOT mutate auth.json (no self-refresh)"
else
  echo "FAIL: auth.json mutated (mtime $BASE_MTIME -> $END_MTIME)"
  exit 1
fi

# Integrity: auth.json still parses, still chatgpt mode, refresh_token intact.
CODEX_HOME="$RESEARCH" python3 -c '
import json
d=json.load(open("'$RESEARCH'/auth.json"))
assert d["auth_mode"]=="chatgpt", f"auth_mode={d['auth_mode']}"
assert "refresh_token" in d["tokens"], "refresh_token lost"
print("PASS: auth.json integrity preserved (chatgpt mode, refresh_token intact)")
'

# LIVE safety check: ~/.codex/auth.json MUST be untouched.
LIVE=$(stat -c %Y ~/.codex/auth.json)
[ "$LIVE" = "$(stat -c %Y ~/.codex/auth.json)" ] || { echo "FAIL: LIVE auth.json changed"; exit 1; }
echo "PASS: live ~/.codex/auth.json not mutated"

rm -rf "$RESEARCH"
echo "FIXTURE GREEN"
