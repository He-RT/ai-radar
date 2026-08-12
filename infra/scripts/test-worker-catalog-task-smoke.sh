#!/usr/bin/env bash
# Exercise the worker's catalog-backed Celery task inside the built image without
# permitting network access or writes outside its disposable /tmp filesystem.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
CATALOG_PATH="$REPO_ROOT/config/sources/ai_radar_sources.json"

if [[ "$#" -ne 1 || -z "$1" ]]; then
  printf 'Usage: %s WORKER_IMAGE\n' "$(basename -- "$0")" >&2
  exit 64
fi

worker_image="$1"

for command in docker python3; do
  command -v "$command" >/dev/null 2>&1 || {
    printf 'ERROR: required command is unavailable: %s\n' "$command" >&2
    exit 1
  }
done

[[ -f "$CATALOG_PATH" ]] || {
  printf 'ERROR: source catalog is unavailable: %s\n' "$CATALOG_PATH" >&2
  exit 1
}

docker image inspect "$worker_image" >/dev/null 2>&1 || {
  printf 'ERROR: build or pull the worker image before the smoke test: %s\n' "$worker_image" >&2
  exit 1
}

expected_catalog_hash="$(python3 - "$CATALOG_PATH" <<'PY'
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)"
[[ "$expected_catalog_hash" =~ ^[a-f0-9]{64}$ ]] || {
  printf '%s\n' 'ERROR: could not calculate the expected catalog SHA-256' >&2
  exit 1
}

docker run --rm -i \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=16m \
  --env HOME=/tmp \
  --env PYTHONDONTWRITEBYTECODE=1 \
  --env RADAR_ENVIRONMENT=production \
  --env RADAR_LOG_FORMAT=json \
  --env RADAR_SERVICE_ROLE=ingest-worker \
  --env RADAR_SYNTHETIC_REPOSITORY=false \
  --env RADAR_DATABASE_URL=postgresql+psycopg://smoke:smoke-password@127.0.0.1:5432/radar \
  --env RADAR_VALKEY_URL=redis://:smoke-valkey-password@127.0.0.1:6379/0 \
  --env RADAR_S3_ENDPOINT=http://127.0.0.1:9000 \
  --env RADAR_S3_ACCESS_KEY=smoke-s3-access-key \
  --env RADAR_S3_SECRET_KEY=smoke-smoke-smoke-smoke-x \
  --env RADAR_S3_BUCKET=smoke-catalog \
  --env RADAR_SOURCE_CATALOG_PATH=/app/config/sources/ai_radar_sources.json \
  --env RADAR_EXPECTED_CATALOG_SHA256="$expected_catalog_hash" \
  "$worker_image" python - <<'PY'
from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path

from zhenfu_api.catalog import FULL_CATALOG_SIZE, load_catalog
from zhenfu_api.config import get_settings
from zhenfu_api.ingest.dispatcher import (
    DispatchReceipt,
    DispatchStatus,
    IngestionDispatcher,
    RuntimeDisposition,
    runtime_plan,
)
from zhenfu_api.jobs import celery_app
from zhenfu_api.workers import ingest


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


catalog_path = Path(os.environ["RADAR_SOURCE_CATALOG_PATH"])
catalog_bytes = catalog_path.read_bytes()
catalog_hash = hashlib.sha256(catalog_bytes).hexdigest()
expected_catalog_hash = os.environ["RADAR_EXPECTED_CATALOG_SHA256"]
require(catalog_hash == expected_catalog_hash, "image catalog SHA-256 does not match the repository")

catalog = load_catalog(catalog_path, require_full_catalog=True)
require(len(catalog.catalog.sources) == FULL_CATALOG_SIZE, "image catalog does not contain 500 sources")
require(catalog.content_hash == expected_catalog_hash, "loaded catalog SHA-256 does not match")

settings = get_settings()
require(settings.environment == "production", "worker did not load production settings")
require(settings.service_role == "ingest-worker", "worker did not load ingest-worker settings")

dispatched = []
fixed_time = datetime(2026, 8, 12, 12, tzinfo=UTC)


async def offline_dispatch(self: IngestionDispatcher, source):
    del self
    plan = runtime_plan(source)
    require(plan.disposition is RuntimeDisposition.SUPPORTED, "task dispatched an unsupported source")
    dispatched.append(source)
    return DispatchReceipt(
        source_id=source.id,
        source_uuid=str(source.stable_uuid),
        disposition=plan.disposition,
        operation=plan.operation,
        status=DispatchStatus.SUCCEEDED,
        fetch_url=plan.fetch_url,
        artifact_sha256="0" * 64,
        candidates=(),
        started_at=fixed_time,
        finished_at=fixed_time,
        reason="offline worker-image smoke dispatch",
    )


ingest._default_worker.cache_clear()
original_dispatch = IngestionDispatcher.dispatch
IngestionDispatcher.dispatch = offline_dispatch
try:
    task_name = "radar.ingest.run_one_due"
    require(task_name in celery_app.tasks, "ingest task is not registered with Celery")
    result = celery_app.tasks[task_name].apply(kwargs={"now": fixed_time.isoformat()})
    payload = result.get(propagate=True)
finally:
    IngestionDispatcher.dispatch = original_dispatch
    ingest._default_worker.cache_clear()

require(len(dispatched) == 1, "task did not dispatch exactly one source")
require(
    runtime_plan(dispatched[0]).disposition is RuntimeDisposition.SUPPORTED,
    "task did not dispatch a supported source",
)
require(isinstance(payload, dict), "task did not return a receipt payload")
require(payload.get("terminal") is True, "task payload is not terminal")
require(payload.get("status") == DispatchStatus.SUCCEEDED.value, "task payload did not succeed")
require(payload.get("source_id") == dispatched[0].id, "task payload source does not match dispatch")

print(
    "Worker catalog task smoke passed: "
    f"sources={len(catalog.catalog.sources)} sha256={catalog_hash} source={dispatched[0].id}"
)
PY
