#!/usr/bin/env bash
# Forced command for the GitHub Actions deployment key.
# It accepts exactly one fixed-order source-bound release identity and three image digests.

ar_parse_forced_deploy_command() {
  local command="$1"

  if [[ "$command" =~ ^deploy\ --version\ ([A-Za-z0-9][A-Za-z0-9._-]{0,127})\ --source-sha\ ([a-f0-9]{40})\ --web-image-digest\ (sha256:[a-f0-9]{64})\ --api-image-digest\ (sha256:[a-f0-9]{64})\ --worker-image-digest\ (sha256:[a-f0-9]{64})$ ]]; then
    release_version="${BASH_REMATCH[1]}"
    source_sha="${BASH_REMATCH[2]}"
    web_image_digest="${BASH_REMATCH[3]}"
    api_image_digest="${BASH_REMATCH[4]}"
    worker_image_digest="${BASH_REMATCH[5]}"
    return 0
  fi

  return 1
}

# Allow the parser to be sourced by the injection regression test without
# opening a test-only path through the SSH forced command itself.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi

set -Eeuo pipefail
IFS=$'\n\t'

readonly DEPLOY_ROOT="/opt/amplitude-radar"
readonly original_command="${SSH_ORIGINAL_COMMAND:-}"

if ar_parse_forced_deploy_command "$original_command"; then
  exec /usr/bin/env -i \
    HOME="$HOME" \
    USER="${USER:-radar-deploy}" \
    LOGNAME="${LOGNAME:-radar-deploy}" \
    PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    /usr/bin/bash "$DEPLOY_ROOT/infra/scripts/deploy.sh" \
      --version "$release_version" \
      --source-sha "$source_sha" \
      --web-image-digest "$web_image_digest" \
      --api-image-digest "$api_image_digest" \
      --worker-image-digest "$worker_image_digest"
fi

printf '%s\n' "Denied: this deployment key accepts only the fixed deploy command with a version, exact lowercase 40-hex source SHA, and web/API/worker sha256 digests." >&2
exit 64
