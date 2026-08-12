#!/usr/bin/env bash
# Shared helpers for production operations. This file is sourced only by sibling scripts.

if [[ -n "${_AMPLITUDE_RADAR_LIB_LOADED:-}" ]]; then
  return 0
fi
_AMPLITUDE_RADAR_LIB_LOADED=1

AR_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
AR_REPO_ROOT="$(cd -- "$AR_SCRIPT_DIR/../.." && pwd -P)"
AR_PRODUCTION_COMPOSE="${AR_PRODUCTION_COMPOSE:-$AR_REPO_ROOT/infra/compose/compose.production.yml}"
AR_ENV_FILE="${AR_ENV_FILE:-/etc/amplitude-radar/app.env}"
AR_PROJECT="${AR_PROJECT:-amplitude-radar}"
AR_RELEASE_STATE_FILE="${AR_RELEASE_STATE_FILE:-/var/lib/amplitude-radar/release.env}"
AR_COMPOSE_PROFILES=()

ar_die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

ar_log() {
  printf '[%s] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >&2
}

ar_require_command() {
  command -v "$1" >/dev/null 2>&1 || ar_die "required command is unavailable: $1"
}

ar_validate_image_tag() {
  local tag="$1"
  [[ "$tag" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] ||
    ar_die "invalid image tag; use an immutable SHA or release tag"
}

ar_validate_image_digest() {
  local digest="$1"
  [[ "$digest" =~ ^sha256:[a-f0-9]{64}$ ]] ||
    ar_die "invalid image digest; use sha256:<64 lowercase hex characters>"
}

ar_validate_source_sha() {
  local source_sha="$1"
  [[ "$source_sha" =~ ^[a-f0-9]{40}$ ]] ||
    ar_die "invalid source SHA; use exactly 40 lowercase hexadecimal characters"
}

ar_assert_checkout_source() {
  local expected_source_sha="$1"
  local checkout_root checkout_source_sha

  ar_validate_source_sha "$expected_source_sha"
  if ! checkout_root="$(git -c safe.directory="$AR_REPO_ROOT" -C "$AR_REPO_ROOT" rev-parse --show-toplevel 2>/dev/null)"; then
    ar_die "trusted deployment checkout is unavailable: $AR_REPO_ROOT"
  fi
  [[ "$checkout_root" == "$AR_REPO_ROOT" ]] ||
    ar_die "trusted deployment checkout resolved outside the expected root: $checkout_root"
  if ! checkout_source_sha="$(git -c safe.directory="$AR_REPO_ROOT" -C "$AR_REPO_ROOT" rev-parse --verify 'HEAD^{commit}' 2>/dev/null)"; then
    ar_die "trusted deployment checkout has no valid commit at HEAD: $AR_REPO_ROOT"
  fi
  [[ "$checkout_source_sha" =~ ^[a-f0-9]{40}$ ]] ||
    ar_die "trusted deployment checkout returned an invalid HEAD"
  [[ "$checkout_source_sha" == "$expected_source_sha" ]] ||
    ar_die "deployment source mismatch: trusted checkout HEAD is $checkout_source_sha but release source is $expected_source_sha. Stop; an administrator must update $AR_REPO_ROOT through the controlled root-owned checkout procedure, verify the release signature and protected-main ancestry, then rerun the protected deployment"
}

ar_env_value() {
  local key="$1"
  local count value
  count="$(grep -Ec "^${key}=" "$AR_ENV_FILE" || true)"
  [[ "$count" == "1" ]] ||
    ar_die "$key must appear exactly once in $AR_ENV_FILE"
  value="$(sed -n "s/^${key}=//p" "$AR_ENV_FILE")"
  printf '%s' "$value"
}

ar_validate_pinned_infrastructure_images() {
  local key value
  local -a keys=(
    CADDY_IMAGE
    POSTGRES_IMAGE
    VALKEY_IMAGE
    MINIO_IMAGE
    MINIO_MC_IMAGE
    MAILPIT_IMAGE
    PROMETHEUS_IMAGE
    GRAFANA_IMAGE
    LOKI_IMAGE
    PROMTAIL_IMAGE
    NODE_EXPORTER_IMAGE
  )

  for key in "${keys[@]}"; do
    value="$(ar_env_value "$key")"
    [[ "$value" =~ ^[^[:space:]@]+@sha256:[a-f0-9]{64}$ ]] ||
      ar_die "$key must be an immutable image reference ending in @sha256:<64 lowercase hex characters>"
  done
}

ar_file_mode() {
  if stat -c '%a' "$1" >/dev/null 2>&1; then
    stat -c '%a' "$1"
  else
    stat -f '%Lp' "$1"
  fi
}

ar_assert_secure_env_file() {
  [[ -f "$AR_ENV_FILE" && -r "$AR_ENV_FILE" ]] ||
    ar_die "environment file is missing or unreadable: $AR_ENV_FILE"

  local mode
  mode="$(ar_file_mode "$AR_ENV_FILE")"
  (( (8#$mode & 8#077) == 0 )) ||
    ar_die "environment file must not be readable by group or others (current mode: $mode)"
}

ar_load_release_version() {
  [[ -r "$AR_RELEASE_STATE_FILE" ]] ||
    ar_die "release state is missing: $AR_RELEASE_STATE_FILE; deploy a release before backup/restore"

  local line_count app_line web_line api_line worker_line source_line
  line_count="$(awk 'END { print NR }' "$AR_RELEASE_STATE_FILE")"
  [[ "$line_count" == "4" || "$line_count" == "5" ]] ||
    ar_die "release state is malformed: $AR_RELEASE_STATE_FILE"
  app_line="$(sed -n '1p' "$AR_RELEASE_STATE_FILE")"
  web_line="$(sed -n '2p' "$AR_RELEASE_STATE_FILE")"
  api_line="$(sed -n '3p' "$AR_RELEASE_STATE_FILE")"
  worker_line="$(sed -n '4p' "$AR_RELEASE_STATE_FILE")"
  source_line="$(sed -n '5p' "$AR_RELEASE_STATE_FILE")"

  [[ "$app_line" =~ ^APP_VERSION=([A-Za-z0-9][A-Za-z0-9._-]{0,127})$ ]] ||
    ar_die "release state is malformed: $AR_RELEASE_STATE_FILE"
  APP_VERSION="${BASH_REMATCH[1]}"
  [[ "$web_line" =~ ^WEB_IMAGE_DIGEST=(sha256:[a-f0-9]{64})$ ]] ||
    ar_die "release state is malformed: $AR_RELEASE_STATE_FILE"
  WEB_IMAGE_DIGEST="${BASH_REMATCH[1]}"
  [[ "$api_line" =~ ^API_IMAGE_DIGEST=(sha256:[a-f0-9]{64})$ ]] ||
    ar_die "release state is malformed: $AR_RELEASE_STATE_FILE"
  API_IMAGE_DIGEST="${BASH_REMATCH[1]}"
  [[ "$worker_line" =~ ^WORKER_IMAGE_DIGEST=(sha256:[a-f0-9]{64})$ ]] ||
    ar_die "release state is malformed: $AR_RELEASE_STATE_FILE"
  WORKER_IMAGE_DIGEST="${BASH_REMATCH[1]}"
  SOURCE_SHA=""
  if [[ "$line_count" == "5" ]]; then
    [[ "$source_line" =~ ^SOURCE_SHA=([a-f0-9]{40})$ ]] ||
      ar_die "release state is malformed: $AR_RELEASE_STATE_FILE"
    SOURCE_SHA="${BASH_REMATCH[1]}"
  fi
  export APP_VERSION WEB_IMAGE_DIGEST API_IMAGE_DIGEST WORKER_IMAGE_DIGEST SOURCE_SHA
}

ar_compose() {
  if [[ -n "${AR_COMPOSE_PROFILES[*]-}" ]]; then
    docker compose \
      --project-name "$AR_PROJECT" \
      --env-file "$AR_ENV_FILE" \
      -f "$AR_PRODUCTION_COMPOSE" \
      "${AR_COMPOSE_PROFILES[@]}" \
      "$@"
  else
    docker compose \
      --project-name "$AR_PROJECT" \
      --env-file "$AR_ENV_FILE" \
      -f "$AR_PRODUCTION_COMPOSE" \
      "$@"
  fi
}

ar_compose_profile() {
  local profile="$1"
  shift
  docker compose \
    --project-name "$AR_PROJECT" \
    --env-file "$AR_ENV_FILE" \
    -f "$AR_PRODUCTION_COMPOSE" \
    --profile "$profile" \
    "$@"
}

ar_wait_for_healthy() {
  local service="$1"
  local timeout_seconds="$2"
  local deadline=$((SECONDS + timeout_seconds))
  local container_id status

  while (( SECONDS < deadline )); do
    container_id="$(ar_compose ps -q "$service" 2>/dev/null || true)"
    if [[ -n "$container_id" ]]; then
      status="$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id" 2>/dev/null || true)"
      case "$status" in
        "running healthy")
          ar_log "$service is $status"
          return 0
          ;;
        exited*|dead*)
          ar_die "$service stopped while waiting ($status)"
          ;;
      esac
    fi
    sleep 2
  done

  ar_die "timed out waiting for healthy service: $service"
}

ar_wait_for_completed() {
  local service="$1"
  local timeout_seconds="$2"
  local deadline=$((SECONDS + timeout_seconds))
  local container_id status

  while (( SECONDS < deadline )); do
    container_id="$(ar_compose ps -aq "$service" 2>/dev/null | head -n 1 || true)"
    if [[ -n "$container_id" ]]; then
      status="$(docker inspect --format '{{.State.Status}} {{.State.ExitCode}}' "$container_id" 2>/dev/null || true)"
      case "$status" in
        "exited 0")
          ar_log "$service completed successfully"
          return 0
          ;;
        exited*|dead*)
          ar_die "$service failed ($status)"
          ;;
      esac
    fi
    sleep 2
  done

  ar_die "timed out waiting for one-shot service: $service"
}

# Restore the PostgreSQL data plane from a verified custom-format dump. The
# in-container preflight deliberately runs before dropdb so an invalid dump or
# missing initialization/grant script cannot replace the current database.
ar_restore_postgresql_data() {
  local database_dump="$1"

  [[ -f "$database_dump" && -r "$database_dump" ]] ||
    ar_die "PostgreSQL restore dump is missing or unreadable: $database_dump"

  ar_log "restoring PostgreSQL (this replaces the current database)"
  ar_compose cp "$database_dump" postgres:/tmp/amplitude-radar-restore.dump
  ar_compose exec -T postgres /bin/sh -ec \
    'test -r /docker-entrypoint-initdb.d/001_extensions.sql; test -r /docker-entrypoint-initdb.d/runtime-grants.sql.template; pg_restore --list /tmp/amplitude-radar-restore.dump >/dev/null; dropdb --force -U "$POSTGRES_USER" --if-exists "$POSTGRES_DB"; createdb -U "$POSTGRES_USER" "$POSTGRES_DB"; psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/001_extensions.sql; psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -v database_name="$POSTGRES_DB" -v migration_user="$POSTGRES_MIGRATION_USER" -v app_user="$POSTGRES_APP_USER" -f /docker-entrypoint-initdb.d/runtime-grants.sql.template; pg_restore --exit-on-error --no-owner --no-privileges --no-comments --role="$POSTGRES_MIGRATION_USER" -U "$POSTGRES_USER" -d "$POSTGRES_DB" /tmp/amplitude-radar-restore.dump; psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -v database_name="$POSTGRES_DB" -v migration_user="$POSTGRES_MIGRATION_USER" -v app_user="$POSTGRES_APP_USER" -f /docker-entrypoint-initdb.d/runtime-grants.sql.template; rm -f /tmp/amplitude-radar-restore.dump'
}

# Restore the MinIO data plane from a verified backup staging directory.
ar_restore_minio_data() {
  local restore_dir="$1"

  [[ -d "$restore_dir/minio" ]] ||
    ar_die "MinIO restore directory is missing: $restore_dir/minio"

  ar_log "restoring MinIO bucket (objects absent from the archive will be deleted)"
  BACKUP_STAGING_DIR="$restore_dir" ar_compose_profile maintenance run --rm --no-deps minio-client \
    'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"; mc mirror --overwrite --remove /backup/minio "local/$MINIO_BUCKET"'
}

# Shared destructive restore primitive. Callers are responsible for archive
# verification and service lifecycle management before invoking it.
ar_restore_data_plane() {
  local restore_dir="$1"

  ar_restore_postgresql_data "$restore_dir/database.dump"
  ar_restore_minio_data "$restore_dir"
}

ar_write_release_state() {
  local version="$1"
  local web_image_digest="$2"
  local api_image_digest="$3"
  local worker_image_digest="$4"
  local source_sha="$5"
  local state_dir temporary

  ar_validate_image_tag "$version"
  ar_validate_image_digest "$web_image_digest"
  ar_validate_image_digest "$api_image_digest"
  ar_validate_image_digest "$worker_image_digest"
  ar_validate_source_sha "$source_sha"

  state_dir="$(dirname -- "$AR_RELEASE_STATE_FILE")"
  install -d -m 0700 "$state_dir"
  temporary="$(mktemp "$state_dir/.release.env.XXXXXX")"
  {
    printf 'APP_VERSION=%s\n' "$version"
    printf 'WEB_IMAGE_DIGEST=%s\n' "$web_image_digest"
    printf 'API_IMAGE_DIGEST=%s\n' "$api_image_digest"
    printf 'WORKER_IMAGE_DIGEST=%s\n' "$worker_image_digest"
    printf 'SOURCE_SHA=%s\n' "$source_sha"
  } >"$temporary"
  chmod 0600 "$temporary"
  mv -f -- "$temporary" "$AR_RELEASE_STATE_FILE"
}
