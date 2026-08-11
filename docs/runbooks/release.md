# Release

## Preconditions

- CI, CodeQL, Trivy, and secret scanning are green for the reviewed commit.
- The change has a rollback plan in its pull request.
- Database migrations are additive and backward compatible with the previous image. If not, plan a maintenance window and a forward-only recovery.
- A current backup exists and its timestamp is recorded.
- The GitHub `release` environment requires the repository owner before GHCR
  publication and permits only the `main` branch or `v*` tags; the `production`
  environment separately protects VPS deployment.

## Build and publish

For a normal release, create an annotated version tag from the reviewed commit and push it. The Build and publish containers workflow builds and publishes web, api, and worker images to GHCR. Missing Dockerfiles or required build targets are release-blocking failures.

For a controlled manual build, use the workflow_dispatch inputs:

- `ref`: any repository ref for a non-publishing candidate build; `publish: true`
  requires an exact 40-character commit SHA that is an ancestor of protected `main`.
- `publish`: leave false for build/scan only; set true only after confirming the exact
  SHA and receiving `release` environment approval.

Only a publishing run records a release version, its exact 40-character source SHA,
and registry-resolvable
`sha256:<64 lowercase hex characters>` digest. It also uploads one
`release-manifest-<service>` artifact containing the same values. Copy the web, API,
and worker digests plus the common `SOURCE_SHA` from that summary or the three
manifests into the release ticket; do not derive a digest from a tag or use a registry
tag as deployment input.

## Deploy

1. Open the protected Deploy production workflow.
2. Enter the release version, `source_sha`, and all three exact digests from the
   published release: `web_image_digest`, `api_image_digest`, and
   `worker_image_digest`.
3. Approvers review the version/source-SHA/digest set, migration risk, backup status, and the
   prior known-good digest set. Do not substitute `latest`, branch names, or mutable aliases.
4. The workflow rejects anything except a safe release version, an exact lowercase
   40-hex source SHA, and three full lowercase SHA-256 digests, then opens SSH as
   radar-deploy with only the fixed `deploy --version ... --source-sha ...
   --web-image-digest ... --api-image-digest ... --worker-image-digest ...` command.
5. Before any pull, service start, or migration, the VPS deploy script requires the
   root-owned checkout HEAD to equal `source_sha`. A stale checkout fails closed.
   Once this passes, it renders Compose, pulls images, waits for PostgreSQL, Valkey,
   MinIO, and Mailpit, initializes the MinIO bucket, runs migration, starts
   web/api/workers/Caddy, and waits for health checks.

The deployment script writes the active release version, source SHA, and all three
digests to `/var/lib/amplitude-radar/release.env` only after a successful health
check. Its `--dry-run` validates this tuple and renders Compose without changing that
state. Backup and restore remain able to read legacy four-line release-state files,
but every new successful deployment writes `SOURCE_SHA`.

## Controlled VPS checkout update

The deployment account must never fetch, pull, switch, or modify the checkout. If a
deployment reports a source mismatch, stop and use an independent administrator
session. Copy `SOURCE_SHA` from the approved release manifest, verify it is exactly 40
lowercase hexadecimal characters, and confirm the configured `origin` is the approved
repository before running the following controlled update:

~~~sh
export SOURCE_SHA=0123456789abcdef0123456789abcdef01234567
[[ "$SOURCE_SHA" =~ ^[a-f0-9]{40}$ ]]
cd /opt/amplitude-radar
test -z "$(sudo git status --porcelain)"
sudo git fetch --no-tags origin '+refs/heads/main:refs/remotes/origin/main'
sudo git cat-file -e "${SOURCE_SHA}^{commit}"
sudo git verify-commit "$SOURCE_SHA"
sudo git merge-base --is-ancestor "$SOURCE_SHA" origin/main
sudo git checkout --detach "$SOURCE_SHA"
sudo chown -R root:root /opt/amplitude-radar
sudo chmod -R go-w /opt/amplitude-radar
test "$(sudo git rev-parse --verify 'HEAD^{commit}')" = "$SOURCE_SHA"
test -z "$(sudo git status --porcelain)"
~~~

For a policy-approved signed release tag, fetch that exact tag, run `git verify-tag`,
and confirm `git rev-parse '<tag>^{commit}'` equals `SOURCE_SHA`; do not replace the
signature check with trust in a tag name. If signature verification or the protected
`origin/main` ancestry check fails, do not update the checkout or redeploy. After all
checks pass, rerun the protected Deploy production workflow with the unchanged five-part
release identity.

## Verify

Before the first VPS release, build the three local `:final` images and run
`bash infra/scripts/test-production-smoke.sh`. It pushes them to an ephemeral local
registry, runs the production Compose core with immutable registry digests, applies
migrations, and requires healthy API, Web, and both workers. Caddy/TLS remains a
separate hostname-level check on the provisioned VPS.

- Open the public homepage and a known API endpoint through Caddy.
- Confirm GET /healthz and GET /readyz are successful from the API container.
- Confirm the migration service exited with code 0.
- Check Caddy, API, and worker logs for error bursts.
- Check Prometheus scrape availability and queue age if observability is enabled.
- Trigger one reversible test ingestion and verify exactly one event, evidence chain, and action record are written.

## Stop conditions

Stop rollout and use [rollback](rollback.md) when:

- readiness fails or error rate materially rises;
- migration fails or unexpectedly takes locks;
- source claims, user data, or authorization behavior regress;
- job duplication, queue age, or LLM-cost control deviates from the release plan.

Do not continue by manually editing containers. Fix the image, configuration, or migration in version control and redeploy an approved digest set.
