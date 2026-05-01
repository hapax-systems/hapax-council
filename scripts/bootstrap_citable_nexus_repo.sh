#!/usr/bin/env bash
# bootstrap_citable_nexus_repo.sh — automate the §3 operator-action sequence
# from docs/governance/citable-nexus-bootstrap-status.md.
#
# Per cc-task `citable-nexus-bootstrap-script-and-workflow-template`. Wraps
# the four `gh repo create` / `git clone` / `gh repo edit --enable-pages` /
# DNS-CNAME-prep steps into one idempotent runnable. Dry-run by default;
# `--commit` opts into the mutating path.
#
# Usage:
#
#   scripts/bootstrap_citable_nexus_repo.sh              # dry-run; reports plan
#   scripts/bootstrap_citable_nexus_repo.sh --commit     # creates repo + pushes site
#
# Idempotency:
#   - If the target repo already exists on GitHub, the script clones it
#     instead of creating a new one.
#   - If the rendered site is byte-identical to what's already at the repo
#     HEAD, no commit is created.
#   - DNS CNAME setup remains operator-action (DNS provider varies); the
#     script writes a `CNAME` file locally so the operator can `git push`
#     when DNS is configured.
#
# References:
#   - docs/governance/citable-nexus-bootstrap-status.md §3 (the spec)
#   - scripts/build_citable_nexus.py (the renderer this script wraps)
#   - docs/citable-nexus/github-actions-deploy.yml.template
#   - docs/citable-nexus/CNAME.template

set -euo pipefail

# ── Defaults (operator-overridable) ──────────────────────────────────

REPO_OWNER="${HAPAX_NEXUS_REPO_OWNER:-ryanklee}"
REPO_NAME="${HAPAX_NEXUS_REPO_NAME:-hapax-research}"
REPO_DESCRIPTION="${HAPAX_NEXUS_REPO_DESC:-Citable nexus for Hapax / Oudepode published artifacts}"
REPO_HOMEPAGE="${HAPAX_NEXUS_REPO_HOMEPAGE:-https://hapax.research}"
DOMAIN="${HAPAX_NEXUS_DOMAIN:-hapax.research}"

WORK_DIR="${HAPAX_NEXUS_WORK_DIR:-$HOME/.cache/hapax/citable-nexus-bootstrap}"
COUNCIL_REPO="${HAPAX_COUNCIL_REPO:-$HOME/projects/hapax-council}"

DRY_RUN=true
ENABLE_PAGES=true

# ── Argv parse ──────────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case "$1" in
        --commit)
            DRY_RUN=false
            shift
            ;;
        --no-pages)
            ENABLE_PAGES=false
            shift
            ;;
        --help|-h)
            sed -n '2,30p' "$0"
            exit 0
            ;;
        *)
            echo "bootstrap_citable_nexus_repo.sh: unknown arg: $1" >&2
            exit 2
            ;;
    esac
done

# ── Helpers ─────────────────────────────────────────────────────────

log() {
    echo "[bootstrap-citable-nexus] $*" >&2
}

run() {
    if [[ "${DRY_RUN}" == "true" ]]; then
        echo "  DRY-RUN: $*"
    else
        eval "$@"
    fi
}

# ── Phase 1: render the site ─────────────────────────────────────────

log "Rendering Phase 0 site via build_citable_nexus.py..."
RENDER_DIR="${WORK_DIR}/render"
mkdir -p "${RENDER_DIR}"
(
    cd "${COUNCIL_REPO}"
    .venv/bin/python scripts/build_citable_nexus.py --out "${RENDER_DIR}"
)
log "Render complete: $(find "${RENDER_DIR}" -name '*.html' | wc -l) pages under ${RENDER_DIR}"

# Drop the CNAME + workflow template into the render dir so the push
# below copies them into the new repo.
log "Copying CNAME + workflow template into render dir..."
mkdir -p "${RENDER_DIR}/.github/workflows"
cp "${COUNCIL_REPO}/docs/citable-nexus/CNAME.template" "${RENDER_DIR}/CNAME"
cp "${COUNCIL_REPO}/docs/citable-nexus/github-actions-deploy.yml.template" \
    "${RENDER_DIR}/.github/workflows/deploy.yml"
# The CNAME file's content is the bare domain — rewrite if HAPAX_NEXUS_DOMAIN
# is set to something other than the template's default.
echo "${DOMAIN}" > "${RENDER_DIR}/CNAME"

# ── Phase 2: create or clone the GitHub repo ─────────────────────────

REPO_FULL="${REPO_OWNER}/${REPO_NAME}"
REPO_DIR="${WORK_DIR}/${REPO_NAME}"

if gh repo view "${REPO_FULL}" >/dev/null 2>&1; then
    log "Repo ${REPO_FULL} already exists; cloning if not present locally."
    if [[ ! -d "${REPO_DIR}" ]]; then
        run "gh repo clone ${REPO_FULL} ${REPO_DIR}"
    fi
else
    log "Repo ${REPO_FULL} does NOT exist; creating."
    run "gh repo create ${REPO_FULL} \
        --public \
        --description \"${REPO_DESCRIPTION}\" \
        --homepage \"${REPO_HOMEPAGE}\""
    if [[ "${DRY_RUN}" == "false" ]]; then
        gh repo clone "${REPO_FULL}" "${REPO_DIR}"
    fi
fi

# ── Phase 3: copy rendered site into the repo + commit ──────────────

if [[ "${DRY_RUN}" == "false" && -d "${REPO_DIR}" ]]; then
    log "Copying rendered site to ${REPO_DIR}..."
    cp -r "${RENDER_DIR}/." "${REPO_DIR}/"
    cd "${REPO_DIR}"
    if [[ -n "$(git status --porcelain)" ]]; then
        git add -A
        git commit -m "feat: Phase 0 — renderer-emitted citable-nexus front door

Bootstrap commit from hapax-council:scripts/bootstrap_citable_nexus_repo.sh.
Source repo: ${COUNCIL_REPO}; renderer: agents/citable_nexus/.

Per the council Phase 0 governance doc, this commit ships:
  - 4 static HTML pages (/, /cite, /refuse, /surfaces)
  - CNAME for ${DOMAIN}
  - .github/workflows/deploy.yml (cron-rebuild)

Phase 1+ pages (/manifesto, /refusal-brief, /deposits, /citation-graph)
land in subsequent renderer extensions in hapax-council."
        git push origin main
        log "Pushed initial commit to ${REPO_FULL}"
    else
        log "Site is already up to date in ${REPO_FULL}; no commit needed."
    fi
fi

# ── Phase 4: enable GitHub Pages ─────────────────────────────────────

if [[ "${ENABLE_PAGES}" == "true" ]]; then
    log "Enabling GitHub Pages on ${REPO_FULL}..."
    # gh CLI does not have a direct `pages enable` subcommand; use the API.
    run "gh api -X POST \
        -H 'Accept: application/vnd.github+json' \
        /repos/${REPO_FULL}/pages \
        -f source[branch]=main \
        -f source[path]=/ \
        || log 'Pages may already be enabled; continuing.'"
fi

# ── Phase 5: DNS instructions (operator-action) ──────────────────────

cat <<EOF

[bootstrap-citable-nexus] Operator-action remaining:

  1. DNS CNAME: add a CNAME record at your DNS provider:
       ${DOMAIN} → ${REPO_OWNER}.github.io

  2. Verify GitHub Pages picks up the CNAME file:
       gh api /repos/${REPO_FULL}/pages

  3. Wait 5-15 min for Let's Encrypt cert provisioning.

  4. Smoke-test the site:
       curl -sI https://${DOMAIN}/ | head -1     # expect HTTP/2 200
       curl -s  https://${DOMAIN}/cite | head -3
       curl -s  https://${DOMAIN}/surfaces | head -3

  5. Update upstream pointers:
       - Refusal Brief footer auto-injection: point at https://${DOMAIN}/refuse
       - Bluesky / Mastodon bios: link https://${DOMAIN}
       - CITATION.cff: cross-reference both repos

  6. Update docs/governance/citable-nexus-bootstrap-status.md to "live as of <iso-date>".

EOF

log "Bootstrap script complete (mode: $([ "${DRY_RUN}" = "true" ] && echo dry-run || echo commit))."
