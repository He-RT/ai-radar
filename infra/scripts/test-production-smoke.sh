#!/usr/bin/env bash
# Run the production Compose core against locally built, registry-addressable images.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
COMPOSE_FILE="$REPO_ROOT/infra/compose/compose.production.yml"
temporary="$(mktemp -d "$REPO_ROOT/.production-smoke.XXXXXX")"
project="radar-production-smoke-$$"
registry_name="radar-smoke-registry-$$"
environment_file="$temporary/app.env"
published_image_refs_file="$temporary/published-image-refs"

for command in docker openssl; do
  command -v "$command" >/dev/null 2>&1 || {
    printf 'ERROR: required command is unavailable: %s\n' "$command" >&2
    exit 1
  }
done

for image in amplitude-radar-web:final amplitude-radar-api:final amplitude-radar-worker:final; do
  docker image inspect "$image" >/dev/null 2>&1 || {
    printf 'ERROR: build the local image before the smoke test: %s\n' "$image" >&2
    exit 1
  }
done

bash "$SCRIPT_DIR/test-worker-catalog-task-smoke.sh" amplitude-radar-worker:final

compose=(
  docker compose
  --project-name "$project"
  --env-file "$environment_file"
  -f "$COMPOSE_FILE"
)

cleanup() {
  if [[ -f "$environment_file" ]]; then
    "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  fi
  docker rm -f "$registry_name" >/dev/null 2>&1 || true
  if [[ -f "$published_image_refs_file" ]]; then
    while IFS= read -r image_ref; do
      docker image rm "$image_ref" >/dev/null 2>&1 || true
    done <"$published_image_refs_file"
  fi
  rm -rf -- "$temporary"
}
trap cleanup EXIT

docker run -d --name "$registry_name" -p 127.0.0.1::5000 \
  registry:2@sha256:a3d8aaa63ed8681a604f1dea0aa03f100d5895b6a58ace528858a7b332415373 \
  >/dev/null
registry_port="$(docker port "$registry_name" 5000/tcp | sed -E 's/.*:([0-9]+)$/\1/')"
[[ "$registry_port" =~ ^[0-9]+$ ]]
registry="127.0.0.1:$registry_port"

publish_local_image() {
  local source_image="$1"
  local repository="$2"
  local target="$repository:smoke"
  local digest
  docker tag "$source_image" "$target"
  printf '%s\n' "$target" >>"$published_image_refs_file"
  docker push "$target" >/dev/null
  digest="$(
    docker image inspect "$target" --format '{{range .RepoDigests}}{{println .}}{{end}}' |
      awk -F@ -v repository="$repository" '$1 == repository { print $2; exit }'
  )"
  [[ "$digest" =~ ^sha256:[a-f0-9]{64}$ ]]
  printf '%s' "$digest"
}

web_repository="$registry/amplitude-radar-web"
api_repository="$registry/amplitude-radar-api"
worker_repository="$registry/amplitude-radar-worker"
web_digest="$(publish_local_image amplitude-radar-web:final "$web_repository")"
api_digest="$(publish_local_image amplitude-radar-api:final "$api_repository")"
worker_digest="$(publish_local_image amplitude-radar-worker:final "$worker_repository")"

bash "$SCRIPT_DIR/generate-env.sh" \
  --domain radar-smoke.example.invalid \
  --email ops@example.invalid \
  --ghcr-owner local \
  --output "$environment_file" >/dev/null

replace_assignment() {
  local key="$1"
  local value="$2"
  local replacement="$temporary/environment.replacement"
  awk -v key="$key" -v value="$value" '
    BEGIN { replaced = 0 }
    index($0, key "=") == 1 { print key "=" value; replaced = 1; next }
    { print }
    END { if (!replaced) exit 2 }
  ' "$environment_file" >"$replacement"
  mv -f -- "$replacement" "$environment_file"
  chmod 0600 "$environment_file"
}

replace_assignment WEB_IMAGE "$web_repository"
replace_assignment API_IMAGE "$api_repository"
replace_assignment WORKER_IMAGE "$worker_repository"
replace_assignment WEB_IMAGE_DIGEST "$web_digest"
replace_assignment API_IMAGE_DIGEST "$api_digest"
replace_assignment WORKER_IMAGE_DIGEST "$worker_digest"
replace_assignment RADAR_LLM_API_KEY smoke-only-approved-key
replace_assignment RADAR_LLM_MODEL smoke-only-approved-model

wait_for_state() {
  local service="$1"
  local expected="$2"
  local attempts=0
  local container_id status=""
  while (( attempts < 120 )); do
    attempts=$((attempts + 1))
    container_id="$("${compose[@]}" ps -aq "$service" | head -n 1)"
    if [[ -n "$container_id" ]]; then
      status="$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.ExitCode}}{{end}}' "$container_id")"
      [[ "$status" == "$expected" ]] && return 0
      [[ "$status" == exited* && "$expected" != "exited 0" ]] && break
    fi
    sleep 1
  done
  printf 'ERROR: %s did not reach %s (last state: %s)\n' "$service" "$expected" "$status" >&2
  return 1
}

"${compose[@]}" up -d postgres valkey minio mailpit >/dev/null
for service in postgres valkey minio mailpit; do
  wait_for_state "$service" "running healthy"
done
"${compose[@]}" up minio-init >/dev/null
wait_for_state minio-init "exited 0"
"${compose[@]}" up migrate >/dev/null
wait_for_state migrate "exited 0"
"${compose[@]}" up -d api web worker-ingest worker-enrichment >/dev/null
for service in api web worker-ingest worker-enrichment; do
  wait_for_state "$service" "running healthy"
done

api_container="$("${compose[@]}" ps -q api)"
web_container="$("${compose[@]}" ps -q web)"
api_ready="$(docker exec "$api_container" python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/readyz').read().decode())")"
web_status="$(docker exec "$web_container" node -e "fetch('http://127.0.0.1:3000/healthz').then(r=>console.log(r.status))")"
radar_status="$(docker exec "$web_container" node -e "fetch('http://127.0.0.1:3000/radar').then(r=>console.log(r.status))")"
# shellcheck disable=SC2016 # Variables expand inside the PostgreSQL container, not this shell.
alembic_version="$("${compose[@]}" exec -T postgres sh -ec '
  export PGPASSWORD="$POSTGRES_APP_PASSWORD"
  psql -h 127.0.0.1 -U "$POSTGRES_APP_USER" -d "$POSTGRES_DB" -Atqc "SELECT version_num FROM alembic_version"
')"

[[ "$api_ready" == '{"status":"ready"}' ]]
[[ "$web_status" == "200" ]]
[[ "$radar_status" == "200" ]]
[[ "$alembic_version" == "0003" ]]
[[ "$(docker inspect --format '{{.Config.User}}' "$api_container")" == "radar" ]]
[[ "$(docker inspect --format '{{.Config.User}}' "$web_container")" == "nextjs" ]]

printf 'Production core smoke passed: readyz=200 web=200 radar=200 migration=%s\n' "$alembic_version"
