#!/usr/bin/env bash
# bootstrap_citable_nexus_repo.sh — render and bootstrap a static publishing repo.
#
# Per cc-task `citable-nexus-bootstrap-script-and-workflow-template`. Wraps
# `gh repo create` / `gh repo clone` / GitHub Pages API / DNS-CNAME-prep
# steps into one runnable. Default mode renders locally and queries repo
# existence; it only prints the remote mutations. `--commit` also copies,
# commits and pushes the site, then requests Pages unless `--no-pages`.
#
# Usage:
#
#   scripts/bootstrap_citable_nexus_repo.sh              # local render + repo query
#   scripts/bootstrap_citable_nexus_repo.sh --commit     # creates repo + pushes site
#
# Idempotency:
#   - If the target repo already exists on GitHub, the script clones it
#     instead of creating a new one.
#   - If the checkout has no changes after reconciliation, no commit is created.
#   - DNS CNAME setup remains operator-action (DNS provider varies); the
#     script includes the generated `CNAME` in the push during `--commit`.
#   - Only known generated files are reconciled in an existing checkout;
#     unrelated files, source and git history are preserved.
#   - Pending changes outside that ownership set refuse delivery before rendering
#     or reconciling the checkout. Resolve them separately before retrying.
#
# References:
#   - docs/governance/citable-nexus-bootstrap-status.md (historical bootstrap status)
#   - scripts/build_citable_nexus.py (the renderer this script wraps)
#   - docs/citable-nexus/github-actions-deploy.yml.template
#   - docs/citable-nexus/CNAME.template

set -euo pipefail

# ── Defaults (operator-overridable) ──────────────────────────────────

REPO_OWNER="${HAPAX_NEXUS_REPO_OWNER:-hapax-systems}"
REPO_NAME="${HAPAX_NEXUS_REPO_NAME:-hapax-research}"
REPO_DESCRIPTION="${HAPAX_NEXUS_REPO_DESC:-Citable nexus for Hapax / Oudepode published artifacts}"
# The canonical host is an explicit build input: no default names a domain. The
# renderer refuses to build without it (build_citable_nexus.py --canonical-url).
DOMAIN="${HAPAX_NEXUS_DOMAIN:?set HAPAX_NEXUS_DOMAIN to the canonical host (no default is assumed)}"
CANONICAL_URL="https://${DOMAIN}"
REPO_HOMEPAGE="${HAPAX_NEXUS_REPO_HOMEPAGE:-${CANONICAL_URL}}"
CLEARED_INPUTS="${HAPAX_NEXUS_CLEARED_INPUTS:-}"

WORK_DIR="${HAPAX_NEXUS_WORK_DIR:-$HOME/.cache/hapax/citable-nexus-bootstrap}"
COUNCIL_REPO="${HAPAX_COUNCIL_REPO:-$HOME/projects/hapax-council}"
REPO_FULL="${REPO_OWNER}/${REPO_NAME}"
REPO_DIR="${WORK_DIR}/${REPO_NAME}"

# Keep this finite ownership set aligned with build_citable_nexus.py's routes.
GENERATED_FILES=(
    index.html cite/index.html 404.html
    manifesto/index.html refusal-brief/index.html
    deposits/index.html citation-graph/index.html
    refuse/index.html surfaces/index.html
    rss.xml CNAME .github/workflows/deploy.yml
)

DRY_RUN=true
ENABLE_PAGES=true

if [[ "${REPO_OWNER}" != "hapax-systems" ]]; then
    echo "bootstrap_citable_nexus_repo.sh: refusing owner '${REPO_OWNER}'; Hapax repositories must live under hapax-systems" >&2
    exit 2
fi

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
        printf '  DRY-RUN:'
        printf ' %q' "$@"
        printf '\n'
    else
        "$@"
    fi
}

refuse_unrelated_changes() {
    local status entry path generated owned unrelated_count=0
    # Quoted porcelain paths stay on one line even with embedded newlines.
    # Disable rename folding so both sides are checked; enumerate untracked
    # files individually, including unrelated files within generated routes.
    if ! status="$(cd "${REPO_DIR}" && git --no-optional-locks -c core.quotePath=true status \
        --porcelain=v1 --untracked-files=all --ignore-submodules=none --no-renames)"; then
        log "Refusing delivery: checkout status could not be read. Next action: repair the publishing checkout and retry."
        exit 2
    fi
    while IFS= read -r entry; do
        [[ -n "${entry}" ]] || continue
        path="${entry:3}"
        owned=false
        for generated in "${GENERATED_FILES[@]}"; do
            if [[ "${path}" == "${generated}" ]]; then
                owned=true
                break
            fi
        done
        if [[ "${owned}" == "false" ]]; then
            unrelated_count=$((unrelated_count + 1))
        fi
    done <<< "${status}"
    if (( unrelated_count > 0 )); then
        log "Refusing delivery: ${unrelated_count} unrelated changed path(s). Next action: resolve those pending changes separately in the publishing checkout, then retry."
        exit 2
    fi
}

# Refuse an existing dirty checkout before any render or remote action.
if [[ "${DRY_RUN}" == "false" && -d "${REPO_DIR}" ]]; then
    refuse_unrelated_changes
fi

# ── Phase 1: render the site ─────────────────────────────────────────

log "Rendering the site via build_citable_nexus.py (canonical ${CANONICAL_URL})..."
RENDER_DIR="${WORK_DIR}/render"
mkdir -p "${RENDER_DIR}"
(
    cd "${COUNCIL_REPO}"
    # The renderer writes the pages, 404.html, the generated CNAME (from the
    # template and the canonical host) and a feed only when cleared entries exist;
    # only explicitly cleared inputs are rendered (none by default).
    uv run python scripts/build_citable_nexus.py \
        --out "${RENDER_DIR}" \
        --canonical-url "${CANONICAL_URL}" \
        ${CLEARED_INPUTS:+--cleared-inputs "${CLEARED_INPUTS}"}
)
log "Render complete: $(find "${RENDER_DIR}" -name '*.html' | wc -l) pages under ${RENDER_DIR}"

# Drop the workflow template into the render dir so the push below copies it
# into the new repo. The CNAME is already generated by the renderer.
log "Copying workflow template into render dir..."
mkdir -p "${RENDER_DIR}/.github/workflows"
cp "${COUNCIL_REPO}/docs/citable-nexus/github-actions-deploy.yml.template" \
    "${RENDER_DIR}/.github/workflows/deploy.yml"

# ── Phase 2: create or clone the GitHub repo ─────────────────────────

if gh repo view "${REPO_FULL}" >/dev/null 2>&1; then
    log "Repo ${REPO_FULL} already exists; cloning if not present locally."
    if [[ ! -d "${REPO_DIR}" ]]; then
        run gh repo clone "${REPO_FULL}" "${REPO_DIR}"
    fi
else
    log "Repo ${REPO_FULL} does NOT exist; creating."
    run gh repo create "${REPO_FULL}" \
        --public \
        --description "${REPO_DESCRIPTION}" \
        --homepage "${REPO_HOMEPAGE}"
    if [[ "${DRY_RUN}" == "false" ]]; then
        gh repo clone "${REPO_FULL}" "${REPO_DIR}"
    fi
fi

# ── Phase 3: copy rendered site into the repo + commit ──────────────

if [[ "${DRY_RUN}" == "false" && -d "${REPO_DIR}" ]]; then
    # Check a newly cloned checkout too, or changes since the initial preflight.
    refuse_unrelated_changes
    log "Reconciling generated files in ${REPO_DIR}..."
    # The delivery boundary needs its own cleanup: a clean render directory
    # does not remove pages/feed copied by a previous bootstrap. Keep this
    # finite ownership set above aligned with build_citable_nexus.py's routes.
    for generated in "${GENERATED_FILES[@]}"; do
        if [[ -f "${RENDER_DIR}/${generated}" ]]; then
            mkdir -p "$(dirname "${REPO_DIR}/${generated}")"
            cp "${RENDER_DIR}/${generated}" "${REPO_DIR}/${generated}"
        else
            rm -f "${REPO_DIR}/${generated}"
        fi
    done
    cd "${REPO_DIR}"
    if [[ -n "$(git status --porcelain)" ]]; then
        git add -A
        git commit -m "feat: renderer-emitted citable-nexus front door

Bootstrap commit from hapax-council:scripts/bootstrap_citable_nexus_repo.sh.
Source: hapax-council; renderer: agents/citable_nexus/.

This commit ships what the renderer emitted for ${CANONICAL_URL}:
  - the home and cite pages and an honest 404.html
  - any explicitly cleared documents (none unless a cleared-inputs file was supplied)
  - a feed only when cleared entries exist
  - CNAME for ${DOMAIN}
  - .github/workflows/deploy.yml (rebuild template; canonical-URL repository variable still requires configuration)"
        git push origin main
        log "Pushed rendered site to ${REPO_FULL}"
    else
        log "Site is already up to date in ${REPO_FULL}; no commit needed."
    fi
fi

# ── Phase 4: enable GitHub Pages ─────────────────────────────────────

if [[ "${ENABLE_PAGES}" == "true" ]]; then
    log "Enabling GitHub Pages on ${REPO_FULL}..."
    # gh CLI does not have a direct `pages enable` subcommand; use the API.
    run gh api -X POST \
        -H 'Accept: application/vnd.github+json' \
        "/repos/${REPO_FULL}/pages" \
        -f 'source[branch]=main' \
        -f 'source[path]=/' \
        || log 'Pages request failed; inspect the Pages API response before claiming it is enabled.'
fi

# ── Phase 5: DNS instructions (operator-action) ──────────────────────

cat <<EOF

[bootstrap-citable-nexus] Operator-action remaining:

  1. DNS CNAME: add a CNAME record at your DNS provider:
       ${DOMAIN} → ${REPO_OWNER}.github.io

  2. Verify GitHub Pages picks up the CNAME file:
       gh api /repos/${REPO_FULL}/pages

  3. Check certificate provisioning in Pages settings before testing HTTPS.

  4. Smoke-test the site:
       curl -sI https://${DOMAIN}/ | head -1     # expect HTTP/2 200
       curl -s  https://${DOMAIN}/cite | head -3
       curl -sI https://${DOMAIN}/no-such-page | head -1   # expect 404 (honest error page)

  5. Configure the copied .github/workflows/deploy.yml rebuild template:
       gh variable set HAPAX_CITABLE_NEXUS_CANONICAL_URL --repo ${REPO_FULL} --body ${CANONICAL_URL}
     The template builds committed home/cite/404 pages with no optional cleared
     inputs. A bootstrap-only cleared-inputs list is not supplied to that workflow.

  6. After verifying the actual deployment, update upstream pointers to
     ${CANONICAL_URL}/ and ${CANONICAL_URL}/cite as appropriate.
     The default build does not include /refuse; do not direct readers there.

  7. Record the verified URL, emitted routes and deployment evidence in current
     status documentation. Script completion alone does not establish a live site.

  Default mode renders locally and queries repository existence; --commit also
  copies, commits and pushes CNAME with the site. DNS is always operator action.
  --no-pages skips the Pages API request; it does not configure another host.

EOF

log "Bootstrap script complete (mode: $([ "${DRY_RUN}" = "true" ] && echo dry-run || echo commit))."
