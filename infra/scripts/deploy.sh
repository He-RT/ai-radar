#!/usr/bin/env bash
# Deploy previously published, digest-pinned images. Run as the restricted radar-deploy user.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=infra/scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

usage() {
  printf '%s\n' "Usage: bash infra/scripts/deploy.sh --version <release-version> --source-sha <40-hex-commit> --web-image-digest <sha256:...> --api-image-digest <sha256:...> --worker-image-digest <sha256:...> [--env-file <path>] [--with-observability] [--dry-run]"
}

version=""
source_sha=""
web_image_digest=""
api_image_digest=""
worker_image_digest=""
with_observability=false
dry_run=false

while (($#)); do
  case "$1" in
    --version)
      (($# >= 2)) || ar_die "--version requires a value"
      version="$2"
      shift 2
      ;;
    --source-sha)
      (($# >= 2)) || ar_die "--source-sha requires a value"
      source_sha="$2"
      shift 2
      ;;
    --web-image-digest)
      (($# >= 2)) || ar_die "--web-image-digest requires a value"
      web_image_digest="$2"
      shift 2
      ;;
    --api-image-digest)
      (($# >= 2)) || ar_die "--api-image-digest requires a value"
      api_image_digest="$2"
      shift 2
      ;;
    --worker-image-digest)
      (($# >= 2)) || ar_die "--worker-image-digest requires a value"
      worker_image_digest="$2"
      shift 2
      ;;
    --env-file)
      (($# >= 2)) || ar_die "--env-file requires a path"
      AR_ENV_FILE="$2"
      shift 2
      ;;
    --with-observability)
      with_observability=true
      shift
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      ar_die "unknown argument: $1"
      ;;
  esac
done

[[ -n "$version" ]] || {
  usage >&2
  ar_die "--version is required"
}
[[ -n "$source_sha" ]] || ar_die "--source-sha is required"
[[ -n "$web_image_digest" ]] || ar_die "--web-image-digest is required"
[[ -n "$api_image_digest" ]] || ar_die "--api-image-digest is required"
[[ -n "$worker_image_digest" ]] || ar_die "--worker-image-digest is required"
(( EUID != 0 )) || ar_die "refusing to run as root; use the dedicated radar-deploy account"

ar_require_command git
ar_validate_source_sha "$source_sha"
ar_assert_checkout_source "$source_sha"
ar_require_command docker
ar_require_command flock
ar_require_command install
ar_require_command mktemp
ar_assert_secure_env_file
ar_validate_pinned_infrastructure_images
ar_validate_image_tag "$version"
ar_validate_image_digest "$web_image_digest"
ar_validate_image_digest "$api_image_digest"
ar_validate_image_digest "$worker_image_digest"
[[ -f "$AR_PRODUCTION_COMPOSE" ]] || ar_die "production Compose file not found: $AR_PRODUCTION_COMPOSE"

export APP_VERSION="$version"
export WEB_IMAGE_DIGEST="$web_image_digest"
export API_IMAGE_DIGEST="$api_image_digest"
export WORKER_IMAGE_DIGEST="$worker_image_digest"
if "$with_observability"; then
  AR_COMPOSE_PROFILES+=(--profile observability)
fi

# Render before touching a running stack. Compose interpolation sees the exported version.
ar_compose config -q

if "$dry_run"; then
  ar_log "Compose rendered successfully; dry-run finished without pulling or restarting containers"
  exit 0
fi

state_dir="$(dirname -- "$AR_RELEASE_STATE_FILE")"
install -d -m 0700 "$state_dir"
exec 9>"$state_dir/operation.lock"
flock -n 9 || ar_die "another deploy, backup, or restore operation is already running"

wait_seconds="$(grep -E '^DEPLOY_WAIT_SECONDS=[0-9]+$' "$AR_ENV_FILE" | tail -n 1 | cut -d= -f2 || true)"
wait_seconds="${wait_seconds:-180}"
[[ "$wait_seconds" =~ ^[0-9]+$ ]] || ar_die "DEPLOY_WAIT_SECONDS must be a positive integer"
(( wait_seconds > 0 )) || ar_die "DEPLOY_WAIT_SECONDS must be greater than zero"

ar_log "pulling release $version"
ar_compose pull caddy postgres valkey minio minio-init mailpit web api worker-ingest worker-enrichment

ar_log "starting stateful dependencies"
ar_compose up -d postgres valkey minio mailpit
ar_wait_for_healthy postgres "$wait_seconds"
ar_wait_for_healthy valkey "$wait_seconds"
ar_wait_for_healthy minio "$wait_seconds"
ar_wait_for_healthy mailpit "$wait_seconds"

ar_log "initializing object-storage bucket"
ar_compose up -d minio-init
ar_wait_for_completed minio-init "$wait_seconds"

ar_log "running database migration"
ar_compose up -d migrate
ar_wait_for_completed migrate "$wait_seconds"

ar_log "starting application services"
ar_compose up -d web api worker-ingest worker-enrichment caddy
ar_wait_for_healthy web "$wait_seconds"
ar_wait_for_healthy api "$wait_seconds"
ar_wait_for_healthy worker-ingest "$wait_seconds"
ar_wait_for_healthy worker-enrichment "$wait_seconds"
ar_wait_for_healthy caddy "$wait_seconds"

if "$with_observability"; then
  ar_log "starting local-only observability services"
  ar_compose up -d prometheus grafana loki promtail node-exporter
fi

ar_write_release_state "$version" "$web_image_digest" "$api_image_digest" "$worker_image_digest" "$source_sha"
ar_compose ps
ar_log "release $version from source $source_sha deployed successfully"
