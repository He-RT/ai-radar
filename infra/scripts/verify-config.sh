#!/usr/bin/env bash
# Render infrastructure configuration without starting containers.

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
environment_file="$REPO_ROOT/infra/env/ci.env"
compose_file="$REPO_ROOT/infra/compose/compose.production.yml"

if [[ "${1:-}" == "--development" ]]; then
  compose_file="$REPO_ROOT/infra/compose/compose.development.yml"
fi

command -v docker >/dev/null 2>&1 || {
  printf '%s\n' "ERROR: docker compose is required for this check" >&2
  exit 1
}

AR_ENV_FILE="$environment_file"
# shellcheck source=infra/scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"
ar_validate_pinned_infrastructure_images

docker compose --env-file "$environment_file" -f "$compose_file" config -q
printf 'Compose configuration is valid: %s\n' "$compose_file"
