#!/usr/bin/env bash
# Restore PostgreSQL and MinIO from an archive created by backup.sh.
# A failed restore intentionally leaves public/application containers stopped.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=infra/scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

usage() {
  printf '%s\n' "Usage: bash infra/scripts/restore.sh --archive <file> --confirm 'RESTORE <archive-name>' [--dry-run] [--env-file <path>]"
}

archive=""
confirmation=""
dry_run=false

while (($#)); do
  case "$1" in
    --archive)
      (($# >= 2)) || ar_die "--archive requires a file"
      archive="$2"
      shift 2
      ;;
    --confirm)
      (($# >= 2)) || ar_die "--confirm requires the confirmation phrase"
      confirmation="$2"
      shift 2
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    --env-file)
      (($# >= 2)) || ar_die "--env-file requires a path"
      # shellcheck disable=SC2034 # Consumed by functions sourced from lib.sh.
      AR_ENV_FILE="$2"
      shift 2
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

[[ -f "$archive" && -r "$archive" ]] || ar_die "archive is missing or unreadable: $archive"
archive_name="$(basename -- "$archive")"
[[ "$confirmation" == "RESTORE $archive_name" ]] ||
  ar_die "confirmation must be exactly: RESTORE $archive_name"

ar_require_command docker
ar_require_command flock
ar_require_command tar
ar_require_command sha256sum
ar_require_command mktemp
ar_assert_secure_env_file
ar_validate_pinned_infrastructure_images
ar_load_release_version
ar_compose config -q

state_dir="$(dirname -- "$AR_RELEASE_STATE_FILE")"
install -d -m 0700 "$state_dir"
exec 9>"$state_dir/operation.lock"
flock -n 9 || ar_die "another deploy, backup, or restore operation is already running"

work="$(mktemp -d "$state_dir/.restore.XXXXXX")"
cleanup() {
  rm -rf -- "$work"
}
trap cleanup EXIT

while IFS= read -r entry; do
  [[ "$entry" != /* && "$entry" != ".." && "$entry" != ../* && "$entry" != */../* ]] ||
    ar_die "archive has an unsafe path: $entry"
done < <(tar -tzf "$archive")

tar -xzf "$archive" -C "$work"
[[ -f "$work/database.dump" && -f "$work/metadata.json" && -f "$work/manifest.sha256" && -d "$work/minio" ]] ||
  ar_die "archive does not have the expected backup layout"
(
  cd -- "$work"
  sha256sum --check manifest.sha256
)

if "$dry_run"; then
  ar_log "archive verified successfully; dry-run finished before stopping services"
  exit 0
fi

ar_log "starting data services and stopping public/application traffic"
ar_compose up -d postgres valkey minio mailpit
ar_wait_for_healthy postgres 180
ar_wait_for_healthy valkey 180
ar_wait_for_healthy minio 180
ar_compose stop caddy web api worker-ingest worker-enrichment || true

ar_restore_data_plane "$work"

ar_log "applying current release migrations and restarting services"
ar_compose up -d minio-init migrate
ar_wait_for_completed minio-init 180
ar_wait_for_completed migrate 180
ar_compose up -d web api worker-ingest worker-enrichment caddy
ar_wait_for_healthy web 180
ar_wait_for_healthy api 180
ar_wait_for_healthy worker-ingest 180
ar_wait_for_healthy worker-enrichment 180
ar_wait_for_healthy caddy 180

ar_log "restore completed successfully"
