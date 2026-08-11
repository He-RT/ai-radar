#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mise exec -- pnpm lint
mise exec -- pnpm typecheck
mise exec -- pnpm test
mise exec -- pnpm build
python3 tools/source_registry/validate.py >/dev/null

if command -v docker >/dev/null 2>&1; then
  docker compose --env-file infra/env/ci.env -f infra/compose/compose.development.yml config --quiet
  docker compose --env-file infra/env/ci.env -f infra/compose/compose.production.yml config --quiet
fi
