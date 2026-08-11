#!/usr/bin/env bash
# Generate a URL-safe production environment file without printing secrets to stdout.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

usage() {
  printf '%s\n' "Usage: bash infra/scripts/generate-env.sh --domain <fqdn> --email <ops-email> --ghcr-owner <lowercase-owner> [--tag <image-tag>] [--output <path>]"
}

domain=""
email=""
owner=""
tag="bootstrap"
output="/etc/amplitude-radar/app.env"

while (($#)); do
  case "$1" in
    --domain)
      (($# >= 2)) || { usage >&2; exit 64; }
      domain="$2"
      shift 2
      ;;
    --email)
      (($# >= 2)) || { usage >&2; exit 64; }
      email="$2"
      shift 2
      ;;
    --ghcr-owner)
      (($# >= 2)) || { usage >&2; exit 64; }
      owner="$2"
      shift 2
      ;;
    --tag)
      (($# >= 2)) || { usage >&2; exit 64; }
      tag="$2"
      shift 2
      ;;
    --output)
      (($# >= 2)) || { usage >&2; exit 64; }
      output="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      printf 'ERROR: unknown argument: %s\n' "$1" >&2
      exit 64
      ;;
  esac
done

[[ "$domain" =~ ^[A-Za-z0-9.-]+$ && "$domain" == *.* ]] || {
  printf '%s\n' "ERROR: --domain must be a fully qualified domain name" >&2
  exit 64
}
[[ "$email" =~ ^[^[:space:]@]+@[^[:space:]@]+$ ]] || {
  printf '%s\n' "ERROR: --email is invalid" >&2
  exit 64
}
[[ "$owner" =~ ^[a-z0-9][a-z0-9._-]*$ ]] || {
  printf '%s\n' "ERROR: --ghcr-owner must be lowercase and URL-safe" >&2
  exit 64
}
[[ "$tag" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || {
  printf '%s\n' "ERROR: --tag is invalid" >&2
  exit 64
}
command -v openssl >/dev/null 2>&1 || {
  printf '%s\n' "ERROR: openssl is required" >&2
  exit 1
}
[[ ! -e "$output" ]] || {
  printf 'ERROR: refusing to overwrite existing file: %s\n' "$output" >&2
  exit 1
}

output_dir="$(dirname -- "$output")"
install -d -m 0700 "$output_dir"
temporary="$(mktemp "$output_dir/.app.env.XXXXXX")"
cleanup() {
  rm -f -- "$temporary"
}
trap cleanup EXIT

secret() {
  openssl rand -hex 32
}

postgres_bootstrap_password="$(secret)"
postgres_migration_password="$(secret)"
postgres_app_password="$(secret)"
valkey_password="$(secret)"
minio_root_password="$(secret)"
radar_s3_access_key="radar-$(openssl rand -hex 6)"
radar_s3_secret_key="$(secret)"
app_secret="$(secret)"
grafana_password="$(secret)"

printf '%s\n' \
  "COMPOSE_PROJECT_NAME=amplitude-radar" \
  "CADDY_SITE_ADDRESS=$domain" \
  "CADDY_EMAIL=$email" \
  "CADDY_IMAGE=caddy:2.10.0-alpine@sha256:ae4458638da8e1a91aafffb231c5f8778e964bca650c8a8cb23a7e8ac557aa3c" \
  "WEB_IMAGE=ghcr.io/$owner/amplitude-radar-web" \
  "API_IMAGE=ghcr.io/$owner/amplitude-radar-api" \
  "WORKER_IMAGE=ghcr.io/$owner/amplitude-radar-worker" \
  "APP_VERSION=$tag" \
  "WEB_IMAGE_DIGEST=sha256:0000000000000000000000000000000000000000000000000000000000000000" \
  "API_IMAGE_DIGEST=sha256:0000000000000000000000000000000000000000000000000000000000000000" \
  "WORKER_IMAGE_DIGEST=sha256:0000000000000000000000000000000000000000000000000000000000000000" \
  "POSTGRES_IMAGE=pgvector/pgvector:pg18@sha256:691673308c99d2161ba298736f3147f1f22d79de2fb7ec93ae9b4afcab870b62" \
  "VALKEY_IMAGE=valkey/valkey:8-alpine@sha256:a038175878d66b9d274fbf8be73c0305e93798b83917647f167e18cef3c71eec" \
  "MINIO_IMAGE=minio/minio:RELEASE.2025-04-22T22-12-26Z@sha256:a1ea29fa28355559ef137d71fc570e508a214ec84ff8083e39bc5428980b015e" \
  "MINIO_MC_IMAGE=minio/mc:RELEASE.2025-04-16T18-13-26Z@sha256:aead63c77f9db9107f1696fb08ecb0faeda23729cde94b0f663edf4fe09728e3" \
  "MAILPIT_IMAGE=axllent/mailpit:v1.30.7@sha256:d5ecbb067db3705fa953d79e1b7f81ef84038df67aba6c52825d8c02a1ea748a" \
  "PROMETHEUS_IMAGE=prom/prometheus:v3.3.0@sha256:339ce86a59413be18d0e445472891d022725b4803fab609069110205e79fb2f1" \
  "GRAFANA_IMAGE=grafana/grafana:12.0.0@sha256:263cbefd5d9b179893c47c415daab4da5c1f3d6770154741eca4f45c81119884" \
  "LOKI_IMAGE=grafana/loki:3.5.0@sha256:4c431d2e6b9b38718694b31c5d56be7c80dc69c513215fde1aeb5b02cd4e2665" \
  "PROMTAIL_IMAGE=grafana/promtail:3.5.0@sha256:507dfecd2f0949475d071c124bea1c26fc4f8c1cff0372eee57478d5b1c5fbff" \
  "NODE_EXPORTER_IMAGE=prom/node-exporter:v1.9.1@sha256:d00a542e409ee618a4edc67da14dd48c5da66726bbd5537ab2af9c1dfc442c8a" \
  "POSTGRES_DB=amplitude_radar" \
  "POSTGRES_USER=amplitude" \
  "POSTGRES_PASSWORD=$postgres_bootstrap_password" \
  "POSTGRES_MIGRATION_USER=amplitude_migrate" \
  "POSTGRES_MIGRATION_PASSWORD=$postgres_migration_password" \
  "POSTGRES_APP_USER=amplitude_app" \
  "POSTGRES_APP_PASSWORD=$postgres_app_password" \
  "VALKEY_PASSWORD=$valkey_password" \
  "MINIO_ROOT_USER=amplitude-minio" \
  "MINIO_ROOT_PASSWORD=$minio_root_password" \
  "MINIO_BUCKET=amplitude-radar" \
  "RADAR_S3_ACCESS_KEY=$radar_s3_access_key" \
  "RADAR_S3_SECRET_KEY=$radar_s3_secret_key" \
  "RADAR_PUBLIC_BASE_URL=https://$domain" \
  "RADAR_APP_SECRET_KEY=$app_secret" \
  "RADAR_LLM_API_KEY=REPLACE_WITH_APPROVED_LLM_API_KEY" \
  "RADAR_LLM_BASE_URL=https://api.openai.com/v1" \
  "RADAR_LLM_MODEL=REPLACE_WITH_APPROVED_MODEL_ID" \
  "RADAR_S3_PUBLIC_ENDPOINT=" \
  "RADAR_MIGRATE_COMMAND=alembic upgrade head" \
  "RADAR_INGEST_WORKER_COMMAND=python -m zhenfu_api.workers.ingest" \
  "RADAR_ENRICHMENT_WORKER_COMMAND=python -m zhenfu_api.workers.enrichment" \
  "GRAFANA_ADMIN_USER=admin" \
  "GRAFANA_ADMIN_PASSWORD=$grafana_password" \
  "BACKUP_RETENTION_DAYS=14" \
  "DEPLOY_WAIT_SECONDS=180" >"$temporary"

chmod 0600 "$temporary"
mv -f -- "$temporary" "$output"
trap - EXIT
printf 'Created %s with mode 0600. Replace both RADAR_LLM placeholders before any deployment.\n' "$output"
