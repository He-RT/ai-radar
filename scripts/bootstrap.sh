#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v mise >/dev/null 2>&1; then
  echo "mise is required: https://mise.jdx.dev/getting-started.html" >&2
  exit 1
fi

mise trust --quiet
mise install
mise exec -- pnpm install --frozen-lockfile=false
mise exec -- pnpm --filter @amplitude/web typegen
mise exec -- uv sync --project apps/api --all-extras

if [[ ! -f infra/env/development.env ]]; then
  cp infra/env/development.env.example infra/env/development.env
  chmod 0600 infra/env/development.env
  echo "Created infra/env/development.env from the non-production example."
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  mise exec -- pnpm compose:up
else
  echo "Docker is not running; application dependencies were installed, but local services were not started." >&2
fi

echo "Bootstrap complete. Run: mise exec -- pnpm dev"
