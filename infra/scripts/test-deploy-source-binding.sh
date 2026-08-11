#!/usr/bin/env bash
# Regression checks for the forced-command parser and source-bound release state.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
GATE="$SCRIPT_DIR/ssh-deploy-gate.sh"
LIB="$SCRIPT_DIR/lib.sh"

# shellcheck source=infra/scripts/ssh-deploy-gate.sh
source "$GATE"

version="v1.2.3"
source_sha="0123456789abcdef0123456789abcdef01234567"
web_digest="sha256:1111111111111111111111111111111111111111111111111111111111111111"
api_digest="sha256:2222222222222222222222222222222222222222222222222222222222222222"
worker_digest="sha256:3333333333333333333333333333333333333333333333333333333333333333"
valid_command="deploy --version $version --source-sha $source_sha --web-image-digest $web_digest --api-image-digest $api_digest --worker-image-digest $worker_digest"

ar_parse_forced_deploy_command "$valid_command" || {
  printf '%s\n' "ERROR: gate rejected the valid fixed-order command" >&2
  exit 1
}
[[ "$release_version" == "$version" ]]
[[ "$source_sha" == "0123456789abcdef0123456789abcdef01234567" ]]
[[ "$web_image_digest" == "$web_digest" ]]
[[ "$api_image_digest" == "$api_digest" ]]
[[ "$worker_image_digest" == "$worker_digest" ]]

expect_denied() {
  if ar_parse_forced_deploy_command "$1"; then
    printf 'ERROR: gate parser accepted unsafe command: %s\n' "$1" >&2
    exit 1
  fi
}

expect_denied " $valid_command"
expect_denied "$valid_command "
expect_denied "deploy --version $version --web-image-digest $web_digest --api-image-digest $api_digest --worker-image-digest $worker_digest"
expect_denied "deploy --version $version --source-sha 0123456789abcdef0123456789abcdef0123456 --web-image-digest $web_digest --api-image-digest $api_digest --worker-image-digest $worker_digest"
expect_denied "deploy --version $version --source-sha 0123456789ABCDEF0123456789ABCDEF01234567 --web-image-digest $web_digest --api-image-digest $api_digest --worker-image-digest $worker_digest"
expect_denied "deploy --version $version --source-sha $source_sha --api-image-digest $api_digest --web-image-digest $web_digest --worker-image-digest $worker_digest"
expect_denied "$valid_command; /usr/bin/id"
expect_denied 'deploy --version $(id) --source-sha 0123456789abcdef0123456789abcdef01234567 --web-image-digest sha256:1111111111111111111111111111111111111111111111111111111111111111 --api-image-digest sha256:2222222222222222222222222222222222222222222222222222222222222222 --worker-image-digest sha256:3333333333333333333333333333333333333333333333333333333333333333'
expect_denied $'deploy --version v1.2.3 --source-sha 0123456789abcdef0123456789abcdef01234567 --web-image-digest sha256:1111111111111111111111111111111111111111111111111111111111111111 --api-image-digest sha256:2222222222222222222222222222222222222222222222222222222222222222 --worker-image-digest sha256:3333333333333333333333333333333333333333333333333333333333333333\n/usr/bin/id'

set +e
gate_output="$(SSH_ORIGINAL_COMMAND="$valid_command; /usr/bin/id" bash "$GATE" 2>&1)"
gate_status=$?
set -e
[[ "$gate_status" == "64" ]]
[[ "$gate_output" == Denied:* ]]

temporary="$(mktemp -d)"
cleanup() {
  rm -rf -- "$temporary"
}
trap cleanup EXIT

# shellcheck source=infra/scripts/lib.sh
source "$LIB"

checkout_source_sha="$(git -c safe.directory="$AR_REPO_ROOT" -C "$AR_REPO_ROOT" rev-parse --verify 'HEAD^{commit}')"
ar_assert_checkout_source "$checkout_source_sha"
set +e
mismatch_output="$(bash -c 'source "$1"; ar_assert_checkout_source "$2"' \
  _ "$LIB" "0000000000000000000000000000000000000000" 2>&1)"
mismatch_status=$?
set -e
[[ "$mismatch_status" == "1" ]]
[[ "$mismatch_output" == *"controlled root-owned checkout procedure"* ]]

old_state="$temporary/old-release.env"
printf '%s\n' \
  "APP_VERSION=$version" \
  "WEB_IMAGE_DIGEST=$web_digest" \
  "API_IMAGE_DIGEST=$api_digest" \
  "WORKER_IMAGE_DIGEST=$worker_digest" \
  >"$old_state"
AR_RELEASE_STATE_FILE="$old_state"
ar_load_release_version
[[ "$SOURCE_SHA" == "" ]]

new_state="$temporary/new-release.env"
AR_RELEASE_STATE_FILE="$new_state"
ar_write_release_state "$version" "$web_digest" "$api_digest" "$worker_digest" \
  "0123456789abcdef0123456789abcdef01234567"
ar_load_release_version
[[ "$SOURCE_SHA" == "0123456789abcdef0123456789abcdef01234567" ]]

printf 'SOURCE_SHA=%s; /usr/bin/id\n' "0123456789abcdef0123456789abcdef01234567" >>"$old_state"
if AR_RELEASE_STATE_FILE="$old_state" bash -c 'source "$1"; ar_load_release_version' _ "$LIB" >/dev/null 2>&1; then
  printf '%s\n' "ERROR: release-state loader accepted an injected SOURCE_SHA line" >&2
  exit 1
fi

printf '%s\n' "Deploy source-binding regression checks passed"
