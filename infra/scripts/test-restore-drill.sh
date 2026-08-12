#!/usr/bin/env bash
# Destructive data-plane restore rehearsal in an isolated Compose project with
# disposable volumes. Dummy application image digests intentionally mean this
# drill does not cover app-image migration, service startup, or readiness.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
COMPOSE_FILE="$REPO_ROOT/infra/compose/compose.production.yml"
if ! command -v flock >/dev/null 2>&1 && command -v brew >/dev/null 2>&1; then
  util_linux_prefix="$(brew --prefix util-linux 2>/dev/null || true)"
  if [[ -n "$util_linux_prefix" && -x "$util_linux_prefix/bin/flock" ]]; then
    PATH="$util_linux_prefix/bin:$PATH"
    export PATH
  fi
fi
command -v flock >/dev/null 2>&1 || {
  printf '%s\n' 'ERROR: flock is required (on macOS: brew install util-linux)' >&2
  exit 1
}
# Keep bind-mounted drill files under the workspace so Docker Desktop/Colima
# can expose them consistently on macOS as well as Linux.
temporary="$(mktemp -d "$REPO_ROOT/.restore-drill.XXXXXX")"
project="radar-restore-drill-$$"
environment_file="$temporary/app.env"
state_file="$temporary/release.env"
backup_dir="$temporary/backups"
restore_work="$temporary/restore-work"

cp "$REPO_ROOT/infra/env/ci.env" "$environment_file"
chmod 0600 "$environment_file"
# Deliberately retain the legacy four-line format to exercise backward-compatible loading.
printf '%s\n' \
  'APP_VERSION=restore-drill' \
  'WEB_IMAGE_DIGEST=sha256:1111111111111111111111111111111111111111111111111111111111111111' \
  'API_IMAGE_DIGEST=sha256:2222222222222222222222222222222222222222222222222222222222222222' \
  'WORKER_IMAGE_DIGEST=sha256:3333333333333333333333333333333333333333333333333333333333333333' \
  >"$state_file"
chmod 0600 "$state_file"

AR_PROJECT="$project"
AR_ENV_FILE="$environment_file"
AR_RELEASE_STATE_FILE="$state_file"
AR_PRODUCTION_COMPOSE="$COMPOSE_FILE"
export AR_PROJECT AR_ENV_FILE AR_RELEASE_STATE_FILE AR_PRODUCTION_COMPOSE
# shellcheck source=infra/scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

compose=(
  docker compose
  --project-name "$project"
  --env-file "$environment_file"
  -f "$COMPOSE_FILE"
)

cleanup() {
  "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf -- "$temporary"
}
trap cleanup EXIT

wait_for_health() {
  local service="$1"
  local container_id status=""
  local attempts=0
  while (( attempts < 90 )); do
    attempts=$((attempts + 1))
    container_id="$("${compose[@]}" ps -q "$service")"
    if [[ -n "$container_id" ]]; then
      status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")"
      [[ "$status" == "healthy" ]] && return 0
    fi
    sleep 1
  done
  printf 'ERROR: %s did not become healthy (last state: %s)\n' "$service" "$status" >&2
  return 1
}

"${compose[@]}" up -d postgres valkey minio mailpit >/dev/null
for service in postgres valkey minio mailpit; do
  wait_for_health "$service"
done
"${compose[@]}" up minio-init >/dev/null

"${compose[@]}" exec -T postgres sh -ec '
  export PGPASSWORD="$POSTGRES_MIGRATION_PASSWORD"
  psql -h 127.0.0.1 -U "$POSTGRES_MIGRATION_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
    -c "CREATE TABLE restore_probe (id integer PRIMARY KEY, value text NOT NULL)" \
    -c "INSERT INTO restore_probe VALUES (1, '\''original'\'')"
'

mkdir -p "$temporary/object-source"
printf 'original-object\n' >"$temporary/object-source/probe.txt"
BACKUP_STAGING_DIR="$temporary/object-source" "${compose[@]}" --profile maintenance \
  run --rm --no-deps minio-client \
  'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null; mc pipe "local/$MINIO_BUCKET/probe.txt" </backup/probe.txt >/dev/null' \
  >/dev/null

bash "$SCRIPT_DIR/backup.sh" --output "$backup_dir" --retain-days 0 >/dev/null
archive="$(find "$backup_dir" -maxdepth 1 -name 'amplitude-radar-*.tar.gz' -print -quit)"
[[ -n "$archive" ]]

"${compose[@]}" exec -T postgres sh -ec '
  export PGPASSWORD="$POSTGRES_MIGRATION_PASSWORD"
  psql -h 127.0.0.1 -U "$POSTGRES_MIGRATION_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
    -c "UPDATE restore_probe SET value = '\''mutated'\'' WHERE id = 1"
' >/dev/null
printf 'mutated-object\n' >"$temporary/object-source/probe.txt"
BACKUP_STAGING_DIR="$temporary/object-source" "${compose[@]}" --profile maintenance \
  run --rm --no-deps minio-client \
  'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null; mc pipe "local/$MINIO_BUCKET/probe.txt" </backup/probe.txt >/dev/null' \
  >/dev/null

bash "$SCRIPT_DIR/restore.sh" --archive "$archive" \
  --confirm "RESTORE $(basename -- "$archive")" --dry-run >/dev/null

mkdir -p "$restore_work"
tar -xzf "$archive" -C "$restore_work"
ar_restore_data_plane "$restore_work" >/dev/null

database_value="$("${compose[@]}" exec -T postgres sh -ec '
  export PGPASSWORD="$POSTGRES_APP_PASSWORD"
  psql -h 127.0.0.1 -U "$POSTGRES_APP_USER" -d "$POSTGRES_DB" -Atqc \
    "SELECT value FROM restore_probe WHERE id = 1"
')"
mkdir -p "$temporary/object-verify"
BACKUP_STAGING_DIR="$temporary/object-verify" "${compose[@]}" --profile maintenance \
  run --rm --no-deps minio-client \
  'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null; mc cat "local/$MINIO_BUCKET/probe.txt" >/backup/restored.txt' \
  >/dev/null
object_value="$(tr -d '\r\n' <"$temporary/object-verify/restored.txt")"

[[ "$database_value" == "original" ]]
[[ "$object_value" == "original-object" ]]
printf 'Restore data-plane drill passed: database=%s object=%s archive=%s\n' \
  "$database_value" "$object_value" "$(basename -- "$archive")"
printf '%s\n' 'Coverage is limited to PostgreSQL and MinIO restore; app-image migration, startup, and readiness are intentionally skipped.'
