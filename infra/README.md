# Deployment baseline

This directory is the operating baseline for a public GitHub monorepo deployed to one Ubuntu VPS in Hong Kong or Singapore with 4 vCPU and 16 GB RAM. It intentionally contains no production secret.

## Topology

- Caddy is the only internet-facing container: TCP 80/443 and UDP 443.
- web and api use an internal application network; PostgreSQL, Valkey, and MinIO use a separate internal data network.
- PostgreSQL uses pgvector/pgvector:pg18; its initial database enables vector and pgcrypto.
- Valkey has a required password and append-only persistence.
- MinIO is private and seeded with a private bucket. Mailpit is an internal delivery sink, not a transactional-email provider.
- Prometheus, Grafana, Loki, Promtail, and node-exporter are optional via the observability profile. Prometheus and Grafana bind only to loopback at 127.0.0.1:9090 and 127.0.0.1:3001 for SSH tunnelling.

The production memory limits leave room for the kernel, Docker, page cache, and short deployment spikes. Do not co-locate unrelated workloads on this VPS.

## Application image contract

The platform configuration expects three GHCR repositories plus independently verified
immutable image digests:

- amplitude-radar-web listens on port 3000 and implements GET /healthz.
- amplitude-radar-api listens on port 8000 and implements GET /healthz, GET /readyz, and internal-only Prometheus GET /metrics.
- amplitude-radar-worker accepts the two worker commands in the environment file and treats jobs as idempotent.

The API image must provide /bin/sh, python, and the configured migration command. The web image must provide node. Keep app state in PostgreSQL or MinIO because app containers have read-only filesystems.

## Local development

~~~sh
cp infra/env/development.env.example infra/env/development.env
docker compose --env-file infra/env/development.env \
  -f infra/compose/compose.development.yml up --build
~~~

Caddy is available on http://127.0.0.1:8080; direct local API, PostgreSQL, Valkey, MinIO, and Mailpit ports are loopback-only. The development compose file expects product sources at apps/web and apps/api.

## Production lifecycle

1. Follow [VPS bootstrap](../docs/runbooks/vps-bootstrap.md).
2. Generate /etc/amplitude-radar/app.env using generate-env.sh; add an approved RADAR_LLM_API_KEY and RADAR_LLM_MODEL.
3. Validate rendering without starting anything.

~~~sh
sudo -u radar-deploy bash infra/scripts/deploy.sh \
  --version RELEASE_VERSION \
  --source-sha SOURCE_SHA \
  --web-image-digest sha256:WEB_DIGEST \
  --api-image-digest sha256:API_DIGEST \
  --worker-image-digest sha256:WORKER_DIGEST \
  --dry-run
~~~

4. Publish images through the GitHub release workflow, update the root-owned checkout
   through the signature- and protected-main-verified procedure in the release runbook,
   then run the protected Deploy production workflow with the reviewed release version,
   exact source SHA, and web/API/worker `sha256` digests. The forced SSH command accepts
   only that fixed-order source-bound, digest-pinned command.
5. Enable observability once the core service is healthy.

~~~sh
sudo -u radar-deploy bash infra/scripts/deploy.sh \
  --version RELEASE_VERSION \
  --source-sha SOURCE_SHA \
  --web-image-digest sha256:WEB_DIGEST \
  --api-image-digest sha256:API_DIGEST \
  --worker-image-digest sha256:WORKER_DIGEST \
  --with-observability
~~~

The generator already emits reviewed digest pins for every infrastructure image. Keep
those pins intact; change a reference only through a reviewed upgrade that updates the
generator, CI fixture, examples, and recovery evidence together.

## Operational commands

Always invoke scripts with bash; executable file modes are not assumed in a fresh checkout.

~~~sh
sudo -u radar-deploy bash infra/scripts/backup.sh
sudo -u radar-deploy bash infra/scripts/restore.sh --archive /var/backups/amplitude-radar/ARCHIVE --confirm "RESTORE ARCHIVE"
sudo -u radar-deploy bash infra/scripts/verify-config.sh
~~~

Detailed release, rollback, backup, incident, LLM, queue, secret, and observability procedures live in [docs/runbooks](../docs/runbooks/README.md).
