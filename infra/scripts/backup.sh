#!/usr/bin/env bash
# Create an application-consistent PostgreSQL + MinIO backup archive.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=infra/scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

usage() {
  printf '%s\n' "Usage: bash infra/scripts/backup.sh [--output <directory>] [--retain-days <days>] [--env-file <path>]"
}

backup_dir="/var/backups/amplitude-radar"
retain_days=""
while (($#)); do
  case "$1" in
    --output)
      (($# >= 2)) || ar_die "--output requires a directory"
      backup_dir="$2"
      shift 2
      ;;
    --retain-days)
      (($# >= 2)) || ar_die "--retain-days requires a number"
      retain_days="$2"
      shift 2
      ;;
    --env-file)
      (($# >= 2)) || ar_die "--env-file requires a path"
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

ar_require_command docker
ar_require_command flock
ar_require_command tar
ar_require_command sha256sum
ar_require_command mktemp
ar_assert_secure_env_file
ar_validate_pinned_infrastructure_images
ar_load_release_version
ar_compose config -q

if [[ -z "$retain_days" ]]; then
  retain_days="$(grep -E '^BACKUP_RETENTION_DAYS=[0-9]+$' "$AR_ENV_FILE" | tail -n 1 | cut -d= -f2 || true)"
  retain_days="${retain_days:-14}"
fi
[[ "$retain_days" =~ ^[0-9]+$ ]] || ar_die "retention must be a non-negative integer"

install -d -m 0700 "$backup_dir"
exec 9>"$(dirname -- "$AR_RELEASE_STATE_FILE")/operation.lock"
flock -n 9 || ar_die "another deploy, backup, or restore operation is already running"

stage="$(mktemp -d "$backup_dir/.staging.XXXXXX")"
cleanup() {
  rm -rf -- "$stage"
}
trap cleanup EXIT

timestamp="$(date -u +'%Y%m%dT%H%M%SZ')"
archive="$backup_dir/amplitude-radar-$timestamp-$APP_VERSION.tar.gz"
partial="$archive.partial"
mkdir -p "$stage/minio"

ar_log "exporting PostgreSQL"
ar_compose exec -T postgres /bin/sh -ec \
  'exec pg_dump --format=custom --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  >"$stage/database.dump"

ar_log "mirroring MinIO bucket to staging"
export BACKUP_STAGING_DIR="$stage"
ar_compose_profile maintenance run --rm --no-deps minio-client \
  'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"; mc mirror --overwrite "local/$MINIO_BUCKET" /backup/minio'

printf '{\n  "created_at": "%s",\n  "app_version": "%s",\n  "format": "pg_dump custom + minio mirror"\n}\n' \
  "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$APP_VERSION" >"$stage/metadata.json"

(
  cd -- "$stage"
  sha256sum database.dump metadata.json >manifest.sha256
  while IFS= read -r -d '' object; do
    sha256sum "$object" >>manifest.sha256
  done < <(find minio -type f -print0 | sort -z)
)

tar -C "$stage" -czf "$partial" database.dump minio metadata.json manifest.sha256
mv -f -- "$partial" "$archive"
chmod 0600 "$archive"

while IFS= read -r -d '' expired; do
  rm -f -- "$expired"
done < <(find "$backup_dir" -maxdepth 1 -type f -name 'amplitude-radar-*.tar.gz' -mtime "+$retain_days" -print0)

ar_log "backup completed: $archive"
