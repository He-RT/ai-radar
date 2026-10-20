# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e

FROM python:3.15-slim-bookworm@sha256:2a41267d9de9d358f77a1de356e0f16ecba8d39827855be0ce9ef4792edce402 AS base

COPY --from=ghcr.io/astral-sh/uv:0.12.3@sha256:2d890623d310b57771ce840f0da5eed5fc6d657da05ffaa45d82797b53fa3abc /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/README.md apps/api/alembic.ini ./
COPY apps/api/alembic ./alembic
COPY apps/api/src ./src
COPY config/sources/ai_radar_sources.json ./config/sources/ai_radar_sources.json

FROM base AS development

RUN uv sync --frozen --all-extras

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "zhenfu_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS production-dependencies

RUN uv sync --frozen --no-dev --no-editable

FROM python:3.15-slim-bookworm@sha256:2a41267d9de9d358f77a1de356e0f16ecba8d39827855be0ce9ef4792edce402 AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

RUN groupadd --system --gid 10001 radar \
    && useradd --system --uid 10001 --gid radar --home-dir /nonexistent --shell /usr/sbin/nologin radar

WORKDIR /app
COPY --from=production-dependencies --chown=radar:radar /app /app

USER radar
EXPOSE 8000
CMD ["uvicorn", "zhenfu_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=127.0.0.1"]

FROM production AS worker

CMD ["python", "-m", "zhenfu_api.workers.enrichment"]
