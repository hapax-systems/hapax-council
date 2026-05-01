#!/usr/bin/env bash
# configure-orcid.sh — write HAPAX_OPERATOR_ORCID to ~/.config/hapax/datacite-mirror.env
#
# Per cc-task `orcid-config-write-automation`. Single-line config write that
# unblocks the DataCite mirror nightly fire (and downstream consumers
# `orcid-verifier-audit-report` + `datacite-citation-graph-refresh-diff-publish`).
#
# Usage:
#   scripts/configure-orcid.sh 0009-0001-5146-4548
#   HAPAX_OPERATOR_ORCID=0009-0001-5146-4548 scripts/configure-orcid.sh
#
# The env-var path is wired via shared.orcid.operator_orcid() which checks
# $HAPAX_OPERATOR_ORCID first and falls back to `pass show orcid/orcid` —
# this script's env-file write becomes load-bearing once the systemd unit
# loads it (or the operator sources it from a shell).
#
# Idempotent: re-running with the same iD is a no-op; re-running with a
# different iD updates the line in place.

set -euo pipefail

ORCID_REGEX='^[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]$'
ENV_FILE="${HOME}/.config/hapax/datacite-mirror.env"

orcid_id="${1:-${HAPAX_OPERATOR_ORCID:-}}"

if [[ -z "${orcid_id}" ]]; then
    echo "configure-orcid.sh: ORCID iD required as positional arg or HAPAX_OPERATOR_ORCID env var" >&2
    echo "  usage: $0 NNNN-NNNN-NNNN-NNNN" >&2
    exit 2
fi

if ! [[ "${orcid_id}" =~ ${ORCID_REGEX} ]]; then
    echo "configure-orcid.sh: invalid ORCID iD format '${orcid_id}'" >&2
    echo "  expected: NNNN-NNNN-NNNN-NNN[N|X]" >&2
    exit 2
fi

mkdir -p "$(dirname "${ENV_FILE}")"

# Idempotent write: if the file already has the same line, no-op (preserves mtime).
desired_line="HAPAX_OPERATOR_ORCID=${orcid_id}"
if [[ -f "${ENV_FILE}" ]] && grep -qxF "${desired_line}" "${ENV_FILE}"; then
    echo "configure-orcid.sh: ${ENV_FILE} already has ${desired_line}; no-op"
    exit 0
fi

# Otherwise: drop any prior HAPAX_OPERATOR_ORCID= line and append the new one
# atomically via a tmp file.
tmp="$(mktemp "${ENV_FILE}.XXXXXX")"
if [[ -f "${ENV_FILE}" ]]; then
    grep -v '^HAPAX_OPERATOR_ORCID=' "${ENV_FILE}" >"${tmp}" || true
fi
echo "${desired_line}" >>"${tmp}"
chmod 600 "${tmp}"
mv "${tmp}" "${ENV_FILE}"

echo "configure-orcid.sh: wrote ${desired_line} to ${ENV_FILE}"
echo "configure-orcid.sh: shared.orcid.operator_orcid() will resolve via this env var"
echo "configure-orcid.sh: if the systemd unit is loaded, restart it to pick up the new value:"
echo "  systemctl --user restart hapax-datacite-mirror.service"
